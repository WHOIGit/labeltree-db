"""End to end: two drafters and an approver on NES2022_taxonomy, and setting up a new
instance from an empty database."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.test import Client
from playwright.sync_api import expect

from api.tests.conftest import make_user
from core.models import Changeset, Tree
from core.tests.helpers import LABELDATA, TAGS, edit, ids_by_label, org, publish
from worms.models import WormsRecord
from worms.tests.fixtures import load

from .conftest import Console, Site

pytestmark = pytest.mark.django_db(transaction=True)

HEMIAULACEAE = 149235


def uncached_aphia_id() -> int:
    """A recorded, accepted AphiaID not in the cache and not under Hemiaulaceae in WoRMS."""
    recorded = load()
    cached = set(WormsRecord.objects.values_list("aphia_id", flat=True))
    for key, entry in recorded.items():
        if not key.startswith("/AphiaRecordByAphiaID/") or entry["status"] != 200:
            continue
        aphia = int(key.rsplit("/", 1)[1])
        lineage = recorded.get(f"/AphiaClassificationByAphiaID/{aphia}")
        record = entry["body"]
        if aphia in cached or not lineage or record.get("valid_AphiaID") != aphia:
            continue
        ids, node = set(), lineage["body"]
        while node:
            ids.add(node["AphiaID"])
            node = node.get("child")
        if HEMIAULACEAE not in ids:
            return aphia
    raise AssertionError("no suitable recorded AphiaID")


def second_site(browser, url):
    page = browser.new_context().new_page()
    return Site(url, page, Console(page))


def menu(site, label, action):
    site.row(label).locator(".kebab").click()
    site.page.click(f'#node-menu [data-action="{action}"]')


def test_split_validate_concurrent_edit_rebase_publish(site, browser, live_server, worms_http):
    call_command(
        "import_tree", str(LABELDATA / "NES2022_taxonomy.json"), tree="NES2022_taxonomy",
        title="NES2022 taxonomy", org=org(), stdout=StringIO(), stderr=StringIO(),
    )  # fmt: skip
    tree = Tree.objects.get(id="NES2022_taxonomy")
    new_aphia = uncached_aphia_id()
    a, b = (
        make_user("drafter_a", roles={"amplify": "drafter"}),
        make_user("drafter_b", roles={"amplify": "drafter"}),
    )
    approver = make_user("approver1", roles={"amplify": "approver"})

    # Drafter A splits Eucampia, giving one new node an uncached AphiaID, and validates.
    site.login(a)
    page = site.open("/trees/NES2022_taxonomy/")
    page.click("#edit-button")
    page.click("#new-draft")
    page.fill("#filter", "Eucampia")
    page.wait_for_timeout(300)
    menu(site, "Eucampia", "split")
    page.click("#wizard-next")
    page.fill('[data-part="0"]', "Eucampia_zodiacus")
    page.locator('[data-part="0"]').locator("xpath=../..").locator("input").nth(1).fill(
        str(new_aphia)
    )
    page.fill('[data-part="1"]', "Eucampia_cornuta")
    page.click("#wizard-next")
    page.select_option('[data-child="Eucampia_morphotype1"]', "0")
    page.select_option('[data-child="Eucampia_morphotype2"]', "1")
    page.click("#wizard-next")
    page.click("#wizard-add")
    worms_http.calls.clear()
    page.click("#validate-button")
    expect(page.locator("#save-button")).to_be_enabled(timeout=20000)
    assert f"/AphiaRecordByAphiaID/{new_aphia}" in worms_http.calls  # the fetch job ran
    assert WormsRecord.objects.filter(aphia_id=new_aphia).exists()
    page.click("#save-button")
    expect(page.locator("#status")).to_have_text("Draft (saved)")
    draft = Changeset.objects.get(state="draft")

    # Drafter B opens the same draft and saves a change to its notes.
    other = second_site(browser, live_server.url)
    other.login(b)
    page_b = other.open(f"/changesets/{draft.pk}/edit/")
    page_b.fill("#notes", "Split Eucampia into two species")
    page_b.click("#save-button")
    expect(page_b.locator("#status")).to_have_text("Draft (saved)")

    # A's copy is now stale: saving gets 412, and A reloads the draft.
    page.fill("#notes", "A's notes")
    page.click("#save-button")
    expect(page.locator("#confirm")).to_contain_text("Someone saved this draft")
    page.click("#confirm-ok")
    expect(page.locator("#notes")).to_have_value("Split Eucampia into two species")

    # A revision is published meanwhile; the approver rebases and publishes.
    ids = ids_by_label("NES2022_taxonomy")
    publish(tree, edit(ids["Foraminifera"], label="Foraminifera_sl"))
    reviewer = second_site(browser, live_server.url)
    reviewer.login(approver)
    page_c = reviewer.open(f"/changesets/{draft.pk}/edit/")
    page_c.click('[data-tab="errors"]')
    page_c.click("#rebase-button")
    expect(page_c.locator("#base-rev")).to_have_text("2")
    expect(page_c.locator("#publish-button")).to_be_enabled()
    page_c.click("#publish-button")
    page_c.fill("#publish-notes", "Split Eucampia")
    page_c.click("#publish-submit")
    expect(page_c.locator("#status")).to_have_text("Published (frozen)")

    # Check the result through the (anonymous) read API.
    api = Client()
    summary = api.get("/api/v1/trees/NES2022_taxonomy").json()
    assert (summary["rev"], summary["notes"], summary["published_by"]) == (
        3,
        "Split Eucampia",
        "approver1",
    )
    eucampia, morph1 = ids["Eucampia"], ids["Eucampia_morphotype1"]
    changes = api.get("/api/v1/trees/NES2022_taxonomy/revisions/3/changes").json()
    versions = {vc["node"]: (vc["from"], vc["to"]) for vc in changes["version_changes"]}
    after = ids_by_label("NES2022_taxonomy")
    zodiacus, cornuta = after["Eucampia_zodiacus"], after["Eucampia_cornuta"]
    assert (
        versions[eucampia] == (1, None)
        and versions[zodiacus] == (None, 1)
        and versions[morph1] == (1, 2)
    )
    assert {c["group"] for c in changes["changes"]} == {"split#1"}
    gone = api.get(f"/api/v1/nodes/{eucampia}").json()
    assert gone["deprecated_in_rev"] == 3
    assert gone["successors"] == [zodiacus, cornuta]
    assert api.get(f"/api/v1/nodes/{morph1}").json()["parent"]["id"] == zodiacus
    history = api.get(f"/api/v1/nodes/{zodiacus}/warning_history").json()
    assert history["count"] == 1
    assert [w["warning"] for w in history["history"][0]["warnings"]] == ["out_of_lineage"]
    assert (
        site.console.errors == [] and other.console.errors == [] and reviewer.console.errors == []
    )


def log_in(site, username, password):
    page = site.page
    page.goto(site.url + "/login/")
    page.fill("#id_username", username)
    page.fill("#id_password", password)
    page.click("button:text-is('Log in')")
    page.wait_for_load_state("networkidle")
    return page


def test_new_instance_setup(site, browser, live_server):
    """From an empty database: the superuser sets up an organization, its owner and a tree."""
    admin = make_user("admin", superuser=True)
    admin.set_password("site-admin-pw-1987")
    admin.save()
    page = log_in(site, "admin", "site-admin-pw-1987")
    page.goto(site.url + "/")
    page.wait_for_url("**/setup/")

    page.fill("#org-id", "lab_a")
    page.fill("#org-name", "Lab A")
    page.click("#org-create")
    page.fill("#user-name", "curator1")
    page.click("#user-add")
    page.fill("#user-password", "curator-pw-1987")
    page.fill("#user-password2", "curator-pw-1987")
    page.click("#user-add")
    expect(page.locator('#setup-members [data-member="curator1"]')).to_contain_text("owner")
    page.click("#users-continue")
    page.set_input_files("#tree-file", str(TAGS))
    expect(page.locator("#tree-id")).to_have_value("NES2022_tags")
    page.fill("#tree-title", "NES2022 tags")
    page.click("#tree-import")
    expect(page.locator('#imported-trees [data-tree="NES2022_tags"]')).to_be_visible(timeout=20000)
    page.click("#setup-done")
    page.wait_for_url("**/trees/NES2022_tags/")
    expect(page.locator('.trow[data-label="interaction"]')).to_be_visible()
    assert Tree.objects.get().org_id == "lab_a"
    assert site.console.errors == []

    owner = second_site(browser, live_server.url)
    page = log_in(owner, "curator1", "curator-pw-1987")
    assert page.url.endswith("/trees/NES2022_tags/")  # home shows the first tree
    expect(page.locator("#edit-button")).to_be_enabled()
    page.goto(owner.url + "/me/")
    assert "Lab A" in page.inner_text("#my-roles") and "owner" in page.inner_text("#my-roles")
    assert owner.console.errors == []
