"""Drift endpoints and the run_drift command (spec: worms-drift)."""

import time

import psycopg
import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import connection

from core.changesets import latest_rev
from core.tests.helpers import deprecate, edit, publish
from worms.warnings import record_warnings


def other_connection():
    s = connection.settings_dict
    return psycopg.connect(
        dbname=s["NAME"], user=s["USER"], password=s["PASSWORD"] or None,
        host=s["HOST"] or None, port=s["PORT"] or None, autocommit=True,
    )  # fmt: skip


@pytest.fixture
def post(client):
    def _post(path):
        response = client.post(f"/api/v1{path}")
        return response.status_code, response.json()

    return _post


@pytest.mark.django_db(transaction=True)
def test_start_a_run(post, get, taxonomy):
    try:
        status, body = post("/trees/taxonomy/drift")
        assert status == 202 and body["tree"] == "taxonomy"
        for _ in range(100):  # the run happens on a background thread
            _, body, _ = get("/trees/taxonomy/drift/status")
            if body["last"]:
                break
            time.sleep(0.05)
        assert body["active"] is None
        assert (body["last"]["ok"], body["last"]["started_by"]) == (True, "anonymous")
        assert body["last"]["total"] == 2
        assert latest_rev("taxonomy") == 1  # no revision
    finally:
        cache.delete("drift:taxonomy")  # the cache table isn't flushed between tests


@pytest.mark.django_db
def test_run_already_active(post, taxonomy):
    with other_connection() as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('drift:taxonomy'))")
        status, body = post("/trees/taxonomy/drift")
    assert (status, body["error"]) == (409, "drift_in_progress")


@pytest.mark.django_db
def test_unknown_tree(post, get):
    assert post("/trees/nope/drift")[0] == 404
    assert get("/trees/nope/drift/status")[0] == 404
    assert get("/trees/nope/drift")[0] == 404


def test_status_before_any_run(get, taxonomy):
    assert get("/trees/taxonomy/drift/status")[1] == {
        "tree": "taxonomy", "active": None, "last": None,
    }  # fmt: skip


def test_status_shows_progress(get, taxonomy):
    active = {"started_by": "a", "started_at": "x", "rev": 1, "done": 120, "total": 175}
    cache.set("drift:taxonomy", {"active": active, "last": None})
    with other_connection() as conn:  # the run is alive in some process
        conn.execute("SELECT pg_advisory_lock(hashtext('drift:taxonomy'))")
        body = get("/trees/taxonomy/drift/status")[1]
        assert (body["active"]["done"], body["active"]["total"]) == (120, 175)
    # its process died: no longer active
    body = get("/trees/taxonomy/drift/status")[1]
    assert body["active"] is None and body["last"]["reason"] == "interrupted"


def test_report_lists_nodes_with_warnings(get, taxonomy):
    out = [{"warning": "out_of_lineage", "detail": "x"}]
    record_warnings({1: out, 2: out, 3: out, 4: out, 6: out})
    record_warnings({4: []})  # cleared
    publish(taxonomy, deprecate(6))  # no longer in the tree
    publish(taxonomy, edit(5, label="Cd"))
    record_warnings({5: out})
    status, body, response = get("/trees/taxonomy/drift")
    assert status == 200 and body["count"] == 4 and body["rev"] == 3
    assert [n["id"] for n in body["nodes"]] == [1, 2, 3, 5]
    assert body["nodes"][3] == {
        "id": 5, "label": "Cd", "version": 2, "aphia_id": 149122, "worms_warnings": out,
    }  # fmt: skip
    assert response["X-Tree-Revision"] == "3"
    page = get("/trees/taxonomy/drift?limit=2&offset=2")[1]
    assert (page["count"], [n["id"] for n in page["nodes"]]) == (4, [3, 5])


def test_report_with_three_warned_nodes(get, taxonomy):
    out = [{"warning": "duplicate_aphia", "detail": "x"}]
    record_warnings({1: out, 2: out, 3: out})
    assert get("/trees/taxonomy/drift")[1]["count"] == 3


# --- run_drift command ----------------------------------------------------------------------


def test_command(taxonomy, capsys):
    call_command("run_drift", "taxonomy", "--user", "cron")
    assert "re-fetched 2 AphiaIDs, 0 node(s)" in capsys.readouterr().out
    assert latest_rev("taxonomy") == 1


def test_command_failure(taxonomy, worms_http):
    worms_http.override({"/AphiaRecordByAphiaID/148985": {"status": 500, "body": None}})
    with pytest.raises(CommandError, match="worms_error"):
        call_command("run_drift", "taxonomy")
    with pytest.raises(CommandError, match="does not exist"):
        call_command("run_drift", "nope")
