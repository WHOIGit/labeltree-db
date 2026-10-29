"""Validate and changeset endpoints (spec: changeset-api)."""

import psycopg
import pytest
from django.db import connection
from django.test import Client

from core.models import Changeset, Tree
from core.tests.helpers import add, deprecate, edit, move, publish, publish_new_tree
from worms.records import get_records

from .conftest import call, logged_in, make_user

pytestmark = pytest.mark.django_db

# taxonomy: Chromista(1) > Bacillariophyceae(2) > Chaetocerotaceae(3) > Chaetoceros(4, 148985)
#           > Chaetoceros_didymus(5, 149122); other(6)


@pytest.fixture
def drafter():
    client = logged_in(make_user("drafter1", roles={"amplify": "drafter"}))
    return lambda *args, **headers: call(client, *args, **headers)


@pytest.fixture
def approver():
    client = logged_in(make_user("approver1", roles={"amplify": "approver"}))
    return lambda *args, **headers: call(client, *args, **headers)


def raw(client_user, method, path, body=None, **headers):
    """The response itself, for headers."""
    client = logged_in(client_user)
    kwargs = {"headers": headers}
    if body is not None:
        kwargs |= {"data": body, "content_type": "application/json"}
    return getattr(client, method)(f"/api/v1{path}", **kwargs)


def save(as_user, *changes, base_rev=1, notes=""):
    status, body = as_user(
        "post", "/changesets",
        {"tree": "taxonomy", "base_rev": base_rev, "changes": list(changes), "notes": notes},
    )  # fmt: skip
    assert status == 201, body
    return body


def etag_of(cs_id, user="drafter1"):
    from accounts.models import User

    return raw(User.objects.get(username=user), "get", f"/changesets/{cs_id}")["ETag"]


def validate(as_user, *changes, base_rev=1):
    body = {"tree": "taxonomy", "base_rev": base_rev, "changes": list(changes)}
    return as_user("post", "/changesets/validate", body)


# --- Validate ------------------------------------------------------------------------------


def test_errors_and_warnings(drafter, taxonomy):
    status, body = validate(
        drafter,
        add("new:1", "other", parent=None),
        add("new:2", "C_didymus_2", parent=4, aphia_id=149122),
    )
    assert status == 200 and body["ok"] is False
    assert [(e["seq"], e["error"]) for e in body["errors"]] == [(1, "label_in_use")]
    assert {w["warning"] for w in body["warnings"]} == {"duplicate_aphia"}
    assert not Changeset.objects.filter(tree=taxonomy, state="draft").exists()


def test_version_preview(drafter, taxonomy):
    body = validate(drafter, edit(4, label="Chaetoceros_genus"), move(5, 4, 6))[1]
    assert body["version_changes"] == [
        {"node": 4, "from": 1, "to": 2}, {"node": 5, "from": 1, "to": 2},
        {"node": 6, "from": 1, "to": 2},
    ]  # fmt: skip
    assert body["ok"] and body["conflicts"] == []


def test_behind_but_clean(drafter, taxonomy):
    publish(taxonomy, edit(4, label="Chaetoceros_genus"))
    publish(taxonomy, edit(6, label="other_things"))
    body = validate(drafter, add("new:1", "Chaetoceros_x", parent=4), base_rev=1)[1]
    assert body["ok"] is False and body["errors"] == [] and body["latest_rev"] == 3
    (conflict,) = body["conflicts"]
    assert conflict["error"] == "stale_base"
    assert conflict["nodes"] == [
        {"node": 4, "base_version": 1, "latest_version": 2, "detail": "Changed in revision 2."}
    ]


def test_provenance(drafter, taxonomy):
    body = validate(
        drafter,
        add("new:1", "a", parent=6, group="split#1"),
        edit(5, label="tmp"), edit(4, label="Chaetoceros_didymus"), edit(5, label="Chaetoceros"),
        move(1, None, 6),
        edit("new:1", label="b"),
    )[1]  # fmt: skip
    sources = {(c["op"], c["node"]): c["sources"] for c in body["reduced_changes"]}
    assert sources[("add", "new:1")] == [1, 6]
    assert [c["sources"] for c in body["reduced_changes"] if c["op"] == "edit"] == [[2], [3], [4]]
    by_node = {n["node"]: n for n in body["node_changes"]}
    assert by_node["new:1"]["groups"] == ["split#1"]
    assert by_node[5]["fields"] == {"label": ["Chaetoceros_didymus", "Chaetoceros"]}


def test_warning_change_on_an_existing_node(drafter, taxonomy):
    body = validate(drafter, add("new:1", "C_didymus_2", parent=4, aphia_id=149122))[1]
    assert ("duplicate_aphia", "new:1") in {(w["warning"], w["node"]) for w in body["warnings"]}
    assert body["warning_changes"] == [{"node": 5, "added": ["duplicate_aphia"], "removed": []}]


def test_new_aphia_id_not_cached_then_fetched(drafter, taxonomy, worms_http):
    worms_http.calls.clear()
    change = add("new:1", "Heterocapsa_triquetra", parent=6, aphia_id=110153)
    body = validate(drafter, change)[1]
    assert (body["worms_missing"], body["unchecked"], body["worms"]) == (
        [110153], [1], "unavailable",
    )  # fmt: skip
    assert worms_http.calls == []
    get_records([110153])  # what a fetch job does
    body = validate(drafter, change)[1]
    assert (body["worms_missing"], body["unchecked"], body["worms"]) == ([], [], "ok")


def test_validate_refuses_an_unknown_base_rev(drafter, taxonomy):
    status, body = validate(drafter, edit(4, label="x"), base_rev=9)
    assert (status, body["error"]) == (422, "invalid_base_rev")


# --- Create, list, get ------------------------------------------------------------------------


def test_new_draft(drafter, taxonomy, worms_http):
    worms_http.calls.clear()
    body = save(drafter, edit(4, label="a"), edit(4, label="b"), notes="Rename")
    assert body["changes"] == [{"seq": 1, "op": "edit", "group": None, "node": 4, "label": "b"}]
    assert (body["state"], body["author"], body["notes"]) == ("draft", "drafter1", "Rename")
    assert body["validation"]["ok"] and worms_http.calls == []


def test_draft_with_errors(drafter, taxonomy):
    body = save(drafter, move(4, 3, 5))
    assert [e["error"] for e in body["validation"]["errors"]] == ["cycle"]


def test_drafts_awaiting_approval(drafter, approver, taxonomy):
    first = save(drafter, edit(4, label="a"))
    save(drafter, edit(6, label="b"), move(5, 4, 6))
    status, body = approver("get", "/changesets?state=draft&tree=taxonomy")
    assert status == 200 and body["count"] == 2
    listed = {c["id"]: c for c in body["changesets"]}
    first = listed[first["id"]]
    assert (first["author"], first["base_rev"], first["tree"], first["org"]) == (
        "drafter1", 1, "taxonomy", "amplify",
    )  # fmt: skip
    assert sorted(c["num_changes"] for c in body["changesets"]) == [1, 2]
    assert approver("get", "/changesets?state=published")[1]["count"] == 1
    assert approver("get", "/changesets?state=open")[0] == 400
    assert approver("get", "/changesets?tree=nope")[0] == 404


def test_only_visible_changesets(drafter, taxonomy):
    save(drafter, edit(4, label="a"))  # on amplify's tree
    publish_new_tree("lab_tree", add("new:1", "a"), org_id="lab_a")
    lab_owner = logged_in(make_user("lab_owner", roles={"lab_a": "owner"}))
    lab_draft = call(
        lab_owner,
        "post",
        "/changesets",
        {"tree": "lab_tree", "base_rev": 1, "changes": [edit(7, label="b")]},
    )[1]
    new_tree_draft = call(lab_owner, "post", "/changesets", new_tree(org="lab_a"))[1]
    body = call(lab_owner, "get", "/changesets?state=draft")[1]
    assert {c["id"] for c in body["changesets"]} == {lab_draft["id"], new_tree_draft["id"]}
    assert call(lab_owner, "get", "/changesets?org=lab_a&state=draft")[1]["count"] == 2
    assert call(lab_owner, "get", "/changesets?org=amplify")[1]["count"] == 0
    admin = logged_in(make_user("admin", superuser=True))
    assert call(admin, "get", "/changesets?state=draft")[1]["count"] == 3


def test_published_changeset(drafter, approver, taxonomy):
    draft = save(drafter, add("new:1", "x", parent=6))
    approver("post", f"/changesets/{draft['id']}/publish", {}, **{"If-Match": etag_of(draft["id"])})
    body = drafter("get", f"/changesets/{draft['id']}")[1]
    assert body["state"] == "published" and body["rev"] == 2 and "validation" not in body
    (change,) = body["changes"]
    assert isinstance(change["node"], int)


def test_unknown_changeset(drafter):
    assert drafter("get", "/changesets/999")[0] == 404


# --- New trees -------------------------------------------------------------------------------


def new_tree(org="amplify", tree_id="lab_tags"):
    return {
        "new_tree": {"id": tree_id, "title": "Lab tags", "org": org},
        "changes": [add("new:1", "a")],
    }


def test_validate_a_new_tree(taxonomy):
    owner = logged_in(make_user("owner1", roles={"amplify": "owner"}))
    status, body = call(owner, "post", "/changesets/validate", new_tree())
    assert status == 200 and body["ok"] and body["latest_rev"] is None
    assert body["tree"] == "lab_tags" and body["reduced_changes"][0]["sources"] == [1]
    assert not Changeset.objects.filter(new_tree_id="lab_tags").exists()
    drafter = logged_in(make_user("drafter2", roles={"amplify": "drafter"}))
    assert call(drafter, "post", "/changesets/validate", new_tree())[0] == 403


def test_tree_or_new_tree(drafter, taxonomy):
    both = {**new_tree(), "tree": "taxonomy", "base_rev": 1}
    assert drafter("post", "/changesets/validate", both)[0] == 400
    assert drafter("post", "/changesets", {"changes": []})[0] == 400
    status, body = drafter("post", "/changesets", {"tree": "taxonomy", "changes": []})
    assert (status, body["error"]) == (422, "invalid_base_rev")


def test_drafter_proposes_a_new_tree(drafter, taxonomy):
    status, body = drafter("post", "/changesets", new_tree())
    assert status == 403


def test_owner_creates_a_tree(taxonomy):
    owner = logged_in(make_user("owner1", roles={"amplify": "owner"}))
    status, draft = call(owner, "post", "/changesets", new_tree())
    assert status == 201 and draft["new_tree"]["org"] == "amplify"
    assert draft["validation"]["ok"] and draft["validation"]["latest_rev"] is None
    etag = raw(owner_user(), "get", f"/changesets/{draft['id']}")["ETag"]
    status, revision = call(owner, "post", f"/changesets/{draft['id']}/publish", None,
                            **{"If-Match": etag})  # fmt: skip
    assert status == 201 and (revision["id"], revision["rev"]) == ("lab_tags", 1)
    assert Tree.objects.get(id="lab_tags").org_id == "amplify"
    # every member of amplify has their role on it
    reader = logged_in(make_user("reader1", roles={"amplify": "reader"}))
    assert call(reader, "get", "/changesets?tree=lab_tags")[0] == 200


def owner_user():
    from accounts.models import User

    return User.objects.get(username="owner1")


def test_new_tree_requests(taxonomy):
    owner = logged_in(make_user("owner1", roles={"amplify": "owner"}))
    assert call(owner, "post", "/changesets", new_tree(org="nope"))[0] == 404
    assert call(owner, "post", "/changesets", new_tree(tree_id="lab tags"))[0] == 400
    status, draft = call(owner, "post", "/changesets", new_tree(tree_id="taxonomy"))
    assert draft["validation"]["conflicts"][0]["error"] == "tree_exists"
    etag = raw(owner_user(), "get", f"/changesets/{draft['id']}")["ETag"]
    status, body = call(owner, "post", f"/changesets/{draft['id']}/publish", None,
                        **{"If-Match": etag})  # fmt: skip
    assert (status, body["error"]) == (409, "tree_exists")


def test_new_tree_drafts_are_seen_by_organization_members(taxonomy):
    owner = logged_in(make_user("owner1", roles={"amplify": "owner"}))
    draft = call(owner, "post", "/changesets", new_tree())[1]
    reader = logged_in(make_user("reader1", roles={"amplify": "reader"}))
    assert call(reader, "get", f"/changesets/{draft['id']}")[0] == 200
    outsider = logged_in(make_user("outsider", roles={"lab_a": "owner"}))
    assert call(outsider, "get", f"/changesets/{draft['id']}")[0] == 403


# --- Update and rebase --------------------------------------------------------------------------


def test_rebase(drafter, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    publish(taxonomy, edit(6, label="b"))
    status, body = drafter("put", f"/changesets/{draft['id']}", {"base_rev": 2},
                           **{"If-Match": etag_of(draft["id"])})  # fmt: skip
    assert status == 200 and body["base_rev"] == 2
    assert body["validation"]["conflicts"] == [] and body["validation"]["ok"]


def test_update_replaces_changes_and_notes(drafter, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    status, body = drafter(
        "put", f"/changesets/{draft['id']}",
        {"changes": [edit(6, label="b"), edit(6, label="c")], "notes": "n"},
        **{"If-Match": etag_of(draft["id"])},
    )  # fmt: skip
    assert status == 200 and body["notes"] == "n"
    assert [c["label"] for c in body["changes"]] == ["c"]


def test_editing_another_drafters_draft(drafter, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    other = logged_in(make_user("drafter2", roles={"amplify": "drafter"}))
    status, _ = call(other, "put", f"/changesets/{draft['id']}", {"notes": "mine"},
                     **{"If-Match": etag_of(draft["id"])})  # fmt: skip
    assert status == 200


def test_update_a_published_changeset(drafter, approver, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    approver("post", f"/changesets/{draft['id']}/publish", {}, **{"If-Match": etag_of(draft["id"])})
    status, body = drafter("put", f"/changesets/{draft['id']}", {"notes": "late"},
                           **{"If-Match": etag_of(draft["id"])})  # fmt: skip
    assert (status, body["error"]) == (409, "not_draft")


def test_concurrent_edit(drafter, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    old = etag_of(draft["id"])
    drafter("put", f"/changesets/{draft['id']}", {"notes": "B was here"}, **{"If-Match": old})
    status, body = drafter("put", f"/changesets/{draft['id']}", {"notes": "A"}, **{"If-Match": old})
    assert (status, body["error"]) == (412, "precondition_failed")


def test_missing_if_match(drafter, approver, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    assert drafter("put", f"/changesets/{draft['id']}", {"notes": "x"})[0] == 428
    status, body = approver("post", f"/changesets/{draft['id']}/publish")
    assert (status, body["error"]) == (428, "precondition_required")


def test_bad_base_rev_on_update(drafter, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    status, body = drafter("put", f"/changesets/{draft['id']}", {"base_rev": 7},
                           **{"If-Match": etag_of(draft["id"])})  # fmt: skip
    assert (status, body["error"]) == (422, "invalid_base_rev")


# --- Publish --------------------------------------------------------------------------------------


def publish_draft(as_user, cs_id, notes=None, etag_user="drafter1"):
    body = {} if notes is None else {"notes": notes}
    etag = etag_of(cs_id, etag_user)
    return as_user("post", f"/changesets/{cs_id}/publish", body, **{"If-Match": etag})


def test_publish_with_approver_notes(drafter, approver, taxonomy):
    draft = save(drafter, edit(4, label="a"), notes="drafter's notes")
    status, body = publish_draft(approver, draft["id"], "Split Thalassiosira")
    assert status == 201
    assert (body["rev"], body["notes"], body["published_by"], body["author"]) == (
        2, "Split Thalassiosira", "approver1", "drafter1",
    )  # fmt: skip


def test_publish_keeps_drafter_notes_without_approver_notes(drafter, approver, taxonomy):
    draft = save(drafter, edit(4, label="a"), notes="drafter's notes")
    assert publish_draft(approver, draft["id"])[1]["notes"] == "drafter's notes"


def test_publishing_ones_own_draft(approver, taxonomy):
    draft = save(approver, edit(4, label="a"))
    assert publish_draft(approver, draft["id"], etag_user="approver1")[0] == 201


def test_drafter_publishes(drafter, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    assert publish_draft(drafter, draft["id"])[0] == 403


def test_stale_draft(drafter, approver, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    publish(taxonomy, edit(6, label="b"))
    status, body = publish_draft(approver, draft["id"])
    assert (status, body["error"]) == (409, "stale_base")
    assert body["validation"]["conflicts"][0]["error"] == "stale_base"


def test_structural_error(drafter, approver, taxonomy):
    draft = save(drafter, move(4, 3, 5))
    status, body = publish_draft(approver, draft["id"])
    assert (status, body["error"]) == (422, "structural")
    assert [e["error"] for e in body["validation"]["errors"]] == ["cycle"]


@pytest.mark.django_db(transaction=True)  # publish locks last until the transaction ends
def test_publish_in_progress(drafter, approver, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    etag = etag_of(draft["id"])
    s = connection.settings_dict
    with psycopg.connect(
        dbname=s["NAME"], user=s["USER"], password=s["PASSWORD"] or None,
        host=s["HOST"] or None, port=s["PORT"] or None, autocommit=True,
    ) as conn:  # fmt: skip
        conn.execute("SELECT pg_advisory_lock(hashtext('publish:taxonomy'))")
        status, body = approver("post", f"/changesets/{draft['id']}/publish", {},
                                **{"If-Match": etag})  # fmt: skip
    assert (status, body["error"]) == (409, "publish_in_progress")


def test_publish_via_token(drafter, taxonomy, token_for):
    from accounts.models import User

    draft = save(drafter, edit(4, label="a"))
    key = token_for(User.objects.create_user("approver_bot"))
    from accounts.models import OrgMember, Role

    OrgMember.objects.create(user=User.objects.get(username="approver_bot"), org_id="amplify",
                             role=Role.APPROVER)  # fmt: skip
    client = Client(enforce_csrf_checks=True)
    status, body = call(
        client,
        "post",
        f"/changesets/{draft['id']}/publish",
        {},
        **{"If-Match": etag_of(draft["id"]), "Authorization": f"Token {key}"},
    )
    assert status == 201 and body["published_by"] == "approver_bot"


# --- Discard -----------------------------------------------------------------------------------


def test_discarded_draft_is_kept(drafter, taxonomy):
    draft = save(drafter, edit(4, label="a"))
    assert drafter("delete", f"/changesets/{draft['id']}")[0] == 204
    body = drafter("get", f"/changesets/{draft['id']}")[1]
    assert body["state"] == "discarded" and len(body["changes"]) == 1
    assert drafter("delete", f"/changesets/{draft['id']}")[0] == 409


# --- Macros ------------------------------------------------------------------------------------


def test_submitting_a_split(drafter, taxonomy):
    body = save(
        drafter,
        add("new:1", "Chaetoceros_a", parent=3, group="split#1"),
        add("new:2", "Chaetoceros_b", parent=3, group="split#1"),
        move(5, 4, "new:1", group="split#1"),
        deprecate(4, successors=["new:1", "new:2"], group="split#1"),
    )
    assert {c["group"] for c in body["changes"]} == {"split#1"}
    assert body["validation"]["ok"]
