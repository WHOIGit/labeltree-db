"""The WoRMS record cache: every WoRMS read in the service goes through here.

`get_records(aphia_ids, max_age)` returns the newest cached row per AphiaID if
it is complete and fetched within `max_age`, and fetches the rest. HTTP runs on
a small thread pool; rows are written on the calling thread, so they belong to
its transaction.

`max_age`: None = any cached row will do (lookups, saves); PUBLISH_MAX_AGE for
the AphiaIDs a publish adds or alters; timedelta(0) = always re-fetch (drift).
"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .client import WormsClient, WormsError
from .models import WormsRecord

PUBLISH_MAX_AGE = timedelta(minutes=10)
POOL_SIZE = 4


def default_client(**options) -> WormsClient:
    """The client used when none is given; tests replace it. `options` go to WormsClient."""
    return WormsClient(**options)


def content_hash(record: dict | None) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def _modified(record: dict | None):
    raw = (record or {}).get("modified")
    return datetime.fromisoformat(raw) if raw else None


def newest_rows(aphia_ids) -> dict[int, WormsRecord]:
    """The newest cached row per AphiaID (most recently fetched); uncached ones are absent."""
    rows = (
        WormsRecord.objects.filter(aphia_id__in=list(set(aphia_ids)))
        .order_by("aphia_id", "-fetched_at", "-id")
        .distinct("aphia_id")
    )
    return {row.aphia_id: row for row in rows}


def store(aphia_id: int, record: dict | None, now=None) -> WormsRecord:
    """Store a fetched record (None: WoRMS has no such record) and return its row.

    Unchanged content only bumps `fetched_at`. A full record matching a
    lineage-less row (a search hit) fills that row in instead of adding one.
    """
    now = now or timezone.now()
    digest = content_hash(record)
    if record is not None and record.get("lineage") is not None:
        bare = content_hash({**record, "lineage": None})
        if not WormsRecord.objects.filter(aphia_id=aphia_id, content_hash=digest).exists():
            try:
                with transaction.atomic():
                    filled = WormsRecord.objects.filter(
                        aphia_id=aphia_id, content_hash=bare
                    ).update(record=record, content_hash=digest, fetched_at=now)
            except IntegrityError:  # a concurrent fetch stored the full row first
                filled = 0
            if filled:
                return WormsRecord.objects.get(aphia_id=aphia_id, content_hash=digest)
    WormsRecord.objects.bulk_create(
        [
            WormsRecord(
                aphia_id=aphia_id,
                record=record,
                content_hash=digest,
                worms_modified=_modified(record),
                fetched_at=now,
            )
        ],
        update_conflicts=True,
        unique_fields=["aphia_id", "content_hash"],
        update_fields=["fetched_at"],
    )
    return WormsRecord.objects.get(aphia_id=aphia_id, content_hash=digest)


def store_search_hit(record: dict, now=None) -> WormsRecord:
    """Cache a search result, which comes without a lineage. If the newest row
    already holds this record, only its `fetched_at` is bumped."""
    aphia_id = record["AphiaID"]
    newest = newest_rows([aphia_id]).get(aphia_id)
    if newest is not None and newest.record is not None:
        if {**newest.record, "lineage": None} == {**record, "lineage": None}:
            WormsRecord.objects.filter(pk=newest.pk).update(fetched_at=now or timezone.now())
            newest.refresh_from_db()
            return newest
    return store(aphia_id, {**record, "lineage": None}, now)


def _fresh(row: WormsRecord | None, max_age: timedelta | None, now) -> bool:
    if row is None or not row.complete:
        return False
    return max_age is None or row.fetched_at > now - max_age


class FetchResult:
    def __init__(self):
        self.rows: dict[int, WormsRecord] = {}
        self.failed: dict[int, WormsError] = {}

    def records(self) -> dict:
        """{aphia_id: record or None} for checks; failed AphiaIDs are absent."""
        return {a: row.record for a, row in self.rows.items()}


def get_records(
    aphia_ids,
    max_age: timedelta | None = None,
    *,
    client: WormsClient | None = None,
    progress=None,
    stop_on_error: bool = False,
) -> FetchResult:
    """Cached rows for `aphia_ids`, fetching those missing, incomplete or stale.

    A fetch that fails after retries is reported in `failed` and leaves the
    cache as it was. `progress(done, total)` is called after each AphiaID.
    With `stop_on_error`, the first failure stops further fetches and the
    remaining AphiaIDs are reported as failing with the same error.
    """
    now = timezone.now()
    ids = list(dict.fromkeys(aphia_ids))
    result = FetchResult()
    cached = newest_rows(ids)
    stale = []
    for aphia_id in ids:
        if _fresh(cached.get(aphia_id), max_age, now):
            result.rows[aphia_id] = cached[aphia_id]
        else:
            stale.append(aphia_id)
    done = len(ids) - len(stale)
    if progress:
        progress(done, len(ids))
    if not stale:
        return result

    own_client = client is None
    client = client or default_client()
    try:
        with ThreadPoolExecutor(POOL_SIZE) as pool:
            futures = [(a, pool.submit(client.full_record, a)) for a in stale]
            for aphia_id, future in futures:
                if stop_on_error and result.failed:
                    future.cancel()
                    result.failed[aphia_id] = next(iter(result.failed.values()))
                    continue
                try:
                    record = future.result()
                except WormsError as exc:
                    result.failed[aphia_id] = exc
                    continue
                result.rows[aphia_id] = store(aphia_id, record)
                done += 1
                if progress:
                    progress(done, len(ids))
    finally:
        if own_client:
            client.close()
    return result


def get_record(aphia_id: int, max_age: timedelta | None = None, **kwargs) -> WormsRecord:
    """One record; raises WormsError if it can't be fetched."""
    result = get_records([aphia_id], max_age, **kwargs)
    if aphia_id in result.failed:
        raise result.failed[aphia_id]
    return result.rows[aphia_id]
