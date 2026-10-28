"""Drift runs (spec: worms-drift), with recorded WoRMS responses."""

import httpx
import psycopg
import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection

from core.changesets import latest_rev
from core.models import Changeset, NodeVersion, Tree
from core.tests.helpers import add, ids_by_label, move, publish, publish_new_tree
from worms import drift
from worms.drift import DriftBusy, get_status, run_drift
from worms.models import NodeWarnings, WormsRecord, current_warnings
from worms.tests.fixtures import load

pytestmark = pytest.mark.django_db

LINEAGE = "/AphiaClassificationByAphiaID/{}"


@pytest.fixture
def diatoms():
    publish_new_tree(
        "diatoms",
        add("new:1", "Chromista", aphia_id=7),
        add("new:2", "Bacillariophyceae", parent="new:1", aphia_id=148899),
        add("new:3", "Chaetocerotaceae", parent="new:2", aphia_id=148984),
        add("new:4", "Chaetoceros", parent="new:3", aphia_id=148985),
        add("new:5", "Chaetoceros_didymus", parent="new:4", aphia_id=149122),
        add("new:6", "Dinophyceae", aphia_id=19542),
        add("new:7", "box"),
    )
    return Tree.objects.get(id="diatoms")


def ids():
    return ids_by_label("diatoms")


def warnings_of(label):
    ref = ids()[label]
    return [w["warning"] for w in current_warnings([ref]).get(ref, [])]


def reclassify_chaetoceros(worms_http):
    """WoRMS moves Chaetoceros out of Chaetocerotaceae: only its lineage changes."""
    body = load()[LINEAGE.format(148985)]["body"]
    lineage, node = [], body
    while node:
        lineage.append({k: v for k, v in node.items() if k != "child"})
        node = node["child"]
    kept = [x for x in lineage if x["AphiaID"] != 148984]
    nested = None
    for x in reversed(kept):
        nested = {**x, "child": nested}
    worms_http.override({LINEAGE.format(148985): {"status": 200, "body": nested}})


def other_connection():
    s = connection.settings_dict
    return psycopg.connect(
        dbname=s["NAME"], user=s["USER"], password=s["PASSWORD"] or None,
        host=s["HOST"] or None, port=s["PORT"] or None, autocommit=True,
    )  # fmt: skip


# --- runs -------------------------------------------------------------------------------


def test_quiet_run(diatoms, worms_http):
    worms_http.calls.clear()
    result = run_drift("diatoms", "alice")
    assert result["ok"] and result["rows_added"] == 0
    assert (result["done"], result["total"]) == (6, 6)
    assert len(worms_http.calls) == 12  # every record and lineage re-fetched
    assert not NodeWarnings.objects.exists()


def test_worms_reclassified_a_family(diatoms, worms_http):
    reclassify_chaetoceros(worms_http)
    result = run_drift("diatoms", "alice")
    assert result["ok"] and result["rows_added"] == 1
    assert warnings_of("Chaetoceros") == ["out_of_lineage"]
    assert WormsRecord.objects.filter(aphia_id=148985).count() == 2


def test_drift_never_edits_the_tree(diatoms, worms_http):
    reclassify_chaetoceros(worms_http)
    before = (latest_rev("diatoms"), Changeset.objects.count(), NodeVersion.objects.count())
    run_drift("diatoms", "alice")
    after = (latest_rev("diatoms"), Changeset.objects.count(), NodeVersion.objects.count())
    assert before == after


def test_status_after_a_run(diatoms):
    run_drift("diatoms", "alice")
    status = get_status("diatoms")
    assert status["active"] is None
    last = status["last"]
    assert (last["started_by"], last["ok"], last["checked_rev"]) == ("alice", True, 1)
    assert last["started_at"] <= last["finished_at"]


def test_progress(diatoms, monkeypatch):
    seen = []
    original = drift.get_records

    def spy(*args, progress, **kwargs):
        def report(done, total):
            progress(done, total)
            active = get_status("diatoms")["active"]
            seen.append((active["done"], active["total"]))

        return original(*args, progress=report, **kwargs)

    monkeypatch.setattr(drift, "get_records", spy)
    run_drift("diatoms", "alice")
    assert seen == [(n, 6) for n in range(7)]


# --- failures ------------------------------------------------------------------------------


def test_outage_mid_run(diatoms, worms_http):
    def down(request):
        raise httpx.ConnectError("down")

    reclassify_chaetoceros(worms_http)  # would add a row, if the run got that far
    worms_http.override({"/AphiaRecordByAphiaID/148985": down})
    result = run_drift("diatoms", "alice")
    assert (result["ok"], result["reason"]) == (False, "worms_unreachable")
    assert get_status("diatoms")["last"]["reason"] == "worms_unreachable"
    assert not NodeWarnings.objects.exists()


def test_run_waits_out_a_worms_hiccup(diatoms, worms_http):
    attempts = []
    recorded = load()["/AphiaRecordByAphiaID/148985"]["body"]

    def hiccup(request):
        attempts.append(1)
        if len(attempts) < 5:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json=recorded)

    worms_http.override({"/AphiaRecordByAphiaID/148985": hiccup})
    result = run_drift("diatoms", "alice")
    assert result["ok"] and worms_http.waits == [10.0, 30.0, 60.0, 120.0]


def test_rate_limited(diatoms, worms_http):
    worms_http.override({"/AphiaRecordByAphiaID/148985": {"status": 429, "body": None}})
    result = run_drift("diatoms", "alice")
    assert (result["ok"], result["reason"]) == (False, "worms_rate_limited")
    # sorted AphiaIDs: 7, 19542, 148899, 148984 fetched before 148985 failed
    assert (result["done"], result["total"]) == (4, 6)


# --- concurrency -----------------------------------------------------------------------------


def test_publish_during_a_run(diatoms, worms_http, monkeypatch):
    original = drift.get_records

    def publish_while_fetching(*args, **kwargs):
        fetched = original(*args, **kwargs)
        publish(diatoms, move(ids()["Chaetoceros"], ids()["Chaetocerotaceae"], ids()["box"]))
        publish(diatoms, move(ids()["box"], None, ids()["Dinophyceae"]))
        # Forget what the publishes wrote: only drift's own check can restore it.
        NodeWarnings.objects.all().delete()
        return fetched

    monkeypatch.setattr(drift, "get_records", publish_while_fetching)
    result = run_drift("diatoms", "alice")
    assert (result["rev"], result["checked_rev"]) == (1, 3)
    assert warnings_of("Chaetoceros") == ["out_of_lineage"]  # under Dinophyceae at rev 3


def test_run_already_active(diatoms):
    with other_connection() as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('drift:diatoms'))")
        with pytest.raises(DriftBusy):
            run_drift("diatoms", "bob")
    run_drift("diatoms", "bob")  # released when that connection closed


def test_interrupted_run_is_cleared_on_startup(diatoms):
    stale = {"started_by": "alice", "started_at": "2026-10-27T00:00:00+00:00", "rev": 1,
             "done": 3, "total": 6}  # fmt: skip
    cache.set("drift:diatoms", {"active": stale, "last": None}, timeout=None)
    with other_connection() as conn:  # still running somewhere: left alone
        conn.execute("SELECT pg_advisory_lock(hashtext('drift:diatoms'))")
        call_command("clear_drift_status")
        assert get_status("diatoms")["active"] == stale
    call_command("clear_drift_status")
    status = get_status("diatoms")
    assert status["active"] is None and status["last"]["reason"] == "interrupted"
    assert run_drift("diatoms", "bob")["ok"]
