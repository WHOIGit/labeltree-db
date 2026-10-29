"""WoRMS job progress, the sync menu and failed AphiaIDs (spec: webapp)."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from django.core.cache import cache
from django.db import connection
from playwright.sync_api import expect

from worms.models import WormsRecord
from worms.tests.fixtures import load

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def forget_jobs():
    yield
    cache.clear()


def other_connection():
    s = connection.settings_dict
    return psycopg.connect(
        dbname=s["NAME"], user=s["USER"], password=s["PASSWORD"] or None,
        host=s["HOST"] or None, port=s["PORT"] or None, autocommit=True,
    )  # fmt: skip


def status(**extra):
    return {
        "id": "j1", "kind": "sync_tree", "tree": "taxonomy", "org": None, "started_by": "drafter1",
        "started_at": "2026-10-28T00:00:00+00:00", "finished_at": None, "state": "running",
        "aphia_ids": None, "total": 60, "done": 40, "failed": [], "retrying": [], "paused": None,
        "checked": [], **extra,
    }  # fmt: skip


def soon(seconds):
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def test_sync_in_progress_elsewhere(site, taxonomy, drafter):
    cache.set("worms-job:cron1", status(id="cron1", started_by="cron", done=120, total=175))
    cache.set("worms-sync:taxonomy", {"active": "cron1", "last": None})
    with other_connection() as conn:  # the scheduled sync is alive in another process
        conn.execute("SELECT pg_advisory_lock(hashtext('worms-job:cron1'))")
        site.login(drafter)
        page = site.open("/trees/taxonomy/")
        page.click("#sync-button")
        running = page.wait_for_selector("#sync-running")
        assert "sync_tree started by cron" in running.inner_text()
        assert "120 of 175" in running.inner_text()
        for kind in ("sync_new", "sync_tree"):
            item = page.locator(f'[data-sync="{kind}"]')
            assert "disabled" in item.get_attribute("class")
            assert item.get_attribute("title") == "A sync is running"
        assert page.locator('[data-sync="sync_all"]').count() == 0  # superusers only


def test_progress_bars_retry_pause_and_failures(site, taxonomy, drafter):
    """Fixture-driven job statuses: a retry, a pause, then a failure and Try again."""
    statuses = [
        status(retrying=[
            {"aphia_id": 149122, "attempt": 2, "retries": 4, "wait_until": soon(1.5)}
        ]),
        status(done=41, paused={"reason": "worms_rate_limited", "until": soon(20)}),
        status(done=59, state="finished", finished_at=soon(0),
               failed=[{"aphia_id": 149122, "reason": "worms_unreachable", "detail": "timed out"}]),
    ]  # fmt: skip
    started = []

    def jobs(route):
        if route.request.method != "POST":
            return route.continue_()
        started.append(json.loads(route.request.post_data))
        route.fulfill(status=202, json=status(id=f"j{len(started)}"))

    def job(route):
        route.fulfill(json=statuses.pop(0) if len(statuses) > 1 else statuses[0])

    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    page.route("**/api/v1/worms/jobs", jobs)
    page.route("**/api/v1/worms/jobs/j*", job)
    page.click("#sync-button")
    page.click('[data-sync="sync_tree"]')
    retry = page.wait_for_selector("#sync-job .retry-bar")
    assert "Retrying AphiaID 149122 (attempt 2 of 4)" in retry.inner_text()
    assert "40 of 60" in page.inner_text("#sync-job")
    pause = page.wait_for_selector("#sync-job .pause-bar")
    assert "Paused by WoRMS rate limiting" in pause.inner_text()
    failed = page.wait_for_selector("#sync-failed")
    assert "149122: worms_unreachable" in failed.inner_text()
    page.click("#sync-failed >> text=Try again")
    page.wait_for_timeout(500)
    assert started[0] == {"kind": "sync_tree", "tree": "taxonomy"}
    assert started[1] == {"kind": "sync_tree", "tree": "taxonomy", "aphia_ids": [149122]}


def test_sync_refreshes_pills_and_warnings(site, taxonomy, drafter, worms_http):
    """WoRMS moved Chaetoceros out of Chaetocerotaceae; a sync shows it."""
    body = load()["/AphiaClassificationByAphiaID/148985"]["body"]
    lineage, node = [], body
    while node:
        lineage.append({k: v for k, v in node.items() if k != "child"})
        node = node["child"]
    nested = None
    for x in reversed([x for x in lineage if x["AphiaID"] != 148984]):
        nested = {**x, "child": nested}
    worms_http.override({"/AphiaClassificationByAphiaID/148985": {"status": 200, "body": nested}})
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    page.click("#warnings-toggle")
    page.click("text=Expand all")
    assert site.row("Chaetoceros").locator(".pill").get_attribute("data-pill") == "green"
    page.click("#sync-button")
    page.click('[data-sync="sync_tree"]')
    page.wait_for_selector("#warnings-panel .crow[data-node]", timeout=20000)
    expect(site.row("Chaetoceros").locator(".pill")).to_have_attribute("data-pill", "orange")
    assert "out_of_lineage" in page.inner_text("#warnings-panel")
    assert site.console.errors == []


# --- failed AphiaIDs in Validate's fetch job --------------------------------------------------


def add_child(site, parent, label, aphia):
    page = site.page
    page.click("text=Expand all")
    site.row(parent).locator(".kebab").click()
    page.click('#node-menu [data-action="child"]')
    page.fill("#f-label", label)
    page.fill("#f-aphia", str(aphia))
    page.click("#f-submit")


def new_draft(site, user):
    site.login(user)
    page = site.open("/trees/taxonomy/")
    page.click("#edit-button")
    page.click("#new-draft")
    return page


def test_new_aphia_id_is_fetched_on_validate(site, taxonomy, drafter, worms_http):
    page = new_draft(site, drafter)
    add_child(site, "other", "Heterocapsa_triquetra", 110153)
    worms_http.calls.clear()
    page.click("#validate-button")
    expect(page.locator("#save-button")).to_be_enabled(timeout=20000)
    assert "/AphiaRecordByAphiaID/110153" in worms_http.calls
    assert WormsRecord.objects.filter(aphia_id=110153).exists()
    page.click('[data-tab="summary"]')
    assert "checks unavailable" not in page.inner_text("#tab-summary")


def test_proceed_anyway(site, taxonomy, drafter, worms_http):
    def down(request):
        raise httpx.ConnectError("down")

    worms_http.override({"/AphiaRecordByAphiaID/110153": down})
    page = new_draft(site, drafter)
    add_child(site, "other", "Heterocapsa_triquetra", 110153)
    page.click("#validate-button")
    failed = page.wait_for_selector("#fetch-failed", timeout=20000)
    assert "110153: worms_unreachable" in failed.inner_text()
    assert page.is_disabled("#save-button")
    page.click("#fetch-failed >> text=Proceed anyway")
    expect(page.locator("#save-button")).to_be_enabled(timeout=20000)
    page.click('[data-tab="summary"]')
    assert "checks unavailable for AphiaIDs 110153" in page.inner_text("#tab-summary")


def test_one_status_poller_however_often_the_menu_opens(site, taxonomy, drafter):
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    polls = []
    page.on("request", lambda r: "/api/v1/worms/jobs?tree=" in r.url and polls.append(r.url))
    for _ in range(4):
        page.click("#sync-button")  # open
        page.click("#tree")  # close (click outside)
    page.click("#sync-button")
    page.wait_for_timeout(2500)
    assert len(polls) <= 4  # about one a second from a single loop


def test_lost_job_status_clears_the_running_sync(site, taxonomy, drafter):
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    page.route(
        "**/api/v1/worms/jobs/*",
        lambda route: route.fulfill(status=502, json={"detail": "bad gateway"}),
    )
    page.click("#sync-button")
    page.click('[data-sync="sync_tree"]')
    # gives up only after its retries (1, 2 and 4 s)
    expect(page.locator(".toast")).to_contain_text("Lost track of the sync", timeout=15000)
    expect(page.locator("#sync-job")).to_have_count(0)


def test_a_transient_poll_failure_is_retried(site, taxonomy, drafter):
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    failures = []

    def flaky(route):
        if len(failures) < 2:
            failures.append(route.request.url)
            route.fulfill(status=502, json={"detail": "bad gateway"})
        else:
            route.continue_()

    page.route("**/api/v1/worms/jobs/*", flaky)
    page.click("#sync-button")
    page.click('[data-sync="sync_tree"]')
    for _ in range(60):  # both failed polls retried, then the sync finished
        if len(failures) == 2 and page.locator("#sync-job").count() == 0:
            break
        page.wait_for_timeout(250)
    assert len(failures) == 2 and page.locator("#sync-job").count() == 0
    assert page.locator(".toast", has_text="Lost track").count() == 0
