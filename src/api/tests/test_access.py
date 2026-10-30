"""Authentication, organizations and roles (spec: access-control)."""

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from accounts.models import ApiToken, Organization, OrgMember, Role
from api.api import api
from core.changesets import NewTree, create_changeset
from core.models import NodeAlias
from core.tests.helpers import add, edit, publish_new_tree
from worms import sync

from .conftest import call, logged_in, make_user

pytestmark = pytest.mark.django_db

# Routes that need no login. A new route needs one unless it is added here.
ANONYMOUS_ROUTES = {
    "GET /health",
    "GET /orgs",
    "GET /orgs/{org_id}",
    "GET /nodes/{node_id}",
    "GET /nodes/{node_id}/ancestors",
    "GET /nodes/{node_id}/descendants",
    "GET /nodes/{node_id}/versions",
    "GET /nodes/{node_id}/versions/{version}",
    "GET /nodes/{node_id}/warning_history",
    "GET /nodes/{node_id}/aliases",
    "GET /nodes/{node_id}/description",
    "GET /trees",
    "GET /trees/{tree_id}",
    "GET /trees/{tree_id}/revisions",
    "GET /trees/{tree_id}/revisions/{rev}/changes",
    "GET /trees/{tree_id}/diff",
    "GET /trees/{tree_id}/nodes_as_tree",
    "GET /trees/{tree_id}/export",
    "GET /trees/{tree_id}/export_flat",
    "GET /trees/{tree_id}/nodes/{label}",
    "GET /trees/{tree_id}/nodes",
    "GET /trees/{tree_id}/search",
    "GET /worms/warnings",
}

SAMPLE_PARAMS = {
    "tree_id": "taxonomy", "node_id": "1", "version": "1", "rev": "1", "label": "other",
    "username": "someone", "org_id": "amplify", "job_id": "j1", "aphia_id": "148985",
    "a": "148985", "b": "149122", "cs": "1", "alias_id": "1",
}  # fmt: skip


def routes() -> dict[str, bool]:
    """'METHOD /path' -> whether the route needs authentication.

    Walks the API's bound routers rather than the OpenAPI schema, so routes
    hidden from the docs (include_in_schema=False) are checked too.
    """
    found = {}
    for router in api._get_bound_routers():
        for path, view in router.path_operations.items():
            for operation in view.operations:
                for method in operation.methods:
                    route = f"{method} {router.prefix}{path}".rstrip("/") or "/"
                    found[route] = bool(operation.auth_callbacks)
    return found


def test_anonymous_routes_are_exactly_the_listed_ones():
    anonymous = {route for route, needs_auth in routes().items() if not needs_auth}
    assert anonymous == ANONYMOUS_ROUTES


def test_every_other_route_answers_401_without_credentials(taxonomy, worms_http):
    worms_http.calls.clear()  # publishing the fixture tree fetched its records
    anonymous = Client()
    for route, needs_auth in routes().items():
        if not needs_auth:
            continue
        method, path = route.split(" ")
        url = re.sub(r"\{(\w+)\}", lambda m: SAMPLE_PARAMS[m.group(1)], path)
        status, body = call(anonymous, method.lower(), url, None if method == "GET" else {})
        assert (status, body["error"]) == (401, "unauthorized"), route
    assert worms_http.calls == []


# --- Anonymous reads -----------------------------------------------------------------


def test_anonymous_read(taxonomy):
    status, body = call(Client(), "get", "/trees")
    assert status == 200 and [t["id"] for t in body["trees"]] == ["taxonomy"]


def test_anonymous_worms_search(worms_http):
    status, _ = call(Client(), "get", "/worms/search?name=Chaetoceros")
    assert status == 401 and worms_http.calls == []


# --- Sessions and tokens -----------------------------------------------------------------


def token_client(key):
    """A client that enforces CSRF, as a browser would; tokens aren't CSRF-checked."""
    client = Client(enforce_csrf_checks=True)
    return lambda method, path, body=None: call(
        client, method, path, body, Authorization=f"Token {key}"
    )


def test_script_token(taxonomy, token_for):
    user = make_user("script1", roles={"amplify": "owner"})
    key = token_for(user)
    as_script = token_client(key)
    assert as_script("get", "/orgs/amplify/members")[0] == 200
    status, body = as_script("put", "/orgs/amplify/members/script1", {"role": "owner"})
    assert status == 200 and body["role"] == "owner"
    assert ApiToken.objects.get(user=user).last_used_at is not None


def test_revoked_token(taxonomy, token_for):
    user = make_user("script1", roles={"amplify": "owner"})
    key = token_for(user)
    ApiToken.objects.update(revoked_at="2026-01-01T00:00Z")
    status, body = token_client(key)("get", "/orgs/amplify/members")
    assert (status, body["error"]) == (401, "unauthorized")


def test_unknown_or_malformed_token(taxonomy):
    assert token_client("nope")("get", "/orgs/amplify/members")[0] == 401
    client = Client()
    assert call(client, "get", "/orgs/amplify/members", Authorization="Bearer x")[0] == 401


def test_token_key_is_stored_hashed(token_for):
    user = make_user("script1")
    key = token_for(user)
    assert not ApiToken.objects.filter(key_hash=key).exists()


def test_session_writes_are_csrf_checked(taxonomy):
    owner = make_user("owner1", roles={"amplify": "owner"})
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    status, body = call(client, "put", "/orgs/amplify/members/owner1", {"role": "owner"})
    assert (status, body["error"]) == (403, "forbidden")
    assert "CSRF" in body["detail"]


# --- Role matrix -----------------------------------------------------------------------


@pytest.fixture
def fake_jobs(monkeypatch):
    """Jobs don't run; returns who started them. Job j1 is a sync on taxonomy."""
    started = []

    def start_job(kind, *, tree=None, org=None, started_by, aphia_ids=None):
        started.append(started_by)
        return {"kind": kind, "tree": tree}

    monkeypatch.setattr(sync, "start_job", start_job)
    monkeypatch.setattr(
        sync, "get_job",
        lambda job_id: job_id and {"id": job_id, "tree": "taxonomy", "state": "finished"},
    )  # fmt: skip
    return started


LADDER = ["none", "reader", "drafter", "approver", "owner", "superuser"]

# (method, path, body, minimum role). Later endpoints add rows here.
STRONG = "plankton-net-1987"  # passes the site's password rules

MATRIX = [
    ("post", "/orgs", {"id": "lab_x", "name": "Lab X"}, "superuser"),
    ("post", "/users", {"username": "newbie", "password": STRONG}, "superuser"),
    ("get", "/orgs/amplify/members", None, "reader"),
    ("put", "/orgs/amplify/members/target", {"role": "reader"}, "owner"),
    ("post", "/orgs/amplify/members", {"username": "target", "role": "drafter"}, "owner"),
    ("delete", "/orgs/amplify/members/target", None, "owner"),
    ("get", "/worms/jobs?tree=taxonomy", None, "reader"),
    ("get", "/worms/jobs/j1", None, "reader"),
    ("post", "/worms/jobs", {"kind": "fetch", "org": "amplify", "aphia_ids": [1]}, "drafter"),
    ("post", "/worms/jobs", {"kind": "sync_new", "tree": "taxonomy"}, "drafter"),
    ("post", "/worms/jobs", {"kind": "sync_tree", "tree": "taxonomy"}, "drafter"),
    ("post", "/worms/jobs", {"kind": "sync_all"}, "superuser"),
    ("get", "/worms/jobs", None, "none"),
    ("get", "/worms/148985", None, "none"),
    ("get", "/worms/148985/lineage", None, "none"),
    ("post", "/changesets/validate", {"tree": "taxonomy", "base_rev": 1, "changes": []}, "drafter"),
    (
        "post",
        "/changesets/validate",
        {"new_tree": {"id": "t2", "title": "T", "org": "amplify"}, "changes": []},
        "owner",
    ),
    ("post", "/changesets", {"tree": "taxonomy", "base_rev": 1, "changes": []}, "drafter"),
    ("get", "/changesets/{draft}", None, "reader"),
    ("put", "/changesets/{draft}", {"notes": "x"}, "drafter"),
    ("post", "/changesets/{draft}/publish", None, "approver"),
    ("delete", "/changesets/{draft}", None, "drafter"),
    (
        "post",
        "/changesets",
        {"new_tree": {"id": "t2", "title": "T", "org": "amplify"}, "changes": []},
        "owner",
    ),
    ("get", "/changesets/{new_tree_draft}", None, "reader"),
    ("put", "/changesets/{new_tree_draft}", {"notes": "x"}, "owner"),
    ("post", "/changesets/{new_tree_draft}/publish", None, "owner"),
    ("delete", "/changesets/{new_tree_draft}", None, "owner"),
    ("post", "/nodes/6/aliases", {"alias": "x"}, "drafter"),
    ("delete", "/nodes/5/aliases/{alias}", None, "drafter"),
    ("put", "/nodes/6/description", {"description": "x"}, "drafter"),
]


def user_with(level: str, org_id="amplify"):
    if level == "superuser":
        return make_user("actor", superuser=True)
    return make_user("actor", roles={} if level == "none" else {org_id: level})


@pytest.mark.parametrize("level", LADDER)
@pytest.mark.parametrize("method,path,body,minimum", MATRIX)
def test_role_matrix(level, method, path, body, minimum, taxonomy, fake_jobs):
    make_user("target", roles={"amplify": "reader"})
    make_user("other_owner", roles={"amplify": "owner"})
    draft = create_changeset(author="a", changes=[edit(6, label="x")], tree=taxonomy, base_rev=1)
    new_tree_draft = create_changeset(
        author="a", changes=[add("new:1", "a")], new_tree=NewTree("t3", "T", "amplify")
    )
    alias = NodeAlias.objects.get(node_id=5)
    path = path.format(draft=draft.pk, new_tree_draft=new_tree_draft.pk, alias=alias.pk)
    client = logged_in(user_with(level))
    status, _ = call(client, method, path, body)
    allowed = LADDER.index(level) >= LADDER.index(minimum)
    assert (status != 403) == allowed, (status, level)
    assert status != 401


def sync_tree(tree):
    return {"kind": "sync_tree", "tree": tree}


def test_member_of_another_organization(taxonomy, fake_jobs):
    publish_new_tree("lab_tree", add("new:1", "a"), org_id="lab_a")
    client = logged_in(make_user("actor", roles={"lab_a": "drafter"}))
    assert call(client, "post", "/worms/jobs", sync_tree("taxonomy"))[0] == 403
    assert call(client, "post", "/worms/jobs", sync_tree("lab_tree"))[0] == 202


def test_new_tree_in_the_organization(taxonomy, fake_jobs):
    client = logged_in(make_user("actor", roles={"amplify": "drafter"}))
    publish_new_tree("NES2022_tags", add("new:1", "a"))  # published after they joined
    assert call(client, "post", "/worms/jobs", sync_tree("NES2022_tags"))[0] == 202


# --- Organizations and members ------------------------------------------------------------------


def test_trees_by_organization(taxonomy):
    publish_new_tree("lab_tree", add("new:1", "a"), org_id="lab_a")
    status, body = call(Client(), "get", "/orgs")
    assert status == 200 and body["orgs"] == [
        {"id": "amplify", "name": "AMPLIfy", "trees": ["taxonomy"]},
        {"id": "lab_a", "name": "lab_a", "trees": ["lab_tree"]},
    ]
    assert call(Client(), "get", "/orgs/lab_a")[1]["trees"] == ["lab_tree"]
    assert call(Client(), "get", "/orgs/nope")[0] == 404
    trees = call(Client(), "get", "/trees")[1]["trees"]
    assert {t["id"]: t["org"] for t in trees} == {"lab_tree": "lab_a", "taxonomy": "amplify"}


@pytest.fixture
def owner(taxonomy):
    return make_user("owner1", roles={"amplify": "owner"})


def role_on(username, org_id="amplify"):
    row = OrgMember.objects.filter(user__username=username, org_id=org_id).first()
    return Role(row.role).label if row else None


def test_list_members(owner):
    make_user("drafter1", roles={"amplify": "drafter"})
    reader = logged_in(make_user("reader1", roles={"amplify": "reader"}))
    status, body = call(reader, "get", "/orgs/amplify/members")
    assert status == 200
    assert body["members"] == [
        {"username": "owner1", "role": "owner"},
        {"username": "drafter1", "role": "drafter"},
        {"username": "reader1", "role": "reader"},
    ]


def test_owner_raises_a_member(owner, taxonomy):
    make_user("drafter1", roles={"amplify": "drafter"})
    status, body = call(logged_in(owner), "put", "/orgs/amplify/members/drafter1",
                        {"role": "approver"})  # fmt: skip
    assert status == 200 and body == {"org": "amplify", "username": "drafter1",
                                      "role": "approver"}  # fmt: skip
    assert role_on("drafter1") == "approver"


def test_setting_the_role_of_a_non_member(owner):
    make_user("newcomer")
    status, _ = call(logged_in(owner), "put", "/orgs/amplify/members/newcomer", {"role": "drafter"})
    assert status == 200 and role_on("newcomer") == "drafter"


def test_co_owner(owner):
    make_user("drafter1", roles={"amplify": "drafter"})
    call(logged_in(owner), "put", "/orgs/amplify/members/drafter1", {"role": "owner"})
    assert OrgMember.objects.filter(org_id="amplify", role=Role.OWNER).count() == 2


def test_approver_manages_members(owner):
    approver = make_user("approver1", roles={"amplify": "approver"})
    make_user("drafter1", roles={"amplify": "drafter"})
    status, _ = call(logged_in(approver), "put", "/orgs/amplify/members/drafter1",
                     {"role": "approver"})  # fmt: skip
    assert status == 403 and role_on("drafter1") == "drafter"


def test_last_owner_steps_down(owner):
    status, body = call(logged_in(owner), "put", "/orgs/amplify/members/owner1",
                        {"role": "approver"})  # fmt: skip
    assert (status, body["error"]) == (409, "last_owner")
    assert call(logged_in(owner), "delete", "/orgs/amplify/members/owner1")[0] == 409
    assert role_on("owner1") == "owner"


def test_owner_steps_down_when_another_remains(owner):
    make_user("owner2", roles={"amplify": "owner"})
    assert call(logged_in(owner), "delete", "/orgs/amplify/members/owner1")[0] == 204
    assert role_on("owner1") is None


def test_site_admin_may_remove_the_last_owner(owner):
    admin = logged_in(make_user("admin", superuser=True))
    assert call(admin, "delete", "/orgs/amplify/members/owner1")[0] == 204


def test_remove_member(owner):
    make_user("drafter1", roles={"amplify": "drafter"})
    status, _ = call(logged_in(owner), "delete", "/orgs/amplify/members/drafter1")
    assert status == 204 and role_on("drafter1") is None
    assert call(logged_in(owner), "delete", "/orgs/amplify/members/drafter1")[0] == 404


def test_member_errors(owner):
    client = logged_in(owner)
    assert call(client, "put", "/orgs/amplify/members/nobody", {"role": "reader"})[0] == 404
    make_user("drafter1")
    status, body = call(client, "put", "/orgs/amplify/members/drafter1", {"role": "admin"})
    assert (status, body["error"]) == (400, "bad_parameter")
    assert call(client, "get", "/orgs/nope/members")[0] == 404


def test_non_member_cannot_list_members(owner):
    assert call(logged_in(make_user("outsider")), "get", "/orgs/amplify/members")[0] == 403


# --- Creating trees -------------------------------------------------------------------------


def test_new_tree_belongs_to_its_organization():
    publish_new_tree("lab_tree", add("new:1", "a"), org_id="lab_a")
    assert role_on("nobody", "lab_a") is None
    assert Organization.objects.get(id="lab_a").trees.get().id == "lab_tree"


# --- Recorded identities --------------------------------------------------------------------


def test_job_started_by_token_user(taxonomy, token_for, fake_jobs):
    key = token_for(make_user("script1", roles={"amplify": "drafter"}))
    assert token_client(key)("post", "/worms/jobs", sync_tree("taxonomy"))[0] == 202
    assert fake_jobs == ["script1"]


def test_add_a_member(owner):
    make_user("newcomer")
    client = logged_in(owner)
    status, body = call(
        client, "post", "/orgs/amplify/members", {"username": "newcomer", "role": "drafter"}
    )
    assert (status, body["role"]) == (201, "drafter") and role_on("newcomer") == "drafter"


def test_adding_an_existing_member_is_refused(owner):
    make_user("approver1", roles={"amplify": "approver"})
    status, body = call(logged_in(owner), "post", "/orgs/amplify/members",
                        {"username": "approver1", "role": "reader"})  # fmt: skip
    assert (status, body["error"]) == (409, "already_member")
    assert role_on("approver1") == "approver"


def test_add_member_errors(owner):
    client = logged_in(owner)
    assert (
        call(client, "post", "/orgs/amplify/members", {"username": "nobody", "role": "reader"})[0]
        == 404
    )
    make_user("newcomer")
    body = {"username": "newcomer", "role": "admin"}
    assert call(client, "post", "/orgs/amplify/members", body)[0] == 400


# --- Creating organizations and users (site admins) ------------------------------------------


def logs_in(username, password):
    """Whether the login page accepts these credentials."""
    response = Client().post("/login/", {"username": username, "password": password})
    return response.status_code == 302


def test_site_admin_creates_an_organization(taxonomy):
    admin = logged_in(make_user("admin", superuser=True))
    status, body = call(admin, "post", "/orgs", {"id": "lab_a", "name": " Lab A "})
    assert (status, body) == (201, {"id": "lab_a", "name": "Lab A"})
    orgs = call(Client(), "get", "/orgs")[1]["orgs"]
    assert {"id": "lab_a", "name": "Lab A", "trees": []} in orgs
    assert not OrgMember.objects.filter(org_id="lab_a").exists()


def test_owner_cannot_create_an_organization(owner):
    status, _ = call(logged_in(owner), "post", "/orgs", {"id": "lab_a", "name": "Lab A"})
    assert status == 403 and not Organization.objects.filter(id="lab_a").exists()


def test_organization_id_taken(taxonomy):
    admin = logged_in(make_user("admin", superuser=True))
    status, body = call(admin, "post", "/orgs", {"id": "amplify", "name": "Other"})
    assert (status, body["error"]) == (409, "org_exists")
    assert Organization.objects.get(id="amplify").name == "AMPLIfy"


@pytest.mark.parametrize(
    "body",
    [
        {"id": "lab a", "name": "Lab A"},
        {"id": "lab_a", "name": "  "},
        {"id": "x" * 101, "name": "X"},
    ],
)
def test_organization_errors(body):
    admin = logged_in(make_user("admin", superuser=True))
    status, answer = call(admin, "post", "/orgs", body)
    assert (status, answer["error"]) == (400, "bad_parameter")
    assert not Organization.objects.exists()


def test_site_admin_creates_a_user():
    admin = logged_in(make_user("admin", superuser=True))
    status, body = call(admin, "post", "/users", {"username": "curator1", "password": STRONG})
    assert (status, body) == (201, {"username": "curator1"})
    assert STRONG not in str(body)
    user = get_user_model().objects.get(username="curator1")
    assert not user.is_superuser and not OrgMember.objects.filter(user=user).exists()
    assert logs_in("curator1", STRONG)


def test_username_taken():
    existing = make_user("curator1")
    existing.set_password("old-password-1987")
    existing.save()
    admin = logged_in(make_user("admin", superuser=True))
    status, body = call(admin, "post", "/users", {"username": "curator1", "password": STRONG})
    assert (status, body["error"]) == (409, "user_exists")
    existing.refresh_from_db()
    assert existing.check_password("old-password-1987")


def test_weak_password():
    admin = logged_in(make_user("admin", superuser=True))
    status, body = call(admin, "post", "/users", {"username": "curator1", "password": "1234"})
    assert (status, body["error"]) == (400, "bad_parameter")
    assert "too short" in body["detail"] and "entirely numeric" in body["detail"]
    assert not get_user_model().objects.filter(username="curator1").exists()


def test_bad_username():
    admin = logged_in(make_user("admin", superuser=True))
    status, body = call(admin, "post", "/users", {"username": "cu rator", "password": STRONG})
    assert (status, body["error"]) == (400, "bad_parameter")


def test_drafter_cannot_create_a_user(taxonomy):
    drafter = logged_in(make_user("drafter1", roles={"amplify": "drafter"}))
    assert call(drafter, "post", "/users", {"username": "x1", "password": STRONG})[0] == 403


def test_readme_setup_through_the_api(token_for):
    """The README's curl sequence: organization, user, owner, with a site admin's token."""
    script = token_client(token_for(make_user("admin", superuser=True)))
    assert script("post", "/orgs", {"id": "lab_a", "name": "Lab A"})[0] == 201
    assert script("post", "/users", {"username": "curator1", "password": STRONG})[0] == 201
    assert script("put", "/orgs/lab_a/members/curator1", {"role": "owner"})[0] == 200
    assert role_on("curator1", "lab_a") == "owner"


def test_required_query_parameters_are_in_the_schema():
    """Parameters an endpoint refuses to do without are marked required in OpenAPI."""
    paths = api.get_openapi_schema()["paths"]
    required = {
        (path, p["name"])
        for path, ops in paths.items()
        for p in ops.get("get", {}).get("parameters", [])
        if p["in"] == "query" and p.get("required")
    }
    assert {
        ("/api/v1/worms/warnings", "tree"),
        ("/api/v1/worms/search", "name"),
        ("/api/v1/trees/{tree_id}/diff", "from"),
        ("/api/v1/trees/{tree_id}/diff", "to"),
    } <= required
