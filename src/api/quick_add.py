"""Quick add: one node, previewed, then confirmed and published (spec: quick-add).

`POST /trees/{tree}/quick_add` plans an `add` from the request: with an
`aphia_id`, a missing label comes from the WoRMS name and a missing parent from
its lineage (worms.placement). Without a valid `confirm` key it returns a
preview: the plan, its issues and a key. The key is signed and binds the user,
the tree, the request (without `confirm` and `notes`) and the plan with its
issues, so sending the same request back with it publishes exactly what was
shown. Anything else gets a fresh preview, saying why the key wasn't used.

Nothing is stored between the two calls. Planning reuses validate(), and
publishing reuses create_changeset() and publish_changeset(), so a quick add
is an ordinary changeset and revision.

Existing direct children of the parent that belong under the new node (it would
give them `misplaced_lineage_ancestor`) are an issue; with
`allow_cross_node_updates` the plan also moves all of them under it.
"""

import hashlib
import json

from django.core import signing
from django.db import transaction
from django.http import JsonResponse
from ninja import Router, Schema

from accounts.models import Role
from accounts.roles import require
from core.changesets import ChangesetError, create_changeset, latest_rev, publish_changeset
from core.engine import TreeState, load_state, specs_from_dicts
from core.models import NodeVersion
from core.validation import validate
from worms.checks import nearest_anchored_ancestor
from worms.client import worms_url
from worms.placement import lineage_parent, worms_label
from worms.records import get_records

from .conventions import APIError, bad_parameter, get_tree
from .worms import cached

router = Router(tags=["trees"])

KEY_SALT = "quick-add"
KEY_MAX_AGE = 15 * 60  # seconds
DEFAULT_NOTES = "Quick add"
PLACEHOLDER = "new:1"


class QuickAddIn(Schema):
    aphia_id: int | None = None
    label: str | None = None
    parent: int | None = None  # missing: work it out; null: the top level
    lowercase_label: bool = True  # for a label derived from the WoRMS name
    allow_cross_node_updates: bool = False  # move the nodes the new one should adopt
    description: str = ""
    aliases: list[str] = []
    notes: str | None = None
    confirm: str | None = None


def _digest(value) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _request_digest(body: QuickAddIn) -> str:
    request = body.dict(exclude={"confirm", "notes"})
    if "parent" not in body.model_fields_set:
        request["parent"] = "auto"
    return _digest(request)


def _node(state: TreeState, ref) -> dict | None:
    return None if ref is None else {"id": ref, "label": state.nodes[ref].label}


def _anchor(state: TreeState, parent) -> int | None:
    """The AphiaID the planned node's placement is checked against."""
    if parent is None or parent not in state:
        return None
    if state.nodes[parent].aphia_id is not None:
        return state.nodes[parent].aphia_id
    anchor = nearest_anchored_ancestor(state, parent)
    return None if anchor is None else state.nodes[anchor].aphia_id


class Plan:
    """The resolved `add`, its validation and its issues, on the latest revision."""

    def __init__(self, tree, body: QuickAddIn):
        self.tree = tree
        self.rev = latest_rev(tree.id)
        state = load_state(tree.id, self.rev)
        record = cached(body.aphia_id).record if body.aphia_id is not None else None
        if record is None and not body.label:
            raise bad_parameter("Give an `aphia_id`, a `label`, or both.")

        if body.label is not None:
            label = body.label
        else:
            label = worms_label(record["scientificname"], lower=body.lowercase_label)
        lineage = (record or {}).get("lineage") or []
        suggested, candidates = lineage_parent(state, lineage, body.aphia_id)
        if "parent" in body.model_fields_set:
            parent, candidates = body.parent, []
        else:
            parent = suggested

        change = {"op": "add", "node": PLACEHOLDER, "label": label, "parent": parent,
                  "aphia_id": body.aphia_id}  # fmt: skip
        if body.description:
            change["description"] = body.description
        if body.aliases:
            change["aliases"] = body.aliases
        # The records the placement checks need, fetched if missing; a failure
        # leaves those checks unavailable, as when saving a draft.
        get_records({a for a in (body.aphia_id, _anchor(state, parent)) if a is not None})
        result = self._validate([change])
        # Every misplaced_lineage_ancestor the add causes on an existing node is
        # about the new node; the direct children of its parent can move under it.
        adopt = sorted({
            w["node"] for w in result["warnings"]
            if w["warning"] == "misplaced_lineage_ancestor" and w["node"] != PLACEHOLDER
            and state.nodes[w["node"]].parent == parent
        })  # fmt: skip
        moves = adopt if body.allow_cross_node_updates else []
        self.changes = [change] + [
            {"op": "move", "node": ref, "from_parent": parent, "to_parent": PLACEHOLDER}
            for ref in moves
        ]
        if moves:
            result = self._validate(self.changes)

        self.plan = {
            "label": label, "parent": _node(state, parent),
            "aphia_id": body.aphia_id, "worms_url": worms_url(body.aphia_id),
            "description": body.description, "aliases": body.aliases,
            "moves": [_node(state, ref) for ref in moves],
        }  # fmt: skip
        self.issues = self._issues(state, record, result, parent, suggested, candidates)
        if adopt and not moves:
            self.issues.append(_adopt_issue(state, label, adopt))
        self.worms = result["worms"]

    def _validate(self, changes: list[dict]) -> dict:
        result = validate(specs_from_dicts(changes), tree_id=self.tree.id, base_rev=self.rev)
        if result["errors"]:
            raise APIError(
                422, "structural", f"The quick add has {len(result['errors'])} error(s).",
                errors=result["errors"],
            )  # fmt: skip
        return result

    def _issues(self, state, record, result, parent, suggested, candidates) -> list[dict]:
        issues = []
        if candidates:
            aphia = state.nodes[candidates[0]].aphia_id
            names = ", ".join(f"{state.nodes[c].label} ({c})" for c in candidates)
            options = [{"label": f"Under {state.nodes[c].label} (node {c})", "set": {"parent": c}}
                       for c in candidates]  # fmt: skip
            options.append({"label": "At the top level", "set": {"parent": None}})
            issues.append({
                "code": "ambiguous_parent",
                "message": f"Several nodes are anchored to AphiaID {aphia}: {names}. "
                           "The node goes at the top level unless you pick one.",
                "options": options,
            })  # fmt: skip
        for warning in result["warnings"]:
            if warning["node"] != PLACEHOLDER:
                continue
            code, options = warning["warning"], []
            if code == "unaccepted_aphia" and record and record.get("valid_AphiaID"):
                valid = record["valid_AphiaID"]
                name = record.get("valid_name") or f"AphiaID {valid}"
                options.append({"label": f"Use the accepted name, {name} ({valid})",
                                 "set": {"aphia_id": valid}})  # fmt: skip
            elif (code in ("out_of_lineage", "misplaced_lineage_ancestor")
                  and suggested is not None and suggested != parent):  # fmt: skip
                options.append({"label": f"Under {state.nodes[suggested].label} (node "
                                         f"{suggested}), from the WoRMS lineage",
                                "set": {"parent": suggested}})  # fmt: skip
            issues.append({"code": code, "message": warning["detail"], "options": options})
        return issues

    def digest(self) -> str:
        return _digest({"plan": self.plan, "issues": self.issues})


def _adopt_issue(state: TreeState, label: str, adopt: list) -> dict:
    names = ", ".join(f"{state.nodes[ref].label} ({ref})" for ref in adopt)
    return {
        "code": "misplaced_lineage_ancestor",
        "message": f"In WoRMS, {label} is in the lineage of {names}, which would sit "
                   f"beside it. Allowing updates to other nodes moves them under {label}.",
        "options": [{"label": f"Move {len(adopt)} node{'s' if len(adopt) > 1 else ''} "
                              f"under {label}", "set": {"allow_cross_node_updates": True}}],
    }  # fmt: skip


def _key(user, tree, request_digest: str, plan: Plan) -> str:
    payload = {"u": user.pk, "t": tree.id, "r": request_digest, "p": plan.digest()}
    return signing.dumps(payload, salt=KEY_SALT, compress=True)


def _confirm_status(key: str | None, user, tree, request_digest: str, plan: Plan) -> str:
    if not key:
        return "none"
    try:
        payload = signing.loads(key, salt=KEY_SALT, max_age=KEY_MAX_AGE)
    except signing.SignatureExpired:
        return "expired"
    except signing.BadSignature:
        return "invalid"
    if not isinstance(payload, dict) or payload.get("u") != user.pk or payload.get("t") != tree.id:
        return "invalid"
    if payload.get("r") != request_digest:
        return "body_changed"
    if payload.get("p") != plan.digest():
        return "plan_changed"
    return "accepted"


def _publish(user, tree, plan: Plan, notes: str | None):
    username = user.get_username()
    with transaction.atomic():
        changeset = create_changeset(
            author=username, changes=plan.changes, tree=tree, base_rev=plan.rev,
            notes=notes or DEFAULT_NOTES,
        )  # fmt: skip
        revision = publish_changeset(changeset, published_by=username)
    node = NodeVersion.objects.get(
        tree=tree, label=plan.plan["label"], valid_from_rev=revision.number,
        valid_to_rev__isnull=True,
    ).node_id  # fmt: skip
    return changeset, revision, node


@router.post("/{tree_id}/quick_add")
def quick_add(request, tree_id: str, body: QuickAddIn):
    """Preview adding one node, or publish it when sent again with the preview's
    `confirm` key. See the API docs for the request and response shapes."""
    tree = get_tree(tree_id)
    require(request.user, tree.id, Role.APPROVER)
    request_digest = _request_digest(body)

    for attempt in range(2):
        plan = Plan(tree, body)
        status = _confirm_status(body.confirm, request.user, tree, request_digest, plan)
        if status != "accepted":
            break
        try:
            changeset, revision, node = _publish(request.user, tree, plan, body.notes)
        except ChangesetError as exc:
            if exc.error == "stale_base" and attempt == 0:
                continue  # published to in between: plan again on the new revision
            if exc.error == "stale_base":
                status = "plan_changed"
                break
            raise APIError(409 if exc.error == "publish_in_progress" else 422, exc.error,
                           exc.detail, errors=exc.errors) from None  # fmt: skip
        return JsonResponse({
            "status": "published", "confirm_status": "accepted", "tree": tree.id,
            "rev": revision.number, "changeset": changeset.pk,
            "node": {"id": node, "label": plan.plan["label"], "parent": plan.plan["parent"],
                     "aphia_id": plan.plan["aphia_id"], "worms_url": plan.plan["worms_url"]},
            "moved": plan.plan["moves"], "warnings": plan.issues,
        }, status=201, json_dumps_params={"ensure_ascii": False})  # fmt: skip

    return JsonResponse({
        "status": "preview", "confirm_status": status, "tree": tree.id, "rev": plan.rev,
        "plan": plan.plan, "issues": plan.issues, "worms": plan.worms,
        "confirm": _key(request.user, tree, request_digest, plan),
    }, json_dumps_params={"ensure_ascii": False})  # fmt: skip
