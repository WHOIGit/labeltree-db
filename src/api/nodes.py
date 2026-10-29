"""/nodes/{id} endpoints (specs: node-read-api, node-aliases, node-descriptions).

Reads are anonymous. Aliases and descriptions are unversioned and change
directly, outside changesets, by a `drafter` in the node's organization.
"""

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from ninja import Router, Schema

from accounts.models import Role
from accounts.roles import require
from core.changesets import latest_rev
from core.models import Node, NodeAlias, NodeDescription, NodeVersion
from worms.models import NodeWarnings

from .conventions import (
    APIError,
    bad_parameter,
    not_found,
    paginate,
    parse_depth,
    resolve_rev,
    respond,
)
from .serializers import RevisionView, deprecation_record

router = Router(tags=["nodes"])


def get_node(node_id: int) -> Node:
    try:
        return Node.objects.select_related("tree").get(pk=node_id)
    except Node.DoesNotExist:
        raise not_found(f"Node {node_id} does not exist.") from None


def node_at(node_id: int, rev: int | None, dropempty: bool):
    """Resolve a node at a revision.

    Returns (node, rev, header_rev, view); view is None if the node was
    deprecated by then. 404 if the node didn't exist yet.
    """
    node = get_node(node_id)
    r, _, by_default = resolve_rev(node.tree_id, rev)
    if r < node.created_in_rev:
        raise not_found(f"Node {node_id} did not exist yet at revision {r}.")
    header_rev = r if by_default else None
    if node.deprecated_in_rev is not None and r >= node.deprecated_in_rev:
        return node, r, header_rev, None
    return node, r, header_rev, RevisionView(node.tree, r, dropempty=dropempty)


@router.get("/{node_id}", auth=None)
def node_detail(request, node_id: int, rev: int | None = None, dropempty: bool = False):
    node, r, header_rev, view = node_at(node_id, rev, dropempty)
    data = view.detailed(node.id) if view else deprecation_record(node, r, dropempty=dropempty)
    return respond(request, data, rev=header_rev)


@router.get("/{node_id}/ancestors", auth=None)
def node_ancestors(request, node_id: int, rev: int | None = None, dropempty: bool = False):
    node, r, header_rev, view = node_at(node_id, rev, dropempty)
    if view is None:
        return respond(request, deprecation_record(node, r, dropempty=dropempty), rev=header_rev)
    data = {
        "tree": node.tree_id,
        "rev": r,
        "node": view.lite(node.id),
        "ancestors": [view.lite(a) for a in view.state.ancestor_ids(node.id)],
    }
    return respond(request, data, rev=header_rev)


@router.get("/{node_id}/descendants", auth=None)
def node_descendants(
    request, node_id: int, rev: int | None = None, depth: str = "all", dropempty: bool = False
):
    limit = parse_depth(depth)
    node, r, header_rev, view = node_at(node_id, rev, dropempty)
    if view is None:
        return respond(request, deprecation_record(node, r, dropempty=dropempty), rev=header_rev)
    data = {"tree": node.tree_id, "rev": r, "node": view.lite(node.id, limit)}
    return respond(request, data, rev=header_rev)


@router.get("/{node_id}/versions", auth=None)
def node_versions(request, node_id: int):
    node = get_node(node_id)
    data = {
        "id": node.id,
        "tree": node.tree_id,
        "created_in_rev": node.created_in_rev,
        "deprecated_in_rev": node.deprecated_in_rev,
        "versions": [
            {"version": v, "valid_from_rev": frm, "valid_to_rev": to}
            for v, frm, to in node.versions.order_by("version").values_list(
                "version", "valid_from_rev", "valid_to_rev"
            )
        ],
    }
    return respond(request, data)


@router.get("/{node_id}/versions/{version}", auth=None)
def node_at_version(
    request, node_id: int, version: int, rev: int | None = None, dropempty: bool = False
):
    node = get_node(node_id)
    try:
        nv = node.versions.get(version=version)
    except NodeVersion.DoesNotExist:
        raise not_found(f"Node {node_id} has no version {version}.") from None
    last = nv.valid_to_rev - 1 if nv.valid_to_rev is not None else latest_rev(node.tree_id)
    if rev is None:
        rev, header_rev = last, last
    elif not nv.valid_from_rev <= rev <= last:
        raise bad_parameter(
            f"Version {version} of node {node_id} is valid for revisions "
            f"{nv.valid_from_rev}-{last}, not {rev}."
        )
    else:
        header_rev = None
    view = RevisionView(node.tree, rev, dropempty=dropempty)
    return respond(request, view.detailed(node.id), rev=header_rev)


@router.get("/{node_id}/warning_history", auth=None)
def node_warning_history(request, node_id: int, limit: int | None = None, offset: int = 0):
    """WoRMS warnings over time, newest first; the first row is the current set."""
    node = get_node(node_id)
    rows = NodeWarnings.objects.filter(node=node).order_by("-computed_at", "-id")
    page, count = paginate(rows, limit, offset)
    data = {
        "id": node.id,
        "tree": node.tree_id,
        "count": count,
        "history": [
            {"computed_at": row.computed_at.isoformat(), "warnings": row.warnings} for row in page
        ],
    }
    return respond(request, data)


# --- Aliases and descriptions -----------------------------------------------------------


class AliasIn(Schema):
    alias: str


class DescriptionIn(Schema):
    description: str


def changeable_node(request, node_id: int) -> Node:
    """A node the user may change aliases and descriptions of: `drafter`, and not
    deprecated (409)."""
    node = get_node(node_id)
    require(request.user, node.tree_id, Role.DRAFTER)
    if node.deprecated_in_rev is not None:
        raise APIError(
            409, "node_deprecated",
            f"Node {node_id} was deprecated in revision {node.deprecated_in_rev}.",
        )  # fmt: skip
    return node


def alias_body(alias: NodeAlias, history: bool) -> dict:
    body = {"id": alias.id, "alias": alias.alias}
    if history:
        body |= {
            "added_by": alias.added_by, "added_at": alias.added_at.isoformat(),
            "removed_by": alias.removed_by,
            "removed_at": alias.removed_at.isoformat() if alias.removed_at else None,
        }  # fmt: skip
    return body


@router.get("/{node_id}/aliases", auth=None)
def node_aliases(
    request, node_id: int, history: bool = False, limit: int | None = None, offset: int = 0
):
    """Current aliases; with history, removed ones too, newest first, paginated."""
    node = get_node(node_id)
    aliases = NodeAlias.objects.filter(node=node)
    if not history:
        current = aliases.filter(removed_at__isnull=True).order_by("id")
        return respond(request, {"id": node.id, "aliases": [alias_body(a, False) for a in current]})
    page, count = paginate(aliases.order_by("-added_at", "-id"), limit, offset)
    data = {"id": node.id, "count": count, "aliases": [alias_body(a, True) for a in page]}
    return respond(request, data)


@router.post("/{node_id}/aliases")
def add_alias(request, node_id: int, body: AliasIn):
    node = changeable_node(request, node_id)
    text = body.alias.strip()
    if not text:
        raise bad_parameter("alias must not be empty.")
    duplicate = APIError(409, "alias_exists", f"Node {node_id} already has alias {text!r}.")
    if NodeAlias.objects.filter(node=node, alias=text, removed_at__isnull=True).exists():
        raise duplicate
    try:
        with transaction.atomic():
            alias = NodeAlias.objects.create(
                node=node, alias=text, added_by=request.user.get_username(),
                added_at=timezone.now(),
            )  # fmt: skip
    except IntegrityError:  # added concurrently
        raise duplicate from None
    response = respond(request, {"id": alias.id, "alias": alias.alias})
    response.status_code = 201
    return response


@router.delete("/{node_id}/aliases/{alias_id}")
def remove_alias(request, node_id: int, alias_id: int):
    node = get_node(node_id)
    require(request.user, node.tree_id, Role.DRAFTER)
    removed = NodeAlias.objects.filter(pk=alias_id, node=node, removed_at__isnull=True).update(
        removed_by=request.user.get_username(), removed_at=timezone.now()
    )
    if not removed:
        raise not_found(f"Node {node_id} has no current alias {alias_id}.")
    return HttpResponse(status=204)


def description_body(entry: NodeDescription) -> dict:
    return {
        "description": entry.description, "added_by": entry.added_by,
        "added_at": entry.added_at.isoformat(),
    }  # fmt: skip


@router.get("/{node_id}/description", auth=None)
def node_description(
    request, node_id: int, history: bool = False, limit: int | None = None, offset: int = 0
):
    """The current description; with history, every entry, newest first, paginated."""
    node = get_node(node_id)
    entries = NodeDescription.objects.filter(node=node).order_by("-added_at", "-id")
    if not history:
        newest = entries.first()
        return respond(
            request, {"id": node.id, "description": newest.description if newest else ""}
        )
    page, count = paginate(entries, limit, offset)
    data = {"id": node.id, "count": count, "history": [description_body(e) for e in page]}
    return respond(request, data)


@router.put("/{node_id}/description")
def set_description(request, node_id: int, body: DescriptionIn):
    """Add a description entry; "" clears the description. Earlier entries are kept."""
    node = changeable_node(request, node_id)
    NodeDescription.objects.create(
        node=node, description=body.description, added_by=request.user.get_username(),
        added_at=timezone.now(),
    )  # fmt: skip
    return respond(request, {"id": node.id, "description": body.description})
