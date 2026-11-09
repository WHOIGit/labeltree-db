"""Placement checks against WoRMS (spec: worms-placement-checks).

Pure functions of a TreeState plus cached records, so validate, save, publish
and syncs compute warnings identically. `records` maps an AphiaID to its cached record
(with `lineage`), or to None if WoRMS has no record for it. An AphiaID missing
from `records` is unavailable: a node whose checks need it gets None instead of
a warning list.

A node is anchored if it has an aphia_id. Unanchored nodes are walked past when
looking for a node's nearest anchored ancestor.

`Lineages` holds what the cached records of a whole tree say beyond the records
a check needs: which AphiaIDs have a given AphiaID in their lineage (for the
recheck scope) and which are synonyms of which (to match nodes). It never makes
a check unavailable: what isn't cached is filled in by the next sync.
"""

from collections import defaultdict

from core.engine import ChangeSpec, NodeRef, TreeState, apply_changes, ref_sort_key

WARNINGS = (
    "out_of_lineage", "unaccepted_aphia", "unknown_aphia", "duplicate_aphia",
    "misplaced_lineage_ancestor",
)  # fmt: skip


def is_synonym(record: dict) -> bool:
    """WoRMS points this name to a different accepted AphiaID, whatever its status
    (`unaccepted`, `superseded combination`, `junior subjective synonym`, and some
    `unassessed` names)."""
    valid = record.get("valid_AphiaID")
    return valid is not None and valid != record["AphiaID"]


class Lineages:
    """From cached records ({aphia_id: record or None}): `valid`, each synonym's
    accepted AphiaID, and `holders`, the AphiaIDs whose lineage holds an AphiaID."""

    def __init__(self, records: dict | None = None):
        self.valid: dict[int, int] = {}
        self._holders: dict[int, set[int]] = defaultdict(set)
        for aphia, record in (records or {}).items():
            if record is None:
                continue
            if is_synonym(record):
                self.valid[aphia] = record["valid_AphiaID"]
            for entry in record.get("lineage") or []:
                if entry["AphiaID"] != aphia:
                    self._holders[entry["AphiaID"]].add(aphia)

    def accepted(self, aphia: int) -> int:
        return self.valid.get(aphia, aphia)

    def holders(self, aphia: int) -> set[int]:
        return self._holders.get(aphia, set())


NO_LINEAGES = Lineages()


def tree_aphia_ids(base: TreeState, changes: list[ChangeSpec] = ()) -> set[int]:
    """The AphiaIDs of `base` and those `changes` give, whose cached records make
    the tree's `Lineages`."""
    ids = {n.aphia_id for n in base.nodes.values()}
    ids |= {c.payload.get("aphia_id") for c in changes if isinstance(c.payload, dict)}
    return ids - {None}


def nearest_anchored_ancestor(state: TreeState, ref: NodeRef) -> NodeRef | None:
    parent = state.nodes[ref].parent
    while parent is not None:
        if state.nodes[parent].aphia_id is not None:
            return parent
        parent = state.nodes[parent].parent
    return None


def aphia_index(state: TreeState) -> dict[int, list[NodeRef]]:
    index = defaultdict(list)
    for ref, node in state.nodes.items():
        if node.aphia_id is not None:
            index[node.aphia_id].append(ref)
    return index


def taxon_index(state: TreeState, lineages: Lineages) -> dict[int, list[NodeRef]]:
    """Nodes by accepted AphiaID: a synonym's node is listed under the accepted
    AphiaID, which is what WoRMS lineages hold."""
    index = defaultdict(list)
    for ref, node in state.nodes.items():
        if node.aphia_id is not None:
            index[lineages.accepted(node.aphia_id)].append(ref)
    return index


def needed_aphia_ids(state: TreeState, node_ids) -> set[int]:
    """The records checking `node_ids` may need: each anchored node's own, and its
    nearest anchored ancestor's."""
    needed = set()
    for ref in node_ids:
        node = state.nodes.get(ref)
        if node is None or node.aphia_id is None:
            continue
        needed.add(node.aphia_id)
        if (anchor := nearest_anchored_ancestor(state, ref)) is not None:
            needed.add(state.nodes[anchor].aphia_id)
    return needed


def _warning(code: str, detail: str) -> dict:
    return {"warning": code, "detail": detail}


def _check_one(state: TreeState, ref, records, index, taxa) -> list[dict] | None:
    node = state.nodes[ref]
    aphia = node.aphia_id
    if aphia is None:
        return []
    if aphia not in records:
        return None
    record = records[aphia]
    warnings = []

    anchor = nearest_anchored_ancestor(state, ref)
    lineage = [x["AphiaID"] for x in (record or {}).get("lineage") or []]
    # Where the nearest anchored ancestor sits in the lineage; None if it doesn't.
    start = 0
    if record is not None and anchor is not None:
        ancestor = state.nodes[anchor]
        start = None
        if ancestor.aphia_id in lineage:
            start = lineage.index(ancestor.aphia_id) + 1
        else:
            # WoRMS lineages hold accepted names only, so a synonym ancestor is
            # compared by the AphiaID it points to.
            if ancestor.aphia_id not in records:
                return None
            ancestor_record = records[ancestor.aphia_id]
            # An ancestor unknown to WoRMS has its own unknown_aphia warning.
            valid = ancestor_record.get("valid_AphiaID") if ancestor_record else None
            if valid in lineage:
                start = lineage.index(valid) + 1
            elif ancestor_record is not None:
                warnings.append(
                    _warning(
                        "out_of_lineage",
                        f"Nearest anchored ancestor {ancestor.label} ({ancestor.aphia_id}) is "
                        f"not in the WoRMS lineage of {record.get('scientificname')} ({aphia}).",
                    )
                )

    if record is not None and start is not None:
        warnings += _misplaced(state, ref, record, lineage[start:], anchor, taxa)

    if record is not None and is_synonym(record):
        warnings.append(
            _warning(
                "unaccepted_aphia",
                f"WoRMS lists AphiaID {aphia} ({record.get('scientificname')}) as "
                f"{record.get('status')}, with accepted AphiaID {record['valid_AphiaID']} "
                f"({record.get('valid_name')}).",
            )
        )

    if record is None:
        warnings.append(_warning("unknown_aphia", f"WoRMS has no record for AphiaID {aphia}."))

    others = [o for o in index.get(aphia, ()) if o != ref]
    if others:
        # Labels, not ids: details computed on a draft would otherwise hold placeholders.
        names = ", ".join(sorted(state.nodes[o].label for o in others))
        warnings.append(_warning("duplicate_aphia", f"AphiaID {aphia} is also used by {names}."))
    return warnings


def _misplaced(state: TreeState, ref, record, below, anchor, taxa) -> list[dict]:
    """misplaced_lineage_ancestor: one per AphiaID of the lineage `below` the
    nearest anchored ancestor that another node has."""
    node = state.nodes[ref]
    own = {node.aphia_id, record.get("valid_AphiaID")}
    names = {x["AphiaID"]: x.get("scientificname") for x in record.get("lineage") or []}
    where = f" between {state.nodes[anchor].label} and it" if anchor is not None else ""
    warnings = []
    for aphia in below:
        holders = [o for o in taxa.get(aphia, ()) if o != ref]
        if aphia in own or not holders:
            continue
        labels = ", ".join(sorted(state.nodes[o].label for o in holders))
        warnings.append(
            _warning(
                "misplaced_lineage_ancestor",
                f"{labels} ({names.get(aphia)}, {aphia}) is in the WoRMS lineage of "
                f"{node.label}{where}, but the tree doesn't place {node.label} under it.",
            )
        )
    return warnings


def check_nodes(
    state: TreeState, node_ids, records: dict, lineages: Lineages = NO_LINEAGES
) -> dict[NodeRef, list[dict] | None]:
    """Warnings for each of `node_ids` in `state` ([] if none, None if unavailable).
    Nodes not in `state` are skipped."""
    index, taxa = aphia_index(state), taxon_index(state, lineages)
    return {
        ref: _check_one(state, ref, records, index, taxa) for ref in node_ids if ref in state.nodes
    }


# --- Recheck scope ------------------------------------------------------------------


def first_anchored_below(state: TreeState, ref: NodeRef) -> set[NodeRef]:
    """The first anchored node on each path down from `ref` (excluding `ref`)."""
    found = set()
    stack = list(state.child_ids(ref))
    while stack:
        child = stack.pop()
        if state.nodes[child].aphia_id is not None:
            found.add(child)
        else:
            stack.extend(state.child_ids(child))
    return found


def recheck_scope(
    before: TreeState, after: TreeState, change: ChangeSpec, lineages: Lineages = NO_LINEAGES
) -> set[NodeRef]:
    """Nodes whose warnings one change can affect: the node it changes, the first
    anchored node on each path below it, every other node with an AphiaID the
    node had or now has, and every node whose cached lineage holds one of those
    AphiaIDs. Ancestors are otherwise not affected. Only nodes in `after`."""
    ref = change.node
    scope = set()
    if ref in after.nodes:
        scope.add(ref)
        scope |= first_anchored_below(after, ref)
    aphias = {s.nodes[ref].aphia_id for s in (before, after) if ref in s.nodes} - {None}
    if aphias:
        index = aphia_index(after)
        for aphia in aphias:
            scope.update(index.get(aphia, ()))
            for holder in lineages.holders(lineages.accepted(aphia)):
                scope.update(index.get(holder, ()))
    return scope


# --- Checks for a change list ---------------------------------------------------------


def _steps(base: TreeState, changes: list[ChangeSpec], lineages: Lineages):
    """(change, before, after, scope) for each change, applied in order. A change
    with a structural error leaves the state as it was."""
    state = base
    for change in changes:
        after = apply_changes(state, [change]).state
        yield change, state, after, recheck_scope(state, after, change, lineages)
        state = after


def needed_for_changes(
    base: TreeState, changes: list[ChangeSpec], lineages: Lineages = NO_LINEAGES
) -> set[int]:
    """Every AphiaID whose record checking `changes` may need."""
    needed = set()
    for _, before, after, scope in _steps(base, changes, lineages):
        needed |= needed_aphia_ids(before, scope) | needed_aphia_ids(after, scope)
    return needed


def change_checks(
    base: TreeState, changes: list[ChangeSpec], records: dict, lineages: Lineages = NO_LINEAGES
):
    """Per change, the warnings it causes ([{warning, node, detail}]), or
    "unavailable" if a record it needs is missing; plus every node rechecked.

    A change causes a warning if one of the nodes it rechecks has it afterwards
    and didn't have it before.
    """
    results, rechecked = [], set()
    for _, before, after, scope in _steps(base, changes, lineages):
        rechecked |= scope
        now = check_nodes(after, scope, records, lineages)
        earlier = check_nodes(before, scope, records, lineages)
        if any(v is None for v in (*now.values(), *earlier.values())):
            results.append("unavailable")
            continue
        results.append(
            [
                {"warning": w["warning"], "node": ref, "detail": w["detail"]}
                for ref in sorted(now, key=ref_sort_key)
                for w in now[ref]
                if w not in earlier.get(ref, [])
            ]
        )
    return results, rechecked
