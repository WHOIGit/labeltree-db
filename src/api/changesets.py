"""Validate and changeset endpoints (spec: changeset-api).

Thin wrappers around the engine: `validate` and a draft's validation share
core.validation; saves, updates and publishes go through core.changesets, which
reads cached WoRMS records only. `PUT` and `publish` need `If-Match` with the
draft's ETag, compared under the draft's row lock.

Roles: drafts on a tree need `drafter` in its organization to change and
`approver` to publish; new-tree changesets need `owner` of the organization
they name. Members of the organization (`reader`) see them.
"""

import json
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import validate_slug
from django.db.models import Count
from django.http import HttpResponse
from ninja import Router, Schema

from accounts.models import Organization, Role
from accounts.roles import require, require_org
from core.changesets import (
    ChangesetError,
    NewTree,
    changeset_etag,
    create_changeset,
    discard_changeset,
    publish_changeset,
    stored_specs,
    update_changeset,
)
from core.engine import ChangeSpec, specs_from_dicts
from core.models import Change, Changeset
from core.validation import validate

from .conventions import APIError, bad_parameter, get_tree, not_found, paginate, respond
from .serializers import RevisionView
from .trees import ordered_payload, summary_body

router = Router(tags=["changesets"])

STATES = [s.value for s in Changeset.State]
# ChangesetError codes -> HTTP status; blocked publishes add the validation.
STATUS = {
    "invalid_base_rev": 422, "not_draft": 409, "precondition_failed": 412,
    "publish_in_progress": 409, "tree_exists": 409, "stale_base": 409, "structural": 422,
}  # fmt: skip


class ValidateIn(Schema):
    base_rev: int | None = None
    changes: list[Any]


class CreateIn(Schema):
    base_rev: int | None = None
    changes: list[Any]
    notes: str = ""


class NewTreeIn(Schema):
    id: str
    title: str
    description: str = ""
    org: str


class CreateNewTreeIn(Schema):
    new_tree: NewTreeIn
    changes: list[Any]
    notes: str = ""


class UpdateIn(Schema):
    changes: list[Any] | None = None
    notes: str | None = None
    base_rev: int | None = None


# --- Serialising ------------------------------------------------------------------------


def change_body(change: ChangeSpec | Change, *, sources=False) -> dict:
    body = {"seq": change.seq, "op": change.op, "group": change.group}
    payload = change.payload if isinstance(change.payload, dict) else {}
    body |= ordered_payload(payload)
    if sources:
        body["sources"] = list(change.sources)
    return body


def validation_body(result: dict) -> dict:
    reduced = [change_body(c, sources=True) for c in result["reduced_changes"]]
    return {**result, "reduced_changes": reduced}


def draft_validation(changeset: Changeset) -> dict:
    """What `validate` reports for the draft's stored changes."""
    return validation_body(
        validate(
            stored_specs(changeset), tree_id=changeset.tree_id, base_rev=changeset.base_rev,
            new_tree_id=changeset.new_tree_id,
        )
    )  # fmt: skip


def changeset_body(changeset: Changeset) -> dict:
    new_tree = None
    if changeset.new_tree_id is not None:
        new_tree = {
            "id": changeset.new_tree_id, "title": changeset.new_tree_title,
            "description": changeset.new_tree_description, "org": changeset.new_tree_org_id,
        }  # fmt: skip
    revision = getattr(changeset, "revision", None) if changeset.state == "published" else None
    body = {
        "id": changeset.pk,
        "tree": changeset.tree_id,
        "new_tree": new_tree,
        "state": changeset.state,
        "base_rev": changeset.base_rev,
        "rev": revision.number if revision else None,
        "author": changeset.author,
        "notes": changeset.notes,
        "created_at": changeset.created_at.isoformat(),
        "updated_at": changeset.updated_at.isoformat(),
        "changes": [change_body(c) for c in changeset.changes.order_by("seq")],
    }
    if changeset.state == Changeset.State.DRAFT:
        body["validation"] = draft_validation(changeset)
    return body


def with_etag(changeset: Changeset, status=200) -> HttpResponse:
    """The changeset with its ETag, which identifies the draft's content, not the
    response (its validation follows the tree)."""
    changeset.refresh_from_db()
    body = json.dumps(changeset_body(changeset), ensure_ascii=False, separators=(",", ":"))
    response = HttpResponse(body, status=status, content_type="application/json")
    response["ETag"] = changeset_etag(changeset)
    return response


# --- Access -----------------------------------------------------------------------------


def get_changeset(cs: int) -> Changeset:
    try:
        return Changeset.objects.get(pk=cs)
    except Changeset.DoesNotExist:
        raise not_found(f"Changeset {cs} does not exist.") from None


def require_on(user, changeset: Changeset, minimum: Role):
    """`minimum` on the changeset's tree; `owner` of the organization for a
    new-tree changeset (`reader` to see it)."""
    if changeset.tree_id is not None:
        require(user, changeset.tree_id, minimum)
    else:
        require_org(user, changeset.new_tree_org_id, Role.READER if minimum == Role.READER
                    else Role.OWNER)  # fmt: skip


def if_match(request) -> str:
    value = request.headers.get("If-Match")
    if not value:
        raise APIError(428, "precondition_required", "Send the draft's ETag as If-Match.")
    return value.strip().removeprefix("W/")


def refused(exc: ChangesetError, changeset: Changeset | None = None) -> APIError:
    extra = {}
    if exc.error in ("stale_base", "structural") and changeset is not None:
        extra["validation"] = draft_validation(changeset)
    return APIError(STATUS.get(exc.error, 409), exc.error, exc.detail, **extra)


# --- Validate ------------------------------------------------------------------------------


@router.post("/trees/{tree_id}/validate")
def validate_changes(request, tree_id: str, body: ValidateIn):
    tree = get_tree(tree_id)
    require(request.user, tree.id, Role.DRAFTER)
    try:
        result = validate(specs_from_dicts(body.changes), tree_id=tree.id, base_rev=body.base_rev)
    except ChangesetError as exc:
        raise refused(exc) from None
    return respond(request, validation_body(result))


# --- Create and list -------------------------------------------------------------------------


@router.post("/trees/{tree_id}/changesets")
def create(request, tree_id: str, body: CreateIn):
    tree = get_tree(tree_id)
    require(request.user, tree.id, Role.DRAFTER)
    try:
        changeset = create_changeset(
            author=request.user.get_username(), changes=body.changes, tree=tree,
            base_rev=body.base_rev, notes=body.notes,
        )  # fmt: skip
    except ChangesetError as exc:
        raise refused(exc) from None
    return with_etag(changeset, status=201)


@router.post("/changesets")
def create_new_tree(request, body: CreateNewTreeIn):
    new = body.new_tree
    if not Organization.objects.filter(pk=new.org).exists():
        raise not_found(f"Organization {new.org} does not exist.")
    require_org(request.user, new.org, Role.OWNER)
    try:
        validate_slug(new.id)
    except ValidationError:
        raise bad_parameter("new_tree.id must be a slug: letters, digits, `_` and `-`.") from None
    if not new.title.strip():
        raise bad_parameter("new_tree.title is required.")
    changeset = create_changeset(
        author=request.user.get_username(), changes=body.changes,
        new_tree=NewTree(new.id, new.title, new.org, new.description), notes=body.notes,
    )  # fmt: skip
    return with_etag(changeset, status=201)


@router.get("/trees/{tree_id}/changesets")
def list_changesets(
    request, tree_id: str, state: str | None = None, limit: int | None = None, offset: int = 0
):
    tree = get_tree(tree_id)
    require(request.user, tree.id, Role.READER)
    if state is not None and state not in STATES:
        raise bad_parameter(f"state must be one of {', '.join(STATES)}.")
    changesets = Changeset.objects.filter(tree=tree).annotate(num_changes=Count("changes"))
    if state is not None:
        changesets = changesets.filter(state=state)
    page, count = paginate(changesets.order_by("-id"), limit, offset)
    data = {
        "tree": tree.id,
        "count": count,
        "changesets": [
            {
                "id": c.pk,
                "state": c.state,
                "base_rev": c.base_rev,
                "author": c.author,
                "notes": c.notes,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "num_changes": c.num_changes,
            }  # fmt: skip
            for c in page
        ],
    }
    return respond(request, data)


# --- One changeset ---------------------------------------------------------------------------


@router.get("/changesets/{cs}")
def get_one(request, cs: int):
    changeset = get_changeset(cs)
    require_on(request.user, changeset, Role.READER)
    return with_etag(changeset)


@router.put("/changesets/{cs}")
def update(request, cs: int, body: UpdateIn):
    changeset = get_changeset(cs)
    require_on(request.user, changeset, Role.DRAFTER)
    try:
        changeset = update_changeset(
            changeset, changes=body.changes, notes=body.notes, base_rev=body.base_rev,
            if_match=if_match(request),
        )  # fmt: skip
    except ChangesetError as exc:
        raise refused(exc) from None
    return with_etag(changeset)


@router.post("/changesets/{cs}/publish")
def publish(request, cs: int):
    changeset = get_changeset(cs)
    require_on(request.user, changeset, Role.APPROVER)
    notes = _optional_notes(request)
    try:
        revision = publish_changeset(
            changeset, published_by=request.user.get_username(), notes=notes,
            if_match=if_match(request),
        )  # fmt: skip
    except ChangesetError as exc:
        raise refused(exc, changeset) from None
    response = respond(request, summary_body(RevisionView(revision.tree, revision.number)))
    response.status_code = 201
    return response


def _optional_notes(request) -> str | None:
    """`{notes}` is optional, and so is the (JSON) body."""
    if not request.body or request.content_type != "application/json":
        return None
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        raise bad_parameter('The body must be JSON, e.g. {"notes": "..."}.') from None
    notes = body.get("notes") if isinstance(body, dict) else None
    if notes is not None and not isinstance(notes, str):
        raise bad_parameter("notes must be a string.")
    return notes


@router.delete("/changesets/{cs}")
def discard(request, cs: int):
    changeset = get_changeset(cs)
    require_on(request.user, changeset, Role.DRAFTER)
    try:
        discard_changeset(changeset)
    except ChangesetError as exc:
        raise refused(exc) from None
    return HttpResponse(status=204)
