"""Drift runs: re-check a whole tree against current WoRMS (spec: worms-drift).

A run re-fetches every AphiaID in the tree's latest revision (max_age 0) with no
tree lock held, then, in one short transaction under the tree's publish lock,
re-checks the latest revision at that moment and adds a NodeWarnings row for
each node whose warnings changed. It never creates changesets, revisions or
node versions.

- One run per tree: a session-level advisory lock `drift:<tree>`, held on the
  worker's own connection for the whole run. Like every advisory lock it is
  database-wide; PostgreSQL releases it if the worker's connection dies.
- Status and progress live in Django's (database) cache under `drift:<tree>`,
  so every server process sees them. `start-django` runs `clear_drift_status`
  on startup, which clears status left by a run whose lock is gone.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

from core.changesets import latest_rev
from core.engine import load_state

from . import records
from .checks import check_nodes
from .client import DRIFT_BACKOFF
from .records import get_records, newest_rows
from .warnings import record_warnings

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="drift")


class DriftBusy(Exception):
    """A run is already active on the tree."""


def _key(tree_id: str) -> str:
    return f"drift:{tree_id}"


def _now() -> str:
    return timezone.now().isoformat()


# --- Lock -----------------------------------------------------------------------------


def _try_lock(tree_id: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", [_key(tree_id)])
        return cursor.fetchone()[0]


def _unlock(tree_id: str):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", [_key(tree_id)])


def is_running(tree_id: str) -> bool:
    """Whether some process holds the tree's drift lock."""
    if not _try_lock(tree_id):
        return True
    _unlock(tree_id)
    return False


# --- Status ---------------------------------------------------------------------------


def _save(tree_id: str, status: dict):
    cache.set(_key(tree_id), status, timeout=None)


def get_status(tree_id: str) -> dict:
    """{tree, active, last}. `active` is the running run's progress, or None;
    `last` is the last finished run, or None if unknown (e.g. after a restart)."""
    status = cache.get(_key(tree_id)) or {}
    return {"tree": tree_id, "active": status.get("active"), "last": status.get("last")}


def clear_status(tree_id: str) -> bool:
    """Clear an active status whose run is gone (its lock is free). Returns True if cleared."""
    status = get_status(tree_id)
    if status["active"] is None or is_running(tree_id):
        return False
    interrupted = {
        **status["active"], "finished_at": None, "ok": False, "reason": "interrupted",
        "detail": "The process running this drift run stopped before it finished.",
    }  # fmt: skip
    _save(tree_id, {"active": None, "last": interrupted})
    return True


# --- Running ----------------------------------------------------------------------------


def _write_warnings(tree_id: str) -> tuple[int, int]:
    """Re-check the latest revision under the publish lock and store changed warnings.
    Returns (revision, rows added)."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            # Waits for a running publish; publishes started meanwhile are refused.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"publish:{tree_id}"])
        rev = latest_rev(tree_id)
        state = load_state(tree_id, rev)
        aphia_ids = {n.aphia_id for n in state.nodes.values() if n.aphia_id is not None}
        records = {a: row.record for a, row in newest_rows(aphia_ids).items() if row.complete}
        return rev, record_warnings(check_nodes(state, state.nodes, records))


def run_drift(tree_id: str, started_by: str, *, on_locked=None) -> dict:
    """Run drift on `tree_id` in this thread and return the finished run's status.

    Raises DriftBusy if a run is already active. `on_locked(ok)` is called once
    the lock is taken (True) or found busy (False).
    """
    if not _try_lock(tree_id):
        if on_locked:
            on_locked(False)
        raise DriftBusy(f"A drift run on tree {tree_id} is already active.")
    if on_locked:
        on_locked(True)
    try:
        rev = latest_rev(tree_id)
        state = load_state(tree_id, rev)
        aphia_ids = sorted({n.aphia_id for n in state.nodes.values() if n.aphia_id is not None})
        active = {
            "started_by": started_by, "started_at": _now(), "rev": rev,
            "done": 0, "total": len(aphia_ids),
        }  # fmt: skip
        last = get_status(tree_id)["last"]
        _save(tree_id, {"active": active, "last": last})

        def progress(done, total):
            active.update(done=done, total=total)
            _save(tree_id, {"active": active, "last": last})

        # No one is waiting on a run, so it retries WoRMS with a long backoff.
        client = records.default_client(backoff=DRIFT_BACKOFF)
        try:
            fetched = get_records(
                aphia_ids, timedelta(0), client=client, progress=progress, stop_on_error=True
            )
            if fetched.failed:
                error = next(iter(fetched.failed.values()))
                result = {
                    **active, "finished_at": _now(), "ok": False, "reason": error.reason,
                    "detail": error.detail, "rows_added": 0,
                }  # fmt: skip
            else:
                written_rev, rows = _write_warnings(tree_id)
                result = {
                    **active, "finished_at": _now(), "ok": True, "checked_rev": written_rev,
                    "rows_added": rows,
                }  # fmt: skip
        except Exception as exc:
            result = {
                **active, "finished_at": _now(), "ok": False, "reason": "error",
                "detail": str(exc), "rows_added": 0,
            }  # fmt: skip
            _save(tree_id, {"active": None, "last": result})
            raise
        finally:
            client.close()
        _save(tree_id, {"active": None, "last": result})
        return result
    finally:
        _unlock(tree_id)


def _run_in_worker(tree_id: str, started_by: str, on_locked):
    try:
        run_drift(tree_id, started_by, on_locked=on_locked)
    except DriftBusy:
        pass
    finally:
        connection.close()  # releases the session lock even if unlock failed


def start_drift(tree_id: str, started_by: str, *, wait: float = 10.0):
    """Start a run on a background thread. Raises DriftBusy if one is active."""
    locked = threading.Event()
    outcome = {}

    def on_locked(ok):
        outcome["ok"] = ok
        locked.set()

    _executor.submit(_run_in_worker, tree_id, started_by, on_locked)
    if not locked.wait(wait) or not outcome["ok"]:
        raise DriftBusy(f"A drift run on tree {tree_id} is already active.")
