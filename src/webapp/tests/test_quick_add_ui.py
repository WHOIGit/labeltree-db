"""The Quick add page (spec: webapp "Quick add page", "Quick add preview and confirm")."""

import pytest
from playwright.sync_api import expect

from core.engine import load_state
from core.models import TreeRevision
from core.tests.helpers import add, deprecate, ids_by_label, move, publish
from worms.tests.fixtures import load

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def searchable(worms_http):
    """searchable(name, *aphia_ids): WoRMS search for `name` returns those recorded records."""
    recorded = load()

    def _searchable(name, *aphia_ids):
        hits = [recorded[f"/AphiaRecordByAphiaID/{a}"]["body"] for a in aphia_ids]
        key = f"/AphiaRecordsByName/{name}?like=true&marine_only=false&offset=1"
        worms_http.override({key: {"status": 200, "body": hits}})

    return _searchable


def open_page(site, user):
    site.login(user)
    return site.open("/trees/taxonomy/quick-add/")


def find(page, name, aphia_id):
    page.fill("#qa-q", name)
    page.click("#qa-search")
    page.click(f'#qa-results [data-aphia="{aphia_id}"] input')


def test_button_for_approvers_only(site, taxonomy, approver, drafter):
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    expect(page.locator("#sync-button")).to_be_visible()
    expect(page.locator("#quick-add-button")).to_have_count(0)
    site.login(approver)
    page = site.open("/trees/taxonomy/")
    button = page.locator("#quick-add-button")
    expect(button).to_have_attribute("href", "/trees/taxonomy/quick-add/")


def test_confirming(site, taxonomy, approver, searchable):
    searchable("Chaetoceros debilis", 149219)
    page = open_page(site, approver)
    find(page, "Chaetoceros debilis", 149219)
    page.click("#qa-preview")
    url = "https://www.marinespecies.org/aphia.php?p=taxdetails&id=149219"
    expect(page.locator("#qa-aphia-link")).to_have_text(url)
    expect(page.locator("#qa-plan-label")).to_have_text("chaetoceros_debilis")
    expect(page.locator("#qa-plan-parent")).to_have_text("Chaetoceros")
    expect(page.locator("#qa-plan-worms")).to_have_text(url)
    expect(page.locator("#qa-plan-worms")).to_have_attribute("target", "_blank")
    page.click("#qa-confirm")
    expect(page.locator("#qa-published")).to_contain_text("Added chaetoceros_debilis in revision 2")
    expect(page.locator("#qa-published-worms")).to_have_attribute("href", url)
    page.click("#qa-node-link")
    expect(page.locator("h1")).to_contain_text("chaetoceros_debilis")
    assert site.console.errors == []


def test_choosing_the_accepted_name(site, taxonomy, approver, searchable):
    # Rhizosolenia alata (149223) is a synonym of Proboscia alata (149168).
    searchable("Rhizosolenia alata", 149223)
    page = open_page(site, approver)
    find(page, "Rhizosolenia alata", 149223)
    page.click("#qa-preview")
    issue = page.locator('[data-issue="unaccepted_aphia"]')
    expect(issue).to_be_visible()
    issue.get_by_role("button").click()
    expect(page.locator("#qa-aphia")).to_contain_text("149168")
    expect(page.locator("#qa-plan-label")).to_have_text("proboscia_alata")
    expect(page.locator('[data-issue="unaccepted_aphia"]')).to_have_count(0)
    assert site.console.errors == []


def test_plan_changed_before_confirming(site, taxonomy, approver, searchable):
    searchable("Chaetoceros debilis", 149219)
    page = open_page(site, approver)
    find(page, "Chaetoceros debilis", 149219)
    page.click("#qa-preview")
    expect(page.locator("#qa-plan-parent")).to_have_text("Chaetoceros")
    publish(taxonomy, add("new:1", "Chaetoceros_sp", aphia_id=148985))  # now a tie
    page.click("#qa-confirm")
    expect(page.locator("#qa-reason")).to_contain_text("The tree changed since the preview")
    expect(page.locator("#qa-plan-parent")).to_have_text("(top level)")
    expect(page.locator('[data-issue="ambiguous_parent"]')).to_be_visible()
    assert TreeRevision.objects.filter(tree_id="taxonomy").count() == 2


def test_label_in_use(site, taxonomy, approver):
    page = open_page(site, approver)
    page.fill("#qa-label", "other")
    page.click("#qa-preview")
    expect(page.locator("#qa-label-error")).to_contain_text("already used")
    expect(page.locator("#qa-plan")).to_have_count(0)
    expect(page.locator("#qa-confirm")).to_have_count(0)


def test_lowercase_off(site, taxonomy, approver, searchable):
    searchable("Chaetoceros debilis", 149219)
    page = open_page(site, approver)
    find(page, "Chaetoceros debilis", 149219)
    expect(page.locator("#qa-lower")).to_be_checked()
    page.uncheck("#qa-lower")
    with page.expect_request("**/quick_add") as request:
        page.click("#qa-preview")
    assert request.value.post_data_json["lowercase_label"] is False
    expect(page.locator("#qa-plan-label")).to_have_text("Chaetoceros_debilis")


def test_no_worms_link_without_aphia(site, taxonomy, approver):
    page = open_page(site, approver)
    page.fill("#qa-label", "detritus")
    page.click("#qa-preview")
    expect(page.locator("#qa-plan-label")).to_have_text("detritus")
    expect(page.locator("#qa-plan-worms")).to_have_count(0)


def test_editing_after_preview_needs_a_new_preview(site, taxonomy, approver):
    page = open_page(site, approver)
    page.fill("#qa-label", "detritus")
    page.click("#qa-preview")
    expect(page.locator("#qa-confirm")).to_be_enabled()
    page.fill("#qa-label", "detritus2")
    expect(page.locator("#qa-confirm")).to_be_disabled()


def test_moving_the_nodes_that_belong_under_it(site, taxonomy, approver, searchable):
    ref = ids_by_label("taxonomy")
    # Chaetoceros beside where its family will go, and no family node yet.
    publish(taxonomy, move(ref["Chaetoceros"], ref["Chaetocerotaceae"], ref["Bacillariophyceae"]),
            deprecate(ref["Chaetocerotaceae"]))  # fmt: skip
    searchable("Chaetocerotaceae", 148984)
    page = open_page(site, approver)
    find(page, "Chaetocerotaceae", 148984)
    page.click("#qa-preview")
    issue = page.locator('[data-issue="misplaced_lineage_ancestor"]')
    expect(issue).to_contain_text("Chaetoceros")
    expect(page.locator("#qa-cross-node")).not_to_be_checked()
    issue.get_by_role("button").click()
    expect(page.locator("#qa-cross-node")).to_be_checked()
    expect(page.locator("#qa-plan-moves")).to_have_text("Chaetoceros")
    expect(page.locator('[data-issue="misplaced_lineage_ancestor"]')).to_have_count(0)
    page.click("#qa-confirm")
    expect(page.locator("#qa-published")).to_contain_text("Added chaetocerotaceae")
    expect(page.locator("#qa-moved")).to_contain_text("Chaetoceros")
    after = ids_by_label("taxonomy")
    assert load_state("taxonomy", 3).nodes[after["Chaetoceros"]].parent == after["chaetocerotaceae"]
    assert site.console.errors == []
