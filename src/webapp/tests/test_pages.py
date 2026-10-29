"""Server-rendered pages (spec: webapp), with Django's test client."""

import pytest
from django.test import Client

from api.tests.conftest import make_user
from core.changesets import create_changeset
from core.models import Tree
from core.tests.helpers import add, deprecate, edit, ids_by_label, move, publish, publish_new_tree
from worms.warnings import record_warnings

pytestmark = pytest.mark.django_db


@pytest.fixture
def tree():
    publish_new_tree(
        "taxonomy",
        add("new:1", "Chromista", aphia_id=7),
        add("new:2", "Chaetoceros", parent="new:1", aphia_id=148985),
        add("new:3", "box"),
    )
    return Tree.objects.get(id="taxonomy")


def logged_in(user):
    client = Client()
    client.force_login(user)
    return client


# --- 5.1 shell -------------------------------------------------------------------------


def test_anonymous_tree_page(tree):
    response = Client().get("/trees/taxonomy/")
    assert response.status_code == 200
    assert b"Log in to edit" in response.content


def test_home_redirects_to_a_tree(tree):
    assert Client().get("/")["Location"] == "/trees/taxonomy/"


@pytest.mark.parametrize(
    "path", ["/me/", "/trees/taxonomy/drafts/", "/changesets/1/", "/changesets/1/edit/"]
)
def test_login_only_pages_redirect(tree, path):
    response = Client().get(path)
    assert response.status_code == 302 and response["Location"].startswith("/login/?next=")


def test_strict_content_security_policy(tree):
    policy = Client().get("/trees/taxonomy/")["Content-Security-Policy"]
    assert "script-src 'self'" in policy and "unsafe-eval" not in policy
    assert "object-src 'none'" in policy and "frame-ancestors 'none'" in policy
    assert "<script>" not in Client().get("/trees/taxonomy/").content.decode()


def test_api_docs_are_exempt(tree):
    assert "Content-Security-Policy" not in Client().get("/api/v1/docs")


def test_login_page():
    response = Client().get("/login/")
    assert response.status_code == 200 and b'name="password"' in response.content


# --- 5.4 node page ------------------------------------------------------------------------


def test_deprecated_node(tree):
    ids = ids_by_label("taxonomy")
    publish(tree, add("new:1", "Chaetoceros_genus", parent=ids["Chromista"]),
            deprecate(ids["box"], successors=["new:1"]))  # fmt: skip
    page = Client().get(f"/nodes/{ids['box']}/").content.decode()
    assert "Deprecated in revision 2" in page
    successor = ids_by_label("taxonomy")["Chaetoceros_genus"]
    assert f'href="/nodes/{successor}/"' in page


def test_warning_history(tree):
    ids = ids_by_label("taxonomy")
    node = ids["Chaetoceros"]
    record_warnings({node: [{"warning": "unaccepted_aphia", "detail": "x"}]})  # a sync
    record_warnings({node: []})  # a later publish
    page = Client().get(f"/nodes/{node}/").content.decode()
    history = page[page.index('id="warning-history"') :]
    assert history.index("none (cleared)") < history.index("unaccepted_aphia")  # newest first
    assert "AphiaID" in page and "148985" in page


def test_node_page_versions(tree):
    ids = ids_by_label("taxonomy")
    publish(tree, edit(ids["box"], label="box2"))
    page = Client().get(f"/nodes/{ids['box']}/").content.decode()
    assert "v2" in page and "box2" in page and "1–1" in page


# --- 6.6 draft list and review ----------------------------------------------------------------


def test_draft_list_and_review(tree):
    reader = logged_in(make_user("reader1", roles={"amplify": "reader"}))
    ids = ids_by_label("taxonomy")
    draft = create_changeset(
        author="drafter1", tree=tree, base_rev=1,
        changes=[add("new:1", "Chaetoceros_x", parent=ids["Chaetoceros"], group="split#1"),
                 move(ids["box"], None, ids["Chromista"])],
    )  # fmt: skip
    discarded = create_changeset(
        author="d", tree=tree, base_rev=1, changes=[edit(ids["box"], label="b")]
    )
    discarded.state = "discarded"
    discarded.save()
    page = reader.get("/trees/taxonomy/drafts/").content.decode()
    open_part = page[page.index('id="open-drafts"') : page.index('id="discarded-drafts"')]
    assert f"#{draft.pk}" in open_part and "drafter1" in open_part
    assert f"#{discarded.pk}" in page[page.index('id="discarded-drafts"') :]

    review = reader.get(f"/changesets/{draft.pk}/").content.decode()
    by_node = review[review.index('id="by-node"') : review.index('id="warning-changes"')]
    assert "Chaetoceros" in by_node and "v1 → v2" in by_node and "new → v1" in by_node
    assert "split#1" in by_node
    assert "split#1" in review[review.index('id="changes"') :]


def test_drafts_need_a_role(tree):
    outsider = logged_in(make_user("outsider"))
    assert outsider.get("/trees/taxonomy/drafts/").status_code == 403


# --- 5.6 organization and user pages -------------------------------------------------------------


def test_org_page(tree):
    make_user("owner1", roles={"amplify": "owner"})
    anonymous = Client().get("/orgs/amplify/").content.decode()
    assert "taxonomy" in anonymous and "owner1" not in anonymous  # members need a membership
    member = logged_in(make_user("reader1", roles={"amplify": "reader"})).get("/orgs/amplify/")
    assert b"owner1" in member.content


def test_my_page():
    user = make_user("curator1", roles={"amplify": "drafter", "lab_a": "owner"})
    page = logged_in(user).get("/me/").content.decode()
    assert "AMPLIfy" in page and "drafter" in page and "lab_a" in page and "owner" in page
