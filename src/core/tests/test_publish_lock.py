"""Per-tree publish lock-out (task 5.5).

These tests use real transactions (transactional_db) and a second database
connection standing in for another process, because the advisory lock lives
until the publishing transaction ends.
"""

import psycopg
import pytest
from django.db import connection

from core.changesets import ChangesetError, create_changeset, latest_rev, publish_changeset
from core.models import Node, NodeAlias, NodeVersion, Tree, TreeRevision

from .helpers import add, edit, ids_by_label, publish_new_tree

pytestmark = pytest.mark.django_db(transaction=True)


def other_process():
    s = connection.settings_dict
    return psycopg.connect(
        dbname=s["NAME"],
        user=s["USER"],
        password=s["PASSWORD"] or None,
        host=s["HOST"] or None,
        port=s["PORT"] or None,
    )


def hold_publish_lock(conn, tree_key):
    """Take the publish lock in an open transaction on `conn`, as a running publish would."""
    got = conn.execute(
        "SELECT pg_try_advisory_xact_lock(hashtext(%s))", [f"publish:{tree_key}"]
    ).fetchone()[0]
    assert got


@pytest.fixture
def tree():
    publish_new_tree("t", add("new:1", "P"), add("new:2", "x", parent="new:1"))
    return Tree.objects.get(id="t")


def draft(tree, *changes):
    return create_changeset(author="a", tree=tree, base_rev=latest_rev("t"), changes=list(changes))


def test_concurrent_publish_is_refused_then_stale(tree):
    x = ids_by_label("t")["x"]
    first, second = draft(tree, edit(x, label="x1")), draft(tree, edit(x, description="d"))

    with other_process() as conn:
        hold_publish_lock(conn, "t")
        with pytest.raises(ChangesetError) as exc:
            publish_changeset(second, published_by="b")
        assert exc.value.error == "publish_in_progress"
        conn.rollback()  # the first publish ends

    publish_changeset(first, published_by="b")
    with pytest.raises(ChangesetError) as exc:
        publish_changeset(second, published_by="b")
    assert exc.value.error == "stale_base"


def test_lock_is_per_tree(tree):
    publish_new_tree("u", add("new:1", "Q"))
    with other_process() as conn:
        hold_publish_lock(conn, "u")
        assert publish_changeset(draft(tree, add("new:1", "R")), published_by="b").number == 2


def test_new_tree_locks_its_proposed_id():
    from core.changesets import NewTree

    cs = create_changeset(author="a", changes=[add("new:1", "x")], new_tree=NewTree("v", "V"))
    with other_process() as conn:
        hold_publish_lock(conn, "v")
        with pytest.raises(ChangesetError) as exc:
            publish_changeset(cs, published_by="b")
        assert exc.value.error == "publish_in_progress"


def test_crashed_publish_does_not_lock_out(tree):
    conn = other_process()
    hold_publish_lock(conn, "t")
    conn.close()  # the process dies mid-publish, without committing
    assert publish_changeset(draft(tree, add("new:1", "R")), published_by="b").number == 2


def test_failure_mid_publish_leaves_no_trace(tree, monkeypatch):
    counts = (TreeRevision.objects.count(), Node.objects.count(), NodeVersion.objects.count())
    cs = draft(tree, add("new:1", "R", aliases=["r"]), edit(ids_by_label("t")["x"], label="x2"))

    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(NodeAlias.objects, "bulk_create", boom)
    with pytest.raises(RuntimeError):
        publish_changeset(cs, published_by="b")
    monkeypatch.undo()

    assert (
        TreeRevision.objects.count(),
        Node.objects.count(),
        NodeVersion.objects.count(),
    ) == counts
    assert NodeAlias.objects.count() == 0
    cs.refresh_from_db()
    assert cs.state == "draft"

    with other_process() as conn:  # the lock was released with the rollback
        hold_publish_lock(conn, "t")
        conn.rollback()
    assert publish_changeset(cs, published_by="b").number == 2
