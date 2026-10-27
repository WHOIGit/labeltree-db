"""Conventions shared by all read endpoints (spec: api-conventions)."""

from django.utils import timezone

from core.models import NodeAlias
from core.tests.helpers import edit, publish


def test_endpoint_location(get, tags):
    status, body, _ = get("/trees")
    assert status == 200
    assert [t["id"] for t in body["trees"]] == ["NES2022_tags"]


def test_future_revision_is_404(get, tags):
    for rev in (50, 0, -1):
        status, body, _ = get(f"/trees/NES2022_tags?rev={rev}")
        assert status == 404 and body["error"] == "not_found"
    status, _, _ = get("/nodes/1?rev=2")
    assert status == 404


def test_empty_fields_are_included(get, tags):
    _, node, _ = get("/nodes/1")
    assert node["description"] == "" and node["aphia_id"] is None and node["aliases"] == []


def test_dropping_empties(get, tags):
    _, node, _ = get("/nodes/1?dropempty=true")
    assert "description" not in node and "aphia_id" not in node and "aliases" not in node
    assert "worms_data" not in node and "parent" not in node and "successors" not in node
    assert node["num_children"] == 0  # zero is not empty


def test_error_body(get, tags):
    status, body, _ = get("/nodes/9999")
    assert status == 404
    assert body == {"status": 404, "error": "not_found", "detail": "Node 9999 does not exist."}


def test_bad_parameter(get, tags):
    for path in ("/nodes/2/descendants?depth=-1", "/nodes/2?rev=x", "/nodes/abc"):
        status, body, _ = get(path)
        assert status == 400, path
        assert set(body) == {"status", "error", "detail"} and body["status"] == 400


def test_revision_header_on_latest(get, tags):
    tree = tags
    publish(tree, edit(1, description="d"))
    _, _, response = get("/trees/NES2022_tags/nodes/bleb")
    assert response["X-Tree-Revision"] == "2"
    _, _, response = get("/trees/NES2022_tags/nodes/bleb?rev=1")
    assert "X-Tree-Revision" not in response


def test_conditional_get(get, tags):
    status, _, first = get("/nodes/10")
    etag = first["ETag"]
    status, body, again = get("/nodes/10", **{"If-None-Match": etag})
    assert status == 304 and again.content == b"" and again["ETag"] == etag

    NodeAlias.objects.create(node_id=10, alias="blebbing", added_by="x", added_at=timezone.now())
    status, body, changed = get("/nodes/10", **{"If-None-Match": etag})
    assert status == 200 and changed["ETag"] != etag
    assert body["aliases"][0]["alias"] == "blebbing"


def test_etag_on_csv(get, tags):
    _, _, response = get("/trees/NES2022_tags/export_flat")
    status, _, _ = get("/trees/NES2022_tags/export_flat", **{"If-None-Match": response["ETag"]})
    assert status == 304


def test_revision_history_page(get, tags):
    for i in range(41):
        publish(tags, edit(1, description=f"d{i}"))
    status, body, _ = get("/trees/NES2022_tags/revisions?limit=10&offset=10")
    assert status == 200 and body["count"] == 42
    assert [r["rev"] for r in body["revisions"]] == list(range(32, 22, -1))


def test_bad_pagination(get, tags):
    assert get("/trees/NES2022_tags/revisions?limit=0")[0] == 400
    assert get("/trees/NES2022_tags/revisions?offset=-1")[0] == 400
