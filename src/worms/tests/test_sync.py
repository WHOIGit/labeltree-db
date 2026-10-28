"""WoRMS jobs and syncs (specs: worms-records, worms-sync), with recorded WoRMS responses."""

import copy
from io import StringIO

import httpx
import psycopg
import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import connection

from core.changesets import create_changeset, latest_rev, publish_changeset
from core.models import Changeset, NodeVersion, Tree
from core.tests.helpers import add, ids_by_label, move, publish, publish_new_tree
from worms import sync
from worms.models import NodeWarnings, WormsRecord, current_warnings
from worms.sync import SyncBusy, get_job, get_syncs, run_job
from worms.tests.fixtures import load

pytestmark = pytest.mark.django_db

RECORD = "/AphiaRecordByAphiaID/{}"
LINEAGE = "/AphiaClassificationByAphiaID/{}"
DIATOM_IDS = [7, 19542, 148899, 148984, 148985, 149122]


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


@pytest.fixture(autouse=True)
def forget_jobs():
    """The cache table isn't rolled back between tests."""
    yield
    cache.clear()


@pytest.fixture
def snapshots(monkeypatch):
    """Every status a job saves, in order."""
    saved = []
    original = sync._Job.save

    def save(self):
        saved.append(copy.deepcopy(self.status))
        original(self)

    monkeypatch.setattr(sync._Job, "save", save)
    return saved


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


def unaccept_bacillariophyceae(worms_http):
    record = {**load()[RECORD.format(148899)]["body"], "status": "unaccepted"}
    record["valid_AphiaID"] = 7
    worms_http.override({RECORD.format(148899): {"status": 200, "body": record}})


def down(request):
    raise httpx.ConnectError("down")


def rate_limited(request):
    return httpx.Response(429, headers={"Retry-After": "30"})


def other_connection():
    s = connection.settings_dict
    return psycopg.connect(
        dbname=s["NAME"], user=s["USER"], password=s["PASSWORD"] or None,
        host=s["HOST"] or None, port=s["PORT"] or None, autocommit=True,
    )  # fmt: skip


def sync_tree(**kwargs):
    return run_job("sync_tree", tree="diatoms", started_by="alice", **kwargs)


# --- Kinds ---------------------------------------------------------------------------------


def test_quiet_sync(diatoms, worms_http):
    worms_http.calls.clear()
    status = sync_tree()
    assert status["state"] == "finished" and status["failed"] == []
    assert (status["done"], status["total"]) == (6, 6)
    assert len(worms_http.calls) == 12  # every record and lineage re-fetched
    assert status["checked"] == [{"tree": "diatoms", "rev": 1, "rows_added": 0}]
    assert not NodeWarnings.objects.exists()


def test_worms_reclassified_a_family(diatoms, worms_http):
    reclassify_chaetoceros(worms_http)
    status = sync_tree()
    assert status["checked"][0]["rows_added"] == 1
    assert warnings_of("Chaetoceros") == ["out_of_lineage"]
    assert WormsRecord.objects.filter(aphia_id=148985).count() == 2


def test_sync_never_edits_the_tree(diatoms, worms_http):
    reclassify_chaetoceros(worms_http)
    before = (latest_rev("diatoms"), Changeset.objects.count(), NodeVersion.objects.count())
    sync_tree()
    after = (latest_rev("diatoms"), Changeset.objects.count(), NodeVersion.objects.count())
    assert before == after


def test_only_new_aphia_ids(diatoms, worms_http):
    cs = create_changeset(  # saved and published without fetching 110153
        author="a", tree=diatoms, base_rev=1,
        changes=[add("new:1", "Heterocapsa_triquetra", parent=ids()["Dinophyceae"],
                     aphia_id=110153)],
    )  # fmt: skip
    publish_changeset(cs, published_by="b")
    worms_http.calls.clear()
    status = run_job("sync_new", tree="diatoms", started_by="alice")
    assert status["total"] == 1 and worms_http.calls == [RECORD.format(110153),
                                                         LINEAGE.format(110153)]  # fmt: skip
    assert status["checked"][0]["rev"] == 2


def test_full_cache_sync(diatoms, worms_http):
    publish_new_tree("other", add("new:1", "Chaetoceros", aphia_id=148985))  # shared
    from worms.records import get_records

    get_records([149120])  # cached, used by no tree
    worms_http.calls.clear()
    status = run_job("sync_all", started_by="admin")
    assert status["total"] == 7
    assert sorted(c for c in worms_http.calls if c.startswith("/AphiaRecord")) == sorted(
        RECORD.format(a) for a in [*DIATOM_IDS, 149120]
    )
    assert [c["tree"] for c in status["checked"]] == ["diatoms", "other"]


def test_try_again(diatoms, worms_http):
    """aphia_ids restricts the fetching; the whole tree is still re-checked."""
    reclassify_chaetoceros(worms_http)
    unaccept_bacillariophyceae(worms_http)  # not fetched this time
    worms_http.calls.clear()
    status = sync_tree(aphia_ids=[148985, 149122])
    assert status["total"] == 2 and len(worms_http.calls) == 4
    assert warnings_of("Chaetoceros") == ["out_of_lineage"]
    assert warnings_of("Bacillariophyceae") == []


def test_fetch_before_validating(diatoms, worms_http):
    worms_http.calls.clear()
    status = run_job("fetch", tree="diatoms", started_by="alice", aphia_ids=[149122, 110153])
    assert (status["total"], status["done"]) == (1, 1)
    assert worms_http.calls == [RECORD.format(110153), LINEAGE.format(110153)]
    assert status["checked"] == [] and not NodeWarnings.objects.exists()


# --- Status --------------------------------------------------------------------------------


def test_status_after_a_sync(diatoms):
    sync_tree()
    syncs = get_syncs("diatoms")
    assert syncs["active"] is None
    last = syncs["last"]
    assert (last["kind"], last["started_by"], last["state"]) == ("sync_tree", "alice", "finished")
    assert last["started_at"] <= last["finished_at"]
    assert get_job(last["id"]) == last


def test_progress(diatoms, snapshots):
    sync_tree()
    progress = [(s["done"], s["total"]) for s in snapshots]
    assert progress[0] == (0, 6) and progress[-1] == (6, 6)
    assert sorted(set(progress)) == [(n, 6) for n in range(7)]


def test_status_without_a_tree_is_sync_all(diatoms):
    status = run_job("sync_all", started_by="admin")
    assert get_syncs(None)["last"]["id"] == status["id"]
    assert get_syncs("diatoms")["last"]["id"] == status["id"]  # also the tree's last sync


# --- Failures ------------------------------------------------------------------------------


def test_outage_for_one_aphia_id(diatoms, worms_http, snapshots):
    unaccept_bacillariophyceae(worms_http)
    reclassify_chaetoceros(worms_http)  # would warn, if 148985 could be fetched
    worms_http.override({RECORD.format(148985): down})
    status = sync_tree()
    assert status["state"] == "finished"
    assert (status["done"], status["total"]) == (5, 6)
    assert [(f["aphia_id"], f["reason"]) for f in status["failed"]] == [
        (148985, "worms_unreachable")
    ]
    assert warnings_of("Bacillariophyceae") == ["unaccepted_aphia"]  # others updated
    # no row for nodes needing the failed record
    needing = [ids()["Chaetoceros"], ids()["Chaetoceros_didymus"]]
    assert not NodeWarnings.objects.filter(node_id__in=needing).exists()
    assert worms_http.waits.count(12.0) == 1  # 1, 2, 5, 12 s: an API-started job
    retrying = [r for s in snapshots for r in s["retrying"]]
    assert {(r["aphia_id"], r["attempt"], r["retries"]) for r in retrying} == {
        (148985, n, 4) for n in (1, 2, 3, 4)
    }
    assert all(r["wait_until"] for r in retrying)
    assert snapshots[-1]["retrying"] == []


def test_outage_mid_sync(diatoms, worms_http):
    """WoRMS stops responding: whatever wasn't fetched fails; the rest is written."""
    unaccept_bacillariophyceae(worms_http)
    worms_http.override({RECORD.format(a): down for a in (148985, 149122, 19542)})
    status = sync_tree()
    assert {f["aphia_id"] for f in status["failed"]} == {148985, 149122, 19542}
    assert {f["reason"] for f in status["failed"]} == {"worms_unreachable"}
    assert warnings_of("Bacillariophyceae") == ["unaccepted_aphia"]


def test_rate_limited_twice(diatoms, worms_http, snapshots, monkeypatch):
    monkeypatch.setattr(sync, "POOL_SIZE", 1)  # one AphiaID at a time: a predictable order
    worms_http.override({RECORD.format(148984): rate_limited})
    pauses = []
    status = sync_tree(sleep=pauses.append)
    assert pauses == [30.0]  # paused once, then stopped at the next 429
    assert any(s["paused"] and s["paused"]["reason"] == "worms_rate_limited" for s in snapshots)
    assert status["done"] == 3  # 7, 19542, 148899
    assert [(f["aphia_id"], f["reason"]) for f in status["failed"]] == [
        (a, "worms_rate_limited") for a in (148984, 148985, 149122)
    ]
    assert status["paused"] is None


def test_rate_limited_once(diatoms, worms_http, monkeypatch):
    answers = [rate_limited(None)]
    recorded = load()[RECORD.format(148984)]["body"]
    worms_http.override(
        {RECORD.format(148984): lambda r: answers.pop() if answers else httpx.Response(
            200, json=recorded)}
    )  # fmt: skip
    pauses = []
    status = sync_tree(sleep=pauses.append)
    assert pauses == [30.0] and status["failed"] == [] and status["done"] == 6


def test_scheduled_jobs_pause_four_times(diatoms, worms_http, monkeypatch):
    monkeypatch.setattr(sync, "POOL_SIZE", 1)
    worms_http.override({RECORD.format(148984): rate_limited})
    pauses = []
    status = sync_tree(scheduled=True, sleep=pauses.append)
    assert pauses == [30.0] * 4
    assert {f["reason"] for f in status["failed"]} == {"worms_rate_limited"}


def test_scheduled_jobs_retry_slowly(diatoms, worms_http):
    worms_http.override({RECORD.format(148985): down})
    sync_tree(scheduled=True)
    assert worms_http.waits == [10.0, 30.0, 60.0, 120.0]


# --- Concurrency ---------------------------------------------------------------------------


def test_publish_during_a_sync(diatoms, monkeypatch):
    original = sync._fetch

    def publish_while_fetching(*args, **kwargs):
        original(*args, **kwargs)
        publish(diatoms, move(ids()["Chaetoceros"], ids()["Chaetocerotaceae"], ids()["box"]))
        publish(diatoms, move(ids()["box"], None, ids()["Dinophyceae"]))
        # Forget what the publishes wrote: only the sync's own check can restore it.
        NodeWarnings.objects.all().delete()

    monkeypatch.setattr(sync, "_fetch", publish_while_fetching)
    status = sync_tree()
    assert status["checked"][0]["rev"] == 3
    assert warnings_of("Chaetoceros") == ["out_of_lineage"]  # under Dinophyceae at rev 3


def test_sync_already_active(diatoms):
    with other_connection() as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('worms-sync:diatoms'))")
        with pytest.raises(SyncBusy):
            sync_tree()
        run_job("fetch", tree="diatoms", started_by="a", aphia_ids=[1])  # fetches don't wait
    sync_tree()  # released when that connection closed


def test_tree_sync_during_a_full_sync(diatoms):
    with other_connection() as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('worms-sync:all'))")
        with pytest.raises(SyncBusy):
            sync_tree()


def test_full_sync_during_a_tree_sync(diatoms):
    with other_connection() as conn:
        conn.execute("SELECT pg_advisory_lock_shared(hashtext('worms-sync:all'))")
        conn.execute("SELECT pg_advisory_lock(hashtext('worms-sync:other'))")
        with pytest.raises(SyncBusy):
            run_job("sync_all", started_by="admin")
        sync_tree()  # a different tree


def test_interrupted_sync(diatoms):
    stale = {
        "id": "dead", "kind": "sync_tree", "tree": "diatoms", "started_by": "alice",
        "started_at": "2026-10-27T00:00:00+00:00", "finished_at": None, "state": "running",
        "aphia_ids": None, "total": 6, "done": 3, "failed": [], "retrying": [], "paused": None,
        "checked": [],
    }  # fmt: skip
    cache.set("worms-job:dead", stale)
    cache.set("worms-sync:diatoms", {"active": "dead", "last": None})
    with other_connection() as conn:  # still running somewhere: left alone
        conn.execute("SELECT pg_advisory_lock(hashtext('worms-job:dead'))")
        call_command("clear_worms_jobs")
        assert get_syncs("diatoms")["active"]["state"] == "running"
    out = StringIO()
    call_command("clear_worms_jobs", stdout=out)
    assert "1 interrupted" in out.getvalue()
    syncs = get_syncs("diatoms")
    assert syncs["active"] is None and syncs["last"]["state"] == "interrupted"
    assert sync_tree()["state"] == "finished"  # a new sync can start at once


# --- Command -------------------------------------------------------------------------------


def worms_sync(*args):
    out, err = StringIO(), StringIO()
    call_command("worms_sync", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_command(diatoms, worms_http):
    reclassify_chaetoceros(worms_http)
    out, _ = worms_sync("diatoms", "--user", "cron")
    assert "sync_tree on diatoms: fetched 6 of 6 AphiaIDs, 1 node(s)" in out
    assert get_syncs("diatoms")["last"]["started_by"] == "cron"
    assert "sync_new on diatoms: fetched 0 of 0" in worms_sync("diatoms", "--new")[0]
    assert "sync_all on all trees" in worms_sync("--all")[0]


def test_command_fails_on_failed_aphia_ids(diatoms, worms_http):
    worms_http.override({RECORD.format(148985): down})
    with pytest.raises(CommandError, match="1 AphiaID"):
        worms_sync("diatoms")
    assert get_syncs("diatoms")["last"]["checked"]  # warnings were still written


@pytest.mark.parametrize("args", [(), ("diatoms", "--all"), ("--all", "--new"), ("nope",)])
def test_command_arguments(diatoms, args):
    with pytest.raises(CommandError):
        worms_sync(*args)


def test_command_while_busy(diatoms):
    with other_connection() as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('worms-sync:diatoms'))")
        with pytest.raises(CommandError, match="already active"):
            worms_sync("diatoms")
