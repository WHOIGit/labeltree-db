"""The WoRMS record cache (spec: worms-records)."""

import threading

import httpx
import pytest
from django.db import connection

from worms.client import WormsClient, WormsError
from worms.models import WormsRecord
from worms.records import (
    cached_records,
    get_record,
    get_records,
    newest_rows,
    store,
    store_search_hit,
)
from worms.tests.fixtures import FixtureTransport, load

RECORD = "/AphiaRecordByAphiaID/{}"
LINEAGE = "/AphiaClassificationByAphiaID/{}"

pytestmark = pytest.mark.django_db


def refetch(aphia_id) -> WormsRecord:
    """Fetch and store again, as a sync does, whatever is cached."""
    from worms import records

    client = records.default_client()
    return store(aphia_id, client.full_record(aphia_id))


def recorded(aphia_id, **changes):
    body = dict(load()[RECORD.format(aphia_id)]["body"])
    return {RECORD.format(aphia_id): {"status": 200, "body": {**body, **changes}}}


def test_cache_miss_fetches_and_stores(worms_http):
    row = get_record(149122)
    assert row.record["scientificname"] == "Chaetoceros didymus"
    assert row.record["lineage"][-1]["AphiaID"] == 149122
    assert row.worms_modified.isoformat().startswith("2005-07-05T10:00:05")
    assert worms_http.calls == [RECORD.format(149122), LINEAGE.format(149122)]


def test_cache_hit_makes_no_call(worms_http):
    get_record(149122)
    worms_http.calls.clear()
    assert get_record(149122).record["AphiaID"] == 149122
    assert worms_http.calls == []


def test_record_changed_in_worms(worms_http):
    first = get_record(149122)
    worms_http.override(recorded(149122, modified="2026-01-01T00:00:00Z", status="unaccepted"))
    second = refetch(149122)
    assert second.pk != first.pk and second.record["status"] == "unaccepted"
    assert WormsRecord.objects.filter(aphia_id=149122).count() == 2
    assert newest_rows([149122])[149122].pk == second.pk


def test_lineage_changed_in_worms(worms_http):
    first = get_record(148985)
    body = load()[LINEAGE.format(148985)]["body"]
    moved = {**body, "child": {"AphiaID": 42, "rank": "Kingdom", "scientificname": "Elsewhere",
                               "child": None}}  # fmt: skip
    worms_http.override({LINEAGE.format(148985): {"status": 200, "body": moved}})
    second = refetch(148985)
    assert second.pk != first.pk
    assert second.record["modified"] == first.record["modified"]
    assert [x["AphiaID"] for x in second.record["lineage"]] == [1, 42]


def test_record_unchanged(worms_http):
    first = get_record(149122)
    second = refetch(149122)
    assert second.pk == first.pk and second.fetched_at > first.fetched_at
    assert WormsRecord.objects.filter(aphia_id=149122).count() == 1


def test_record_changing_back_makes_the_old_row_newest(worms_http):
    a = get_record(149122)
    worms_http.override(recorded(149122, status="unaccepted"))
    refetch(149122)
    worms_http.override(recorded(149122))
    again = refetch(149122)
    assert again.pk == a.pk and WormsRecord.objects.filter(aphia_id=149122).count() == 2


def test_cached_records_never_call_worms(worms_http):
    get_records([149122])
    store_search_hit({**load()[RECORD.format(148985)]["body"]})  # no lineage: incomplete
    worms_http.calls.clear()
    records = cached_records([149122, 148985, 999])
    assert set(records) == {149122} and worms_http.calls == []


def test_unknown_aphia_id_is_cached_as_absent(worms_http):
    row = get_record(999999999)
    assert row.record is None and row.complete
    worms_http.calls.clear()
    assert get_record(999999999).record is None and worms_http.calls == []


def test_failure_leaves_the_cache_alone(worms_http):
    worms_http.override({RECORD.format(149122): {"status": 503, "body": None}})
    result = get_records([149122, 148985])
    assert result.failed[149122].reason == "worms_error"
    assert set(result.rows) == {148985}
    assert not WormsRecord.objects.filter(aphia_id=149122).exists()
    with pytest.raises(WormsError):
        get_record(149122)


def test_failures_skip(worms_http):
    def down(request):
        raise httpx.ConnectError("down")

    worms_http.override({RECORD.format(148985): down})
    result = get_records([149122, 148985, 148984])
    assert set(result.rows) == {149122, 148984}
    assert {a: e.reason for a, e in result.failed.items()} == {148985: "worms_unreachable"}


def test_search_hit_is_cached_without_lineage_then_filled(worms_http):
    hit = WormsClient(transport=FixtureTransport()).search("Chaetoceros didymus", limit=1)[0]
    row = store_search_hit(hit)
    assert row.record["lineage"] is None and not row.complete
    full = get_record(hit["AphiaID"])  # incomplete counts as a miss
    assert full.pk == row.pk and full.record["lineage"]
    assert WormsRecord.objects.filter(aphia_id=hit["AphiaID"]).count() == 1


def test_search_hit_of_a_cached_record_keeps_the_lineage(worms_http):
    full = get_record(149122)
    hit = {k: v for k, v in full.record.items() if k != "lineage"}
    assert store_search_hit(hit).pk == full.pk
    assert newest_rows([149122])[149122].complete


def test_refresh_never_touches_node_versions(worms_http):
    from core.models import NodeVersion
    from core.tests.helpers import add, publish_new_tree

    publish_new_tree("t", add("new:1", "Chaetoceros_didymus", aphia_id=149122))
    before = list(NodeVersion.objects.values_list("node_id", "version", "valid_to_rev"))
    refetch(149122)
    worms_http.override(recorded(149122, status="unaccepted"))
    refetch(149122)
    assert list(NodeVersion.objects.values_list("node_id", "version", "valid_to_rev")) == before


@pytest.mark.django_db(transaction=True)
def test_concurrent_fetches_store_one_row():
    record = WormsClient(transport=FixtureTransport()).full_record(149122)
    barrier = threading.Barrier(4)

    def fetch():
        barrier.wait()
        try:
            store(149122, record)
        finally:
            connection.close()

    threads = [threading.Thread(target=fetch) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert WormsRecord.objects.filter(aphia_id=149122).count() == 1
