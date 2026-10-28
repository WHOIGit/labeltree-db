import json

import pytest
from django.db import connection
from django.test import Client

from accounts.models import ApiToken, OrgMember, Role, User
from core.importer import expand_import
from core.models import Tree
from core.tests.helpers import TAGS, add, ids_by_label, org, publish_new_tree


@pytest.fixture(autouse=True)
def node_ids_from_1(db):
    """Node ids come from a sequence, which test rollbacks don't reset."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT setval('core_node_id_seq', 1, false)")


@pytest.fixture
def get(client):
    """GET a URL under /api/v1 and return (status, json-or-text, response)."""

    def _get(path, **headers):
        response = client.get(f"/api/v1{path}", headers=headers)
        if response.status_code == 304:
            return 304, None, response
        if response["Content-Type"].startswith("application/json"):
            return response.status_code, response.json(), response
        return response.status_code, response.content.decode(), response

    return _get


@pytest.fixture
def tags():
    publish_new_tree("NES2022_tags", *expand_import(json.loads(TAGS.read_text())))
    return Tree.objects.get(id="NES2022_tags")


@pytest.fixture
def taxonomy():
    """Revision 1 of a small taxonomy: Chromista > Bacillariophyceae > Chaetocerotaceae >
    Chaetoceros (148985) > Chaetoceros_didymus (149122); plus top-level `other`."""
    publish_new_tree(
        "taxonomy",
        add("new:1", "Chromista"),
        add("new:2", "Bacillariophyceae", parent="new:1"),
        add("new:3", "Chaetocerotaceae", parent="new:2"),
        add("new:4", "Chaetoceros", parent="new:3", aphia_id=148985),
        add("new:5", "Chaetoceros_didymus", parent="new:4", aphia_id=149122,
            aliases=["Chaetoceros didymus"]),
        add("new:6", "other"),
    )  # fmt: skip
    return Tree.objects.get(id="taxonomy")


@pytest.fixture
def ids():
    return ids_by_label


# --- Users and roles ---------------------------------------------------------------


def make_user(username, *, roles=None, superuser=False) -> User:
    """A user with `roles` {org_id: "drafter", ...}; missing organizations are created."""
    user = User.objects.create_user(username, is_superuser=superuser)
    for org_id, role in (roles or {}).items():
        OrgMember.objects.create(user=user, org_id=org(org_id), role=Role.named(role))
    return user


def logged_in(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def call(client, method, path, body=None, **headers):
    """Send a request under /api/v1; returns (status, json-or-None)."""
    kwargs = {"headers": headers}
    if body is not None:
        kwargs |= {"data": json.dumps(body), "content_type": "application/json"}
    response = getattr(client, method)(f"/api/v1{path}", **kwargs)
    is_json = response.get("Content-Type", "").startswith("application/json")
    return response.status_code, response.json() if is_json else None


@pytest.fixture
def user_factory(db):
    return make_user


@pytest.fixture
def as_user():
    """as_user(user) -> a function (method, path, body=None) -> (status, json)."""

    def _as(user):
        client = logged_in(user) if user is not None else Client()
        return lambda method, path, body=None, **headers: call(
            client, method, path, body, **headers
        )

    return _as


@pytest.fixture
def token_for():
    def _token(user, name="script"):
        return ApiToken.issue(user, name)[1]

    return _token
