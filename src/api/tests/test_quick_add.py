"""Quick add (spec: quick-add): POST /trees/{tree}/quick_add."""

import time

import httpx
import pytest
from django.core import signing
from django.test import Client

from api import quick_add
from core.changesets import ChangesetError
from core.models import Changeset, TreeRevision
from core.tests.helpers import add, publish
from worms.client import worms_url

from .conftest import call

URL = "/trees/taxonomy/quick_add"
DEBILIS = 149219  # Chaetoceros debilis, under Chaetoceros (148985)
ROTULA = 148942  # Thalassiosira rotula, a synonym of 149102


@pytest.fixture
def approver(user_factory):
    return user_factory("app", roles={"amplify": "approver"})


@pytest.fixture
def qa(taxonomy, approver, as_user):
    """POST a quick add as the approver; returns (status, body)."""
    send = as_user(approver)
    return lambda body: send("post", URL, body)


def confirmed(qa, body):
    """Preview `body`, then send it back with its key."""
    status, preview = qa(body)
    assert status == 200, preview
    return qa({**body, "confirm": preview["confirm"]})


# --- Access ---------------------------------------------------------------------------------


def test_anonymous(taxonomy):
    assert call(Client(), "post", URL, {"label": "x"})[0] == 401


def test_drafter_refused(taxonomy, user_factory, as_user):
    drafter = user_factory("d", roles={"amplify": "drafter"})
    assert as_user(drafter)("post", URL, {"label": "x"})[0] == 403


def test_approver_token(taxonomy, approver, token_for):
    status, body = call(Client(), "post", URL, {"label": "x"},
                        Authorization=f"Token {token_for(approver)}")  # fmt: skip
    assert (status, body["status"]) == (200, "preview")


def test_unknown_tree(approver, as_user):
    assert as_user(approver)("post", "/trees/nope/quick_add", {"label": "x"})[0] == 404


# --- Request, label and parent ------------------------------------------------------------


def test_needs_aphia_id_or_label(qa):
    status, body = qa({})
    assert status == 400 and "confirm" not in body


def test_label_only_goes_at_the_top_level(qa):
    status, body = qa({"label": "detritus"})
    assert status == 200
    assert body["plan"] == {"label": "detritus", "parent": None, "aphia_id": None,
                            "worms_url": None, "description": "", "aliases": []}  # fmt: skip
    assert body["issues"] == [] and body["confirm_status"] == "none" and body["rev"] == 1


def test_derived_label_and_parent(qa, ids):
    status, body = qa({"aphia_id": DEBILIS})
    assert status == 200
    assert body["plan"]["label"] == "chaetoceros_debilis"
    assert body["plan"]["parent"] == {"id": ids("taxonomy")["Chaetoceros"], "label": "Chaetoceros"}
    assert body["plan"]["worms_url"] == (
        f"https://www.marinespecies.org/aphia.php?p=taxdetails&id={DEBILIS}"
    )
    assert body["issues"] == []


def test_derived_label_keeping_the_case(qa):
    body = qa({"aphia_id": DEBILIS, "lowercase_label": False})[1]
    assert body["plan"]["label"] == "Chaetoceros_debilis"


def test_given_label_is_used_as_is(qa):
    assert qa({"aphia_id": DEBILIS, "label": "debilis"})[1]["plan"]["label"] == "debilis"
    given = {"aphia_id": DEBILIS, "label": "Chaetoceros_debilis"}
    for lowercase in (True, False):
        body = qa({**given, "lowercase_label": lowercase})[1]
        assert body["plan"]["label"] == "Chaetoceros_debilis"


def test_toggling_lowercase_changes_the_request(qa):
    key = qa({"aphia_id": DEBILIS})[1]["confirm"]
    status, body = qa({"aphia_id": DEBILIS, "lowercase_label": False, "confirm": key})
    assert (status, body["confirm_status"]) == (200, "body_changed")
    assert body["plan"]["label"] == "Chaetoceros_debilis"


def test_explicit_top_level(qa):
    assert qa({"aphia_id": DEBILIS, "parent": None})[1]["plan"]["parent"] is None


def test_nothing_anchored(qa):
    # Dinophysis (109462): nothing in its lineage is in the tree.
    status, body = qa({"aphia_id": 109462})
    assert status == 200 and body["plan"]["parent"] is None


def test_deprecated_nodes_are_not_parents(qa, taxonomy, ids):
    ref = ids("taxonomy")
    publish(taxonomy, {"op": "deprecate", "node": ref["Chaetoceros_didymus"]},
            {"op": "deprecate", "node": ref["Chaetoceros"]})  # fmt: skip
    assert qa({"aphia_id": DEBILIS})[1]["plan"]["parent"] is None


def test_ambiguous_parent(qa, taxonomy, ids):
    publish(taxonomy, add("new:1", "Chaetoceros_sp", aphia_id=148985))
    ref = ids("taxonomy")
    status, body = qa({"aphia_id": DEBILIS})
    assert status == 200 and body["plan"]["parent"] is None
    [issue] = [i for i in body["issues"] if i["code"] == "ambiguous_parent"]
    tied = sorted([ref["Chaetoceros"], ref["Chaetoceros_sp"]])
    expected = [{"parent": t} for t in tied] + [{"parent": None}]
    assert [o["set"] for o in issue["options"]] == expected
    assert body["confirm"]


def test_picking_a_parent_clears_the_ambiguity(qa, taxonomy, ids):
    publish(taxonomy, add("new:1", "Chaetoceros_sp", aphia_id=148985))
    parent = ids("taxonomy")["Chaetoceros_sp"]
    body = qa({"aphia_id": DEBILIS, "parent": parent})[1]
    assert body["plan"]["parent"]["id"] == parent
    assert "ambiguous_parent" not in [i["code"] for i in body["issues"]]


# --- Issues and errors ------------------------------------------------------------------


def test_unaccepted_aphia(qa):
    status, body = qa({"aphia_id": ROTULA})
    assert status == 200 and body["confirm"]
    [issue] = body["issues"]
    assert issue["code"] == "unaccepted_aphia"
    assert [o["set"] for o in issue["options"]] == [{"aphia_id": 149102}]


def test_duplicate_aphia(qa, ids):
    status, body = qa({"aphia_id": 149122, "label": "didymus_again"})
    assert status == 200 and body["confirm"]
    [issue] = body["issues"]
    assert issue["code"] == "duplicate_aphia" and "Chaetoceros_didymus" in issue["message"]
    assert issue["options"] == []


def test_out_of_lineage_suggests_the_lineage_parent(qa, ids):
    ref = ids("taxonomy")
    status, body = qa({"aphia_id": DEBILIS, "parent": ref["Chaetoceros_didymus"]})
    codes = {i["code"]: i for i in body["issues"]}
    assert codes["out_of_lineage"]["options"][0]["set"] == {"parent": ref["Chaetoceros"]}


def test_label_in_use(qa):
    status, body = qa({"label": "other"})
    assert (status, body["error"]) == (422, "structural")
    assert [e["error"] for e in body["errors"]] == ["label_in_use"] and "confirm" not in body


def test_invalid_label(qa):
    status, body = qa({"label": "has space"})
    assert status == 422 and body["errors"][0]["error"] == "invalid_label"


def test_unknown_parent(qa):
    status, body = qa({"label": "x", "parent": 99999})
    assert status == 422 and body["errors"][0]["error"] == "parent_not_in_tree"


def test_no_worms_record(qa):
    status, body = qa({"aphia_id": 999999999})
    assert status == 404 and "confirm" not in body


def test_worms_unreachable(qa, worms_http):
    def down(request):
        raise httpx.ConnectError("down")

    worms_http.override({f"/AphiaRecordByAphiaID/{DEBILIS}": down})
    status, body = qa({"aphia_id": DEBILIS})
    assert (status, body["error"]) == (503, "worms_unreachable") and "confirm" not in body


def test_preview_stores_nothing(qa):
    before = Changeset.objects.count()
    qa({"aphia_id": DEBILIS})
    assert Changeset.objects.count() == before and TreeRevision.objects.count() == 1


# --- Confirming -----------------------------------------------------------------------------


def test_confirmed(qa, ids):
    status, body = confirmed(qa, {"aphia_id": DEBILIS})
    assert (status, body["status"], body["confirm_status"]) == (201, "published", "accepted")
    new = ids("taxonomy")["chaetoceros_debilis"]
    assert body["node"] == {"id": new, "label": "chaetoceros_debilis",
                            "parent": {"id": ids("taxonomy")["Chaetoceros"],
                                       "label": "Chaetoceros"},
                            "aphia_id": DEBILIS,
                            "worms_url": worms_url(DEBILIS)}  # fmt: skip
    assert body["rev"] == 2
    revision = TreeRevision.objects.get(tree_id="taxonomy", number=2)
    changeset = Changeset.objects.get(pk=body["changeset"])
    assert (changeset.author, revision.published_by, revision.notes) == ("app", "app", "Quick add")
    assert [(c.op, c.payload["label"]) for c in changeset.changes.all()] == [
        ("add", "chaetoceros_debilis")
    ]


def test_notes_can_change_at_confirm(qa):
    status, preview = qa({"label": "detritus", "notes": "first"})
    status, body = qa({"label": "detritus", "notes": "from the app", "confirm": preview["confirm"]})
    assert status == 201
    assert TreeRevision.objects.get(tree_id="taxonomy", number=2).notes == "from the app"


def test_key_from_another_user(qa, taxonomy, user_factory, as_user):
    other = user_factory("other", roles={"amplify": "approver"})
    key = as_user(other)("post", URL, {"label": "detritus"})[1]["confirm"]
    status, body = qa({"label": "detritus", "confirm": key})
    assert (status, body["confirm_status"]) == (200, "invalid")
    assert TreeRevision.objects.count() == 1


def test_tampered_key(qa):
    key = qa({"label": "detritus"})[1]["confirm"]
    status, body = qa({"label": "detritus", "confirm": key[:-2] + "xx"})
    assert (status, body["confirm_status"]) == (200, "invalid")


def test_modified_request(qa):
    key = qa({"aphia_id": ROTULA})[1]["confirm"]
    status, body = qa({"aphia_id": ROTULA, "label": "rotula", "confirm": key})
    assert (status, body["confirm_status"]) == (200, "body_changed")
    assert body["confirm"] != key and TreeRevision.objects.count() == 1


def test_tree_changed_the_plan(qa, taxonomy):
    key = qa({"aphia_id": DEBILIS})[1]["confirm"]
    publish(taxonomy, add("new:1", "Chaetoceros_sp", aphia_id=148985))  # now a tie
    status, body = qa({"aphia_id": DEBILIS, "confirm": key})
    assert (status, body["confirm_status"]) == (200, "plan_changed")
    assert body["plan"]["parent"] is None and body["rev"] == 2
    assert TreeRevision.objects.filter(tree_id="taxonomy").count() == 2


def test_unrelated_publish(qa, taxonomy):
    key = qa({"aphia_id": DEBILIS})[1]["confirm"]
    publish(taxonomy, add("new:1", "detritus"))
    status, body = qa({"aphia_id": DEBILIS, "confirm": key})
    assert (status, body["rev"]) == (201, 3)


def test_expired_key(qa, monkeypatch):
    real = time.time
    monkeypatch.setattr(signing.time, "time", lambda: real() - quick_add.KEY_MAX_AGE - 1)
    key = qa({"label": "detritus"})[1]["confirm"]
    monkeypatch.setattr(signing.time, "time", real)
    status, body = qa({"label": "detritus", "confirm": key})
    assert (status, body["confirm_status"]) == (200, "expired")


def test_retry_adds_nothing_twice(qa):
    body = {"aphia_id": DEBILIS}
    key = qa(body)[1]["confirm"]
    assert qa({**body, "confirm": key})[0] == 201
    status, again = qa({**body, "confirm": key})
    assert status == 422 and again["errors"][0]["error"] == "label_in_use"
    assert TreeRevision.objects.filter(tree_id="taxonomy").count() == 2


def test_stale_base_is_planned_again(qa, monkeypatch):
    real, calls = quick_add._publish, []

    def flaky(*args):
        calls.append(1)
        if len(calls) == 1:
            raise ChangesetError("stale_base", "behind")
        return real(*args)

    monkeypatch.setattr(quick_add, "_publish", flaky)
    assert confirmed(qa, {"label": "detritus"})[0] == 201 and len(calls) == 2


def test_publish_in_progress(qa, monkeypatch):
    def busy(*args):
        raise ChangesetError("publish_in_progress", "busy")

    monkeypatch.setattr(quick_add, "_publish", busy)
    status, body = confirmed(qa, {"label": "detritus"})
    assert (status, body["error"]) == (409, "publish_in_progress")


# --- Auth and schema ------------------------------------------------------------------------


def test_session_quick_add_is_csrf_checked(taxonomy, approver):
    client = Client(enforce_csrf_checks=True)
    client.force_login(approver)
    status, body = call(client, "post", URL, {"label": "x"})
    assert status == 403 and "CSRF" in body["detail"]


def test_in_the_openapi_schema():
    from api.api import api

    operation = api.get_openapi_schema()["paths"]["/api/v1/trees/{tree_id}/quick_add"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    fields = api.get_openapi_schema()["components"]["schemas"][schema["$ref"].split("/")[-1]]
    assert set(fields["properties"]) == {
        "aphia_id", "label", "parent", "lowercase_label", "description", "aliases", "notes",
        "confirm",
    }  # fmt: skip
    assert "required" not in fields


def test_readme_quick_add(taxonomy, approver, token_for):
    """The README's curl sequence: preview, then the same body with the key."""
    token = token_for(approver)
    send = lambda body: call(Client(), "post", URL, body, Authorization=f"Token {token}")  # noqa: E731
    status, preview = send({"aphia_id": DEBILIS})
    assert (status, preview["status"], preview["plan"]["label"], preview["issues"]) == (
        200, "preview", "chaetoceros_debilis", []
    )  # fmt: skip
    status, published = send({"aphia_id": DEBILIS, "confirm": preview["confirm"]})
    assert (status, published["status"], published["node"]["label"]) == (
        201, "published", "chaetoceros_debilis"
    )  # fmt: skip
