"""/worms lookups, served from the record cache (spec: worms-records).

Only these endpoints (plus saves, publishes and drift) call WoRMS, and only on a
cache miss, except search, which always asks WoRMS and caches what it returns.
Every WoRMS-derived value carries the `fetched_at` of the cached row it came
from, for citation ("WoRMS, accessed <fetched_at>").
"""

from ninja import Router

from worms import records
from worms.client import WormsError
from worms.models import WormsRecord
from worms.records import get_record, store_search_hit

from .conventions import APIError, bad_parameter, not_found, respond

router = Router(tags=["worms"])


def unavailable(exc: WormsError) -> APIError:
    return APIError(503, exc.reason, exc.detail)


def cached(aphia_id: int) -> WormsRecord:
    """The cached row, fetching on a miss. 404 if WoRMS has no such record."""
    try:
        row = get_record(aphia_id)
    except WormsError as exc:
        raise unavailable(exc) from None
    if row.record is None:
        raise not_found(f"WoRMS has no record for AphiaID {aphia_id}.")
    return row


def record_body(row: WormsRecord) -> dict:
    body = {k: v for k, v in row.record.items() if k != "lineage"}
    return {**body, "fetched_at": row.fetched_at.isoformat()}


def entry(item: dict) -> dict:
    return {k: item[k] for k in ("AphiaID", "rank", "scientificname")}


@router.get("/search")
def search(request, name: str = "", limit: int = 20):
    if not name.strip():
        raise bad_parameter("`name` is required.")
    if not 1 <= limit <= 100:
        raise bad_parameter("limit must be between 1 and 100.")
    client = records.default_client()
    try:
        hits = client.search(name.strip(), limit)
    except WormsError as exc:
        raise unavailable(exc) from None
    finally:
        client.close()
    rows = [store_search_hit(hit) for hit in hits if hit.get("AphiaID") is not None]
    return respond(request, {"name": name, "results": [record_body(row) for row in rows]})


@router.get("/{aphia_id}")
def record(request, aphia_id: int):
    return respond(request, record_body(cached(aphia_id)))


@router.get("/{aphia_id}/lineage")
def lineage(request, aphia_id: int):
    row = cached(aphia_id)
    ancestors = [entry(x) for x in row.record["lineage"] if x["AphiaID"] != aphia_id]
    data = {"aphia_id": aphia_id, "fetched_at": row.fetched_at.isoformat(), "lineage": ancestors}
    return respond(request, data)


def _ids(row: WormsRecord) -> list[int]:
    return [x["AphiaID"] for x in row.record["lineage"]]


@router.get("/{a}/between/{b}")
def between(request, a: int, b: int):
    rows = {a: cached(a), b: cached(b)}
    for upper, lower in ((a, b), (b, a)):
        path = _ids(rows[lower])
        if upper in path:
            records = rows[lower].record["lineage"][path.index(upper) :]
            data = {
                "a": a,
                "b": b,
                "fetched_at": rows[lower].fetched_at.isoformat(),
                "records": [entry(x) for x in records],
            }
            return respond(request, data)
    raise bad_parameter(f"Neither {a} nor {b} is a WoRMS ancestor of the other.")


@router.get("/{a}/common_ancestor/{b}")
def common_ancestor(request, a: int, b: int):
    ra, rb = cached(a), cached(b)
    in_b = set(_ids(rb))
    common = [x for x in ra.record["lineage"] if x["AphiaID"] in in_b]
    data = {
        "a": a,
        "b": b,
        "fetched_at": min(ra.fetched_at, rb.fetched_at).isoformat(),
        "common_ancestor": entry(common[-1]) if common else None,
    }
    return respond(request, data)
