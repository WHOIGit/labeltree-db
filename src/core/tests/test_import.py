"""Import format, expansion into add changes, and the import_tree command."""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from core.engine import check_changes, specs_from_dicts
from core.importer import ImportFormatError, expand_import
from core.models import Changeset, NodeAlias, NodeVersion, Tree

from .helpers import TAGS, ids_by_label, make_state, publish_new_tree

# --- 6.1 format and expansion -----------------------------------------------------------


def test_minimal_node():
    assert expand_import({"nodes": [{"label": "bleb"}]}) == [
        {"op": "add", "group": "import#1", "node": "new:1", "label": "bleb", "parent": None}
    ]


def test_unknown_keys_are_ignored():
    data = {
        "tree": "other",
        "nodes": [
            {"id": 7, "version": 3, "tree": "x", "num_children": 1, "label": "a", "aphia_id": 5,
             "description": "d", "aliases": ["A"], "worms_data": None,
             "children": [{"id": 8, "label": "b", "children": []}]},
        ],
    }  # fmt: skip
    assert expand_import(data) == [
        {"op": "add", "group": "import#1", "node": "new:1", "label": "a", "parent": None,
         "description": "d", "aphia_id": 5, "aliases": ["A"]},
        {"op": "add", "group": "import#1", "node": "new:2", "label": "b", "parent": "new:1"},
    ]  # fmt: skip


def test_nested_import_parents_first_in_file_order():
    data = {
        "nodes": [
            {"label": "organism_state", "children": [{"label": "bleb"}, {"label": "dividing"}]}
        ]
    }
    changes = expand_import(data, group="import#2")
    assert [(c["node"], c["label"], c["parent"], c["group"]) for c in changes] == [
        ("new:1", "organism_state", None, "import#2"),
        ("new:2", "bleb", "new:1", "import#2"),
        ("new:3", "dividing", "new:1", "import#2"),
    ]


def test_import_under_existing_node():
    changes = expand_import({"nodes": [{"label": "x"}]}, parent=42)
    assert changes[0]["parent"] == 42


@pytest.mark.parametrize(
    ("data", "position"),
    [
        ({"nodes": [{"label": "a"}, {"label": "b", "children": [{"description": "no label"}]}]},
         "nodes[1].children[0]"),
        ({"nodes": [{"label": "a", "children": "nope"}]}, "nodes[0]"),
        ({"nodes": [{"label": "a", "aliases": "A"}]}, "nodes[0]"),
        ({"nodes": [{"label": "a", "aphia_id": "149122"}]}, "nodes[0]"),
        ({"nodes": ["a"]}, "nodes[0]"),
        ({"tree": "t"}, "file"),
        ([], "file"),
    ],
)  # fmt: skip
def test_malformed_file(data, position):
    with pytest.raises(ImportFormatError) as exc:
        expand_import(data)
    assert exc.value.position == position


def test_label_clash_with_target_tree():
    base = make_state([(1, "bleb", None)])
    result = check_changes(base, specs_from_dicts(expand_import({"nodes": [{"label": "bleb"}]})))
    assert [e["error"] for e in result.errors] == ["label_in_use"]


@pytest.mark.django_db
def test_imported_aliases_become_initial_aliases():
    data = {"nodes": [{"label": "C_didymus", "aliases": ["Chaetoceros didymus"]}]}
    publish_new_tree("t", *expand_import(data), author="erin")
    alias = NodeAlias.objects.get(node_id=ids_by_label("t")["C_didymus"])
    assert (alias.alias, alias.added_by, alias.removed_at) == ("Chaetoceros didymus", "erin", None)


# --- 6.2 import_tree command ----------------------------------------------------------------


def import_tree(path, tree="NES2022_tags", **kwargs):
    out, err = StringIO(), StringIO()
    call_command(
        "import_tree", str(path), tree=tree, title="NES2022 tags", stdout=out, stderr=err, **kwargs
    )
    return out.getvalue(), err.getvalue()


@pytest.mark.django_db
def test_load_nes2022_tags():
    out, _ = import_tree(TAGS, user="op")
    assert "revision 1" in out and "18 nodes, 5 top-level" in out
    tree = Tree.objects.get(id="NES2022_tags")
    current = NodeVersion.objects.filter(tree=tree, valid_to_rev__isnull=True)
    assert current.count() == 18
    assert current.filter(parent__isnull=True).count() == 5
    assert set(current.values_list("version", flat=True)) == {1}
    revision = tree.revisions.get()
    assert (revision.number, revision.published_by, revision.changeset.author) == (1, "op", "op")
    assert set(revision.changeset.changes.values_list("group", flat=True)) == {"import#1"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "nodes",
    [
        [{"label": "a", "children": [{"label": "b"}]}, {"label": "b"}],
        [{"label": "Chaetoceros didymus"}],
    ],
)
def test_errors_abort_the_import(tmp_path, nodes):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"nodes": nodes}))
    with pytest.raises(CommandError, match="nothing was stored"):
        _, err = import_tree(path, tree="bad")
    assert not Tree.objects.filter(id="bad").exists()
    assert not Changeset.objects.exists()


@pytest.mark.django_db
def test_errors_are_reported_per_change(tmp_path):
    path = tmp_path / "dup.json"
    path.write_text(json.dumps({"nodes": [{"label": "a"}, {"label": "a"}]}))
    err = StringIO()
    with pytest.raises(CommandError):
        call_command("import_tree", str(path), tree="d", title="D", stderr=err)
    assert "change 2 (new:2): label_in_use" in err.getvalue()


@pytest.mark.django_db
def test_malformed_file_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"nodes": [{"label": "a", "children": [{}]}]}))
    with pytest.raises(CommandError, match=r"nodes\[0\].children\[0\]"):
        import_tree(path, tree="bad")
    assert not Changeset.objects.exists()


@pytest.mark.django_db
def test_existing_tree_is_refused():
    import_tree(TAGS)
    with pytest.raises(CommandError, match="tree_exists"):
        import_tree(TAGS)
