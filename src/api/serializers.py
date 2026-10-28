"""Node shapes rendered from one TreeState per request (spec: node-read-api).

- lite:      {id, label, version, num_children, children}
- content:   {id, label, version, aphia_id, description, aliases, num_children, children}
- detailed:  every field, including lifetime fields, worms_data and worms_warnings
- deprecation record for nodes no longer in the requested revision

`depth` controls expansion: None expands everything, 0 leaves `children: null`.
Descriptions, aliases, successors and WoRMS warnings are always current, whatever
revision is requested; worms_data comes from the newest cached WoRMS record.
"""

from collections import defaultdict

from core.engine import TreeState, load_state
from core.models import Node, NodeAlias, Successor, Tree, current_descriptions
from worms.models import current_warnings
from worms.records import newest_rows

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
        self._descriptions: dict[int, str] = {}
        self._successors: dict[int, list] = {}
        self._warnings: dict[int, list] = {}
        self._worms: dict[int, dict | None] = {}

    def preload(self, ids=None):
        """Load lifetime fields, current descriptions, aliases, successors and WoRMS
        warnings, and cached WoRMS records, for `ids` (default: all)."""
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
        descriptions = current_descriptions(ids)
        warnings = current_warnings(ids)
        aphia_ids = [self.state.nodes[nid].aphia_id for nid in ids if nid in self.state.nodes]
        rows = newest_rows(a for a in aphia_ids if a is not None)
        for nid in ids:
            self._descriptions[nid] = descriptions.get(nid, "")
            self._aliases[nid] = aliases[nid]
            self._successors[nid] = successors[nid]
            self._warnings[nid] = warnings.get(nid, [])
            node = self.state.nodes.get(nid)
            row = rows.get(node.aphia_id) if node is not None else None
            self._worms[nid] = worms_data(row)

    def _out(self, node: dict) -> dict:
        return drop_empty(node) if self.dropempty else node

    def description(self, ref) -> str:
        self.preload([ref])
        return self._descriptions[ref]

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
                "description": self.description(ref),
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
            "description": self.description(ref),
            "aliases": self.aliases(ref),
            "aphia_id": n.aphia_id,
            "worms_data": self._worms[ref],
            "worms_warnings": self._warnings[ref],
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


def worms_data(row) -> dict | None:
    """The detailed node's `worms_data`: null if not cached or unknown to WoRMS."""
    if row is None or row.record is None:
        return None
    record = row.record
    return {
        "scientificname": record.get("scientificname"),
        "rank": record.get("rank"),
        "status": record.get("status"),
        "link": record.get("url")
        or f"https://www.marinespecies.org/aphia.php?p=taxdetails&id={row.aphia_id}",
        "fetched_at": row.fetched_at.isoformat(),
    }


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
