"""Merge and split wizards, import, Add from WoRMS, aliases, descriptions and
clone (spec: webapp)."""

import json

import pytest
from playwright.sync_api import expect

from accounts.models import Organization
from api.tests.conftest import make_user
from core.changesets import latest_rev
from core.models import Changeset, NodeAlias, NodeDescription
from core.tests.helpers import ids_by_label
from worms.tests.fixtures import load

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


def edited(page):
    """(op, group, text) of every change in As edited, groups expanded."""
    return page.eval_on_selector_all(
        "#tab-edited .crow",
        "rs => rs.map(r => [r.querySelector('.op').textContent, r.classList.contains('in-group'),"
        " r.querySelector('.txt > div').textContent])",
    )


def wizard_next(page):
    page.click("#wizard-next")


# --- 7.1 merge --------------------------------------------------------------------------------


def test_merge_with_replacement(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    menu(site, "Chaetoceros", "merge")
    page.fill("#merge-find", "box")
    page.click('#merge-candidates [data-label="box"] input')
    wizard_next(page)
    wizard_next(page)  # with replacement (default)
    page.fill("#merge-label", "Chaetoceros_box")
    expect(page.locator("#merge-parent")).to_have_value("")  # common parent: top level
    wizard_next(page)
    review = page.inner_text("#wizard-review")
    assert "labels and aliases are copied" in page.inner_text("#wizard")
    page.click("#wizard-add")
    assert page.locator('[data-group="merge#1"]').is_visible()
    assert [(op, grouped) for op, grouped, _ in edited(page)] == [
        ("add", True),
        ("move", True),
        ("deprecate", True),
        ("deprecate", True),
    ]
    texts = [t for *_, t in edited(page)]
    assert "Chaetoceros_didymus: Chaetoceros → Chaetoceros_box (new:1)" in texts
    assert "Chaetoceros → successors Chaetoceros_box (new:1)" in texts and review


def test_merge_without_replacement(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    menu(site, "Chaetoceros", "merge")
    page.fill("#merge-find", "box")
    page.click('#merge-candidates [data-label="box"] input')
    wizard_next(page)
    page.click("#m-norepl")
    page.select_option("#survivor", str(ids_by_label("taxonomy")["box"]))
    wizard_next(page)
    wizard_next(page)
    page.click("#wizard-add")
    assert [(op, t) for op, _, t in edited(page)] == [
        ("move", "Chaetoceros_didymus: Chaetoceros → box"),
        ("deprecate", "Chaetoceros → successors box"),
    ]


def test_aliases_after_a_merge(site, taxonomy):
    page = new_draft(site, make_user("approver1", roles={"amplify": "approver"}))
    menu(site, "Chaetoceros_didymus", "merge")  # alias "Chaetoceros didymus"
    page.fill("#merge-find", "box")
    page.click('#merge-candidates [data-label="box"] input')
    wizard_next(page)
    wizard_next(page)
    page.fill("#merge-label", "C_merged")
    wizard_next(page)
    page.click("#wizard-add")
    page.click("#validate-button")
    expect(page.locator("#save-button")).to_be_enabled()
    page.click("#save-button")
    expect(page.locator("#publish-button")).to_be_enabled()
    page.click("#publish-button")
    page.click("#publish-submit")
    expect(page.locator("#status")).to_have_text("Published (frozen)")
    merged = ids_by_label("taxonomy")["C_merged"]
    aliases = set(
        NodeAlias.objects.filter(node_id=merged, removed_at__isnull=True).values_list(
            "alias", flat=True
        )
    )
    assert aliases == {"Chaetoceros_didymus", "Chaetoceros didymus", "box"}


# --- 7.2 split --------------------------------------------------------------------------------


def test_split_with_replacement(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    menu(site, "Chaetoceros", "split")
    wizard_next(page)  # with replacement
    page.fill('[data-part="0"]', "Chaetoceros_a")
    page.fill('[data-part="1"]', "Chaetoceros_b")
    wizard_next(page)
    expect(page.locator("#wizard-error")).to_have_text("Assign every child")
    assert page.is_disabled("#wizard-next")  # unassigned child
    page.select_option('[data-child="Chaetoceros_didymus"]', "0")
    wizard_next(page)
    page.click("#wizard-add")
    assert [op for op, *_ in edited(page)] == ["add", "add", "move", "deprecate"]
    assert "Chaetoceros → successors Chaetoceros_a (new:1), Chaetoceros_b (new:2)" in [
        t for *_, t in edited(page)
    ]
    assert page.locator('[data-group="split#1"]').is_visible()


def test_split_without_replacement(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    menu(site, "Chaetoceros", "split")
    page.click("#m-norepl")
    wizard_next(page)
    page.fill('[data-part="0"]', "Chaetoceros_sibling")
    wizard_next(page)
    wizard_next(page)  # leave the child with Chaetoceros
    page.click("#wizard-add")
    assert [op for op, *_ in edited(page)] == ["add"]


# --- 7.3 import -------------------------------------------------------------------------------


def test_import_under_a_node(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    page.click("#import-button")
    data = {
        "nodes": [
            {"label": "external_flagellate"},
            {"label": "grazing", "children": [{"label": "deep"}]},
        ]
    }
    page.fill("#import-text", json.dumps(data))
    page.select_option("#import-under", str(ids_by_label("taxonomy")["other"]))
    page.click("#import-submit")
    group = page.locator('[data-group="import#1"]')
    expect(group).to_contain_text("3 changes")
    assert page.locator("#tab-edited .crow").count() == 0  # collapsed
    group.click()
    texts = [t for *_, t in edited(page)]
    assert (
        texts[0] == "external_flagellate (new:1) under other"
        and texts[2] == "deep (new:3) under grazing (new:2)"
    )


def test_import_errors(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    page.click("#import-button")
    page.fill("#import-text", '{"nodes": [{"label": "a", "children": [{}]}]}')
    page.click("#import-submit")
    expect(page.locator("#import-error")).to_contain_text("nodes[0].children[0]")


# --- 7.4 Add from WoRMS -----------------------------------------------------------------------


def search_returns(worms_http, name, record):
    worms_http.override({f"/AphiaRecordsByName/{name}?like=true&marine_only=false&offset=1":
                         {"status": 200, "body": [record]}})  # fmt: skip


def add_from_worms(site, name):
    page = site.page
    page.click("#worms-add")
    page.fill("#worms-q", name)
    page.click("#worms-search")
    page.click("#worms-results label")
    expect(page.locator("#worms-label")).not_to_have_value("")
    page.wait_for_load_state("networkidle")
    return page


def test_suggested_parent(site, taxonomy, drafter, worms_http):
    search_returns(
        worms_http, "Chaetoceros debilis", load()["/AphiaRecordByAphiaID/149219"]["body"]
    )
    new_draft(site, drafter)
    page = add_from_worms(site, "Chaetoceros debilis")
    expect(page.locator("#worms-label")).to_have_value("Chaetoceros_debilis")
    expect(page.locator("#worms-parent")).to_have_value(
        str(ids_by_label("taxonomy")["Chaetoceros"])
    )
    page.click("#worms-submit")
    assert [t for *_, t in edited(page)] == [
        "Chaetoceros_debilis (new:1) under Chaetoceros, AphiaID 149219"
    ]


def test_unsafe_characters(site, taxonomy, drafter, worms_http):
    record = {
        **load()["/AphiaRecordByAphiaID/149219"]["body"],
        "scientificname": "Chaetoceros (Hyalochaete) debilis",
    }
    search_returns(worms_http, "Hyalochaete", record)
    new_draft(site, drafter)
    page = add_from_worms(site, "Hyalochaete")
    expect(page.locator("#worms-label")).to_have_value("Chaetoceros_Hyalochaete_debilis")


# --- 7.5 aliases, descriptions, clone ---------------------------------------------------------


def test_edit_aliases_in_static_mode(site, taxonomy, drafter):
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    page.click("text=Expand all")
    menu(site, "box", "aliases")
    assert "saved at once" in page.inner_text("#aliases-dialog")
    page.fill("#alias-input", "L1")
    page.click("#alias-add")
    expect(page.locator("#aliases-dialog .list-group")).to_contain_text("L1")
    assert NodeAlias.objects.get(node_id=ids_by_label("taxonomy")["box"]).added_by == "drafter1"
    assert not Changeset.objects.filter(state="draft").exists()


def test_aliases_unavailable_for_new_nodes(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    page.click("#new-node")
    page.fill("#f-label", "crate")
    page.click("#f-submit")
    site.row("crate").locator(".kebab").click()
    item = page.locator('#node-menu [data-action="aliases"]')
    assert item.get_attribute("title") == "Not published yet"


def test_edit_a_description_in_static_mode(site, taxonomy, drafter):
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    page.click("text=Expand all")
    menu(site, "box", "description")
    page.fill("#description-text", "Cells with a bleb")
    page.click("#description-save")
    expect(page.locator(".toast")).to_contain_text("Description of box saved")
    assert NodeDescription.objects.get().description == "Cells with a bleb"
    assert latest_rev("taxonomy") == 1 and not Changeset.objects.filter(state="draft").exists()


def test_description_of_a_new_node_goes_in_its_add(site, taxonomy, drafter):
    page = new_draft(site, drafter)
    page.click("#new-node")
    page.fill("#f-label", "crate")
    page.click("#f-submit")
    menu(site, "crate", "description")
    assert "written when the draft is published" in page.inner_text("#description-dialog")
    page.fill("#description-text", "Wooden")
    page.click("#description-save")
    assert not NodeDescription.objects.exists()
    assert page.inner_text("#status") == "Draft (unsaved)"


def test_clone_flow(site, taxonomy):
    Organization.objects.create(id="lab_a", name="Lab A")
    owner = make_user("lab_owner", roles={"lab_a": "owner"})
    site.login(owner)
    page = site.open("/trees/taxonomy/")
    page.click("#clone-button")
    expect(page.locator("#clone-org")).to_have_value("lab_a")
    page.fill("#clone-id", "lab_taxonomy")
    page.fill("#clone-title", "Lab taxonomy")
    page.click("#clone-submit")
    expect(page.locator("#status")).to_have_text("Draft (saved)")
    assert "lab_taxonomy" in page.inner_text(".topbar")
    group = page.locator('[data-group="import#1"]')
    expect(group).to_contain_text("7 changes")
    assert page.locator("#tab-edited .crow").count() == 0  # one collapsed group
    draft = Changeset.objects.get(new_tree_id="lab_taxonomy")
    assert (draft.new_tree_org_id, draft.base_rev) == ("lab_a", None)
    expect(site.row("Chromista")).to_be_visible()
