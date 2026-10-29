"""Op reduction on save."""

from core.engine import apply_changes, check_changes, reduce_changes, specs_from_dicts

from .helpers import add, deprecate, edit, make_state, move, specs

# P(1), Q(2), R(3) top level; A(4) "x" under P; B(5) "y" under P
BASE = [(1, "P", None), (2, "Q", None), (3, "R", None), (4, "x", 1), (5, "y", 1)]


def reduce(*changes, base=BASE):
    return [c.as_dict() for c in reduce_changes(make_state(base), specs(*changes))]


def test_two_renames():
    assert reduce(edit(4, label="y2"), move(5, 1, 2), edit(4, label="z")) == [
        {"seq": 1, "op": "move", "group": None, "node": 5, "from_parent": 1, "to_parent": 2},
        {"seq": 2, "op": "edit", "group": None, "node": 4, "label": "z"},
    ]


def test_edits_merge_net_fields():
    assert reduce(edit(4, label="a", aphia_id=3), edit(4, label="b")) == [
        {"seq": 1, "op": "edit", "group": None, "node": 4, "label": "b",
         "aphia_id": 3},
    ]  # fmt: skip


def test_two_moves():
    assert reduce(move(4, 1, 2), move(4, 2, 3)) == [
        {"seq": 1, "op": "move", "group": None, "node": 4, "from_parent": 1, "to_parent": 3},
    ]


def test_edit_of_new_node_folds_into_add():
    assert reduce(add("new:1", "a", parent=1), edit("new:1", label="b")) == [
        {"seq": 1, "op": "add", "group": None, "node": "new:1", "label": "b", "parent": 1},
    ]


def test_move_of_new_node_folds_into_add():
    assert reduce(add("new:1", "a", parent=1), move("new:1", 1, 2)) == [
        {"seq": 1, "op": "add", "group": None, "node": "new:1", "label": "a", "parent": 2},
    ]


def test_folded_add_takes_last_position():
    out = reduce(add("new:1", "a"), edit(4, label="w"), edit("new:1", aphia_id=5))
    assert [(c["op"], c["node"]) for c in out] == [("edit", 4), ("add", "new:1")]


def test_rename_and_rename_back():
    assert reduce(edit(4, label="tmp"), edit(4, label="x")) == []


def test_partial_no_op_edit_keeps_real_fields():
    assert reduce(edit(4, label="tmp", aphia_id=5), edit(4, label="x")) == [
        {"seq": 1, "op": "edit", "group": None, "node": 4, "aphia_id": 5},
    ]


def test_move_back_to_original_parent():
    assert reduce(move(4, 1, 2), move(4, 2, 1)) == []


def test_add_then_deprecate():
    assert reduce(add("new:1", "a", parent=1), edit("new:1", label="b"), deprecate("new:1")) == []


def test_label_swap_is_kept():
    changes = (edit(4, label="tmp"), edit(5, label="x"), edit(4, label="y"))
    assert [c["seq"] for c in reduce(*changes)] == [1, 2, 3]


def test_different_groups_merge_and_keep_last_group():
    changes = (move(4, 1, 2, group="merge#1"), move(4, 2, 3, group="split#2"))
    assert reduce(*changes) == [
        {"seq": 1, "op": "move", "group": "split#2", "node": 4, "from_parent": 1, "to_parent": 3},
    ]


def test_same_group_merges():
    out = reduce(move(4, 1, 2, group="split#2"), move(4, 2, 3, group="split#2"))
    assert out == [
        {"seq": 1, "op": "move", "group": "split#2", "node": 4, "from_parent": 1, "to_parent": 3},
    ]


def test_edit_of_new_node_with_new_children_folds_at_first_position():
    # At the rename's position the add would come after its child's add, so the
    # merged add stays where the original add was.
    changes = (add("new:1", "a"), add("new:2", "b", parent="new:1"), edit("new:1", label="c"))
    assert reduce(*changes) == [
        {"seq": 1, "op": "add", "group": None, "node": "new:1", "label": "c", "parent": None},
        {"seq": 2, "op": "add", "group": None, "node": "new:2", "label": "b", "parent": "new:1"},
    ]


def test_moved_by_split_then_deprecated():
    changes = (
        add("new:1", "P_a", parent=2, group="split#1"),
        move(4, 1, "new:1", group="split#1"),
        move(5, 1, "new:1", group="split#1"),
        deprecate(1, successors=["new:1"], group="split#1"),
        deprecate(4),
    )
    out = reduce(*changes)
    assert [(c["op"], c["node"], c["group"]) for c in out] == [
        ("add", "new:1", "split#1"),
        ("deprecate", 4, None),
        ("move", 5, "split#1"),
        ("deprecate", 1, "split#1"),
    ]


def test_split_of_a_split():
    # P(1) > x(4), y(5), z(6): split P into new:1 and new:2, then new:1 into new:3 and new:4.
    base = BASE + [(6, "z", 1)]
    changes = (
        add("new:1", "A", parent=2, group="split#1"),
        add("new:2", "B", parent=2, group="split#1"),
        move(4, 1, "new:1", group="split#1"),
        move(5, 1, "new:1", group="split#1"),
        move(6, 1, "new:2", group="split#1"),
        deprecate(1, successors=["new:1", "new:2"], group="split#1"),
        add("new:3", "A1", parent=2, group="split#2"),
        add("new:4", "A2", parent=2, group="split#2"),
        move(4, "new:1", "new:3", group="split#2"),
        move(5, "new:1", "new:4", group="split#2"),
        deprecate("new:1", successors=["new:3", "new:4"], group="split#2"),
    )
    original = apply_changes(make_state(base), specs(*changes))
    assert [e["error"] for e in original.errors] == ["invalid_successor"]

    out = reduce(*changes, base=base)
    assert not any(c["node"] == "new:1" for c in out)
    moves = {c["node"]: (c["from_parent"], c["to_parent"]) for c in out if c["op"] == "move"}
    assert moves == {4: (1, "new:3"), 5: (1, "new:4"), 6: (1, "new:2")}
    (dep,) = [c for c in out if c["op"] == "deprecate"]
    assert (dep["node"], dep["successors"]) == (1, ["new:3", "new:4", "new:2"])
    assert sorted(c["node"] for c in out if c["op"] == "add") == ["new:2", "new:3", "new:4"]
    assert apply_changes(make_state(base), specs_from_dicts(out)).errors == []


def test_chain_through_existing_node():
    out = reduce(deprecate(4, successors=[5]), deprecate(5, successors=[3]))
    assert [(c["node"], c["successors"]) for c in out] == [(4, [3]), (5, [3])]


def test_successor_deprecated_later_without_successors_is_kept():
    changes = (deprecate(4, successors=[5]), deprecate(5))
    out = reduce(*changes)
    assert [(c["node"], c["successors"]) for c in out] == [(4, [5]), (5, [])]
    assert [e["error"] for e in apply_changes(make_state(BASE), specs_from_dicts(out)).errors] == [
        "invalid_successor"
    ]


def test_successor_deprecated_earlier_is_not_collapsed():
    out = reduce(deprecate(5, successors=[3]), deprecate(4, successors=[5]))
    assert [(c["node"], c["successors"]) for c in out] == [(5, [3]), (4, [5])]


def test_successor_cycle_terminates():
    reduce(deprecate(4, successors=[5]), deprecate(5, successors=[3]), deprecate(3, successors=[5]))


def test_reduction_keeps_existing_errors_and_state():
    changes = specs(edit(4, label="y"), edit(4, label="q"), edit(4, label="r"))
    base = make_state(BASE)
    reduced = reduce_changes(base, changes)
    assert [c.payload for c in reduced] == [{"node": 4, "label": "r"}]
    assert (
        apply_changes(base, reduced).state.contents()
        == apply_changes(base, changes).state.contents()
    )


# --- Sources: which submitted changes each reduced change was built from ---------------


def sources(*changes, base=BASE):
    return [(c.op, c.node, c.sources) for c in reduce_changes(make_state(base), specs(*changes))]


def test_unreduced_changes_keep_their_own_position():
    assert sources(edit(4, label="a"), move(5, 1, 2)) == [("edit", 4, (1,)), ("move", 5, (2,))]


def test_split_then_rename():
    """An add folded with a later edit is built from both, whatever their groups."""
    changes = (
        add("new:1", "x1", parent=1, group="split#1"),
        add("new:2", "x2", parent=1, group="split#1"),
        deprecate(4, successors=["new:1", "new:2"], group="split#1"),
        edit(5, label="y2"),
        move(5, 1, 2),
        edit("new:1", label="x_one"),
    )
    out = reduce_changes(make_state(BASE), specs(*changes))
    (folded,) = [c for c in out if c.node == "new:1"]
    assert (folded.op, folded.group, folded.sources) == ("add", None, (1, 6))
    assert [c.sources for c in out if c.node == 5] == [(4,), (5,)]


def test_label_swap_kept_apart():
    out = sources(edit(4, label="tmp"), edit(5, label="x"), edit(4, label="y"))
    assert out == [("edit", 4, (1,)), ("edit", 5, (2,)), ("edit", 4, (3,))]


def test_move_undone_by_hand():
    assert sources(move(4, 1, 2), edit(5, label="z"), move(4, 2, 1)) == [("edit", 5, (2,))]
    assert sources(move(4, 1, 2), edit(5, label="z"), move(4, 2, 3)) == [
        ("edit", 5, (2,)), ("move", 4, (1, 3)),
    ]  # fmt: skip


def test_chained_deprecations_keep_both_sources():
    out = sources(deprecate(4, successors=[5]), deprecate(5, successors=[3]))
    assert out == [("deprecate", 4, (1, 2)), ("deprecate", 5, (2,))]


def test_dropped_changes_leave_no_sources():
    assert sources(edit(4, label="w"), deprecate(4)) == [("deprecate", 4, (2,))]
    assert sources(add("new:1", "a"), edit(4, label="w"), deprecate("new:1")) == [("edit", 4, (2,))]


# --- Net changes per node ---------------------------------------------------------------


def net(*changes, base=BASE):
    state = make_state(base)
    submitted = specs(*changes)
    result = check_changes(state, submitted)
    return {e["node"]: e for e in result.node_changes}


def test_split():
    # P(1) > A(4) > C1(6), C2(7): split A into new:1 and new:2 under P.
    base = BASE + [(6, "c1", 4), (7, "c2", 4)]
    out = net(
        add("new:1", "x1", parent=1, group="split#1"),
        add("new:2", "x2", parent=1, group="split#1"),
        move(6, 4, "new:1", group="split#1"),
        move(7, 4, "new:2", group="split#1"),
        deprecate(4, successors=["new:1", "new:2"], group="split#1"),
        base=base,
    )
    assert set(out) == {1, 4, 6, 7, "new:1", "new:2"}
    assert (out[4]["to"], out[4]["successors"]) == (None, ["new:1", "new:2"])
    assert out["new:1"]["fields"] == {"label": [None, "x1"], "parent": [None, 1]}
    assert (out["new:1"]["from"], out["new:1"]["to"]) == (None, 1)
    assert out["new:1"]["children_gained"] == [6]
    assert out[1]["children_gained"] == ["new:1", "new:2"] and out[1]["children_lost"] == [4]
    assert out[6]["fields"] == {"parent": [4, "new:1"]}
    assert all(e["groups"] == ["split#1"] for e in out.values())


def test_temporary_label_hidden():
    out = net(edit(4, label="tmp"), edit(5, label="x"), edit(4, label="y"))
    assert out[4]["fields"] == {"label": ["x", "y"]}
    assert out[5]["fields"] == {"label": ["y", "x"]}
    assert out[4]["seqs"] == [1, 3]


def test_order_does_not_matter():
    a = net(edit(4, label="w"), move(5, 1, 2))
    b = net(move(5, 1, 2), edit(4, label="w"))
    strip = lambda d: {k: {f: v for f, v in e.items() if f != "seqs"} for k, e in d.items()}  # noqa: E731
    assert strip(a) == strip(b)


def test_split_add_renamed_by_hand_keeps_its_group():
    out = net(add("new:1", "a", parent=2, group="split#1"), edit("new:1", label="b"))
    assert out["new:1"]["groups"] == ["split#1"] and out["new:1"]["fields"]["label"] == [None, "b"]
