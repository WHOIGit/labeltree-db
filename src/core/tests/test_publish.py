"""Changeset save, states, publish, new trees and rebase (tasks 5.1-5.4)."""

import pytest

from core.changesets import (
    ChangesetError,
    NewTree,
    create_changeset,
    discard_changeset,
    latest_rev,
    publish_changeset,
    rebase_changeset,
    update_changeset,
)
from core.models import Changeset, Node, NodeAlias, NodeVersion, Successor, Tree, TreeRevision

from .helpers import add, deprecate, edit, ids_by_label, move, publish, publish_new_tree

pytestmark = pytest.mark.django_db


@pytest.fixture
def tree():
    """Revision 1: P > x, y;  Q;  R"""
    publish_new_tree(
        "t",
        add("new:1", "P"),
        add("new:2", "Q"),
        add("new:3", "R"),
        add("new:4", "x", parent="new:1"),
        add("new:5", "y", parent="new:1"),
    )
    return Tree.objects.get(id="t")


def versions(node_id):
    return [
        (v.version, v.valid_from_rev, v.valid_to_rev)
        for v in NodeVersion.objects.filter(node_id=node_id).order_by("version")
    ]


def refused(error, fn, *args, **kwargs):
    with pytest.raises(ChangesetError) as exc:
        fn(*args, **kwargs)
    assert exc.value.error == error, exc.value.detail
    return exc.value


# --- 5.1 save and states -------------------------------------------------------------


def test_save_reduces_then_stores(tree):
    ids = ids_by_label("t")
    cs = create_changeset(
        author="alice",
        tree=tree,
        base_rev=1,
        changes=[edit(ids["x"], label="a"), edit(ids["x"], label="b")],
    )
    assert cs.state == "draft"
    assert [(c.seq, c.op, c.payload) for c in cs.changes.all()] == [
        (1, "edit", {"node": ids["x"], "label": "b"})
    ]


def test_drafts_may_hold_structural_errors(tree):
    cs = create_changeset(
        author="alice", tree=tree, base_rev=1, changes=[edit(ids_by_label("t")["x"], label="y")]
    )
    assert cs.changes.count() == 1


def test_base_rev_must_exist(tree):
    refused("invalid_base_rev", create_changeset, author="a", tree=tree, base_rev=2, changes=[])


def test_update_replaces_changes_and_notes(tree):
    ids = ids_by_label("t")
    cs = create_changeset(author="a", tree=tree, base_rev=1, changes=[edit(ids["x"], label="a")])
    update_changeset(cs, changes=[edit(ids["y"], description="d")], notes="n")
    cs.refresh_from_db()
    assert cs.notes == "n"
    assert [c.payload for c in cs.changes.all()] == [{"node": ids["y"], "description": "d"}]


def test_discarded_changeset_is_frozen(tree):
    ids = ids_by_label("t")
    cs = create_changeset(author="a", tree=tree, base_rev=1, changes=[edit(ids["x"], label="a")])
    discard_changeset(cs)
    cs.refresh_from_db()
    assert cs.state == "discarded"
    refused("not_draft", publish_changeset, cs, published_by="b")
    refused("not_draft", update_changeset, cs, notes="again")
    refused("not_draft", discard_changeset, cs)
    assert latest_rev("t") == 1
    assert [c.payload for c in cs.changes.all()] == [{"node": ids["x"], "label": "a"}]


def test_published_changeset_is_frozen(tree):
    cs = Changeset.objects.get(revision__tree=tree, revision__number=1)
    assert cs.state == "published"
    refused("not_draft", update_changeset, cs, notes="x")
    refused("not_draft", publish_changeset, cs, published_by="b")


# --- 5.2 publish ------------------------------------------------------------------


def test_one_revision_per_publish(tree):
    ids = ids_by_label("t")
    rev = publish(tree, edit(ids["x"], label="x2"), notes="rename", published_by="carol")
    assert (rev.number, rev.published_by, rev.notes) == (2, "carol", "rename")
    assert rev.changeset.author == "alice" and rev.changeset.state == "published"
    assert rev.published_at is not None


def test_publish_notes_override(tree):
    ids = ids_by_label("t")
    cs = create_changeset(
        author="a", tree=tree, base_rev=1, notes="drafter", changes=[edit(ids["x"], label="z")]
    )
    assert publish_changeset(cs, published_by="b", notes="approver").notes == "approver"


def test_placeholders_get_real_ids(tree):
    ids = ids_by_label("t")
    publish(tree, add("new:1", "N1", parent=ids["Q"]), add("new:2", "N2", parent="new:1"))
    after = ids_by_label("t")
    n1, n2 = after["N1"], after["N2"]
    assert isinstance(n1, int) and isinstance(n2, int) and n1 != n2
    published = TreeRevision.objects.get(tree=tree, number=2).changeset.changes.order_by("seq")
    assert [c.payload for c in published] == [
        {"node": n1, "label": "N1", "parent": ids["Q"]},
        {"node": n2, "label": "N2", "parent": n1},
    ]
    assert Node.objects.get(id=n2).created_in_rev == 2


def test_discarded_draft_allocates_no_ids(tree):
    before = max(Node.objects.values_list("id", flat=True))
    cs = create_changeset(author="a", tree=tree, base_rev=1, changes=[add("new:1", "Z")])
    discard_changeset(cs)
    publish(tree, add("new:1", "W"))
    assert ids_by_label("t")["W"] == before + 1


def test_ids_never_reused(tree):
    ids = ids_by_label("t")
    publish(tree, deprecate(ids["y"]))
    publish(tree, add("new:1", "y", parent=ids["P"]))
    assert ids_by_label("t")["y"] != ids["y"]


def test_clearing_aphia_id(tree):
    x = ids_by_label("t")["x"]
    publish(tree, edit(x, aphia_id=149122))
    publish(tree, edit(x, aphia_id=None))
    assert NodeVersion.objects.get(node_id=x, valid_to_rev__isnull=True).aphia_id is None


def test_five_revision_example(tree):
    publish(tree, add("new:1", "Chaetoceros"), add("new:2", "Thalassiosira"))  # rev 2
    ids = ids_by_label("t")
    publish(tree, add("new:1", "C_didymus", parent=ids["Chaetoceros"]))  # rev 3
    ch, th, did = ids["Chaetoceros"], ids["Thalassiosira"], ids_by_label("t")["C_didymus"]
    publish(tree, add("new:1", "C_socialis", parent=ch))  # rev 4
    soc = ids_by_label("t")["C_socialis"]
    publish(tree, edit(did, label="C_didymus_sl"))  # rev 5
    publish(tree, move(soc, ch, th))  # rev 6
    publish(tree, deprecate(did), edit(ch, description="Genus"))  # rev 7

    # Revisions 3-7 here correspond to revisions 1-5 of the design example.
    assert versions(ch)[1:] == [(2, 3, 4), (3, 4, 6), (4, 6, 7), (5, 7, None)]
    assert versions(did) == [(1, 3, 5), (2, 5, 7)]
    assert Node.objects.get(id=did).deprecated_in_rev == 7
    assert versions(soc) == [(1, 4, 6), (2, 6, None)]
    assert versions(th) == [(1, 2, 6), (2, 6, None)]


def test_rename_and_back_does_not_bump(tree):
    ids = ids_by_label("t")
    publish(
        tree, edit(ids["x"], label="tmp"), edit(ids["x"], label="x"), edit(ids["R"], label="R2")
    )
    assert versions(ids["x"]) == [(1, 1, None)]


def test_empty_changeset_is_refused(tree):
    ids = ids_by_label("t")
    err = refused(
        "structural", publish, tree, edit(ids["x"], label="tmp"), edit(ids["x"], label="x")
    )
    assert [e["error"] for e in err.errors] == ["empty_changeset"]


def test_structural_errors_refuse_publish(tree):
    ids = ids_by_label("t")
    err = refused("structural", publish, tree, edit(ids["x"], label="y"))
    assert err.errors[0]["error"] == "label_in_use"
    assert latest_rev("t") == 1


def test_split_with_replacement(tree):
    # P > x(830), y(831) play 812 > 830, 831; Q plays 450.
    ids = ids_by_label("t")
    publish(
        tree,
        add("new:1", "P_a", parent=ids["Q"], group="split#3"),
        add("new:2", "P_b", parent=ids["Q"], group="split#3"),
        move(ids["x"], ids["P"], "new:1", group="split#3"),
        move(ids["y"], ids["P"], "new:2", group="split#3"),
        deprecate(ids["P"], successors=["new:1", "new:2"], group="split#3"),
    )
    after = ids_by_label("t")
    a, b = after["P_a"], after["P_b"]
    assert versions(ids["Q"]) == [(1, 1, 2), (2, 2, None)]
    assert versions(ids["x"]) == [(1, 1, 2), (2, 2, None)]
    assert versions(ids["y"]) == [(1, 1, 2), (2, 2, None)]
    assert versions(ids["P"]) == [(1, 1, 2)]
    assert versions(a) == [(1, 2, None)] and versions(b) == [(1, 2, None)]
    assert Node.objects.get(id=ids["P"]).deprecated_in_rev == 2
    assert list(
        Successor.objects.filter(deprecated_node=ids["P"]).values_list("successor_node", flat=True)
    ) == [a, b]
    assert [
        c.group for c in TreeRevision.objects.get(number=2, tree=tree).changeset.changes.all()
    ] == ["split#3"] * 5


def test_label_reused_after_deprecation(tree):
    ids = ids_by_label("t")
    publish(tree, deprecate(ids["y"]))
    publish(tree, add("new:1", "y", parent=ids["Q"]))
    assert ids_by_label("t", 1)["y"] == ids["y"]
    assert ids_by_label("t", 3)["y"] != ids["y"]


def test_initial_aliases(tree):
    publish(tree, add("new:1", "Cd", aliases=["Chaetoceros didymus", "C. didymus"]), author="dan")
    node = ids_by_label("t")["Cd"]
    aliases = NodeAlias.objects.filter(node_id=node).order_by("id")
    assert [a.alias for a in aliases] == ["Chaetoceros didymus", "C. didymus"]
    assert {a.added_by for a in aliases} == {"dan"}
    assert all(a.added_at and a.removed_at is None for a in aliases)


def test_two_drafts_add_the_same_label(tree):
    first = create_changeset(author="a", tree=tree, base_rev=1, changes=[add("new:1", "bleb")])
    second = create_changeset(author="b", tree=tree, base_rev=1, changes=[add("new:1", "bleb")])
    publish_changeset(first, published_by="c")
    result = rebase_changeset(second)
    assert [e["error"] for e in result.errors] == ["label_in_use"]
    err = refused("structural", publish_changeset, second, published_by="c")
    assert err.errors[0]["error"] == "label_in_use"


# --- 5.3 new trees ------------------------------------------------------------------


def test_first_revision():
    rev = publish_new_tree("NES", *[add(f"new:{i}", f"n{i}") for i in range(1, 19)], title="N")
    assert rev.number == 1
    tree = Tree.objects.get(id="NES")
    assert tree.title == "N"
    open_versions = NodeVersion.objects.filter(tree=tree, valid_to_rev__isnull=True)
    assert open_versions.count() == 18
    assert set(open_versions.values_list("version", flat=True)) == {1}
    assert rev.changeset.tree == tree


def test_tree_id_taken(tree):
    cs = create_changeset(author="a", changes=[add("new:1", "x")], new_tree=NewTree("t", "dup"))
    refused("tree_exists", publish_changeset, cs, published_by="b")


def test_new_tree_publish_failure_creates_no_tree():
    cs = create_changeset(
        author="a", changes=[add("new:1", "x"), add("new:2", "x")], new_tree=NewTree("u", "U")
    )
    refused("structural", publish_changeset, cs, published_by="b")
    assert not Tree.objects.filter(id="u").exists()


# --- 5.4 rebase -----------------------------------------------------------------------


def test_fell_behind_then_rebased(tree):
    ids = ids_by_label("t")
    draft = create_changeset(
        author="a", tree=tree, base_rev=1, changes=[edit(ids["R"], description="d")]
    )
    publish(tree, edit(ids["x"], label="x2"))  # revision 2
    refused("stale_base", publish_changeset, draft, published_by="b")
    assert rebase_changeset(draft).errors == []
    draft.refresh_from_db()
    assert draft.base_rev == 2
    assert publish_changeset(draft, published_by="b").number == 3


def test_split_of_a_split_publishes_collapsed_successors(tree):
    # P > x, y: split P into A (x, y) and B, then split A into A1 (x) and A2 (y).
    ids = ids_by_label("t")
    P, x, y, Q = ids["P"], ids["x"], ids["y"], ids["Q"]
    publish(
        tree,
        add("new:1", "A", parent=Q, group="split#1"),
        add("new:2", "B", parent=Q, group="split#1"),
        move(x, P, "new:1", group="split#1"),
        move(y, P, "new:1", group="split#1"),
        deprecate(P, successors=["new:1", "new:2"], group="split#1"),
        add("new:3", "A1", parent=Q, group="split#2"),
        add("new:4", "A2", parent=Q, group="split#2"),
        move(x, "new:1", "new:3", group="split#2"),
        move(y, "new:1", "new:4", group="split#2"),
        deprecate("new:1", successors=["new:3", "new:4"], group="split#2"),
    )
    after = ids_by_label("t")
    assert "A" not in after
    successors = Successor.objects.filter(deprecated_node=P).order_by("position")
    assert [s.successor_node_id for s in successors] == [after["A1"], after["A2"], after["B"]]
    assert NodeVersion.objects.get(node_id=x, valid_to_rev__isnull=True).parent_id == after["A1"]
