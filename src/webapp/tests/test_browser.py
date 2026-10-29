"""The tree browser in static mode (spec: webapp): pickers, filter, AphiaID
pills, revision changes and the warnings panel."""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from playwright.sync_api import expect

from core.changesets import create_changeset, publish_changeset
from core.models import Tree
from core.tests.helpers import LABELDATA, TAGS, add, deprecate, edit, ids_by_label, org, publish
from worms.warnings import record_warnings

pytestmark = pytest.mark.django_db(transaction=True)

EXPECTED = Path(__file__).resolve().parents[2] / "worms/tests/expected_taxonomy_warnings.json"


def pills(site):
    """label -> (kind, badge, title) of every visible pill."""
    out = {}
    for row in site.page.locator(".trow").all():
        pill = row.locator(".pill")
        if pill.count():
            badge = pill.locator(".pb")
            out[row.get_attribute("data-label")] = (
                pill.get_attribute("data-pill"),
                badge.inner_text() if badge.count() else "",
                pill.get_attribute("title"),
            )
    return out


# --- 5.1 ---------------------------------------------------------------------------------


def test_pages_load_without_csp_violations(site, taxonomy, drafter):
    for path in [
        "/trees/taxonomy/",
        "/orgs/amplify/",
        f"/nodes/{ids_by_label('taxonomy')['box']}/",
        "/login/",
    ]:
        site.open(path)
    site.login(drafter)
    for path in ["/trees/taxonomy/", "/trees/taxonomy/drafts/", "/me/", "/orgs/amplify/"]:
        site.open(path)
    assert site.console.errors == []


def test_reader_sees_edit_disabled(site, taxonomy):
    from api.tests.conftest import make_user

    site.login(make_user("reader1", roles={"amplify": "reader"}))
    page = site.open("/trees/taxonomy/")
    assert page.is_disabled("#edit-button")
    assert page.get_attribute("#edit-button", "title") == "Needs the drafter role"


# --- 5.2 ---------------------------------------------------------------------------------


def test_aphia_pills(site, taxonomy, worms_http):
    ids = ids_by_label("taxonomy")
    out, dup, unknown = (
        {"warning": "out_of_lineage", "detail": "not in lineage"},
        {"warning": "duplicate_aphia", "detail": "also used"},
        {"warning": "unknown_aphia", "detail": "no record"},
    )
    record_warnings({ids["Chaetoceros"]: [out, dup], ids["Chaetocerotaceae"]: [unknown, dup]})
    worms_http.override(
        {"/AphiaRecordByAphiaID/110153": lambda r: (_ for _ in ()).throw(OSError())}
    )
    cs = create_changeset(  # never fetched: published without fetching its record
        author="a", tree=taxonomy, base_rev=1,
        changes=[add("new:1", "Heterocapsa", parent=ids["other"], aphia_id=110153)],
    )  # fmt: skip
    publish_changeset(cs, published_by="b")
    site.open("/trees/taxonomy/")
    site.page.click("text=Expand all")
    found = pills(site)
    assert found["Chaetoceros"][:2] == ("orange", "!")
    assert "AphiaID 148985" in found["Chaetoceros"][2]
    assert (
        "out_of_lineage" in found["Chaetoceros"][2] and "duplicate_aphia" in found["Chaetoceros"][2]
    )
    assert found["Chaetocerotaceae"][:2] == ("red", "?")
    assert "duplicate_aphia" in found["Chaetocerotaceae"][2]
    assert found["Heterocapsa"][:2] == ("grey", "")
    assert found["Chaetoceros_didymus"][:2] == ("green", "")
    assert "other" not in found and "box" not in found  # no AphiaID: no pill
    link = site.row("Chaetoceros_didymus").locator(".pill")
    assert link.get_attribute("href").endswith("taxdetails&id=149122")
    assert link.get_attribute("target") == "_blank"


def test_tags_tree_has_no_pills(site, transactional_db):
    call_command(
        "import_tree", str(TAGS), tree="NES2022_tags", title="tags", org=org(), stdout=StringIO()
    )
    site.open("/trees/NES2022_tags/")
    site.page.click("text=Expand all")
    assert site.row("interaction").is_visible() and pills(site) == {}


def test_tree_picker_groups_by_organization(site, taxonomy):
    from core.tests.helpers import publish_new_tree

    publish_new_tree("lab_tree", add("new:1", "a"), org_id="lab_a")
    page = site.open("/trees/taxonomy/")
    groups = page.eval_on_selector_all(
        "#tree-picker optgroup",
        "gs => gs.map(g => [g.label, [...g.querySelectorAll('option')].map(o => o.value)])",
    )
    assert groups == [["AMPLIfy", ["taxonomy"]], ["lab_a", ["lab_tree"]]]


def test_viewing_a_past_revision(site, taxonomy):
    ids = ids_by_label("taxonomy")
    publish(taxonomy, add("new:1", "box2", parent=ids["other"]))
    publish(taxonomy, deprecate(ids["box"]))
    page = site.open("/trees/taxonomy/")
    page.click("text=Expand all")
    assert site.row("box").count() == 0
    options = page.eval_on_selector_all("#rev-picker option", "os => os.map(o => o.textContent)")
    assert (
        options[0].startswith("3 ·") and options[0].endswith("(latest)") and "alice" in options[0]
    )
    page.select_option("#rev-picker", "2")
    expect(site.row("box")).to_be_visible()  # box's parent is top level, so already expanded


def test_filter(site, taxonomy):
    page = site.open("/trees/taxonomy/")
    page.fill("#filter", "didymus")
    page.wait_for_timeout(400)
    labels = page.eval_on_selector_all(".trow", "rs => rs.map(r => r.dataset.label)")
    assert labels == [
        "Chromista",
        "Bacillariophyceae",
        "Chaetocerotaceae",
        "Chaetoceros",
        "Chaetoceros_didymus",
    ]


def test_filter_matches_aliases(site, taxonomy):
    page = site.open("/trees/taxonomy/")
    page.fill("#filter", "chaetoceros didymus")
    page.wait_for_timeout(400)
    assert site.row("Chaetoceros_didymus").is_visible()


def test_revision_changes_in_static_mode(site, taxonomy):
    ids = ids_by_label("taxonomy")
    publish(taxonomy,
            add("new:1", "boxes", parent=ids["other"], group="merge#1"),
            deprecate(ids["box"], successors=["new:1"], group="merge#1"),
            notes="Merge the boxes")  # fmt: skip
    page = site.open("/trees/taxonomy/")
    panel = page.locator("#revision-changes")
    assert panel.locator('[data-group="merge#1"]').is_visible()
    assert "Merge the boxes" in panel.inner_text()
    assert "box" in panel.inner_text() and panel.locator(".x").count() == 0  # no remove buttons


# --- 5.3 ---------------------------------------------------------------------------------


def test_warnings_panel_on_nes2022_taxonomy(site, transactional_db, worms_http):
    call_command(
        "import_tree", str(LABELDATA / "NES2022_taxonomy.json"), tree="NES2022_taxonomy",
        title="NES2022 taxonomy", org=org(), stdout=StringIO(), stderr=StringIO(),
    )  # fmt: skip
    expected = json.loads(EXPECTED.read_text())  # the 13 unaccepted_aphia nodes
    page = site.open("/trees/NES2022_taxonomy/")
    page.click("#warnings-toggle")
    page.wait_for_selector("#warnings-panel .crow")
    entries = page.locator("#warnings-panel .crow")
    assert entries.count() == 13
    shown = page.eval_on_selector_all(
        "#warnings-panel .crow .txt > div:first-child", "es => es.map(e => e.textContent)"
    )
    assert set(shown) == set(expected)
    # jump to a node in a collapsed branch
    first = entries.first
    label = first.locator(".txt > div").first.inner_text()
    first.click()
    page.wait_for_timeout(300)
    assert site.row(label).is_visible()
    assert "flash" in site.row(label).get_attribute("class")
    assert Tree.objects.get(id="NES2022_taxonomy")


def test_a_slow_revision_load_does_not_overwrite_a_newer_one(site, taxonomy):
    ids = ids_by_label("taxonomy")
    publish(taxonomy, add("new:1", "crate", parent=ids["other"]))
    page = site.open("/trees/taxonomy/")
    held = []

    def stall_first(route):
        if held:
            route.continue_()
        else:
            held.append(route)  # the first rev 2 load stalls

    page.select_option("#rev-picker", "1")
    page.wait_for_load_state("networkidle")
    page.route("**/export?rev=2", stall_first)
    page.select_option("#rev-picker", "2")  # stalls
    page.wait_for_timeout(300)
    page.select_option("#rev-picker", "1")
    page.wait_for_load_state("networkidle")
    held[0].continue_()  # the stale response arrives last
    page.wait_for_timeout(500)
    page.click("text=Expand all")
    assert site.row("crate").count() == 0  # still revision 1


def test_renames_show_their_old_name(site, taxonomy):
    ids = ids_by_label("taxonomy")
    publish(taxonomy, edit(ids["box"], label="crate"))
    page = site.open("/trees/taxonomy/")
    assert "box: label → crate" in page.inner_text("#revision-changes")


def test_a_revision_that_only_adds_needs_no_old_labels(site, taxonomy):
    ids = ids_by_label("taxonomy")
    publish(taxonomy, add("new:1", "crate", parent=ids["other"]))
    lookups = []
    site.page.on("request", lambda r: "/nodes?ids=" in r.url and lookups.append(r.url))
    page = site.open("/trees/taxonomy/")
    expect(page.locator("#revision-changes")).to_contain_text("crate under other")
    assert lookups == []


def test_a_failed_revision_load_keeps_the_picker(site, taxonomy):
    ids = ids_by_label("taxonomy")
    publish(taxonomy, add("new:1", "crate", parent=ids["other"]))
    page = site.open("/trees/taxonomy/")
    page.wait_for_load_state("networkidle")
    page.route("**/export?rev=1", lambda route: route.fulfill(status=500, json={"detail": "boom"}))
    page.select_option("#rev-picker", "1")
    expect(page.locator(".toast")).to_contain_text("Couldn't load the tree: boom")
    expect(page.locator("#rev-picker")).to_have_value("2")
    page.click("text=Expand all")
    expect(site.row("crate")).to_be_visible()  # still revision 2


def test_new_draft_starts_although_a_sync_reload_overtakes_it(site, taxonomy, drafter):
    ids = ids_by_label("taxonomy")
    publish(taxonomy, add("new:1", "crate", parent=ids["other"]))
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    page.select_option("#rev-picker", "1")
    page.wait_for_load_state("networkidle")
    started = page.evaluate("""async () => {
        const c = Alpine.$data(document.querySelector('.shell'));
        const draft = c.startNewDraft();  // loads revision 2 first
        await c.afterSync(null);           // a sync ends meanwhile and reloads it
        await draft;
        return [c.mode, c.viewRev];
    }""")
    assert started == ["edit", 2]


def test_picker_shows_the_requested_revision_after_a_sync(site, taxonomy, drafter):
    ids = ids_by_label("taxonomy")
    publish(taxonomy, add("new:1", "crate", parent=ids["other"]))
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    page.select_option("#rev-picker", "1")
    page.wait_for_load_state("networkidle")
    page.click("#sync-button")
    page.click('[data-sync="sync_tree"]')
    page.wait_for_timeout(500)
    expect(page.locator("#sync-job")).to_have_count(0, timeout=15000)  # the sync reloaded the view
    page.wait_for_load_state("networkidle")
    expect(page.locator("#rev-picker")).to_have_value("1")
    page.click("text=Expand all")
    assert site.row("crate").count() == 0
