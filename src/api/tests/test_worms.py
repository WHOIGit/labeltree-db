"""/worms lookups (spec: worms-records)."""

import httpx
import pytest

from worms.models import WormsRecord

from .conftest import logged_in, make_user


@pytest.fixture
def get(db):
    """Lookups need a login (any user, no role)."""
    client = logged_in(make_user("someone"))

    def _get(path, **headers):
        response = client.get(f"/api/v1{path}", headers=headers)
        return response.status_code, response.json(), response

    return _get


def test_cache_miss_is_fetched_cached_and_returned(get, worms_http):
    status, body, _ = get("/worms/148985")
    assert status == 200
    assert (body["AphiaID"], body["scientificname"], body["rank"]) == (
        148985,
        "Chaetoceros",
        "Genus",
    )
    assert "lineage" not in body
    assert WormsRecord.objects.filter(aphia_id=148985).exists()
    worms_http.calls.clear()
    assert get("/worms/148985")[0] == 200 and worms_http.calls == []


def test_record_response_has_fetched_at(get):
    _, body, _ = get("/worms/149122")
    row = WormsRecord.objects.get(aphia_id=149122)
    assert body["fetched_at"] == row.fetched_at.isoformat()


def test_unreachable_and_not_cached(get, worms_http):
    def down(request):
        raise httpx.ConnectError("down")

    worms_http.override({"/AphiaRecordByAphiaID/149122": down})
    status, body, _ = get("/worms/149122")
    assert (status, body["error"]) == (503, "worms_unreachable")


def test_unreachable_but_cached(get, worms_http):
    get("/worms/149122")
    worms_http.override({"/AphiaRecordByAphiaID/149122": {"status": 503, "body": None}})
    assert get("/worms/149122")[0] == 200


def test_unknown_aphia_id(get):
    status, body, _ = get("/worms/999999999")
    assert (status, body["error"]) == (404, "not_found")


def test_lineage_top_level_first(get):
    _, body, _ = get("/worms/149122/lineage")
    names = [x["scientificname"] for x in body["lineage"]]
    assert names[0] == "Biota" and names[-1] == "Chaetoceros"
    assert "fetched_at" in body


def test_between_a_genus_and_its_species(get):
    for path in ("/worms/148985/between/149122", "/worms/149122/between/148985"):
        _, body, _ = get(path)
        assert [x["AphiaID"] for x in body["records"]] == [148985, 149122], path


def test_between_further_apart(get):
    _, body, _ = get("/worms/148899/between/149122")
    ids = [x["AphiaID"] for x in body["records"]]
    assert ids[0] == 148899 and ids[-1] == 149122 and 148985 in ids


def test_between_unrelated_records(get):
    status, body, _ = get("/worms/149122/between/19542")
    assert (status, body["error"]) == (400, "bad_parameter")


def test_ancestor_is_the_common_ancestor(get):
    _, body, _ = get("/worms/148985/common_ancestor/149122")
    assert body["common_ancestor"]["AphiaID"] == 148985


def test_common_ancestor_of_cousins(get):
    # Chaetoceros didymus and Rhizosolenia alata are both diatoms.
    _, body, _ = get("/worms/149122/common_ancestor/149223")
    assert body["common_ancestor"]["scientificname"] == "Coscinodiscophycidae"


def test_search(get, worms_http):
    status, body, _ = get("/worms/search?name=Chaetoceros&limit=3")
    assert status == 200 and len(body["results"]) == 3
    assert body["results"][0]["scientificname"] == "Chaetoceros"
    assert all("fetched_at" in r for r in body["results"])
    assert WormsRecord.objects.filter(aphia_id=148985).exists()


def test_search_nothing_found(get):
    assert get("/worms/search?name=zzzqqq")[1]["results"] == []


def test_search_parameters(get):
    assert get("/worms/search")[0] == 400
    assert get("/worms/search?name=Chaetoceros&limit=101")[0] == 400


def test_search_unreachable(get, worms_http):
    worms_http.override(
        {"/AphiaRecordsByName/Chaetoceros?like=true&marine_only=false&offset=1": {
            "status": 429, "body": None}}
    )  # fmt: skip
    status, body, _ = get("/worms/search?name=Chaetoceros")
    assert (status, body["error"]) == (503, "worms_rate_limited")


def test_bad_aphia_id(get):
    assert get("/worms/abc/lineage")[0] in (400, 404)
