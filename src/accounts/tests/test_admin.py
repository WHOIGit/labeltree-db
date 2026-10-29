"""Site admins issue tokens and repair memberships in Django admin (README steps)."""

import re

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import ApiToken, Organization, OrgMember, Role, User
from core.models import Tree
from core.tests.helpers import add, publish_new_tree

pytestmark = pytest.mark.django_db


@pytest.fixture
def tree():
    publish_new_tree("taxonomy", add("new:1", "a"))
    return "taxonomy"


def test_issue_a_token(admin_client, tree):
    script_user = User.objects.create_user("script1")
    response = admin_client.post(
        reverse("admin:accounts_apitoken_add"),
        {"user": script_user.pk, "name": "nightly import"},
        follow=True,
    )
    key = re.search(r"Token key for script1: (\S+)", response.content.decode()).group(1)
    token = ApiToken.objects.get(user=script_user)
    assert token.key_hash != key and ApiToken.lookup(key) == token

    # the key is not shown again
    page = admin_client.get(reverse("admin:accounts_apitoken_change", args=[token.pk]))
    assert key not in page.content.decode()

    # and it works against the API
    response = Client().get("/api/v1/worms/search?name=", headers={"Authorization": f"Token {key}"})
    assert response.status_code == 400  # authenticated; the empty name is refused


def test_revoke_tokens(admin_client):
    token, key = ApiToken.issue(User.objects.create_user("script1"), "x")
    admin_client.post(
        reverse("admin:accounts_apitoken_changelist"),
        {"action": "revoke", "_selected_action": [token.pk]},
    )
    assert ApiToken.lookup(key) is None


def test_create_an_organization_and_its_owner(admin_client):
    user = User.objects.create_user("curator1")
    admin_client.post(
        reverse("admin:accounts_organization_add"),
        {
            "id": "lab_a", "name": "Lab A",
            "members-TOTAL_FORMS": 0, "members-INITIAL_FORMS": 0,
        },
    )  # fmt: skip
    assert Organization.objects.get(id="lab_a").name == "Lab A"
    admin_client.post(
        reverse("admin:accounts_orgmember_add"),
        {"user": user.pk, "org": "lab_a", "role": Role.OWNER},
    )
    assert OrgMember.objects.get(user=user, org_id="lab_a").role == Role.OWNER
    assert admin_client.get(reverse("admin:accounts_orgmember_changelist")).status_code == 200


def test_members_and_tokens_pick_users_by_username(admin_client):
    User.objects.create_user("curator1")
    User.objects.create_user("drafter1")
    for page in ["admin:accounts_orgmember_add", "admin:accounts_apitoken_add"]:
        assert "admin-autocomplete" in admin_client.get(reverse(page)).content.decode()
    found = admin_client.get(
        reverse("admin:autocomplete"),
        {"term": "cura", "app_label": "accounts", "model_name": "orgmember", "field_name": "user"},
    ).json()
    assert [r["text"] for r in found["results"]] == ["curator1"]


def test_move_a_tree_to_another_organization(admin_client, tree):
    Organization.objects.create(id="lab_a", name="Lab A")
    url = reverse("admin:core_tree_change", args=[tree])
    assert admin_client.get(url).status_code == 200
    admin_client.post(url, {"org": "lab_a"})
    moved = Tree.objects.get(id=tree)
    assert (moved.org_id, moved.title) == ("lab_a", tree)


def test_only_site_admins_move_trees(client, tree):
    staff = User.objects.create_user("staff1", is_staff=True)
    client.force_login(staff)
    url = reverse("admin:core_tree_change", args=[tree])
    client.post(url, {"org": "amplify"})
    assert Tree.objects.get(id=tree).org_id == "amplify"
    assert client.get(url).status_code in (302, 403)
