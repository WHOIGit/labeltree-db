"""The setup wizard for a new instance (spec: instance-setup), in Chromium."""

import json

import httpx
import pytest
from django.contrib.auth import get_user_model
from playwright.sync_api import expect

from accounts.models import Organization, OrgMember, Role
from api.tests.conftest import make_user
from core.changesets import latest_rev
from core.models import Changeset, Node, Tree
from worms.models import WormsRecord

pytestmark = pytest.mark.django_db(transaction=True)

STRONG = "plankton-net-1987"


@pytest.fixture
def admin(transactional_db):
    return make_user("admin", superuser=True)


def open_setup(site, admin):
    site.login(admin)
    return site.open("/")  # sent on to /setup/


def with_org(org_id="lab_a", name="Lab A"):
    return Organization.objects.create(id=org_id, name=name)


def step_shown(page, step):
    expect(page.locator(f'#setup-steps [data-step="{step}"]')).to_have_class(
        "badge text-bg-primary"
    )


def at_trees(site, admin):
    with_org()
    page = open_setup(site, admin)
    page.click("#users-continue")
    step_shown(page, "trees")
    return page


def fill_tree(page, tree_id, data):
    page.fill("#tree-id", tree_id)
    page.fill("#tree-title", tree_id.replace("_", " ").capitalize())
    page.fill("#tree-text", data if isinstance(data, str) else json.dumps(data))


SMALL = {"nodes": [{"label": "detritus"}, {"label": "bubble", "children": [{"label": "small"}]}]}


# --- Organization step -------------------------------------------------------------------------


def test_first_organization(site, admin):
    page = open_setup(site, admin)
    assert page.url.endswith("/setup/")
    step_shown(page, "org")
    expect(page.locator("#setup-skip")).to_be_disabled()  # no organization yet
    page.fill("#org-id", "lab_a")
    page.fill("#org-name", "Lab A")
    page.click("#org-create")
    step_shown(page, "users")
    expect(page.locator("#step-users h2")).to_have_text("Users of Lab A")
    assert Organization.objects.get(id="lab_a").name == "Lab A"
    assert site.console.errors == []


def test_existing_organization_id(site, admin):
    with_org()
    with_org("lab_b", "Lab B")  # two: the wizard asks which
    page = open_setup(site, admin)
    step_shown(page, "org")
    page.fill("#org-id", "lab_a")
    page.fill("#org-name", "Another")
    page.click("#org-create")
    expect(page.locator("#org-error")).to_contain_text("Organization lab_a already exists")
    step_shown(page, "org")
    page.click('#existing-orgs [data-org="lab_b"]')
    expect(page.locator("#step-users h2")).to_have_text("Users of Lab B")


def test_resuming_after_creating_an_organization(site, admin):
    with_org()
    page = open_setup(site, admin)
    step_shown(page, "users")
    expect(page.locator("#step-users h2")).to_have_text("Users of Lab A")


# --- Users step --------------------------------------------------------------------------------


def test_adding_a_new_user(site, admin):
    with_org()
    page = open_setup(site, admin)
    page.fill("#user-name", "curator1")
    expect(page.locator("#user-role")).to_have_value("owner")  # no owner yet
    page.click("#user-add")
    expect(page.locator("#new-account")).to_contain_text("curator1 has no account yet")
    page.fill("#user-password", STRONG)
    page.fill("#user-password2", STRONG + "x")
    expect(page.locator("#user-add")).to_be_disabled()  # the passwords differ
    page.fill("#user-password2", STRONG)
    page.click("#user-add")
    expect(page.locator('#setup-members [data-member="curator1"]')).to_contain_text("owner")
    expect(page.locator("#new-account")).to_have_count(0)
    expect(page.locator("#user-role")).to_have_value("drafter")  # the org has an owner now
    user = get_user_model().objects.get(username="curator1")
    assert user.check_password(STRONG)
    assert OrgMember.objects.get(user=user, org_id="lab_a").role == Role.OWNER


def test_adding_an_existing_user(site, admin):
    with_org()
    drafter = make_user("drafter1")
    drafter.set_password("drafter-pw-1987")
    drafter.save()
    page = open_setup(site, admin)
    page.fill("#user-name", "drafter1")
    page.select_option("#user-role", "drafter")
    page.click("#user-add")
    expect(page.locator('#setup-members [data-member="drafter1"]')).to_contain_text("drafter")
    assert page.locator("#user-password").count() == 0  # never asked for a password
    drafter.refresh_from_db()
    assert drafter.check_password("drafter-pw-1987")


def test_weak_initial_password(site, admin):
    with_org()
    page = open_setup(site, admin)
    page.fill("#user-name", "curator1")
    page.click("#user-add")
    page.fill("#user-password", "1234")
    page.fill("#user-password2", "1234")
    page.click("#user-add")
    expect(page.locator("#user-error")).to_contain_text("too short")
    assert not get_user_model().objects.filter(username="curator1").exists()


def test_skipping_users(site, admin):
    with_org()
    page = open_setup(site, admin)
    page.click("#setup-skip")
    step_shown(page, "trees")
    assert not OrgMember.objects.exists()


def test_leaving_users_with_a_username_not_added(site, admin):
    with_org()
    page = open_setup(site, admin)
    page.fill("#user-name", "curator1")
    page.click("#users-continue")
    expect(page.locator("#discard-dialog")).to_contain_text("curator1 hasn't been added")
    page.click("#discard-cancel")
    step_shown(page, "users")
    expect(page.locator("#user-name")).to_have_value("curator1")  # kept

    page.click("#setup-skip")
    expect(page.locator("#discard-dialog")).to_be_visible()
    page.click("#discard-ok")
    step_shown(page, "trees")
    assert not get_user_model().objects.filter(username="curator1").exists()


def test_continue_without_a_typed_username_asks_nothing(site, admin):
    with_org()
    page = open_setup(site, admin)
    page.fill("#user-name", "   ")
    page.click("#users-continue")
    step_shown(page, "trees")
    assert page.locator("#discard-dialog").count() == 0


# --- Trees step --------------------------------------------------------------------------------


def test_importing_a_tree_and_a_second_one(site, admin):
    page = at_trees(site, admin)
    fill_tree(page, "lab_tags", SMALL)
    page.click("#tree-import")
    expect(page.locator('#imported-trees [data-tree="lab_tags"]')).to_contain_text("revision 1")
    tree = Tree.objects.get(id="lab_tags")
    assert tree.org_id == "lab_a" and latest_rev("lab_tags") == 1
    assert Node.objects.filter(tree=tree).count() == 3
    expect(page.locator("#tree-text")).to_have_value("")  # ready for another

    fill_tree(page, "lab_more", {"nodes": [{"label": "other"}]})
    page.click("#tree-import")
    expect(page.locator("#imported-trees li")).to_have_count(2)
    assert set(Tree.objects.values_list("id", flat=True)) == {"lab_tags", "lab_more"}
    page.click("#setup-done")
    page.wait_for_url("**/trees/lab_tags/")
    assert site.console.errors == []


def test_loading_a_file(site, admin, tmp_path):
    page = at_trees(site, admin)
    path = tmp_path / "lab_tags.json"
    path.write_text(json.dumps(SMALL))
    page.set_input_files("#tree-file", str(path))
    expect(page.locator("#tree-text")).to_have_value(json.dumps(SMALL))
    expect(page.locator("#tree-id")).to_have_value("lab_tags")
    page.fill("#tree-text", json.dumps({"nodes": [{"label": "edited"}]}))  # editable
    page.click("#tree-import")
    expect(page.locator('#imported-trees [data-tree="lab_tags"]')).to_be_visible()
    assert Node.objects.get(tree_id="lab_tags").versions.get().label == "edited"


def test_malformed_file(site, admin):
    page = at_trees(site, admin)
    fill_tree(page, "lab_tags", {"nodes": [{"label": "a"}, {"label": "b", "children": [{}]}]})
    page.click("#tree-import")
    expect(page.locator("#tree-errors")).to_contain_text("nodes[1].children[0]")
    fill_tree(page, "lab_tags", "{not json")
    page.click("#tree-import")
    expect(page.locator("#tree-errors")).to_contain_text("Not valid JSON")
    assert not Changeset.objects.exists() and not Tree.objects.exists()


def test_duplicate_labels(site, admin):
    page = at_trees(site, admin)
    fill_tree(page, "lab_tags", {"nodes": [{"label": "detritus"}, {"label": "detritus"}]})
    page.click("#tree-import")
    expect(page.locator("#tree-errors")).to_contain_text("detritus")
    assert not Changeset.objects.exists() and not Tree.objects.exists()


def test_taken_tree_id(site, admin):
    page = at_trees(site, admin)
    fill_tree(page, "lab_tags", SMALL)
    page.click("#tree-import")
    expect(page.locator("#imported-trees li")).to_have_count(1)
    fill_tree(page, "lab_tags", {"nodes": [{"label": "other"}]})
    page.click("#tree-import")
    expect(page.locator("#tree-errors")).to_contain_text("Tree lab_tags already exists")
    assert Changeset.objects.count() == 1


def test_import_with_aphia_ids(site, admin, worms_http):
    page = at_trees(site, admin)
    data = {"nodes": [{"label": "Chaetoceros", "aphia_id": 148985}]}
    fill_tree(page, "lab_taxonomy", data)
    page.click("#tree-import")
    expect(page.locator('#imported-trees [data-tree="lab_taxonomy"]')).to_be_visible(timeout=20000)
    assert WormsRecord.objects.filter(aphia_id=148985).exists()
    assert "/AphiaRecordByAphiaID/148985" in worms_http.calls


def test_worms_unreachable(site, admin, worms_http):
    def down(request):
        raise httpx.ConnectError("down")

    worms_http.override({"/AphiaRecordByAphiaID/110153": down})
    page = at_trees(site, admin)
    fill_tree(page, "lab_taxonomy", {"nodes": [{"label": "Heterocapsa", "aphia_id": 110153}]})
    page.click("#tree-import")
    failed = page.wait_for_selector("#fetch-failed", timeout=20000)
    assert "110153: worms_unreachable" in failed.inner_text()
    assert not Tree.objects.exists()
    page.click("#fetch-failed >> text=Proceed anyway")
    expect(page.locator('#imported-trees [data-tree="lab_taxonomy"]')).to_be_visible(timeout=20000)
    assert latest_rev("lab_taxonomy") == 1


def test_publish_again_after_a_failed_publish(site, admin):
    page = at_trees(site, admin)
    page.route(
        "**/api/v1/changesets/*/publish",
        lambda route: route.fulfill(status=502, json={"detail": "bad gateway"}),
    )
    fill_tree(page, "lab_tags", SMALL)
    page.click("#tree-import")
    expect(page.locator("#tree-errors")).to_contain_text("The draft is saved as #")
    expect(page.locator("#tree-import")).to_have_text("Publish again")
    page.unroute("**/api/v1/changesets/*/publish")
    page.click("#tree-import")
    expect(page.locator('#imported-trees [data-tree="lab_tags"]')).to_be_visible()
    assert Changeset.objects.count() == 1  # the same draft, published


def test_leaving_trees_with_a_tree_not_imported(site, admin):
    page = at_trees(site, admin)
    fill_tree(page, "lab_tags", SMALL)
    page.click("#setup-skip")
    dialog = page.locator("#discard-dialog")
    expect(dialog).to_contain_text("lab_tags hasn't been imported")
    page.click("#discard-cancel")
    expect(page.locator("#tree-id")).to_have_value("lab_tags")  # kept
    page.click("#tree-import")
    expect(page.locator("#imported-trees li")).to_have_count(1)

    fill_tree(page, "lab_more", {"nodes": [{"label": "other"}]})
    page.click("#setup-done")
    expect(dialog).to_contain_text("lab_more hasn't been imported")
    page.click("#discard-ok")
    page.wait_for_url("**/trees/lab_tags/")
    assert not Tree.objects.filter(id="lab_more").exists()


def test_leaving_trees_with_an_unpublished_draft(site, admin):
    page = at_trees(site, admin)
    page.route(
        "**/api/v1/changesets/*/publish",
        lambda route: route.fulfill(status=502, json={"detail": "bad gateway"}),
    )
    fill_tree(page, "lab_tags", SMALL)
    page.click("#tree-import")
    expect(page.locator("#tree-import")).to_have_text("Publish again")
    page.click("#setup-skip")
    draft = Changeset.objects.get()
    expect(page.locator("#discard-dialog")).to_contain_text(
        f"lab_tags is saved as draft #{draft.pk} but not published"
    )
    page.click("#discard-ok")
    page.wait_for_url("**/orgs/lab_a/")
    assert Changeset.objects.get().state == "draft"


def test_skipping_trees(site, admin):
    page = at_trees(site, admin)
    page.click("#setup-skip")
    page.wait_for_url("**/orgs/lab_a/")
