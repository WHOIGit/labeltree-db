"""Validating a change list without storing it (spec: changeset-api).

`validate` reduces and checks changes against the tree's latest revision, so a
stale draft shows what publishing after a rebase would do, and reports the
stale base as a conflict. WoRMS checks use cached records only. The result is
what `POST /changesets/validate` returns, and what `GET /changesets/{cs}`
reports for a draft.
"""

from core.engine import ChangeSpec, TreeState, check_changes, load_state, ref_sort_key, refs_in
from worms.checks import change_checks, check_nodes, needed_for_changes
from worms.models import current_warnings
from worms.records import cached_records

from .changesets import ChangesetError, latest_rev
from .models import Node, NodeVersion, Tree


def validate(
    specs: list[ChangeSpec], *, tree_id: str | None = None, base_rev: int | None = None,
    new_tree_id: str | None = None,
) -> dict:  # fmt: skip
    """Check `specs` (as submitted) against an existing tree's latest revision, or
    against an empty new tree. Raises ChangesetError(invalid_base_rev)."""
    conflicts = []
    if tree_id is not None:
        latest = latest_rev(tree_id)
        if not isinstance(base_rev, int) or not 1 <= base_rev <= latest:
            raise ChangesetError(
                "invalid_base_rev",
                f"Tree {tree_id} has no revision {base_rev}; latest is {latest}.",
            )
        base = load_state(tree_id, latest)
    else:
        latest = None
        base = TreeState(new_tree_id, 0)
        if Tree.objects.filter(pk=new_tree_id).exists():
            conflicts.append(
                {"error": "tree_exists", "detail": f"Tree {new_tree_id} already exists."}
            )

    result = check_changes(base, specs)
    if tree_id is not None and base_rev < latest:
        conflicts.append(_stale_base(result.reduced, base_rev, latest))

    needed = needed_for_changes(base, result.reduced)
    records = cached_records(needed)
    checks, rechecked = change_checks(base, result.reduced, records)
    warnings = [
        {"seq": change.seq, **warning}
        for change, check in zip(result.reduced, checks, strict=True)
        if check != "unavailable"
        for warning in check
    ]
    unchecked = [c.seq for c, check in zip(result.reduced, checks, strict=True)
                 if check == "unavailable"]  # fmt: skip

    return {
        "tree": tree_id or new_tree_id,
        "base_rev": base_rev,
        "latest_rev": latest,
        "ok": not result.errors and not conflicts,
        "errors": result.errors,
        "conflicts": conflicts,
        "reduced_changes": result.reduced,
        "version_changes": [vc.as_dict() for vc in result.version_changes],
        "node_changes": result.node_changes,
        "warnings": warnings,
        "warning_changes": _warning_changes(result.state, rechecked, records),
        "unchecked": unchecked,
        "worms_missing": sorted(needed - records.keys()),
        "worms": "unavailable" if unchecked else "ok",
    }


def _stale_base(reduced: list[ChangeSpec], base_rev: int, latest: int) -> dict:
    """The stale_base conflict, with the touched nodes later revisions changed."""
    touched = {ref for c in reduced for ref in refs_in(c) if isinstance(ref, int)}
    deprecated_in = dict(Node.objects.filter(id__in=touched).values_list("id", "deprecated_in_rev"))
    versions = {}
    for node, version, frm, to in NodeVersion.objects.filter(node_id__in=touched).values_list(
        "node_id", "version", "valid_from_rev", "valid_to_rev"
    ):
        versions.setdefault(node, []).append((version, frm, to))
    nodes = []
    for node in sorted(versions):
        revs = {frm for _, frm, _ in versions[node] if frm > base_rev}
        if (gone := deprecated_in.get(node)) is not None and gone > base_rev:
            revs.add(gone)
        if not revs:
            continue
        at_base = next(
            (
                v
                for v, frm, to in versions[node]
                if frm <= base_rev and (to is None or to > base_rev)
            ),
            None,
        )
        current = next((v for v, _, to in versions[node] if to is None), None)
        listed = ", ".join(map(str, sorted(revs)))
        nodes.append({
            "node": node, "base_version": at_base, "latest_version": current,
            "detail": f"Changed in revision{'s' if len(revs) > 1 else ''} {listed}.",
        })  # fmt: skip
    return {
        "error": "stale_base",
        "detail": f"Base revision {base_rev} is behind latest revision {latest}.",
        "nodes": nodes,
    }


def _warning_changes(final: TreeState, rechecked, records) -> list[dict]:
    """Existing nodes whose current warnings the changes would change."""
    existing = [ref for ref in rechecked if isinstance(ref, int)]
    now = check_nodes(final, existing, records)
    current = current_warnings(existing)
    changes = []
    for ref in sorted(now, key=ref_sort_key):
        if now[ref] is None:
            continue
        before = [w["warning"] for w in current.get(ref, [])]
        after = [w["warning"] for w in now[ref]]
        added = [w for w in after if w not in before]
        removed = [w for w in before if w not in after]
        if added or removed:
            changes.append({"node": ref, "added": added, "removed": removed})
    return changes
