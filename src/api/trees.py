"""/trees read endpoints (spec: tree-read-api)."""

import csv
import io

from django.db import connection
from django.db.models import Count
from ninja import Router

from core.changesets import latest_rev
from core.models import Change, Node, NodeAlias, NodeVersion, Tree, TreeRevision

from .conventions import (
    bad_parameter,
    get_tree,
    not_found,
    paginate,
    parse_depth,
    resolve_rev,
    respond,
)
from .serializers import RevisionView, deprecation_record

router = Router(tags=["trees"])

SEARCH_METHODS = ("exact", "prefix", "substring", "fuzzy")


def view_at(tree_id: str, rev: int | None, dropempty=False):
    """(view, header_rev) for a tree at ?rev, or at the latest revision."""
    tree = get_tree(tree_id)
    r, _, by_default = resolve_rev(tree.id, rev)
    return RevisionView(tree, r, dropempty=dropempty), (r if by_default else None)


def revision_meta(revision: TreeRevision) -> dict:
    return {
        "published_at": revision.published_at.isoformat(),
        "published_by": revision.published_by,
        "author": revision.changeset.author,
        "notes": revision.notes,
        "changeset": revision.changeset_id,
    }


def int_param(request, name: str) -> int:
    raw = request.GET.get(name)
    if raw is None:
        raise bad_parameter(f"`{name}` is required.")
    try:
        return int(raw)
    except ValueError:
        raise bad_parameter(f"`{name}` must be an integer, not {raw!r}.") from None


# --- Tree info and history -------------------------------------------------------------


@router.get("")
def list_trees(request):
    trees = []
    for tree in Tree.objects.order_by("id"):
        latest = tree.revisions.order_by("-number").select_related("changeset").first()
        trees.append(
            {
                "id": tree.id,
                "title": tree.title,
                "description": tree.description,
                "latest_rev": latest.number,
                "published_at": latest.published_at.isoformat(),
                "num_nodes": NodeVersion.objects.filter(
                    tree=tree, valid_to_rev__isnull=True
                ).count(),
            }
        )
    return respond(request, {"trees": trees})


@router.get("/{tree_id}")
def tree_summary(request, tree_id: str, rev: int | None = None):
    view, header_rev = view_at(tree_id, rev)
    revision = view.tree.revisions.select_related("changeset").get(number=view.rev)
    data = {
        "id": view.tree.id,
        "title": view.tree.title,
        "description": view.tree.description,
        "rev": view.rev,
        "latest_rev": latest_rev(view.tree.id),
        **revision_meta(revision),
        "num_nodes": len(view.state.nodes),
        "num_top_level": len(view.state.child_ids(None)),
        "max_depth": view.state.max_depth(),
    }
    return respond(request, data, rev=header_rev)


@router.get("/{tree_id}/revisions")
def tree_revisions(request, tree_id: str, limit: int | None = None, offset: int = 0):
    tree = get_tree(tree_id)
    revisions = (
        tree.revisions.select_related("changeset")
        .annotate(num_changes=Count("changeset__changes"))
        .order_by("-number")
    )
    page, count = paginate(revisions, limit, offset)
    data = {
        "tree": tree.id,
        "count": count,
        "revisions": [
            {"rev": r.number, **revision_meta(r), "num_changes": r.num_changes} for r in page
        ],
    }
    return respond(request, data)


def revision_version_changes(tree_id: str, rev: int) -> list[dict]:
    """Derived from version ranges: versions opened at rev, and versions closed at
    rev by deprecation."""
    opened = NodeVersion.objects.filter(tree_id=tree_id, valid_from_rev=rev).values_list(
        "node_id", "version"
    )
    closed = NodeVersion.objects.filter(
        tree_id=tree_id, valid_to_rev=rev, node__deprecated_in_rev=rev
    ).values_list("node_id", "version")
    changes = [{"node": n, "from": v - 1 if v > 1 else None, "to": v} for n, v in opened]
    changes += [{"node": n, "from": v, "to": None} for n, v in closed]
    return sorted(changes, key=lambda c: c["node"])


PAYLOAD_ORDER = [
    "node", "label", "parent", "from_parent", "to_parent", "description", "aphia_id", "aliases",
    "successors",
]  # fmt: skip


def ordered_payload(payload: dict) -> dict:
    """jsonb doesn't keep key order; emit payload fields in the documented order."""
    return dict(sorted(payload.items(), key=lambda kv: PAYLOAD_ORDER.index(kv[0])))


@router.get("/{tree_id}/revisions/{rev}/changes")
def revision_changes(request, tree_id: str, rev: int):
    tree = get_tree(tree_id)
    try:
        revision = tree.revisions.get(number=rev)
    except TreeRevision.DoesNotExist:
        raise not_found(f"Tree {tree.id} has no revision {rev}.") from None
    changes = Change.objects.filter(changeset_id=revision.changeset_id).order_by("seq")
    data = {
        "tree": tree.id,
        "rev": rev,
        "notes": revision.notes,
        "changes": [
            {"seq": c.seq, "op": c.op, "group": c.group, **ordered_payload(c.payload)}
            for c in changes
        ],
        "version_changes": revision_version_changes(tree.id, rev),
    }
    return respond(request, data)


@router.get("/{tree_id}/diff")
def tree_diff(request, tree_id: str):
    tree = get_tree(tree_id)
    frm, to = int_param(request, "from"), int_param(request, "to")
    resolve_rev(tree.id, frm)
    resolve_rev(tree.id, to)
    if frm > to:
        raise bad_parameter("`from` must not be after `to`.")
    before = RevisionView(tree, frm)
    after = RevisionView(tree, to)
    a, b = before.state.nodes, after.state.nodes

    added = [after.lite(ref) for ref in sorted(b.keys() - a.keys())]
    gone = sorted(a.keys() - b.keys())
    deprecated = []
    for node in Node.objects.filter(id__in=gone).order_by("id"):
        record = deprecation_record(node, to)
        deprecated.append(
            {k: record[k] for k in ("id", "label", "deprecated_in_rev", "successors")}
        )
    moved, edited = [], []
    for ref in sorted(a.keys() & b.keys()):
        old, new = a[ref], b[ref]
        if old.parent != new.parent:
            moved.append(
                {"id": ref, "label": new.label, "from_parent": old.parent, "to_parent": new.parent}
            )
        fields = {
            f: [getattr(old, f), getattr(new, f)]
            for f in ("label", "description", "aphia_id")
            if getattr(old, f) != getattr(new, f)
        }
        if fields:
            edited.append({"id": ref, "label": new.label, "fields": fields})
    data = {
        "tree": tree.id,
        "from": frm,
        "to": to,
        "added": added,
        "deprecated": deprecated,
        "moved": moved,
        "edited": edited,
    }
    return respond(request, data)


# --- Browsing and export ----------------------------------------------------------------


@router.get("/{tree_id}/nodes_as_tree")
def nodes_as_tree(
    request, tree_id: str, rev: int | None = None, depth: str = "all", dropempty: bool = False
):
    limit = parse_depth(depth)
    if limit == 0:
        raise bad_parameter("depth must be at least 1: the top-level nodes are level 1.")
    view, header_rev = view_at(tree_id, rev, dropempty)
    view.preload()
    child_depth = None if limit is None else limit - 1
    data = {
        "tree": view.tree.id,
        "rev": view.rev,
        "nodes": [view.content(ref, child_depth) for ref in view.state.child_ids(None)],
    }
    return respond(request, data, rev=header_rev)


@router.get("/{tree_id}/export")
def export(
    request, tree_id: str, rev: int | None = None, parents: bool = False, dropempty: bool = False
):
    view, header_rev = view_at(tree_id, rev, dropempty)
    view.preload()
    data = {
        "tree": view.tree.id,
        "rev": view.rev,
        "nodes": [
            view.detailed(ref, nested=True, parent=parents) for ref in view.state.child_ids(None)
        ],
    }
    return respond(request, data, rev=header_rev)


FLAT_COLUMNS = [
    "id",
    "label",
    "version",
    "parent",
    "children",
    "tree_depth",
    "description",
    "aliases",
    "aphia_id",
    "worms_scientificname",
    "worms_rank",
    "worms_status",
    "worms_link",
    "worms_warnings",
    "created_in_rev",
]


@router.get("/{tree_id}/export_flat")
def export_flat(request, tree_id: str, rev: int | None = None):
    view, header_rev = view_at(tree_id, rev)
    view.preload()
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(FLAT_COLUMNS)
    stack = list(reversed(view.state.child_ids(None)))
    while stack:  # depth-first, parents before children
        ref = stack.pop()
        node = view.detailed(ref)
        writer.writerow(
            [
                ref,
                node["label"],
                node["version"],
                node["parent"]["id"] if node["parent"] else "",
                "|".join(str(c["id"]) for c in node["children"]),
                node["tree_depth"],
                node["description"],
                "|".join(a["alias"] for a in node["aliases"]),
                "" if node["aphia_id"] is None else node["aphia_id"],
                "",
                "",
                "",
                "",
                "|".join(node["worms_warnings"]),
                node["created_in_rev"],
            ]
        )
        stack.extend(reversed(view.state.child_ids(ref)))
    return respond(request, out.getvalue(), rev=header_rev, content_type="text/csv; charset=utf-8")


# --- Finding nodes -------------------------------------------------------------------------


@router.get("/{tree_id}/nodes/{label}")
def node_by_label(
    request, tree_id: str, label: str, rev: int | None = None, dropempty: bool = False
):
    view, header_rev = view_at(tree_id, rev, dropempty)
    ref = view.state.by_label.get(label)
    if ref is None:
        raise not_found(f"No node in tree {view.tree.id} has label {label} at revision {view.rev}.")
    return respond(request, view.detailed(ref), rev=header_rev)


def _split(raw: str | None) -> list[str]:
    return [part for part in (raw or "").split(",") if part != ""]


@router.get("/{tree_id}/nodes")
def nodes_batch(
    request,
    tree_id: str,
    ids: str | None = None,
    labels: str | None = None,
    rev: int | None = None,
    dropempty: bool = False,
):
    try:
        wanted_ids = [int(i) for i in _split(ids)]
    except ValueError:
        raise bad_parameter("ids must be a comma-separated list of integers.") from None
    view, header_rev = view_at(tree_id, rev, dropempty)
    view.preload([i for i in wanted_ids if i in view.state])
    others = Node.objects.in_bulk([i for i in wanted_ids if i not in view.state])

    nodes = []
    for nid in wanted_ids:
        node = others.get(nid)
        if nid in view.state:
            nodes.append(view.detailed(nid))
        elif (
            node is not None
            and node.tree_id == view.tree.id
            and node.deprecated_in_rev is not None
            and node.created_in_rev <= view.rev
            and node.deprecated_in_rev <= view.rev
        ):
            nodes.append(deprecation_record(node, view.rev, dropempty=dropempty))
        else:
            nodes.append({"id": nid, "error": "not_found"})
    for label in _split(labels):
        ref = view.state.by_label.get(label)
        nodes.append(
            view.detailed(ref) if ref is not None else {"label": label, "error": "not_found"}
        )
    data = {"tree": view.tree.id, "rev": view.rev, "nodes": nodes}
    return respond(request, data, rev=header_rev)


def _normalise(text: str) -> str:
    return text.lower().replace("_", " ")


def _fuzzy_scores(query: str, candidates: list[str]) -> dict[str, float]:
    """pg_trgm similarity for candidates above the similarity threshold."""
    if not candidates:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT s, similarity(s, %s) FROM unnest(%s::text[]) AS s WHERE s %% %s",
            [query, list(set(candidates)), query],
        )
        return dict(cursor.fetchall())


@router.get("/{tree_id}/search")
def search(
    request,
    tree_id: str,
    q: str | None = None,
    aphia_id: int | None = None,
    method: str | None = None,
    limit: int = 20,
    rev: int | None = None,
    dropempty: bool = False,
):
    if (q is None) == (aphia_id is None):
        raise bad_parameter("Give exactly one of `q` or `aphia_id`.")
    if method is not None and method not in SEARCH_METHODS:
        raise bad_parameter(f"method must be one of {', '.join(SEARCH_METHODS)}.")
    if not 1 <= limit <= 100:
        raise bad_parameter("limit must be between 1 and 100.")
    view, header_rev = view_at(tree_id, rev, dropempty)
    state = view.state

    def result(ref, matched_on):
        path = [state.nodes[a].label for a in state.ancestor_ids(ref)] + [state.nodes[ref].label]
        return {**view.lite(ref), "path": "/".join(path), "matched_on": matched_on}

    if aphia_id is not None:
        hits = sorted(ref for ref, n in state.nodes.items() if n.aphia_id == aphia_id)
        data = {
            "tree": view.tree.id,
            "rev": view.rev,
            "aphia_id": aphia_id,
            "results": [result(ref, "aphia_id") for ref in hits[:limit]],
        }
        return respond(request, data, rev=header_rev)

    query = _normalise(q)
    candidates = [(ref, "label", _normalise(n.label)) for ref, n in state.nodes.items()]
    for ref, alias in NodeAlias.objects.filter(
        node_id__in=list(state.nodes), removed_at__isnull=True
    ).values_list("node_id", "alias"):
        candidates.append((ref, "alias", _normalise(alias)))

    methods = [method] if method else list(SEARCH_METHODS)
    fuzzy = _fuzzy_scores(query, [c[2] for c in candidates]) if "fuzzy" in methods else {}
    best = {}  # ref -> (rank, -score, label-first, matched_on)
    for ref, matched_on, text in candidates:
        for rank, name in enumerate(SEARCH_METHODS):
            if name not in methods:
                continue
            if name == "exact":
                hit, score = text == query, 1.0
            elif name == "prefix":
                hit, score = text.startswith(query), 1.0
            elif name == "substring":
                hit, score = query in text, 1.0
            else:
                hit, score = text in fuzzy, fuzzy.get(text, 0.0)
            if hit:
                key = (rank, -score, matched_on != "label", matched_on)
                if ref not in best or key < best[ref]:
                    best[ref] = key
                break
    ranked = sorted(best, key=lambda ref: (best[ref][:3], len(state.nodes[ref].label), ref))
    data = {
        "tree": view.tree.id,
        "rev": view.rev,
        "q": q,
        "results": [result(ref, best[ref][3]) for ref in ranked[:limit]],
    }
    return respond(request, data, rev=header_rev)
