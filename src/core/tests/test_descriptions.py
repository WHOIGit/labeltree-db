"""Unversioned node descriptions (spec: node-descriptions)."""

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import NodeDescription, NodeVersion, TreeRevision, current_descriptions

from .helpers import add, edit, ids_by_label, publish, publish_new_tree

pytestmark = pytest.mark.django_db


@pytest.fixture
def node():
    publish_new_tree("t", add("new:1", "bleb", description="Cells with a bleb"), author="ann")
    return ids_by_label("t")["bleb"]


def describe(node_id, text, by="bea"):
    return NodeDescription.objects.create(
        node_id=node_id, description=text, added_by=by, added_at=timezone.now()
    )


def test_initial_description_from_add(node):
    entry = NodeDescription.objects.get(node_id=node)
    assert (entry.description, entry.added_by) == ("Cells with a bleb", "ann")
    revision = TreeRevision.objects.get(tree_id="t", number=1)
    assert entry.added_at == revision.published_at


def test_empty_initial_description_writes_no_entry():
    publish_new_tree("u", add("new:1", "x"), add("new:2", "y", description=""))
    assert not NodeDescription.objects.exists()


def test_description_updated(node):
    describe(node, "Cells with one or more blebs")
    assert current_descriptions([node]) == {node: "Cells with one or more blebs"}
    assert NodeDescription.objects.filter(node_id=node).count() == 2


def test_no_description():
    publish_new_tree("u", add("new:1", "x"))
    assert current_descriptions([ids_by_label("u")["x"]]) == {}


def test_cleared_description(node):
    describe(node, "")
    assert current_descriptions([node]) == {node: ""}
    assert NodeDescription.objects.filter(node_id=node).count() == 2


def test_description_change_creates_no_version_or_revision(node):
    describe(node, "changed")
    assert NodeVersion.objects.filter(node_id=node).count() == 1
    assert TreeRevision.objects.filter(tree_id="t").count() == 1


def test_description_survives_versioned_edits(node):
    publish(TreeRevision.objects.get(tree_id="t").tree, edit(node, label="bleb2"))
    assert current_descriptions([node]) == {node: "Cells with a bleb"}


def test_admin_adds_entries_but_never_changes_them(admin_client, admin_user, node):
    response = admin_client.post(
        reverse("admin:core_nodedescription_add"), {"node": node, "description": "From admin"}
    )
    assert response.status_code == 302
    latest = NodeDescription.objects.order_by("-id").first()
    assert (latest.description, latest.added_by) == ("From admin", admin_user.username)
    change_url = reverse("admin:core_nodedescription_change", args=[latest.pk])
    admin_client.post(change_url, {"node": node, "description": "Rewritten"})
    latest.refresh_from_db()
    assert latest.description == "From admin"
    assert (
        admin_client.get(reverse("admin:core_nodedescription_delete", args=[latest.pk])).status_code
        == 403
    )
