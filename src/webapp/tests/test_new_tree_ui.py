"""Starting a new tree: the New tree menu and the organization page (spec: webapp
"New tree menu", "New tree from the organization page")."""

import json

import pytest
from playwright.sync_api import expect

from accounts.models import Organization
from api.tests.conftest import make_user
from core.models import Changeset

pytestmark = pytest.mark.django_db(transaction=True)

SMALL = {"nodes": [{"label": "detritus"}, {"label": "bubble", "children": [{"label": "small"}]}]}


@pytest.fixture
def lab_owner(transactional_db):
    Organization.objects.create(id="lab_a", name="Lab A")
    return make_user("lab_owner", roles={"lab_a": "owner"})


def open_menu(site, user, entry):
    site.login(user)
    page = site.open("/trees/taxonomy/")
    page.click("#new-tree-button")
    page.click(f'#new-tree-menu [data-new-tree="{entry}"]')
    expect(page.locator("#new-tree-dialog")).to_be_visible()
    return page


def name_it(page, tree_id, title):
    page.fill("#new-tree-id", tree_id)
    page.fill("#new-tree-title", title)


def test_empty_tree(site, taxonomy, lab_owner):
    page = open_menu(site, lab_owner, "empty")
    expect(page.locator("#new-tree-org")).to_have_value("lab_a")
    name_it(page, "lab_tags", "Lab tags")
    page.click("#new-tree-submit")
    expect(page.locator("#status")).to_have_text("Draft (saved)")
    assert "lab_tags" in page.inner_text(".topbar")
    draft = Changeset.objects.get(new_tree_id="lab_tags")
    assert (draft.new_tree_org_id, draft.changes.count(), draft.notes) == ("lab_a", 0, "New tree.")
    assert site.console.errors == []


def test_tree_from_an_import_file(site, taxonomy, lab_owner, tmp_path):
    page = open_menu(site, lab_owner, "import")
    name_it(page, "lab_tags", "Lab tags")
    expect(page.locator("#new-tree-submit")).to_be_disabled()  # no file yet
    path = tmp_path / "lab_tags.json"
    path.write_text(json.dumps(SMALL))
    page.set_input_files("#new-tree-file", str(path))
    expect(page.locator("#new-tree-text")).to_have_value(json.dumps(SMALL))
    page.click("#new-tree-submit")
    expect(page.locator("#status")).to_have_text("Draft (saved)")
    expect(page.locator('[data-group="import#1"]')).to_contain_text("3 changes")
    draft = Changeset.objects.get(new_tree_id="lab_tags")
    assert draft.notes == "Import of lab_tags.json."
    assert [c.op for c in draft.changes.order_by("seq")] == ["add", "add", "add"]


def test_malformed_import_file(site, taxonomy, lab_owner):
    page = open_menu(site, lab_owner, "import")
    name_it(page, "lab_tags", "Lab tags")
    page.fill("#new-tree-text", json.dumps({"nodes": [{"label": "a"}, {"children": []}]}))
    page.click("#new-tree-submit")
    expect(page.locator("#new-tree-error")).to_contain_text("nodes[1]")
    page.fill("#new-tree-text", "{nope")
    page.click("#new-tree-submit")
    expect(page.locator("#new-tree-error")).to_contain_text("Not valid JSON")
    assert not Changeset.objects.filter(new_tree_id="lab_tags").exists()


def test_clone_flow(site, taxonomy, lab_owner):
    page = open_menu(site, lab_owner, "clone")
    expect(page.locator("#new-tree-dialog .modal-title")).to_have_text(
        "New tree from taxonomy revision 1"
    )
    name_it(page, "lab_taxonomy", "Lab taxonomy")
    page.click("#new-tree-submit")
    expect(page.locator("#status")).to_have_text("Draft (saved)")
    assert "lab_taxonomy" in page.inner_text(".topbar")
    group = page.locator('[data-group="import#1"]')
    expect(group).to_contain_text("7 changes")
    assert page.locator("#tab-edited .crow").count() == 0  # one collapsed group
    draft = Changeset.objects.get(new_tree_id="lab_taxonomy")
    assert (draft.new_tree_org_id, draft.base_rev) == ("lab_a", None)
    expect(site.row("Chromista")).to_be_visible()


def test_switching_kind_in_the_dialog(site, taxonomy, lab_owner):
    page = open_menu(site, lab_owner, "empty")
    assert page.locator("#new-tree-text").count() == 0
    page.check("#nt-import")
    expect(page.locator("#new-tree-text")).to_be_visible()
    page.check("#nt-clone")
    expect(page.locator("#new-tree-dialog .modal-title")).to_contain_text("revision 1")


def test_not_an_owner(site, taxonomy, drafter):
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    button = page.locator("#new-tree-button")
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("title", "Needs the owner role in an organization")


def test_owner_starts_a_tree_from_the_organization_page(site, lab_owner):
    site.login(lab_owner)
    page = site.open("/orgs/lab_a/")
    page.click("#org-new-tree")
    expect(page.locator("#new-tree-dialog")).to_be_visible()
    expect(page.locator("#new-tree-org")).to_have_value("lab_a")
    assert page.locator("#nt-clone").count() == 0  # no revision to clone here
    name_it(page, "lab_tags", "Lab tags")
    page.click("#new-tree-submit")
    expect(page.locator("#status")).to_have_text("Draft (saved)")
    assert Changeset.objects.get(new_tree_id="lab_tags").new_tree_org_id == "lab_a"
    assert site.console.errors == []


def test_cancel_returns_to_the_organization_page(site, lab_owner):
    site.login(lab_owner)
    page = site.open("/orgs/lab_a/new-tree/")
    page.click("#new-tree-cancel")
    page.wait_for_url("**/orgs/lab_a/")
