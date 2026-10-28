"""The WoRMS record cache: every WoRMS read in the service goes through here.

`cached_records(aphia_ids)` reads the cache only; validate, saves and publishes
use it, so they never wait on WoRMS. `get_records(aphia_ids)` returns the
newest complete cached row per AphiaID and fetches the rest; the lookup
endpoints and `import_tree` use it, and WoRMS jobs (worms.sync) fetch through
the same `store`. HTTP runs on a small thread pool; rows are written on the
calling thread, so they belong to its transaction.
"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from .client import WormsClient, WormsError
from .models import WormsRecord

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


def cached_records(aphia_ids) -> dict:
    """{aphia_id: record or None} from complete cached rows, for checks. AphiaIDs
    without one are absent, which makes the checks that need them unavailable."""
    return {a: row.record for a, row in newest_rows(aphia_ids).items() if row.complete}


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


class FetchResult:
    def __init__(self):
        self.rows: dict[int, WormsRecord] = {}
        self.failed: dict[int, WormsError] = {}

    def records(self) -> dict:
        """{aphia_id: record or None} for checks; failed AphiaIDs are absent."""
        return {a: row.record for a, row in self.rows.items()}


def get_records(aphia_ids, *, client: WormsClient | None = None) -> FetchResult:
    """Cached rows for `aphia_ids`, fetching those missing or incomplete.

    A fetch that fails after retries is reported in `failed`, leaves the cache
    as it was, and doesn't stop the others.
    """
    ids = list(dict.fromkeys(aphia_ids))
    result = FetchResult()
    cached = newest_rows(ids)
    stale = []
    for aphia_id in ids:
        row = cached.get(aphia_id)
        if row is not None and row.complete:
            result.rows[aphia_id] = row
        else:
            stale.append(aphia_id)
    if not stale:
        return result

    own_client = client is None
    client = client or default_client()
    try:
        with ThreadPoolExecutor(POOL_SIZE) as pool:
            futures = [(a, pool.submit(client.full_record, a)) for a in stale]
            for aphia_id, future in futures:
                try:
                    record = future.result()
                except WormsError as exc:
                    result.failed[aphia_id] = exc
                    continue
                result.rows[aphia_id] = store(aphia_id, record)
    finally:
        if own_client:
            client.close()
    return result


def get_record(aphia_id: int, **kwargs) -> WormsRecord:
    """One record; raises WormsError if it can't be fetched."""
    result = get_records([aphia_id], **kwargs)
    if aphia_id in result.failed:
        raise result.failed[aphia_id]
    return result.rows[aphia_id]
