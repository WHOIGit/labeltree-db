import pytest
from django.db import IntegrityError, transaction

from core.labels import allocate_node_ids
from core.models import Node, NodeVersion, Tree

pytestmark = pytest.mark.django_db


@pytest.fixture
def tree():
    return Tree.objects.create(id="t", title="T")


def make_node(tree, node_id, created=1):
    return Node.objects.create(id=node_id, tree=tree, created_in_rev=created)


def make_version(node, version, label, frm, to=None, parent=None):
    return NodeVersion.objects.create(
        node=node,
        tree=node.tree,
        version=version,
        label=label,
        valid_from_rev=frm,
        valid_to_rev=to,
        parent=parent,
    )


def test_overlapping_same_label_versions_fail(tree):
    a, b = make_node(tree, 1), make_node(tree, 2)
    make_version(a, 1, "bleb", 1, 5)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_version(b, 1, "bleb", 4)


def test_same_label_after_range_closes(tree):
    a, b = make_node(tree, 1), make_node(tree, 2)
    make_version(a, 1, "bleb", 1, 5)
    make_version(b, 1, "bleb", 5)


def test_labels_are_case_sensitive(tree):
    a, b = make_node(tree, 1), make_node(tree, 2)
    make_version(a, 1, "Chain", 1)
    make_version(b, 1, "chain", 1)


def test_same_label_in_other_tree(tree):
    other = Tree.objects.create(id="u", title="U")
    make_version(make_node(tree, 1), 1, "bleb", 1)
    make_version(make_node(other, 2), 1, "bleb", 1)


def test_one_open_version_per_node(tree):
    a = make_node(tree, 1)
    make_version(a, 1, "x", 1)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_version(a, 2, "y", 2)


def test_empty_range_rejected(tree):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_version(make_node(tree, 1), 1, "x", 3, 3)


def test_node_ids_are_unique_and_increasing():
    first = allocate_node_ids(3)
    second = allocate_node_ids(2)
    assert len(set(first + second)) == 5
    assert max(first) < min(second)
    assert allocate_node_ids(0) == []
