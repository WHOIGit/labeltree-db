"""WoRMS jobs: fill the record cache and, for syncs, re-check trees (specs:
worms-records, worms-sync).

| kind        | fetches                                              | then              |
|-------------|------------------------------------------------------|-------------------|
| `fetch`     | the given AphiaIDs without a complete cached record  | nothing           |
| `sync_new`  | the tree's AphiaIDs without a complete cached record | re-check the tree |
| `sync_tree` | every AphiaID in the tree's latest revision          | re-check the tree |
| `sync_all`  | every cached AphiaID and every tree's AphiaIDs       | re-check all trees|

`aphia_ids` restricts what a sync fetches (Try again); it still re-checks the
whole tree. No job ever edits a tree.

- Failures skip: an AphiaID that still fails after the client's retries goes to
  the job's `failed` list and the others carry on. Re-checks write no warning
  row for a node whose records are missing or failed.
- HTTP 429 pauses the whole job for `Retry-After`. Another 429 after resuming
  stops an API-started job; command jobs pause up to 4 times. Whatever is left
  goes to `failed` as `worms_rate_limited`.
- Locks are session-level advisory locks on the job's own connection, released
  by PostgreSQL if that connection dies. Every job holds `worms-job:<id>`, so a
  `running` status whose lock is free is reported `interrupted`. Tree syncs hold
  `worms-sync:<tree>` and a shared `worms-sync:all`; `sync_all` holds
  `worms-sync:all` exclusively, so it excludes every tree sync and vice versa.
  Fetch jobs exclude nothing.
- Status lives in Django's (database) cache, shared by every server process:
  `worms-job:<id>` holds a job's status, and `worms-sync:<tree>` and
  `worms-sync:all` point to the active and last sync.
- HTTP runs on a few worker threads; everything touching the database (storing
  records, status, warnings) runs on the job's own thread.
"""

import queue
import threading
import time
import uuid
from collections import deque
from datetime import timedelta

from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

from core.changesets import latest_rev
from core.engine import load_state
from core.models import NodeVersion, Tree

from . import records
from .checks import check_nodes
from .client import JOB_BACKOFF, SCHEDULED_BACKOFF, RateLimited, WormsError
from .models import WormsRecord
from .records import cached_records, newest_rows, store
from .warnings import record_warnings

KINDS = ("fetch", "sync_new", "sync_tree", "sync_all")
SYNC_KINDS = ("sync_new", "sync_tree", "sync_all")
POOL_SIZE = 4
API_PAUSES = 1
SCHEDULED_PAUSES = 4
STATUS_TIMEOUT = timedelta(days=7).total_seconds()


class SyncBusy(Exception):
    """A sync that would overlap this one is active."""


def job_key(job_id: str) -> str:
    return f"worms-job:{job_id}"


def sync_key(tree_id: str | None) -> str:
    """The lock and status pointer of a tree's syncs, or of `sync_all` for None."""
    return "worms-sync:all" if tree_id is None else f"worms-sync:{tree_id}"


def _now():
    return timezone.now()


# --- Locks ------------------------------------------------------------------------------


def _try_lock(key: str, *, shared=False) -> bool:
    fn = "pg_try_advisory_lock_shared" if shared else "pg_try_advisory_lock"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {fn}(hashtext(%s))", [key])
        return cursor.fetchone()[0]


def _unlock(key: str, *, shared=False):
    fn = "pg_advisory_unlock_shared" if shared else "pg_advisory_unlock"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {fn}(hashtext(%s))", [key])


def _is_held(key: str) -> bool:
    """Whether some session holds the lock (in either mode)."""
    if not _try_lock(key):
        return True
    _unlock(key)
    return False


def _sync_locks(kind: str, tree_id: str | None) -> list[tuple[str, bool]]:
    """(key, shared) locks the kind holds, in the order they are taken."""
    if kind == "sync_all":
        return [(sync_key(None), False)]
    if kind in SYNC_KINDS:
        return [(sync_key(None), True), (sync_key(tree_id), False)]
    return []


# --- Status ------------------------------------------------------------------------------


def _pointer(tree_id: str | None) -> dict:
    return cache.get(sync_key(tree_id)) or {"active": None, "last": None}


def _set_pointer(tree_id: str | None, **changes):
    cache.set(sync_key(tree_id), {**_pointer(tree_id), **changes}, timeout=None)


def get_job(job_id: str | None) -> dict | None:
    """A job's status, or None if unknown. A running job whose lock is free is
    marked `interrupted`."""
    if not job_id:
        return None
    status = cache.get(job_key(job_id))
    if status is None or status["state"] != "running" or _is_held(job_key(job_id)):
        return status
    status = {**status, "state": "interrupted", "retrying": [], "paused": None}
    cache.set(job_key(job_id), status, timeout=STATUS_TIMEOUT)
    if status["kind"] in SYNC_KINDS:
        tree_id = None if status["kind"] == "sync_all" else status["tree"]
        if _pointer(tree_id)["active"] == job_id:
            _set_pointer(tree_id, active=None, last=job_id)
    return status


def get_syncs(tree_id: str | None) -> dict:
    """{tree, active, last}: the tree's active and last sync, an active `sync_all`
    counting as the tree's. Without a tree, the active and last `sync_all`."""
    active_all, last_all = _active_and_last(None)
    if tree_id is None:
        return {"tree": None, "active": active_all, "last": last_all}
    active, last = _active_and_last(tree_id)
    if last_all and (last is None or (last_all["finished_at"] or "") > (last["finished_at"] or "")):
        last = last_all
    return {"tree": tree_id, "active": active or active_all, "last": last}


def _active_and_last(tree_id: str | None):
    # Resolving the active job first moves it to `last` if its process died.
    active = _running(get_job(_pointer(tree_id)["active"]))
    return active, get_job(_pointer(tree_id)["last"])


def _running(status):
    return status if status and status["state"] == "running" else None


def clear_jobs() -> int:
    """Mark syncs whose process died as interrupted, e.g. on startup. Returns how many."""
    cleared = 0
    for tree_id in [None, *Tree.objects.values_list("id", flat=True)]:
        job_id = _pointer(tree_id)["active"]
        if job_id and (get_job(job_id) or {}).get("state") == "interrupted":
            cleared += 1
    return cleared


class _Job:
    """A running job's status, saved to the cache on every change."""

    def __init__(self, job_id, kind, tree_id, started_by, aphia_ids, total):
        self.status = {
            "id": job_id, "kind": kind, "tree": tree_id, "started_by": started_by,
            "started_at": _now().isoformat(), "finished_at": None, "state": "running",
            "aphia_ids": aphia_ids, "total": total, "done": 0, "failed": [],
            "retrying": [], "paused": None, "checked": [],
        }  # fmt: skip
        self.save()

    def save(self):
        cache.set(job_key(self.status["id"]), self.status, timeout=STATUS_TIMEOUT)

    def _settle(self, aphia_id):
        self.status["retrying"] = [r for r in self.status["retrying"] if r["aphia_id"] != aphia_id]

    def retrying(self, aphia_id, attempt, retries, seconds):
        self._settle(aphia_id)
        until = (_now() + timedelta(seconds=seconds)).isoformat()
        self.status["retrying"].append(
            {"aphia_id": aphia_id, "attempt": attempt, "retries": retries, "wait_until": until}
        )
        self.save()

    def fetched(self, aphia_id):
        self._settle(aphia_id)
        self.status["done"] += 1
        self.save()

    def failed(self, aphia_id, reason, detail):
        self._settle(aphia_id)
        self.status["failed"].append({"aphia_id": aphia_id, "reason": reason, "detail": detail})
        self.save()

    def requeued(self, aphia_id):
        self._settle(aphia_id)
        self.save()

    def pause(self, seconds):
        until = (_now() + timedelta(seconds=seconds)).isoformat()
        self.status["paused"] = {"reason": "worms_rate_limited", "until": until}
        self.save()

    def resume(self):
        self.status["paused"] = None
        self.save()

    def finish(self, **extra):
        self.status.update(extra, state="finished", finished_at=_now().isoformat())
        self.status.update(retrying=[], paused=None)
        self.save()

    @property
    def failed_ids(self) -> set[int]:
        return {f["aphia_id"] for f in self.status["failed"]}


# --- What to fetch ------------------------------------------------------------------------


def _tree_aphia_ids(tree_id: str | None) -> set[int]:
    """AphiaIDs in a tree's latest revision (every tree's for None): the current
    node versions."""
    versions = NodeVersion.objects.filter(valid_to_rev__isnull=True, aphia_id__isnull=False)
    if tree_id is not None:
        versions = versions.filter(tree_id=tree_id)
    return set(versions.values_list("aphia_id", flat=True))


def _uncached(aphia_ids) -> set[int]:
    rows = newest_rows(aphia_ids)
    return {a for a in aphia_ids if a not in rows or not rows[a].complete}


def ids_to_fetch(kind: str, tree_id: str | None, aphia_ids=None) -> list[int]:
    if kind == "fetch":
        ids = _uncached(set(aphia_ids or []))
    elif kind == "sync_new":
        ids = _uncached(_tree_aphia_ids(tree_id))
    elif kind == "sync_tree":
        ids = _tree_aphia_ids(tree_id)
    else:
        cached = set(WormsRecord.objects.values_list("aphia_id", flat=True).distinct())
        ids = cached | _tree_aphia_ids(None)
    if aphia_ids is not None and kind != "fetch":
        ids &= set(aphia_ids)
    return sorted(ids)


# --- Fetching -----------------------------------------------------------------------------


def _fetch(job: _Job, ids: list[int], *, scheduled: bool, sleep):
    """Fetch and store `ids`, skipping failures and pausing on HTTP 429."""
    pending = deque(ids)
    lock = threading.Lock()
    events = queue.Queue()
    go = threading.Event()  # cleared while paused
    go.set()
    state = {"stopped": False, "epoch": 0}  # epoch: pauses begun so far

    client = records.default_client(
        backoff=SCHEDULED_BACKOFF if scheduled else JOB_BACKOFF,
        on_wait=lambda aphia_id, *wait: events.put(("wait", aphia_id, wait)),
        raise_rate_limited=True,
    )
    max_pauses = SCHEDULED_PAUSES if scheduled else API_PAUSES

    def worker():
        try:
            while True:
                go.wait()
                with lock:
                    if state["stopped"] or not pending:
                        return
                    aphia_id, epoch = pending.popleft(), state["epoch"]
                try:
                    events.put(("ok", aphia_id, client.full_record(aphia_id)))
                except RateLimited as exc:
                    # Back in the queue, and the whole job waits, unless this request
                    # was sent before a pause that has begun since.
                    with lock:
                        pending.appendleft(aphia_id)
                        if epoch == state["epoch"]:
                            state["epoch"] += 1
                            go.clear()
                            events.put(("limited", aphia_id, exc))
                except WormsError as exc:
                    events.put(("error", aphia_id, exc))
                except Exception as exc:  # noqa: BLE001 - reported, the job goes on
                    events.put(("error", aphia_id, WormsError("worms_error", str(exc))))
        finally:
            events.put(("exit", None, None))

    threads = [
        threading.Thread(target=worker, daemon=True) for _ in range(min(POOL_SIZE, len(ids)))
    ]
    for thread in threads:
        thread.start()
    running, pauses = len(threads), 0
    try:
        while running:
            what, aphia_id, value = events.get()
            if what == "exit":
                running -= 1
            elif what == "wait":
                job.retrying(aphia_id, *value)
            elif what == "ok":
                store(aphia_id, value)
                job.fetched(aphia_id)
            elif what == "error":
                job.failed(aphia_id, value.reason, value.detail)
            else:  # limited: the workers are held until this is decided
                job.requeued(aphia_id)
                if pauses == max_pauses:
                    with lock:
                        state["stopped"] = True
                else:
                    pauses += 1
                    job.pause(value.retry_after)
                    sleep(value.retry_after)
                    job.resume()
                go.set()
    finally:
        with lock:
            state["stopped"] = True
        go.set()
        client.close()
    for aphia_id in pending:
        job.failed(aphia_id, "worms_rate_limited", "WoRMS kept answering HTTP 429; not fetched.")


# --- Re-checking ----------------------------------------------------------------------------


def _write_warnings(tree_id: str, failed: set[int]) -> dict:
    """Re-check the tree's latest revision under its publish lock and store changed
    warnings, skipping nodes that need a failed or uncached record."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            # Waits for a running publish; publishes started meanwhile are refused.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"publish:{tree_id}"])
        rev = latest_rev(tree_id)
        state = load_state(tree_id, rev)
        aphia_ids = {n.aphia_id for n in state.nodes.values() if n.aphia_id is not None}
        known = cached_records(aphia_ids - failed)
        rows = record_warnings(check_nodes(state, state.nodes, known))
    return {"tree": tree_id, "rev": rev, "rows_added": rows}


# --- Running -----------------------------------------------------------------------------


def run_job(
    kind: str,
    *,
    tree: str | None = None,
    started_by: str,
    aphia_ids: list[int] | None = None,
    scheduled: bool = False,
    job_id: str | None = None,
    on_started=None,
    sleep=time.sleep,
) -> dict:
    """Run a job in this thread and return its finished status.

    `scheduled` jobs (the management command) use the long retry schedule and
    pause more often. Raises SyncBusy if the kind's locks are taken.
    `on_started(status or None)` is called once the job has started or found busy.
    """
    if kind not in KINDS:
        raise ValueError(kind)
    job_id = job_id or uuid.uuid4().hex
    held = []
    try:
        for key, shared in [(job_key(job_id), False), *_sync_locks(kind, tree)]:
            if not _try_lock(key, shared=shared):
                if on_started:
                    on_started(None)
                where = "any tree" if kind == "sync_all" else f"tree {tree}"
                raise SyncBusy(f"A sync overlapping {where} is already active.")
            held.append((key, shared))

        ids = ids_to_fetch(kind, tree, aphia_ids)
        job = _Job(job_id, kind, tree, started_by, aphia_ids, len(ids))
        pointer_tree = None if kind == "sync_all" else tree
        if kind in SYNC_KINDS:
            _set_pointer(pointer_tree, active=job_id)
        if on_started:
            on_started(job.status)
        try:
            _fetch(job, ids, scheduled=scheduled, sleep=sleep)
            if kind in SYNC_KINDS:
                trees = (
                    [tree]
                    if tree
                    else list(Tree.objects.order_by("id").values_list("id", flat=True))
                )
                checked = [_write_warnings(t, job.failed_ids) for t in trees]
                job.finish(checked=checked)
            else:
                job.finish()
        except Exception as exc:
            job.finish(error=str(exc))
            raise
        finally:
            if kind in SYNC_KINDS:
                _set_pointer(pointer_tree, active=None, last=job_id)
        return job.status
    finally:
        for key, shared in reversed(held):
            _unlock(key, shared=shared)


def start_job(kind: str, *, tree=None, started_by: str, aphia_ids=None, wait=10.0) -> dict:
    """Start a job on a background thread and return its first status. Raises
    SyncBusy if an overlapping sync is active."""
    started = threading.Event()
    outcome = {}

    def on_started(status):
        outcome["status"] = status
        started.set()

    def work():
        try:
            run_job(kind, tree=tree, started_by=started_by, aphia_ids=aphia_ids,
                    on_started=on_started)  # fmt: skip
        except SyncBusy:
            pass
        except Exception as exc:
            if not started.is_set():  # failed before starting: the caller reports it
                outcome["error"] = exc
                started.set()
            raise
        finally:
            connection.close()  # releases the session locks even if unlocking failed

    threading.Thread(target=work, daemon=True, name=f"worms-{kind}").start()
    if not started.wait(wait):
        raise TimeoutError(f"The {kind} job didn't start within {wait} s.")
    if "error" in outcome:
        raise outcome["error"]
    if outcome["status"] is None:
        raise SyncBusy(f"A sync overlapping {tree or 'any tree'} is already active.")
    return outcome["status"]
