"""Net per-node diff and version increases (design/backend.md, Versioning example)."""

from core.engine import apply_changes, version_changes

from .helpers import add, advance, deprecate, edit, make_state, move, specs

CHAETOCEROS, C_DIDYMUS, THALASSIOSIRA, ROOT = 10, 11, 20, 1


def test_five_revision_example():
    # rev 1: Chaetoceros > C_didymus; Thalassiosira. Both genera under a common root.
    s1 = make_state(
        [
            (ROOT, "Bacillariophyceae", None),
            (CHAETOCEROS, "Chaetoceros", ROOT),
            (C_DIDYMUS, "C_didymus", CHAETOCEROS),
            (THALASSIOSIRA, "Thalassiosira", ROOT),
        ]
    )

    s2, bumps = advance(s1, add("new:1", "C_socialis", parent=CHAETOCEROS))
    assert bumps == {CHAETOCEROS: (1, 2), "new:1": (None, 1)}

    s3, bumps = advance(s2, edit(C_DIDYMUS, label="C_didymus_sl"))
    assert bumps == {C_DIDYMUS: (1, 2)}  # child renamed: no bump for Chaetoceros

    s4, bumps = advance(s3, move("new:1", CHAETOCEROS, THALASSIOSIRA))
    assert bumps == {CHAETOCEROS: (2, 3), "new:1": (1, 2), THALASSIOSIRA: (1, 2)}

    s5, bumps = advance(
        s4, deprecate(C_DIDYMUS), edit(CHAETOCEROS, description="Genus of centric diatoms")
    )
    assert bumps == {CHAETOCEROS: (3, 4), C_DIDYMUS: (2, None)}  # one bump for two reasons

    assert {ref: n.version for ref, n in s5.nodes.items()} == {
        ROOT: 1,
        CHAETOCEROS: 4,
        "new:1": 2,
        THALASSIOSIRA: 2,
    }


def bumps_for(base, *changes):
    result = apply_changes(base, specs(*changes))
    return {vc.node: (vc.from_version, vc.to_version) for vc in version_changes(base, result.state)}


TREE = [(1, "G", None), (2, "P", 1), (3, "N", 2), (4, "C", 3), (5, "Q", None)]


def test_grandparent_moved():
    assert bumps_for(make_state(TREE), move(2, 1, 5)) == {1: (1, 2), 2: (1, 2), 5: (1, 2)}


def test_moved_and_renamed_bumps_once():
    assert bumps_for(make_state(TREE), move(3, 2, 5), edit(3, label="N2"))[3] == (1, 2)


def test_rename_and_back_is_no_bump():
    assert bumps_for(make_state(TREE), edit(3, label="tmp"), edit(3, label="N")) == {}


def test_child_deprecated_and_parent_edited():
    assert bumps_for(make_state(TREE), deprecate(4), edit(3, description="x")) == {
        3: (1, 2),
        4: (1, None),
    }
