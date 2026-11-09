"""Label and parent rules for placing a WoRMS record (spec: quick-add)."""

import json
from pathlib import Path

import pytest

from core.engine import NodeState, TreeState
from worms.placement import lineage_parent, worms_label

LABEL_CASES = json.loads((Path(__file__).parent / "label_cases.json").read_text())

# Chaetoceros debilis (149128) and its lineage, top level first.
LINEAGE = [
    {"AphiaID": 1, "scientificname": "Biota"},
    {"AphiaID": 7, "scientificname": "Chromista"},
    {"AphiaID": 148899, "scientificname": "Bacillariophyceae"},
    {"AphiaID": 148984, "scientificname": "Chaetocerotaceae"},
    {"AphiaID": 148985, "scientificname": "Chaetoceros"},
    {"AphiaID": 149128, "scientificname": "Chaetoceros debilis"},
]


def state(*nodes):
    """nodes: (id, label, parent, aphia_id)."""
    return TreeState("t", 1, [NodeState(i, lb, p, a, 1) for i, lb, p, a in nodes])


@pytest.mark.parametrize(("name", "label"), LABEL_CASES)
def test_worms_label(name, label):
    assert worms_label(name) == label


def test_nearest_anchored_ancestor():
    s = state((1, "Bacillariophyceae", None, 148899), (2, "Chaetoceros", 1, 148985),
              (3, "other", None, None))  # fmt: skip
    assert lineage_parent(s, LINEAGE, 149128) == (2, [])


def test_skips_unanchored_levels():
    s = state((1, "Bacillariophyceae", None, 148899), (2, "diatoms_misc", 1, None))
    assert lineage_parent(s, LINEAGE, 149128) == (1, [])


def test_nothing_anchored():
    s = state((1, "detritus", None, None), (2, "Dinophysis", None, 109462))
    assert lineage_parent(s, LINEAGE, 149128) == (None, [])


def test_tie_at_the_deepest_level():
    s = state((1, "Bacillariophyceae", None, 148899), (812, "Chaetoceros", 1, 148985),
              (977, "Chaetoceros_sp", 1, 148985))  # fmt: skip
    assert lineage_parent(s, LINEAGE, 149128) == (None, [812, 977])


def test_the_record_itself_is_not_a_parent():
    s = state((1, "Chaetoceros", None, 148985), (2, "Chaetoceros_debilis", 1, 149128))
    assert lineage_parent(s, LINEAGE, 149128) == (1, [])
