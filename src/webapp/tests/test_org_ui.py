"""The organization page and the user's own page (spec: webapp)."""

import pytest
from playwright.sync_api import expect

from accounts.models import OrgMember, Role
from api.tests.conftest import make_user

pytestmark = pytest.mark.django_db(transaction=True)


def test_owner_adds_a_drafter(site, taxonomy):
    owner = make_user("owner1", roles={"amplify": "owner"})
    make_user("curator2")
    site.login(owner)
    page = site.open("/orgs/amplify/")
    assert "taxonomy" in page.inner_text("#org-trees")
    assert "applies to every tree" in page.inner_text("#members")
    page.fill('[name="new-user"]', "curator2")
    page.select_option('[name="new-role"]', "drafter")
    page.click("text=Add member")
    expect(page.locator('[data-member="curator2"] select')).to_have_value("drafter")
    assert OrgMember.objects.get(user__username="curator2").role == Role.DRAFTER
    assert site.console.errors == []


def test_last_owner(site, taxonomy):
    owner = make_user("owner1", roles={"amplify": "owner"})
    site.login(owner)
    page = site.open("/orgs/amplify/")
    page.select_option('[data-member="owner1"] select', "approver")
    expect(page.locator("#members .alert-danger")).to_contain_text(
        "The organization needs an owner"
    )
    expect(page.locator('[data-member="owner1"] select')).to_have_value("owner")


def test_members_see_but_cannot_change(site, taxonomy):
    make_user("owner1", roles={"amplify": "owner"})
    site.login(make_user("reader1", roles={"amplify": "reader"}))
    page = site.open("/orgs/amplify/")
    expect(page.locator('[data-member="owner1"]')).to_contain_text("owner")
    assert page.locator("#members select").count() == 0


def test_my_page(site, taxonomy):
    site.login(make_user("curator1", roles={"amplify": "drafter"}))
    page = site.open("/me/")
    assert "AMPLIfy" in page.inner_text("#my-roles") and "drafter" in page.inner_text("#my-roles")
