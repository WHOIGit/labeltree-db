import json

import pytest
from django.db import connection

from core.importer import expand_import
from core.models import Tree
from core.tests.helpers import TAGS, add, ids_by_label, publish_new_tree


@pytest.fixture(autouse=True)
def node_ids_from_1(db):
    """Node ids come from a sequence, which test rollbacks don't reset."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT setval('core_node_id_seq', 1, false)")


@pytest.fixture
def get(client):
    """GET a URL under /api/v1 and return (status, json-or-text, response)."""

    def _get(path, **headers):
        response = client.get(f"/api/v1{path}", headers=headers)
        if response.status_code == 304:
            return 304, None, response
        if response["Content-Type"].startswith("application/json"):
            return response.status_code, response.json(), response
        return response.status_code, response.content.decode(), response

    return _get


@pytest.fixture
def tags():
    publish_new_tree("NES2022_tags", *expand_import(json.loads(TAGS.read_text())))
    return Tree.objects.get(id="NES2022_tags")


@pytest.fixture
def taxonomy():
    """Revision 1 of a small taxonomy: Chromista > Bacillariophyceae > Chaetocerotaceae >
    Chaetoceros (148985) > Chaetoceros_didymus (149122); plus top-level `other`."""
    publish_new_tree(
        "taxonomy",
        add("new:1", "Chromista"),
        add("new:2", "Bacillariophyceae", parent="new:1"),
        add("new:3", "Chaetocerotaceae", parent="new:2"),
        add("new:4", "Chaetoceros", parent="new:3", aphia_id=148985),
        add("new:5", "Chaetoceros_didymus", parent="new:4", aphia_id=149122,
            aliases=["Chaetoceros didymus"]),
        add("new:6", "other"),
    )  # fmt: skip
    return Tree.objects.get(id="taxonomy")


@pytest.fixture
def ids():
    return ids_by_label
