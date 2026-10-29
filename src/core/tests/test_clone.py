"""Cloning a revision as a new tree (spec: tree-import)."""

import pytest

from core.changesets import NewTree, publish_changeset
from core.clone import clone_as_new_tree, clone_changes
from core.models import Node, NodeAlias, NodeDescription, Tree
from core.tests.helpers import add, edit, ids_by_label, org, publish, publish_new_tree

pytestmark = pytest.mark.django_db


@pytest.fixture
def source():
    publish_new_tree(
        "NES2022_taxonomy",
        add("new:1", "Chromista", aphia_id=7, description="Kingdom"),
        add("new:2", "Chaetoceros", parent="new:1", aphia_id=148985,
            aliases=["Chaetoceros sp."]),
        add("new:3", "box"),
    )  # fmt: skip
    tree = Tree.objects.get(id="NES2022_taxonomy")
    publish(tree, edit(ids_by_label(tree.id)["box"], label="box2"))
    publish(tree, add("new:1", "Chaetoceros_didymus", parent=ids_by_label(tree.id)["Chaetoceros"],
                      aphia_id=149122))  # fmt: skip
    publish(tree, edit(ids_by_label(tree.id)["box2"], label="box3"))  # revision 4
    return tree


def test_clone_revision_3(source):
    ids = ids_by_label(source.id)
    NodeDescription.objects.create(node_id=ids["box3"], description="later", added_by="x")
    changes = clone_changes(source.id, 3)
    assert [(c["label"], c["parent"]) for c in changes] == [
        ("Chromista", None), ("Chaetoceros", "new:1"), ("Chaetoceros_didymus", "new:2"),
        ("box2", None),
    ]  # fmt: skip
    assert {c["group"] for c in changes} == {"import#1"}
    by_label = {c["label"]: c for c in changes}
    assert by_label["Chromista"]["description"] == "Kingdom"
    assert by_label["Chaetoceros"]["aliases"] == ["Chaetoceros sp."]
    assert by_label["Chaetoceros_didymus"]["aphia_id"] == 149122
    assert by_label["box2"]["description"] == "later"  # current descriptions

    draft = clone_as_new_tree(source.id, 3, NewTree("lab_taxonomy", "Lab", org("lab_a")),
                              author="owner1")  # fmt: skip
    assert (draft.base_rev, draft.new_tree_id, draft.new_tree_org_id) == (
        None, "lab_taxonomy", "lab_a",
    )  # fmt: skip
    revision = publish_changeset(draft, published_by="owner1")
    clone = Tree.objects.get(id="lab_taxonomy")
    assert (revision.number, clone.org_id) == (1, "lab_a")
    assert set(ids_by_label(clone.id)) == {
        "Chromista",
        "Chaetoceros",
        "Chaetoceros_didymus",
        "box2",
    }


def test_clone_is_independent(source):
    draft = clone_as_new_tree(source.id, 4, NewTree("lab_taxonomy", "Lab", org()), author="o")
    publish_changeset(draft, published_by="o")
    original, clone = ids_by_label(source.id), ids_by_label("lab_taxonomy")
    assert not set(original.values()) & set(clone.values())
    publish(source, edit(original["Chromista"], label="Chromista_kingdom"))
    assert "Chromista" in ids_by_label("lab_taxonomy")
    assert NodeAlias.objects.get(node_id=clone["Chaetoceros"]).alias == "Chaetoceros sp."
    assert Node.objects.filter(tree_id="lab_taxonomy").count() == 4
