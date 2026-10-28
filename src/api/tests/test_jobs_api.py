"""/worms/jobs and /worms/warnings (specs: worms-records, worms-sync)."""

import time

import psycopg
import pytest
from django.core.cache import cache
from django.db import connection
from django.test import Client

from core.changesets import latest_rev
from core.tests.helpers import deprecate, edit, publish
from worms import sync
from worms.warnings import record_warnings

from .conftest import call, logged_in, make_user


def other_connection():
    s = connection.settings_dict
    return psycopg.connect(
        dbname=s["NAME"], user=s["USER"], password=s["PASSWORD"] or None,
        host=s["HOST"] or None, port=s["PORT"] or None, autocommit=True,
    )  # fmt: skip


@pytest.fixture(autouse=True)
def forget_jobs():
    """The cache table isn't rolled back between tests."""
    yield
    cache.clear()


@pytest.fixture
def drafter(db):
    client = logged_in(make_user("curator1", roles={"amplify": "drafter"}))
    return lambda method, path, body=None: call(client, method, path, body)


def wait_for(drafter, job_id):
    for _ in range(200):  # jobs run on a background thread
        status, body = drafter("get", f"/worms/jobs/{job_id}")
        if body["state"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("job didn't finish")


# --- Starting jobs ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_start_a_sync(drafter, taxonomy):
    status, body = drafter("post", "/worms/jobs", {"kind": "sync_tree", "tree": "taxonomy"})
    assert status == 202 and (body["kind"], body["tree"], body["state"]) == (
        "sync_tree", "taxonomy", "running",
    )  # fmt: skip
    finished = wait_for(drafter, body["id"])
    assert (finished["state"], finished["started_by"], finished["total"]) == (
        "finished", "curator1", 2,
    )  # fmt: skip
    assert drafter("get", "/worms/jobs?tree=taxonomy")[1]["last"]["id"] == body["id"]
    assert latest_rev("taxonomy") == 1  # no revision


@pytest.mark.django_db(transaction=True)
def test_fetch_before_validating(drafter, taxonomy):
    body = drafter(
        "post", "/worms/jobs", {"kind": "fetch", "tree": "taxonomy", "aphia_ids": [149122, 110153]}
    )[1]
    assert body["total"] == 1  # 149122 is cached
    assert wait_for(drafter, body["id"])["done"] == 1


@pytest.mark.django_db
def test_sync_already_active(drafter, taxonomy):
    with other_connection() as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('worms-sync:taxonomy'))")
        status, body = drafter("post", "/worms/jobs", {"kind": "sync_new", "tree": "taxonomy"})
    assert (status, body["error"]) == (409, "sync_in_progress")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {"kind": "refresh", "tree": "taxonomy"},
        {"kind": "sync_tree"},
        {"kind": "fetch", "tree": "taxonomy"},
        {"kind": "fetch", "tree": "taxonomy", "aphia_ids": []},
        {"kind": "sync_all", "tree": "taxonomy"},
    ],
)
def test_bad_job_requests(drafter, taxonomy, body):
    status, error = drafter("post", "/worms/jobs", body)
    assert (status, error["error"]) == (400, "bad_parameter")


@pytest.mark.django_db
def test_unknown_tree_or_job(drafter):
    assert drafter("post", "/worms/jobs", {"kind": "sync_tree", "tree": "nope"})[0] == 404
    assert drafter("get", "/worms/jobs?tree=nope")[0] == 404
    assert drafter("get", "/worms/jobs/0123abcd")[0] == 404


@pytest.mark.django_db
def test_only_site_admins_sync_everything(taxonomy, monkeypatch):
    monkeypatch.setattr(sync, "start_job", lambda kind, **kw: {"kind": kind})
    owner = logged_in(make_user("owner1", roles={"amplify": "owner"}))
    assert call(owner, "post", "/worms/jobs", {"kind": "sync_all"})[0] == 403
    admin = logged_in(make_user("admin", superuser=True))
    assert call(admin, "post", "/worms/jobs", {"kind": "sync_all"})[0] == 202


# --- Status ---------------------------------------------------------------------------------


@pytest.mark.django_db
def test_status_before_any_sync(drafter, taxonomy):
    assert drafter("get", "/worms/jobs?tree=taxonomy")[1] == {
        "tree": "taxonomy", "active": None, "last": None,
    }  # fmt: skip
    assert drafter("get", "/worms/jobs")[1] == {"tree": None, "active": None, "last": None}


def running(job_id, tree="taxonomy", kind="sync_tree", **extra):
    return {
        "id": job_id, "kind": kind, "tree": tree, "started_by": "a", "started_at": "x",
        "finished_at": None, "state": "running", "aphia_ids": None, "total": 175,
        "done": 120, "failed": [], "retrying": [], "paused": None, "checked": [], **extra,
    }  # fmt: skip


@pytest.mark.django_db
def test_progress(drafter, taxonomy):
    cache.set("worms-job:j1", running("j1"))
    cache.set("worms-sync:taxonomy", {"active": "j1", "last": None})
    with other_connection() as conn:  # the job is alive in some process
        conn.execute("SELECT pg_advisory_lock(hashtext('worms-job:j1'))")
        active = drafter("get", "/worms/jobs?tree=taxonomy")[1]["active"]
        assert (active["done"], active["total"]) == (120, 175)
    # its process died: no longer active
    body = drafter("get", "/worms/jobs?tree=taxonomy")[1]
    assert body["active"] is None and body["last"]["state"] == "interrupted"
    assert drafter("get", "/worms/jobs/j1")[1]["state"] == "interrupted"


@pytest.mark.django_db
def test_full_sync_shows_on_every_tree(drafter, taxonomy):
    cache.set("worms-job:all1", running("all1", tree=None, kind="sync_all"))
    cache.set("worms-sync:all", {"active": "all1", "last": None})
    with other_connection() as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('worms-job:all1'))")
        assert drafter("get", "/worms/jobs?tree=taxonomy")[1]["active"]["kind"] == "sync_all"
        assert drafter("get", "/worms/jobs")[1]["active"]["id"] == "all1"
        # any logged-in user may see a full sync
        other = logged_in(make_user("outsider"))
        assert call(other, "get", "/worms/jobs/all1")[0] == 200


@pytest.mark.django_db
def test_job_status_needs_a_role_on_its_tree(taxonomy):
    cache.set("worms-job:j1", running("j1"))
    outsider = logged_in(make_user("outsider"))
    assert call(outsider, "get", "/worms/jobs/j1")[0] == 403
    assert call(outsider, "get", "/worms/jobs?tree=taxonomy")[0] == 403
    reader = logged_in(make_user("reader1", roles={"amplify": "reader"}))
    assert call(reader, "get", "/worms/jobs/j1")[0] == 200


# --- Warnings report -------------------------------------------------------------------------


def get(path):
    response = Client().get(f"/api/v1{path}")
    return response.status_code, response.json(), response


@pytest.mark.django_db
def test_report_lists_nodes_with_warnings(taxonomy):
    out = [{"warning": "out_of_lineage", "detail": "x"}]
    record_warnings({1: out, 2: out, 3: out, 4: out, 6: out})
    record_warnings({4: []})  # cleared
    publish(taxonomy, deprecate(6))  # no longer in the tree
    publish(taxonomy, edit(5, label="Cd"))
    record_warnings({5: out})
    status, body, response = get("/worms/warnings?tree=taxonomy")  # anonymous
    assert status == 200 and body["count"] == 4 and body["rev"] == 3
    assert [n["id"] for n in body["nodes"]] == [1, 2, 3, 5]
    assert body["nodes"][3] == {
        "id": 5, "label": "Cd", "version": 2, "aphia_id": 149122, "worms_warnings": out,
    }  # fmt: skip
    assert response["X-Tree-Revision"] == "3"
    page = get("/worms/warnings?tree=taxonomy&limit=2&offset=2")[1]
    assert [n["id"] for n in page["nodes"]] == [3, 5] and page["count"] == 4


@pytest.mark.django_db
def test_report_needs_a_known_tree(taxonomy):
    assert get("/worms/warnings")[0] == 400
    assert get("/worms/warnings?tree=nope")[0] == 404
