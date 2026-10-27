"""Node shapes rendered from one TreeState per request (spec: node-read-api).

- lite:      {id, label, version, num_children, children}
- content:   {id, label, version, aphia_id, description, aliases, num_children, children}
- detailed:  every field, including lifetime fields and WoRMS placeholders
- deprecation record for nodes no longer in the requested revision

`depth` controls expansion: None expands everything, 0 leaves `children: null`.
Aliases and successors are always current, whatever revision is requested.
"""

from collections import defaultdict

from core.engine import TreeState, load_state
from core.models import Node, NodeAlias, Successor, Tree

from .conventions import drop_empty


def _next(depth):
    return None if depth is None else depth - 1


class RevisionView:
    def __init__(self, tree: Tree, rev: int, *, state: TreeState | None = None, dropempty=False):
        self.tree = tree
        self.rev = rev
        self.state = state if state is not None else load_state(tree.id, rev)
        self.dropempty = dropempty
        self._meta: dict[int, tuple] = {}
        self._aliases: dict[int, list] = {}
        self._successors: dict[int, list] = {}

    def preload(self, ids=None):
        """Load lifetime fields, current aliases and successors for `ids` (default: all)."""
        ids = list(self.state.nodes) if ids is None else [i for i in ids if i not in self._meta]
        if not ids:
            return
        for nid, created, deprecated in Node.objects.filter(id__in=ids).values_list(
            "id", "created_in_rev", "deprecated_in_rev"
        ):
            self._meta[nid] = (created, deprecated)
        aliases = defaultdict(list)
        for nid, aid, alias in (
            NodeAlias.objects.filter(node_id__in=ids, removed_at__isnull=True)
            .order_by("id")
            .values_list("node_id", "id", "alias")
        ):
            aliases[nid].append({"id": aid, "alias": alias})
        successors = defaultdict(list)
        for nid, sid in (
            Successor.objects.filter(deprecated_node_id__in=ids)
            .order_by("position")
            .values_list("deprecated_node_id", "successor_node_id")
        ):
            successors[nid].append(sid)
        for nid in ids:
            self._aliases[nid] = aliases[nid]
            self._successors[nid] = successors[nid]

    def _out(self, node: dict) -> dict:
        return drop_empty(node) if self.dropempty else node

    def aliases(self, ref) -> list[dict]:
        self.preload([ref])
        return self._aliases[ref]

    def lite(self, ref, depth=0) -> dict:
        n = self.state.nodes[ref]
        children = None
        if depth is None or depth > 0:
            children = [self.lite(c, _next(depth)) for c in self.state.child_ids(ref)]
        return self._out(
            {
                "id": ref,
                "label": n.label,
                "version": n.version,
                "num_children": self.state.num_children(ref),
                "children": children,
            }
        )

    def content(self, ref, depth=None) -> dict:
        n = self.state.nodes[ref]
        children = None
        if depth is None or depth > 0:
            children = [self.content(c, _next(depth)) for c in self.state.child_ids(ref)]
        return self._out(
            {
                "id": ref,
                "label": n.label,
                "version": n.version,
                "aphia_id": n.aphia_id,
                "description": n.description,
                "aliases": [a["alias"] for a in self.aliases(ref)],
                "num_children": self.state.num_children(ref),
                "children": children,
            }
        )

    def detailed(self, ref, *, nested=False, parent=True) -> dict:
        """Detailed node. `nested` expands children as detailed nodes (export)."""
        self.preload([ref])
        n = self.state.nodes[ref]
        created, deprecated = self._meta[ref]
        if nested:
            children = [
                self.detailed(c, nested=True, parent=parent) for c in self.state.child_ids(ref)
            ]
        else:
            children = [self.lite(c) for c in self.state.child_ids(ref)]
        node = {
            "id": ref,
            "version": n.version,
            "tree": self.tree.id,
            "rev": self.rev,
            "label": n.label,
            "description": n.description,
            "aliases": self.aliases(ref),
            "aphia_id": n.aphia_id,
            "worms_data": None,
            "worms_warnings": [],
            "tree_depth": self.state.depth(ref),
            "num_children": self.state.num_children(ref),
            "parent": self.lite(n.parent) if n.parent is not None else None,
            "children": children,
            "created_in_rev": created,
            "deprecated_in_rev": deprecated,
            "successors": self._successors[ref],
        }
        if not parent:
            del node["parent"]
        return self._out(node)


def deprecation_record(node: Node, rev: int, *, dropempty=False) -> dict:
    """What a node lookup returns for a node deprecated at or before `rev`."""
    last = node.versions.order_by("-version").first()
    record = {
        "id": node.id,
        "tree": node.tree_id,
        "rev": rev,
        "label": last.label if last else None,
        "last_version": last.version if last else None,
        "deprecated_in_rev": node.deprecated_in_rev,
        "successors": list(
            Successor.objects.filter(deprecated_node=node)
            .order_by("position")
            .values_list("successor_node_id", flat=True)
        ),
    }
    return drop_empty(record) if dropempty else record
