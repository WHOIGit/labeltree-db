"""/worms: lookups, WoRMS jobs and the warnings report (specs: worms-records,
worms-sync).

Only the lookups and WoRMS jobs call WoRMS. Lookups are served from the record
cache and call WoRMS on a miss, except search, which always asks WoRMS and
caches what it returns. They need a login, since a miss calls WoRMS, but no
role. Every WoRMS-derived value carries the `fetched_at` of the cached row it
came from, for citation ("WoRMS, accessed <fetched_at>").

Jobs run in the background (worms.sync); clients poll their status.
"""

from ninja import Router, Schema

from accounts.models import Role
from accounts.roles import require, require_org, require_superuser
from worms import records, sync
from worms.client import WormsError
from worms.models import WormsRecord, current_warnings
from worms.records import get_record, store_search_hit

from .conventions import APIError, bad_parameter, get_tree, not_found, paginate, respond
from .orgs import get_org
from .trees import view_at

router = Router(tags=["worms"])


# --- Jobs ------------------------------------------------------------------------------------


class JobIn(Schema):
    kind: str
    tree: str | None = None
    org: str | None = None
    aphia_ids: list[int] | None = None


@router.post("/jobs")
def start_job(request, body: JobIn):
    """Start a WoRMS job: 202 with its status, or 409 if it overlaps an active sync."""
    if body.kind not in sync.KINDS:
        raise bad_parameter(f"kind must be one of {', '.join(sync.KINDS)}.")
    if body.kind == "fetch":
        # Only fills the cache, so it belongs to an organization, not a tree, and
        # serves new-tree drafts too.
        if body.org is None or body.tree is not None:
            raise bad_parameter("A fetch job takes an org, not a tree.")
        if not body.aphia_ids:
            raise bad_parameter("A fetch job needs aphia_ids.")
        require_org(request.user, get_org(body.org).id, Role.DRAFTER)
    elif body.kind == "sync_all":
        if body.tree is not None or body.org is not None:
            raise bad_parameter("sync_all takes no tree or org.")
        require_superuser(request.user)
    else:
        if body.tree is None or body.org is not None:
            raise bad_parameter(f"{body.kind} takes a tree, not an org.")
        require(request.user, get_tree(body.tree).id, Role.DRAFTER)
    try:
        status = sync.start_job(
            body.kind, tree=body.tree, org=body.org, started_by=request.user.get_username(),
            aphia_ids=body.aphia_ids,
        )  # fmt: skip
    except sync.SyncBusy as exc:
        raise APIError(409, "sync_in_progress", str(exc)) from None
    response = respond(request, status)
    response.status_code = 202
    return response


@router.get("/jobs")
def list_syncs(request, tree: str | None = None):
    """The tree's active and last sync, or, without a tree, the active and last sync_all."""
    if tree is not None:
        require(request.user, get_tree(tree).id, Role.READER)
    return respond(request, sync.get_syncs(tree))


@router.get("/jobs/{job_id}")
def job_status(request, job_id: str):
    status = sync.get_job(job_id)
    if status is None:
        raise not_found(f"No WoRMS job {job_id} is known; status is kept for 7 days.")
    if status["tree"] is not None:
        require(request.user, status["tree"], Role.READER)
    elif status.get("org") is not None:
        require_org(request.user, status["org"], Role.READER)
    return respond(request, status)


# --- Warnings report -------------------------------------------------------------------------


@router.get("/warnings", auth=None)
def warnings_report(request, tree: str = "", limit: int | None = None, offset: int = 0):
    """Nodes in the tree's latest revision that currently have WoRMS warnings."""
    if not tree:
        raise bad_parameter("`tree` is required.")
    view, header_rev = view_at(tree, None)
    warnings = {ref: ws for ref, ws in current_warnings(view.state.nodes).items() if ws}
    page, count = paginate(sorted(warnings), limit, offset)
    data = {
        "tree": view.tree.id,
        "rev": view.rev,
        "count": count,
        "nodes": [
            {
                "id": ref,
                "label": view.state.nodes[ref].label,
                "version": view.state.nodes[ref].version,
                "aphia_id": view.state.nodes[ref].aphia_id,
                "worms_warnings": warnings[ref],
            }
            for ref in page
        ],
    }
    return respond(request, data, rev=header_rev)


# --- Lookups ---------------------------------------------------------------------------------


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
