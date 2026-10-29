"""The draft editor (spec: webapp): edit mode, composing, Validate before save,
the changes panel tabs, draft markings, and saving, rebasing and publishing."""

import pytest
from playwright.sync_api import expect

from core.changesets import create_changeset, latest_rev
from core.models import Changeset
from core.tests.helpers import add, edit, ids_by_label, publish

pytestmark = pytest.mark.django_db(transaction=True)


def new_draft(site, user):
    site.login(user)
    page = site.open("/trees/taxonomy/")
    page.click("#edit-button")
    page.click("#new-draft")
    page.click("text=Expand all")
    return page


def menu(site, label, action):
    site.row(label).locator(".kebab").click()
    site.page.click(f'#node-menu [data-action="{action}"]')


def add_child(site, parent, label, aphia=None):
    menu(site, parent, "child")
    site.page.fill("#f-label", label)
    if aphia:
        site.page.fill("#f-aphia", str(aphia))
    site.page.click("#f-submit")


def validate(page):
    page.click("#validate-button")
    expect(page.locator("#validate-button")).to_have_attribute(
        "title", "Already validated", timeout=20000
    )


def changes(page):
    return page.eval_on_selector_all(
        "#tab-edited .crow .txt > div:first-child", "es => es.map(e => e.textContent)"
    )


# --- 6.1 edit mode and composing --------------------------------------------------------------


def test_open_an_existing_draft(site, taxonomy, drafter):
    ids = ids_by_label("taxonomy")
    draft = create_changeset(
        author="drafter1", tree=taxonomy, base_rev=1, changes=[edit(ids["box"], label="crate")]
    )
    publish(taxonomy, edit(ids["other"], label="others"))
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    page.click("#edit-button")
    page.click(f'#edit-menu [data-draft="{draft.pk}"]')
    expect(page.locator("#draft-id")).to_have_text(f"#{draft.pk}")
    assert page.inner_text("#base-rev") == "1"
    assert page.inner_text("#status") == "Draft (saved)"
    assert changes(page) == ["box: label → crate"]


def test_leave_with_unsaved_changes(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    add_child(site, "other", "crate")
    page.click("#exit-button")
    expect(page.locator("#confirm")).to_contain_text("Leave without saving?")
    page.click("#confirm >> text=Cancel")
    assert page.inner_text("#status") == "Draft (unsaved)"
    page.click("#exit-button")
    page.click("#confirm-ok")
    expect(page.locator("#status")).to_have_text("Published (frozen)")


def test_composing_makes_no_server_calls(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    calls = []
    page.on("request", lambda r: "/api/" in r.url and calls.append(r.url))
    add_child(site, "other", "crate")
    menu(site, "box", "edit")
    page.fill("#f-label", "box2")
    page.click("#f-submit")
    menu(site, "Chaetoceros_didymus", "move")
    site.row("box2").click()
    assert len(changes(page)) == 3 and calls == []


def test_move_to_a_descendant(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    menu(site, "Bacillariophyceae", "move")
    assert "unpickable" in site.row("Chaetoceros").get_attribute("class")
    site.row("Chaetoceros").click()
    assert page.locator("#pick-banner").is_visible() and changes(page) == []
    site.row("other").click()
    assert changes(page) == ["Bacillariophyceae: Chromista → other"]


def test_deprecate_a_parent(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    menu(site, "Chaetoceros", "deprecate")
    expect(page.locator("#deprecate-blocked")).to_contain_text(
        "must be moved, merged or split first"
    )
    assert page.is_disabled("#deprecate-submit")


# --- 6.2 Validate before save -----------------------------------------------------------------


def test_edit_after_validating(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    add_child(site, "other", "crate")
    assert page.is_disabled("#save-button")
    validate(page)
    assert page.is_enabled("#save-button")
    add_child(site, "other", "crate2")
    assert page.is_disabled("#save-button") and page.is_enabled("#validate-button")
    page.click('[data-tab="bynode"]')
    assert page.locator("#stale-note").is_visible()


# --- 6.3 tabs, notifications, jump, safe removal ----------------------------------------------


def test_label_clash_appears(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    menu(site, "other", "child")
    page.fill("#f-label", "box")  # the dialog flags it, but composing allows it
    assert page.is_disabled("#f-submit")
    page.keyboard.press("Escape")
    menu(site, "box", "edit")
    page.fill("#f-label", "Chromista")
    assert page.is_disabled("#f-submit")


def test_server_error_under_its_change(site, taxonomy, drafter):
    """A label clash the dialog can't see: two drafts' worth of changes in one list."""
    ids = ids_by_label("taxonomy")
    draft = create_changeset(
        author="drafter1", tree=taxonomy, base_rev=1,
        changes=[add("new:1", "crate", parent=ids["other"]),
                 add("new:2", "crate", parent=ids["other"])],
    )  # fmt: skip
    site.login(drafter)
    page = site.open(f"/changesets/{draft.pk}/edit/")
    errors = page.locator('#tab-edited [data-change="2"] .chk.err')
    expect(errors).to_contain_text("label_in_use")
    assert page.is_disabled("#publish-button")


def compose_an_error(site):
    """Move box under a new node, then remove that node's add: the move fails."""
    add_child(site, "other", "crate")
    menu(site, "box", "move")
    site.row("crate").click()
    site.page.click('#tab-edited [data-change="1"] .x')


def test_tab_notifications(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    compose_an_error(site)
    page.click('[data-tab="bynode"]')
    validate(page)
    tab = page.locator('[data-tab="errors"]')
    expect(tab.locator(".count")).to_have_text("1")
    assert tab.locator(".dot").count() == 1
    tab.click()
    assert tab.locator(".dot").count() == 0
    expect(page.locator("#tab-errors")).to_contain_text("parent_not_in_tree")


def test_jump_to_a_collapsed_node(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    menu(site, "Chaetoceros_didymus", "edit")
    page.fill("#f-label", "C_didymus")
    page.click("#f-submit")
    validate(page)
    page.click("text=Collapse all")
    assert site.row("C_didymus").count() == 0
    page.click('[data-tab="bynode"]')
    page.locator("#tab-bynode .crow", has_text="C_didymus").first.click()
    expect(site.row("C_didymus")).to_be_visible()
    assert "flash" in site.row("C_didymus").get_attribute("class")


def test_hover_highlights_the_node(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    add_child(site, "other", "crate")
    page.hover('#tab-edited [data-change="1"]')
    assert "hl" in site.row("crate").get_attribute("class")


def test_remove_an_add_with_dependants(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    add_child(site, "other", "crate")
    menu(site, "box", "move")
    site.row("crate").click()
    page.click('#tab-edited [data-change="1"] .x')
    assert len(changes(page)) == 1
    validate(page)
    expect(page.locator('#tab-edited [data-change="1"] .chk.err')).to_contain_text(
        "parent_not_in_tree"
    )


# --- 6.4 markings -----------------------------------------------------------------------------


def test_child_added(site, taxonomy, drafter):
    new_draft(site, drafter)
    add_child(site, "Chaetoceros", "Chaetoceros_debilis")
    assert "mark-new" in site.row("Chaetoceros_debilis").get_attribute("class")
    chaetoceros = site.row("Chaetoceros")
    assert "mark-bump" in chaetoceros.get_attribute("class")
    expect(chaetoceros.locator(".b-bump")).to_have_text("v1 → v2")


def test_deprecated_node_stays_in_place(site, taxonomy, drafter):
    new_draft(site, drafter)
    menu(site, "box", "deprecate")
    site.page.click("#deprecate-submit")
    assert "mark-dep" in site.row("box").get_attribute("class")


# --- 6.5 save, rebase, publish, discard -------------------------------------------------------


def test_save_with_errors(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    compose_an_error(site)
    validate(page)
    page.click("#save-button")
    expect(page.locator("#confirm")).to_contain_text("will not be publishable as it is")
    page.click("#confirm-ok")
    expect(page.locator("#status")).to_have_text("Draft (saved)")
    draft = Changeset.objects.get(state="draft")
    assert draft.author == "drafter1" and draft.changes.count() == 1


def test_save_stores_the_reduced_list(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    for label in ("crate", "crate2"):
        menu(site, "box" if label == "crate" else "crate", "edit")
        page.fill("#f-label", label)
        page.click("#f-submit")
    validate(page)
    page.click("#save-button")
    expect(page.locator("#status")).to_have_text("Draft (saved)")
    assert changes(page) == ["box: label → crate2"]


def test_rebase_then_publish(site, taxonomy, approver):
    ids = ids_by_label("taxonomy")
    draft = create_changeset(author="drafter1", tree=taxonomy, base_rev=1,
                             changes=[edit(ids["box"], label="crate")])  # fmt: skip
    publish(taxonomy, edit(ids["other"], label="others"))
    site.login(approver)
    page = site.open(f"/changesets/{draft.pk}/edit/")
    assert page.is_disabled("#publish-button")
    page.click('[data-tab="errors"]')
    page.click("#rebase-button")
    expect(page.locator("#base-rev")).to_have_text("2")
    expect(page.locator("#publish-button")).to_be_enabled()
    page.click("#publish-button")
    page.fill("#publish-notes", "Rename the box")
    page.click("#publish-submit")
    expect(page.locator("#status")).to_have_text("Published (frozen)")
    assert latest_rev("taxonomy") == 3
    revision = taxonomy.revisions.get(number=3)
    assert (revision.notes, revision.published_by) == ("Rename the box", "approver1")


def test_drafter_cannot_publish(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    assert page.get_attribute("#publish-button", "title") == "Needs the approver role"


def test_discard(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    add_child(site, "other", "crate")
    validate(page)
    page.click("#save-button")
    expect(page.locator("#status")).to_have_text("Draft (saved)")
    page.click("#discard-button")
    page.click("#confirm-ok")
    expect(page.locator("#status")).to_have_text("Published (frozen)")
    assert Changeset.objects.get(author="drafter1").state == "discarded"


# --- 6.6 review -------------------------------------------------------------------------------


def test_review_and_publish(site, taxonomy, approver):
    ids = ids_by_label("taxonomy")
    crate = add("new:1", "crate", parent=ids["other"], group="split#1")
    draft = create_changeset(author="drafter1", tree=taxonomy, base_rev=1, changes=[crate])
    site.login(approver)
    page = site.open(f"/changesets/{draft.pk}/")
    assert "new → v1" in page.inner_text("#by-node") and "split#1" in page.inner_text("#by-node")
    assert "v1 → v2" in page.inner_text("#by-node")  # other gains a child
    page.click("#actions >> text=Publish")
    page.fill("#publish-notes", "Add a crate")
    page.click(".modal button.btn-success")
    page.wait_for_url("**/trees/taxonomy/")
    assert latest_rev("taxonomy") == 2 and site.console.errors == []
