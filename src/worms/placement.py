"""Placing a WoRMS record in a tree (spec: quick-add).

The same rules as the web app's Add from WoRMS (`wormsLabel` and `suggestParent`
in static/app/expanders.js), except that a tie for the parent is reported
instead of broken arbitrarily. `tests/label_cases.json` holds label cases
both implementations are tested against.
"""

import re

from core.engine import NodeRef, TreeState

from .checks import aphia_index


def worms_label(name: str | None) -> str:
    """A scientific name as a label: whitespace to `_`, characters that aren't
    machine-safe dropped, leading punctuation removed."""
    label = re.sub(r"\s+", "_", (name or "").strip())
    label = re.sub(r"[^A-Za-z0-9_.-]", "", label)
    return re.sub(r"^[^A-Za-z0-9]+", "", label)


def lineage_parent(
    state: TreeState, lineage: list[dict], aphia_id: int | None = None
) -> tuple[NodeRef | None, list[NodeRef]]:
    """The parent for a record with `lineage` (top level first): the live node
    anchored to the deepest lineage AphiaID that any node is anchored to, other
    than `aphia_id` itself.

    Returns (node, []), (None, candidates) when several nodes tie, or (None, [])
    when nothing in the lineage is in the tree.
    """
    index = aphia_index(state)
    for entry in reversed(lineage):
        if entry["AphiaID"] == aphia_id or not (anchored := index.get(entry["AphiaID"])):
            continue
        if len(anchored) == 1:
            return anchored[0], []
        return None, sorted(anchored)
    return None, []
