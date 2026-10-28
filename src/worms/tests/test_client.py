"""WoRMS client against recorded responses (no live calls)."""

import httpx
import pytest

from worms.client import DRIFT_BACKOFF, RETRIES, WormsClient, WormsError

from .fixtures import FixtureTransport


def client(overrides=None):
    transport = FixtureTransport(overrides)
    waits = []
    return WormsClient(transport=transport, sleep=waits.append), transport, waits


def test_record_is_normalised():
    c, _, _ = client()
    record = c.record(149122)
    assert record == {
        "AphiaID": 149122,
        "url": "https://www.marinespecies.org/aphia.php?p=taxdetails&id=149122",
        "scientificname": "Chaetoceros didymus",
        "authority": "Ehrenberg, 1845",
        "status": "accepted",
        "unacceptreason": None,
        "rank": "Species",
        "valid_AphiaID": 149122,
        "valid_name": "Chaetoceros didymus",
        "modified": "2005-07-05T10:00:05.587Z",
    }


def test_lineage_is_flattened_top_level_first():
    c, _, _ = client()
    lineage = c.lineage(149122)
    assert lineage[0] == {"AphiaID": 1, "rank": "Superdomain", "scientificname": "Biota"}
    assert [x["AphiaID"] for x in lineage[-3:]] == [148984, 148985, 149122]


def test_full_record_carries_its_lineage():
    c, _, _ = client()
    record = c.full_record(149122)
    assert record["scientificname"] == "Chaetoceros didymus"
    assert record["lineage"][-1]["AphiaID"] == 149122


def test_unknown_aphia_id_is_none():
    c, _, _ = client()
    assert c.record(999999999) is None
    assert c.full_record(999999999) is None


def test_synonym():
    c, _, _ = client()
    record = c.record(149223)
    assert (record["status"], record["valid_AphiaID"]) == ("unaccepted", 149168)


def test_search():
    c, transport, _ = client()
    results = c.search("Chaetoceros", limit=5)
    assert len(results) == 5 and results[0]["scientificname"] == "Chaetoceros"
    assert set(results[0]) == {
        "AphiaID", "url", "scientificname", "authority", "status", "unacceptreason", "rank",
        "valid_AphiaID", "valid_name", "modified",
    }  # fmt: skip
    assert c.search("zzzqqq") == []


def test_search_pages_until_limit():
    page = [{"AphiaID": i, "scientificname": f"n{i}"} for i in range(50)]
    key = "/AphiaRecordsByName/many?like=true&marine_only=false&offset={}"
    c, transport, _ = client(
        {
            key.format(1): {"status": 200, "body": page},
            key.format(51): {"status": 200, "body": page[:10]},
        }
    )
    assert len(c.search("many", limit=100)) == 60
    assert len(transport.calls) == 2


# --- failures ------------------------------------------------------------------


def failing(exc_or_status, headers=None):
    def respond(request):
        if isinstance(exc_or_status, int):
            return httpx.Response(exc_or_status, headers=headers or {})
        raise exc_or_status

    return {
        "/AphiaRecordByAphiaID/149122": respond,
        "/AphiaClassificationByAphiaID/149122": respond,
    }


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (httpx.ConnectTimeout("timed out"), "worms_unreachable"),
        (httpx.ConnectError("refused"), "worms_unreachable"),
        (503, "worms_error"),
        (429, "worms_rate_limited"),
    ],
)
def test_persistent_failure_is_classified_after_retries(failure, reason):
    c, transport, waits = client(failing(failure))
    with pytest.raises(WormsError) as info:
        c.record(149122)
    assert info.value.reason == reason
    assert len(transport.calls) == RETRIES + 1
    assert len(waits) == RETRIES


def test_rate_limit_waits_for_retry_after():
    c, _, waits = client(failing(429, {"Retry-After": "7"}))
    with pytest.raises(WormsError):
        c.record(149122)
    assert waits == [7.0, 7.0]


def test_rate_limit_default_wait():
    c, _, waits = client(failing(429))
    with pytest.raises(WormsError):
        c.record(149122)
    assert waits == [30.0, 30.0]


def test_client_error_is_not_retried():
    c, transport, _ = client(failing(400))
    with pytest.raises(WormsError) as info:
        c.record(149122)
    assert info.value.reason == "worms_error" and len(transport.calls) == 1


def test_transient_failure_recovers():
    attempts = []

    def flaky(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json={"AphiaID": 149122, "scientificname": "x"})

    c, _, waits = client({"/AphiaRecordByAphiaID/149122": flaky})
    assert c.record(149122)["AphiaID"] == 149122
    assert len(waits) == 1


def test_backoff_waits():
    c, _, waits = client(failing(503))
    with pytest.raises(WormsError):
        c.record(149122)
    assert waits == [1.0, 2.0]


def test_long_backoff_for_drift():
    transport = FixtureTransport(failing(httpx.ConnectTimeout("slow")))
    waits = []
    c = WormsClient(transport=transport, sleep=waits.append, backoff=DRIFT_BACKOFF)
    with pytest.raises(WormsError):
        c.record(149122)
    assert waits == [10.0, 30.0, 60.0, 120.0] and len(transport.calls) == 5
