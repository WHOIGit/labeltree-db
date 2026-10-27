"""Loading a TreeState for (tree, rev) from hand-built node versions."""

import pytest

from core.engine import load_state
from core.models import Node, NodeVersion, Tree

pytestmark = pytest.mark.django_db


@pytest.fixture
def history():
    """Revisions 1-3 of a small tree, written directly as rows.

    rev 1: K(1) > L(3) > A(4);  J(2);  K > D(5)
    rev 2: D deprecated
    rev 3: L moved from K to J (K and J bump, L bumps)
    """
    tree = Tree.objects.create(id="t", title="T")
    nodes = {
        i: Node.objects.create(id=i, tree=tree, created_in_rev=1, deprecated_in_rev=None)
        for i in (1, 2, 3, 4, 5)
    }
    Node.objects.filter(id=5).update(deprecated_in_rev=2)

    def v(node, version, label, parent, frm, to=None):
        NodeVersion.objects.create(
            node=nodes[node],
            tree=tree,
            version=version,
            label=label,
            parent=nodes.get(parent),
            valid_from_rev=frm,
            valid_to_rev=to,
        )

    v(1, 1, "K", None, 1, 2)
    v(1, 2, "K", None, 2, 3)  # child D deprecated
    v(1, 3, "K", None, 3)  # child L moved out
    v(2, 1, "J", None, 1, 3)
    v(2, 2, "J", None, 3)  # child L moved in
    v(3, 1, "L", 1, 1, 3)
    v(3, 2, "L", 2, 3)
    v(4, 1, "A", 3, 1)
    v(5, 1, "D", 1, 1, 2)
    return tree


def test_revision_1(history):
    s = load_state("t", 1)
    assert set(s.nodes) == {1, 2, 3, 4, 5}
    assert s.child_ids(None) == [1, 2]
    assert s.child_ids(1) == [3, 5]
    assert s.child_ids(2) == []
    assert s.depth(4) == 2
    assert s.by_label["D"] == 5
    assert s.nodes[1].version == 1


def test_revision_2_drops_deprecated(history):
    s = load_state("t", 2)
    assert 5 not in s
    assert "D" not in s.by_label
    assert s.child_ids(1) == [3]
    assert s.nodes[1].version == 2


def test_revision_3_after_move(history):
    s = load_state("t", 3)
    assert s.child_ids(1) == []
    assert s.child_ids(2) == [3]
    assert s.ancestor_ids(4) == [2, 3]
    assert s.depth(3) == 1
    assert {ref: n.version for ref, n in s.nodes.items()} == {1: 3, 2: 2, 3: 2, 4: 1}
    assert s.max_depth() == 2


def test_other_tree_is_separate(history):
    Tree.objects.create(id="u", title="U")
    assert load_state("u", 1).nodes == {}
