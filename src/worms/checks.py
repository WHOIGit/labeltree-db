"""Placement checks against WoRMS (spec: worms-placement-checks).

Pure functions of a TreeState plus cached records, so save, publish and drift
compute warnings identically. `records` maps an AphiaID to its cached record
(with `lineage`), or to None if WoRMS has no record for it. An AphiaID missing
from `records` is unavailable: a node whose checks need it gets None instead of
a warning list.

A node is anchored if it has an aphia_id. Unanchored nodes are walked past when
looking for a node's nearest anchored ancestor.
"""

from collections import defaultdict

from core.engine import ChangeSpec, NodeRef, TreeState, apply_changes, ref_sort_key

WARNINGS = ("out_of_lineage", "unaccepted_aphia", "unknown_aphia", "duplicate_aphia")


def is_synonym(record: dict) -> bool:
    """WoRMS points this name to a different accepted AphiaID, whatever its status
    (`unaccepted`, `superseded combination`, `junior subjective synonym`, and some
    `unassessed` names)."""
    valid = record.get("valid_AphiaID")
    return valid is not None and valid != record["AphiaID"]


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


def _check_one(state: TreeState, ref, records, index) -> list[dict] | None:
    node = state.nodes[ref]
    aphia = node.aphia_id
    if aphia is None:
        return []
    if aphia not in records:
        return None
    record = records[aphia]
    warnings = []

    anchor = nearest_anchored_ancestor(state, ref)
    if record is not None and anchor is not None:
        ancestor = state.nodes[anchor]
        lineage = {x["AphiaID"] for x in record.get("lineage") or []}
        if ancestor.aphia_id not in lineage:
            # WoRMS lineages hold accepted names only, so a synonym ancestor is
            # compared by the AphiaID it points to.
            if ancestor.aphia_id not in records:
                return None
            ancestor_record = records[ancestor.aphia_id]
            # An ancestor unknown to WoRMS has its own unknown_aphia warning.
            valid = ancestor_record.get("valid_AphiaID") if ancestor_record else None
            if ancestor_record is not None and valid not in lineage:
                warnings.append(
                    _warning(
                        "out_of_lineage",
                        f"Nearest anchored ancestor {ancestor.label} ({ancestor.aphia_id}) is "
                        f"not in the WoRMS lineage of {record.get('scientificname')} ({aphia}).",
                    )
                )

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


def check_nodes(state: TreeState, node_ids, records: dict) -> dict[NodeRef, list[dict] | None]:
    """Warnings for each of `node_ids` in `state` ([] if none, None if unavailable).
    Nodes not in `state` are skipped."""
    index = aphia_index(state)
    return {ref: _check_one(state, ref, records, index) for ref in node_ids if ref in state.nodes}


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


def recheck_scope(before: TreeState, after: TreeState, change: ChangeSpec) -> set[NodeRef]:
    """Nodes whose warnings one change can affect: the node it changes, the first
    anchored node on each path below it, and every other node with an AphiaID the
    node had or now has. Ancestors are never affected. Only nodes in `after`."""
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
    return scope


# --- Checks for a change list ---------------------------------------------------------


def _steps(base: TreeState, changes: list[ChangeSpec]):
    """(change, before, after, scope) for each change, applied in order. A change
    with a structural error leaves the state as it was."""
    state = base
    for change in changes:
        after = apply_changes(state, [change]).state
        yield change, state, after, recheck_scope(state, after, change)
        state = after


def needed_for_changes(base: TreeState, changes: list[ChangeSpec]) -> set[int]:
    """Every AphiaID whose record checking `changes` may need."""
    needed = set()
    for _, before, after, scope in _steps(base, changes):
        needed |= needed_aphia_ids(before, scope) | needed_aphia_ids(after, scope)
    return needed


def changed_aphia_ids(changes: list[ChangeSpec]) -> set[int]:
    """AphiaIDs that `add` and `edit` changes set: publish re-fetches these."""
    return {
        c.payload["aphia_id"]
        for c in changes
        if c.op in ("add", "edit")
        and isinstance(c.payload, dict)
        and isinstance(c.payload.get("aphia_id"), int)
    }


def change_checks(base: TreeState, changes: list[ChangeSpec], records: dict):
    """Per change, the warnings it causes ([{warning, node, detail}]), or
    "unavailable" if a record it needs is missing; plus every node rechecked.

    A change causes a warning if one of the nodes it rechecks has it afterwards
    and didn't have it before.
    """
    results, rechecked = [], set()
    for _, before, after, scope in _steps(base, changes):
        rechecked |= scope
        now = check_nodes(after, scope, records)
        earlier = check_nodes(before, scope, records)
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
