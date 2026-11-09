"""Placement checks and recheck scope (spec: worms-placement-checks), in memory."""

from core.engine import NodeState, TreeState, apply_changes, specs_from_dicts
from core.tests.helpers import add, deprecate, edit, move
from worms.checks import Lineages, change_checks, check_nodes, needed_aphia_ids, recheck_scope
from worms.client import WormsClient

from .fixtures import FixtureTransport


def state(*nodes, tree_id="t"):
    """nodes: (id, label, parent, aphia_id)."""
    return TreeState(tree_id, 1, [NodeState(i, lb, p, a, 1) for i, lb, p, a in nodes])


def records_for(s: TreeState, **extra):
    """Recorded records for every AphiaID in `s`; `a<id>=record` supplies others."""
    given = {int(k.removeprefix("a")): v for k, v in extra.items()}
    client = WormsClient(transport=FixtureTransport())
    records = {a: client.full_record(a) for a in needed_aphia_ids(s, s.nodes) - set(given)}
    return {**records, **given}


def codes(warnings):
    return [w["warning"] for w in warnings]


DIATOMS = [
    (1, "Chromista", None, 7),
    (2, "Bacillariophyceae", 1, 148899),
    (3, "Chaetocerotaceae", 2, 148984),
    (4, "Chaetoceros", 3, 148985),
    (5, "Chaetoceros_morphotype1", 4, None),
    (6, "Chaetoceros_didymus", 5, 149122),
]


def test_correct_tree_has_no_warnings():
    s = state(*DIATOMS)
    assert check_nodes(s, s.nodes, records_for(s)) == {i: [] for i in range(1, 7)}


def test_morphotype_in_between_is_passed_through():
    s = state(*DIATOMS)
    records = records_for(s)
    assert needed_aphia_ids(s, [6]) == {149122, 148985}
    assert check_nodes(s, [6], records) == {6: []}


def test_no_anchored_ancestor_no_lineage_check():
    s = state((1, "stuff", None, None), (2, "Chaetoceros", 1, 148985))
    assert check_nodes(s, [2], records_for(s)) == {2: []}


def test_genus_under_the_wrong_class():
    s = state((1, "Dinophyceae", None, 19542), (2, "Chaetoceros", 1, 148985))
    (warning,) = check_nodes(s, [2], records_for(s))[2]
    assert warning["warning"] == "out_of_lineage"
    assert "Dinophyceae" in warning["detail"]


def test_rank_inversion():
    s = state((1, "Chaetoceros_didymus", None, 149122), (2, "Chaetoceros", 1, 148985))
    assert codes(check_nodes(s, [2], records_for(s))[2]) == ["out_of_lineage"]


def test_ancestor_is_a_synonym():
    # Rhizosolenia alata (149223) is a synonym of Proboscia alata (149168).
    s = state((1, "Rhizosolenia_alata", None, 149223), (2, "child", 1, 900))
    child = {"AphiaID": 900, "valid_AphiaID": 900, "status": "accepted",
             "lineage": [{"AphiaID": 149168}, {"AphiaID": 900}]}  # fmt: skip
    assert check_nodes(s, [2], records_for(s, a900=child))[2] == []
    child["lineage"] = [{"AphiaID": 1}, {"AphiaID": 900}]
    assert codes(check_nodes(s, [2], records_for(s, a900=child))[2]) == ["out_of_lineage"]


def test_name_became_a_synonym():
    s = state((1, "Chaetoceros_x", None, 500))
    record = {
        "AphiaID": 500, "scientificname": "Chaetoceros x", "status": "unaccepted",
        "valid_AphiaID": 149120, "valid_name": "Chaetoceros danicus", "lineage": [],
    }  # fmt: skip
    (warning,) = check_nodes(s, [1], {500: record})[1]
    assert warning["warning"] == "unaccepted_aphia" and "149120" in warning["detail"]


def test_recorded_synonym():
    s = state((1, "Rhizosolenia_alata", None, 149223))
    (warning,) = check_nodes(s, [1], records_for(s))[1]
    assert warning["warning"] == "unaccepted_aphia" and "149168" in warning["detail"]


def test_unassessed_with_an_accepted_name():
    s = state((1, "Guinardia_delicatula", None, 149112))
    (warning,) = check_nodes(s, [1], records_for(s))[1]
    assert warning["warning"] == "unaccepted_aphia" and "149114" in warning["detail"]


def test_unassessed_is_not_unaccepted():
    s = state((1, "x", None, 500))
    record = {"AphiaID": 500, "status": "unassessed", "valid_AphiaID": 500, "lineage": []}
    assert check_nodes(s, [1], {500: record}) == {1: []}


def test_same_species_twice():
    s = state(
        (1, "Chaetoceros", None, 148985),
        (2, "Chaetoceros_didymus", 1, 149122),
        (3, "C_didymus_again", 1, 149122),
    )
    result = check_nodes(s, [2, 3], records_for(s))
    assert codes(result[2]) == codes(result[3]) == ["duplicate_aphia"]
    assert "C_didymus_again" in result[2][0]["detail"]
    assert "Chaetoceros_didymus" in result[3][0]["detail"]


def test_other_trees_are_not_duplicates():
    one = state((1, "Chaetoceros_didymus", None, 149122), tree_id="a")
    two = state((2, "Chaetoceros_didymus", None, 149122), tree_id="b")
    assert check_nodes(one, [1], records_for(one)) == {1: []}
    assert check_nodes(two, [2], records_for(two)) == {2: []}


def test_unavailable_record():
    s = state(*DIATOMS)
    records = records_for(s)
    del records[149122]
    assert check_nodes(s, [4, 6], records) == {4: [], 6: None}


def test_aphia_id_unknown_to_worms():
    s = state((1, "Chaetoceros", None, 148985), (2, "mystery", 1, 999999999))
    (warning,) = check_nodes(s, [2], records_for(s))[2]
    assert warning["warning"] == "unknown_aphia" and "999999999" in warning["detail"]


def test_unknown_ancestor_does_not_put_children_out_of_lineage():
    s = state((1, "mystery", None, 999999999), (2, "Chaetoceros", 1, 148985))
    result = check_nodes(s, [1, 2], records_for(s))
    assert (codes(result[1]), result[2]) == (["unknown_aphia"], [])


def test_unknown_and_duplicate():
    s = state((1, "a", None, 999999999), (2, "b", None, 999999999))
    assert codes(check_nodes(s, [1], records_for(s))[1]) == ["unknown_aphia", "duplicate_aphia"]


# --- misplaced_lineage_ancestor ------------------------------------------------------------


def misplaced(warnings):
    return [w["detail"] for w in warnings if w["warning"] == "misplaced_lineage_ancestor"]


def test_family_beside_its_genus():
    s = state((2, "Bacillariophyceae", None, 148899), (3, "Chaetocerotaceae", 2, 148984),
              (4, "Chaetoceros", 2, 148985))  # fmt: skip
    result = check_nodes(s, [3, 4], records_for(s))
    assert result[3] == []
    (warning,) = result[4]
    assert warning["warning"] == "misplaced_lineage_ancestor"
    assert warning["detail"].startswith("Chaetocerotaceae (Chaetocerotaceae, 148984) is in")
    assert "between Bacillariophyceae and it" in warning["detail"]


def test_ancestor_elsewhere_in_the_tree():
    s = state((2, "Bacillariophyceae", None, 148899), (4, "Chaetoceros", None, 148985))
    (detail,) = misplaced(check_nodes(s, [4], records_for(s))[4])
    assert detail.startswith("Bacillariophyceae (Bacillariophyceae, 148899)")


def test_already_under_it():
    s = state(*DIATOMS)
    assert misplaced(check_nodes(s, [4, 6], records_for(s))[4]) == []


def test_missing_two_ancestors():
    s = state((1, "Chromista", None, 7), (2, "Bacillariophyceae", 1, 148899),
              (3, "Chaetocerotaceae", 2, 148984), (4, "Chaetoceros", 1, 148985))  # fmt: skip
    details = misplaced(check_nodes(s, [4], records_for(s))[4])
    assert [d.split(" ")[0] for d in details] == ["Bacillariophyceae", "Chaetocerotaceae"]


def test_synonym_node_matches_through_its_accepted_aphia_id():
    s = state((2, "Bacillariophyceae", None, 148899), (3, "old_family", 2, 901),
              (4, "Chaetoceros", 2, 148985))  # fmt: skip
    synonym = {"AphiaID": 901, "valid_AphiaID": 148984, "status": "unaccepted",
               "lineage": [{"AphiaID": 901}]}  # fmt: skip
    records = records_for(s, a901=synonym)
    assert misplaced(check_nodes(s, [4], records)[4]) == []  # not cached as a synonym
    (detail,) = misplaced(check_nodes(s, [4], records, Lineages(records))[4])
    assert detail.startswith("old_family (Chaetocerotaceae, 148984)")


def test_no_misplaced_warning_when_out_of_lineage():
    s = state((1, "Dinophyceae", None, 19542), (2, "Chaetoceros", 1, 148985),
              (3, "Chaetocerotaceae", None, 148984))  # fmt: skip
    assert codes(check_nodes(s, [2], records_for(s))[2]) == ["out_of_lineage"]


def test_adding_an_ancestor_taxon_warns_its_would_be_children():
    s = state((2, "Bacillariophyceae", None, 148899), (4, "Chaetoceros", 2, 148985),
              (5, "Chaetoceros_didymus", 4, 149122))  # fmt: skip
    family = state((3, "Chaetocerotaceae", None, 148984))
    records = {**records_for(s), **records_for(family)}
    lineages = Lineages(records)
    (spec,) = specs_from_dicts([add("new:1", "Chaetocerotaceae", parent=2, aphia_id=148984)])
    after = apply_changes(s, [spec]).state
    assert recheck_scope(s, after, spec, lineages) == {"new:1", 4, 5}
    assert recheck_scope(s, after, spec) == {"new:1"}  # without cached lineages
    [checks], _ = change_checks(s, [spec], records, lineages)
    assert [(w["warning"], w["node"]) for w in checks] == [("misplaced_lineage_ancestor", 4)]

    (gone,) = specs_from_dicts([deprecate("new:1")])
    [cleared], _ = change_checks(after, [gone], records, lineages)
    assert cleared == []
    assert check_nodes(apply_changes(after, [gone]).state, [4], records, lineages) == {4: []}


# --- 2.2 recheck scope ----------------------------------------------------------------


def scope_of(before, change):
    (spec,) = specs_from_dicts([change])
    after = apply_changes(before, [spec])
    assert after.errors == []
    return recheck_scope(before, after.state, spec)


TREE = [
    (1, "Chaetoceros", None, 148985),
    (2, "morphotype", 1, None),  # unanchored, with anchored children
    (3, "Chaetoceros_didymus", 2, 149122),
    (4, "Chaetoceros_danicus", 2, 149120),
    (5, "didymus_tag", 3, 149122),  # grandchild of 2, and a duplicate of 3
    (6, "other", None, None),
    (7, "deeper", 2, None),
    (8, "Chaetoceros_x", 7, 500),
]


def test_moving_an_unanchored_node():
    s = state(*TREE)
    assert scope_of(s, move(2, 1, 6)) == {2, 3, 4, 8}


def test_removing_a_duplicate():
    s = state(*TREE)
    assert scope_of(s, edit(5, aphia_id=None)) == {5, 3}
    records = records_for(state(*TREE[:5]))
    assert codes(check_nodes(s, [3], records)[3]) == ["duplicate_aphia"]
    after = apply_changes(s, specs_from_dicts([edit(5, aphia_id=None)])).state
    assert check_nodes(after, [3], records)[3] == []


def test_changing_an_aphia_id_rechecks_old_and_new_duplicates():
    s = state(*TREE)
    assert scope_of(s, edit(4, aphia_id=149122)) == {4, 3, 5}
    assert scope_of(s, edit(3, aphia_id=149120)) == {3, 4, 5}


def test_deprecating_rechecks_same_aphia_nodes_only():
    s = state(*TREE)
    assert scope_of(s, deprecate(5)) == {3}


def test_ancestors_are_not_rechecked():
    s = state(*TREE)
    assert 1 not in scope_of(s, edit(3, label="C_didymus"))
