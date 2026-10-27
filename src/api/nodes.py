"""/nodes/{id} read endpoints (spec: node-read-api)."""

from ninja import Router

from core.changesets import latest_rev
from core.models import Node, NodeVersion

from .conventions import bad_parameter, not_found, parse_depth, resolve_rev, respond
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


@router.get("/{node_id}")
def node_detail(request, node_id: int, rev: int | None = None, dropempty: bool = False):
    node, r, header_rev, view = node_at(node_id, rev, dropempty)
    data = view.detailed(node.id) if view else deprecation_record(node, r, dropempty=dropempty)
    return respond(request, data, rev=header_rev)


@router.get("/{node_id}/ancestors")
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


@router.get("/{node_id}/descendants")
def node_descendants(
    request, node_id: int, rev: int | None = None, depth: str = "all", dropempty: bool = False
):
    limit = parse_depth(depth)
    node, r, header_rev, view = node_at(node_id, rev, dropempty)
    if view is None:
        return respond(request, deprecation_record(node, r, dropempty=dropempty), rev=header_rev)
    data = {"tree": node.tree_id, "rev": r, "node": view.lite(node.id, limit)}
    return respond(request, data, rev=header_rev)


@router.get("/{node_id}/versions")
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


@router.get("/{node_id}/versions/{version}")
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
