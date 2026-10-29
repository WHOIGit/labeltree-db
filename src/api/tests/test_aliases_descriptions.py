"""Alias and description endpoints (specs: node-aliases, node-descriptions)."""

import pytest
from django.test import Client

from core.changesets import latest_rev
from core.models import NodeAlias
from core.tests.helpers import deprecate, publish

from .conftest import call, logged_in, make_user

pytestmark = pytest.mark.django_db

# taxonomy: ... Chaetoceros(4) > Chaetoceros_didymus(5, alias "Chaetoceros didymus"); other(6)


@pytest.fixture
def drafter():
    client = logged_in(make_user("drafter1", roles={"amplify": "drafter"}))
    return lambda *args: call(client, *args)


def anonymous(path):
    return call(Client(), "get", path)


# --- Aliases ----------------------------------------------------------------------------------


def test_add_a_legacy_string(drafter, taxonomy):
    status, body = drafter("post", "/nodes/6/aliases", {"alias": "L1"})
    assert status == 201 and body["alias"] == "L1" and isinstance(body["id"], int)
    node = anonymous("/nodes/6")[1]
    assert [a["alias"] for a in node["aliases"]] == ["L1"]
    assert latest_rev("taxonomy") == 1  # no new revision
    assert NodeAlias.objects.get(pk=body["id"]).added_by == "drafter1"


def test_duplicate_alias(drafter, taxonomy):
    status, body = drafter("post", "/nodes/5/aliases", {"alias": "Chaetoceros didymus"})
    assert (status, body["error"]) == (409, "alias_exists")


def test_alias_on_a_deprecated_node(drafter, taxonomy):
    publish(taxonomy, deprecate(6))
    assert drafter("post", "/nodes/6/aliases", {"alias": "L1"})[0] == 409


def test_remove(drafter, taxonomy):
    (alias,) = anonymous("/nodes/5/aliases")[1]["aliases"]
    assert drafter("delete", f"/nodes/5/aliases/{alias['id']}")[0] == 204
    assert anonymous("/nodes/5/aliases")[1]["aliases"] == []
    row = NodeAlias.objects.get(pk=alias["id"])
    assert row.removed_by == "drafter1" and row.removed_at is not None
    assert drafter("delete", f"/nodes/5/aliases/{alias['id']}")[0] == 404
    assert drafter("delete", f"/nodes/6/aliases/{alias['id']}")[0] == 404  # not node 6's


def test_history(drafter, taxonomy):
    first = drafter("post", "/nodes/6/aliases", {"alias": "L1"})[1]
    drafter("delete", f"/nodes/6/aliases/{first['id']}")
    drafter("post", "/nodes/6/aliases", {"alias": "L2"})
    assert [a["alias"] for a in anonymous("/nodes/6/aliases")[1]["aliases"]] == ["L2"]
    status, body = anonymous("/nodes/6/aliases?history=true")
    assert status == 200 and body["count"] == 2
    entries = {a["alias"]: a for a in body["aliases"]}
    assert entries["L1"]["removed_by"] == "drafter1" and entries["L1"]["removed_at"]
    assert entries["L2"]["removed_by"] is None and entries["L2"]["added_by"] == "drafter1"
    assert anonymous("/nodes/6/aliases?history=true&limit=1")[1]["aliases"][0]["alias"] == "L2"


def test_readded_alias(drafter, taxonomy):
    first = drafter("post", "/nodes/6/aliases", {"alias": "L1"})[1]
    drafter("delete", f"/nodes/6/aliases/{first['id']}")
    assert drafter("post", "/nodes/6/aliases", {"alias": "L1"})[0] == 201


def test_alias_requests(drafter, taxonomy):
    assert drafter("post", "/nodes/6/aliases", {"alias": "  "})[0] == 400
    assert drafter("post", "/nodes/999/aliases", {"alias": "x"})[0] == 404
    reader = logged_in(make_user("reader1", roles={"amplify": "reader"}))
    assert call(reader, "post", "/nodes/6/aliases", {"alias": "x"})[0] == 403


# --- Descriptions -------------------------------------------------------------------------------


def test_description_set(drafter, taxonomy):
    status, body = drafter("put", "/nodes/6/description", {"description": "Cells with a bleb"})
    assert status == 200 and body == {"id": 6, "description": "Cells with a bleb"}
    assert anonymous("/nodes/6")[1]["description"] == "Cells with a bleb"
    assert anonymous("/nodes/6/description")[1]["description"] == "Cells with a bleb"
    assert latest_rev("taxonomy") == 1


def test_description_cleared(drafter, taxonomy):
    drafter("put", "/nodes/6/description", {"description": "x"})
    drafter("put", "/nodes/6/description", {"description": ""})
    assert anonymous("/nodes/6/description")[1]["description"] == ""
    assert anonymous("/nodes/6/description?history=true")[1]["count"] == 2


def test_history_after_two_edits(drafter, taxonomy):
    drafter("put", "/nodes/6/description", {"description": "first"})
    drafter("put", "/nodes/6/description", {"description": "second"})
    body = anonymous("/nodes/6/description?history=true")[1]
    assert [e["description"] for e in body["history"]] == ["second", "first"]
    assert body["history"][0]["added_by"] == "drafter1"


def test_description_of_a_deprecated_node(drafter, taxonomy):
    publish(taxonomy, deprecate(6))
    status, body = drafter("put", "/nodes/6/description", {"description": "x"})
    assert (status, body["error"]) == (409, "node_deprecated")


def test_node_without_a_description(taxonomy):
    assert anonymous("/nodes/6/description")[1] == {"id": 6, "description": ""}
