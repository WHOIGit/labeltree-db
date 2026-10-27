"""Applying atomic changes and the structural error conditions."""

from core.engine import apply_changes, check_changes

from .helpers import add, deprecate, edit, make_state, move, specs

# K(1) > L(3) > A(4);  J(2);  K > B(5)
BASE = [(1, "K", None), (2, "J", None), (3, "L", 1), (4, "A", 3), (5, "B", 1)]


def run(*changes, base=BASE):
    return apply_changes(make_state(base), specs(*changes))


def codes(result):
    return [(e["seq"], e["error"]) for e in result.errors]


# --- each op's effect -----------------------------------------------------------


def test_add_top_level_and_child_of_new_node():
    r = run(add("new:1", "X"), add("new:2", "Y", parent="new:1", description="d", aphia_id=7))
    assert r.errors == []
    assert r.state.child_ids(None) == [1, 2, "new:1"]
    assert r.state.child_ids("new:1") == ["new:2"]
    y = r.state.nodes["new:2"]
    assert (y.label, y.description, y.aphia_id, y.version) == ("Y", "d", 7, None)


def test_edit_changes_only_given_fields():
    r = run(edit(4, label="A2"), edit(4, aphia_id=12), edit(4, description="x"))
    a = r.state.nodes[4]
    assert (a.label, a.aphia_id, a.description, a.parent) == ("A2", 12, "x", 3)
    assert "A" not in r.state.by_label and r.state.by_label["A2"] == 4


def test_edit_clears_aphia_id():
    base = [(1, "K", None)]
    r = run(edit(1, aphia_id=5), edit(1, aphia_id=None), base=base)
    assert r.state.nodes[1].aphia_id is None


def test_move():
    r = run(move(3, 1, 2))
    assert r.errors == []
    assert r.state.child_ids(1) == [5] and r.state.child_ids(2) == [3]
    assert r.state.ancestor_ids(4) == [2, 3]


def test_move_to_top_level():
    r = run(move(4, 3, None))
    assert r.state.child_ids(None) == [1, 2, 4]


def test_deprecate_removes_node_and_frees_label():
    r = run(deprecate(5), add("new:1", "B", parent=2))
    assert r.errors == []
    assert 5 not in r.state and r.state.by_label["B"] == "new:1"


# --- structural errors ------------------------------------------------------------


def test_label_swap_through_temporary_label():
    r = run(edit(1, label="tmp"), edit(2, label="K"), edit(1, label="J"))
    assert r.errors == []


def test_direct_label_swap():
    r = run(edit(1, label="J"))
    assert codes(r) == [(1, "label_in_use")]


def test_error_report_shape():
    r = run(add("new:1", "X"), edit(4, label="A2"), move(5, 1, 2), add("new:2", "K"))
    assert r.errors == [
        {
            "seq": 4,
            "error": "label_in_use",
            "node": "new:2",
            "detail": "Label K is already used by node 1.",
        }
    ]


def test_label_is_case_sensitive():
    assert run(add("new:1", "k")).errors == []


def test_invalid_label():
    assert codes(run(add("new:1", "Chaetoceros didymus"))) == [(1, "invalid_label")]
    assert codes(run(edit(4, label="a/b"))) == [(1, "invalid_label")]


def test_node_not_in_tree():
    assert codes(run(edit(99, label="Z"))) == [(1, "node_not_in_tree")]
    assert codes(run(deprecate(5), edit(5, label="Z"))) == [(2, "node_not_in_tree")]


def test_cycle():
    assert codes(run(move(1, None, 4))) == [(1, "cycle")]
    assert codes(run(move(3, 1, 3))) == [(1, "cycle")]


def test_deprecating_node_with_children():
    assert codes(run(deprecate(3))) == [(1, "has_children")]


def test_stale_from_parent():
    assert codes(run(move(4, 1, 2))) == [(1, "from_parent_mismatch")]


def test_parent_in_another_tree():
    # Node 30 belongs to another tree, so it isn't in this tree's state.
    assert codes(run(add("new:1", "X", parent=30))) == [(1, "parent_not_in_tree")]


def test_move_under_deprecated_node():
    # D(6) was deprecated in an earlier revision, so it is absent from the base state.
    assert codes(run(move(4, 3, 6))) == [(1, "parent_not_in_tree")]


def test_add_under_node_deprecated_earlier_in_changeset():
    assert codes(run(deprecate(5), add("new:1", "X", parent=5))) == [(2, "parent_not_in_tree")]


def test_successor_added_later_in_same_changeset():
    r = run(deprecate(5, successors=["new:1"]), add("new:1", "X", parent=1))
    assert r.errors == []


def test_successor_deprecated_in_same_changeset():
    r = run(deprecate(5), deprecate(4, successors=[5]))
    assert codes(r) == [(2, "invalid_successor")]


def test_successor_deprecated_later_in_same_changeset():
    r = run(deprecate(4, successors=[5]), deprecate(5))
    assert codes(r) == [(1, "invalid_successor")]


def test_self_as_successor():
    assert codes(run(deprecate(4, successors=[4]))) == [(1, "invalid_successor")]


def test_successor_may_be_new_node():
    r = run(add("new:1", "X", parent=1), deprecate(5, successors=["new:1"]))
    assert r.errors == []


def test_failures_do_not_stop_later_changes():
    r = run(edit(1, label="J"), move(4, 3, 2), add("new:1", "K"), edit(1, label="K2"))
    assert codes(r) == [(1, "label_in_use"), (3, "label_in_use")]
    assert r.state.nodes[4].parent == 2
    assert r.state.by_label["K2"] == 1


def test_malformed_changes():
    r = run(
        {"op": "rename", "node": 1},
        {"op": "edit", "node": 1},
        {"op": "add", "node": 7, "label": "X", "parent": None},
        add("new:1", "X"),
        add("new:1", "Y"),
    )
    assert [e["error"] for e in r.errors] == ["invalid_change"] * 4
    assert [e["seq"] for e in r.errors] == [1, 2, 3, 5]


def test_empty_changeset():
    result = check_changes(make_state(BASE), specs(edit(1, label="K")))
    assert result.reduced == []
    assert [e["error"] for e in result.errors] == ["empty_changeset"]
