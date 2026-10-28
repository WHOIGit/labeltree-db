"""Checks on save and publish, and warning history (spec: worms-placement-checks)."""

from datetime import timedelta

import httpx
import pytest

from core import changesets
from core.changesets import create_changeset, latest_rev, publish_changeset
from core.models import Change, NodeVersion, Tree
from core.tests.helpers import add, edit, ids_by_label, move, publish, publish_new_tree
from worms.models import NodeWarnings, WormsRecord, current_warnings

pytestmark = pytest.mark.django_db


@pytest.fixture
def diatoms():
    """Chromista > Bacillariophyceae > Chaetocerotaceae > Chaetoceros > Chaetoceros_didymus;
    plus Dinophyceae (19542) at the top level."""
    publish_new_tree(
        "diatoms",
        add("new:1", "Chromista", aphia_id=7),
        add("new:2", "Bacillariophyceae", parent="new:1", aphia_id=148899),
        add("new:3", "Chaetocerotaceae", parent="new:2", aphia_id=148984),
        add("new:4", "Chaetoceros", parent="new:3", aphia_id=148985),
        add("new:5", "Chaetoceros_didymus", parent="new:4", aphia_id=149122),
        add("new:6", "Dinophyceae", aphia_id=19542),
    )
    return Tree.objects.get(id="diatoms")


def ids():
    return ids_by_label("diatoms")


def warnings_of(label):
    return [w["warning"] for w in current_warnings([ids()[label]]).get(ids()[label], [])]


def down(request):
    raise httpx.ConnectError("down")


def test_correct_tree_stores_no_warning_rows(diatoms):
    assert not NodeWarnings.objects.exists()
    checks = Change.objects.filter(changeset__tree=diatoms).values_list("checks", flat=True)
    assert set(map(str, checks)) == {"[]"}


# --- 3.1 save --------------------------------------------------------------------------


def test_saved_draft_with_a_duplicate_aphia_id(diatoms):
    cs = create_changeset(
        author="a", tree=diatoms, base_rev=1,
        changes=[edit(ids()["Dinophyceae"], label="Dino"),
                 add("new:1", "C_didymus_2", parent=ids()["Chaetoceros"], aphia_id=149122)],
    )  # fmt: skip
    first, second = cs.changes.order_by("seq")
    assert first.checks == []
    assert [(c["warning"], c["node"]) for c in second.checks] == [
        ("duplicate_aphia", ids()["Chaetoceros_didymus"]),
        ("duplicate_aphia", "new:1"),
    ]


def test_save_while_worms_is_down(diatoms, worms_http):
    worms_http.override({"/AphiaRecordByAphiaID/110153": down})
    cs = create_changeset(
        author="a", tree=diatoms, base_rev=1,
        changes=[add("new:1", "Heterocapsa_triquetra", parent=ids()["Dinophyceae"],
                     aphia_id=110153),
                 edit(ids()["Chaetoceros_didymus"], label="Cd")],
    )  # fmt: skip
    first, second = cs.changes.order_by("seq")
    assert first.checks == "unavailable"
    assert second.checks == []


def test_update_refreshes_checks(diatoms):
    cs = create_changeset(
        author="a", tree=diatoms, base_rev=1, changes=[edit(ids()["Dinophyceae"], label="D")]
    )
    changesets.update_changeset(
        cs, changes=[move(ids()["Chaetoceros"], ids()["Chaetocerotaceae"], ids()["Dinophyceae"])]
    )
    (change,) = cs.changes.all()
    assert [c["warning"] for c in change.checks] == ["out_of_lineage"]
    assert "Dinophyceae" in change.checks[0]["detail"]


# --- 3.2 publish -------------------------------------------------------------------------


def test_publish_with_warnings(diatoms):
    chaetoceros, dino = ids()["Chaetoceros"], ids()["Dinophyceae"]
    revision = publish(diatoms, move(chaetoceros, ids()["Chaetocerotaceae"], dino))
    assert revision.number == 2
    bumped = set(NodeVersion.objects.filter(valid_from_rev=2).values_list("node_id", flat=True))
    assert bumped == {chaetoceros, dino, ids()["Chaetocerotaceae"]}  # structural only
    assert warnings_of("Chaetoceros") == ["out_of_lineage"]
    assert warnings_of("Chaetoceros_didymus") == []  # below the moved anchor: not rechecked
    (change,) = Change.objects.filter(changeset=revision.changeset)
    assert change.checks[0]["node"] == chaetoceros


def test_warnings_clear(diatoms):
    chaetoceros = ids()["Chaetoceros"]
    publish(diatoms, move(chaetoceros, ids()["Chaetocerotaceae"], ids()["Dinophyceae"]))
    publish(diatoms, move(chaetoceros, ids()["Dinophyceae"], ids()["Chaetocerotaceae"]))
    rows = NodeWarnings.objects.filter(node_id=chaetoceros).order_by("-computed_at")
    assert [[w["warning"] for w in r.warnings] for r in rows] == [[], ["out_of_lineage"]]
    assert warnings_of("Chaetoceros") == []


def test_quiet_recheck_adds_no_row(diatoms):
    chaetoceros, dino = ids()["Chaetoceros"], ids()["Dinophyceae"]
    publish(
        diatoms,
        move(chaetoceros, ids()["Chaetocerotaceae"], dino),
        add("new:1", "box", parent=dino),
    )
    # Rechecked twice more, still out of lineage under Dinophyceae.
    publish(diatoms, move(chaetoceros, dino, ids()["box"]))
    publish(diatoms, edit(chaetoceros, label="Chaetoceros_genus"))
    assert NodeWarnings.objects.filter(node_id=chaetoceros).count() == 1


def test_placeholders_are_rewritten_in_published_checks(diatoms):
    revision = publish(
        diatoms, add("new:1", "C_didymus_2", parent=ids()["Chaetoceros"], aphia_id=149122)
    )
    (change,) = Change.objects.filter(changeset=revision.changeset)
    new_id = ids()["C_didymus_2"]
    assert {c["node"] for c in change.checks} == {new_id, ids()["Chaetoceros_didymus"]}
    assert warnings_of("C_didymus_2") == warnings_of("Chaetoceros_didymus") == ["duplicate_aphia"]


def test_worms_is_fetched_before_the_publish_lock(diatoms, worms_http, monkeypatch):
    events = []
    take_lock = changesets._take_publish_lock
    monkeypatch.setattr(
        changesets, "_take_publish_lock", lambda key: (events.append("lock"), take_lock(key))
    )
    recorded = worms_http.transport.responses["/AphiaRecordByAphiaID/149120"]
    worms_http.override(
        {"/AphiaRecordByAphiaID/149120": lambda r: (
            events.append("fetch"), httpx.Response(200, json=recorded["body"]))[1]}
    )  # fmt: skip
    publish(diatoms, add("new:1", "Chaetoceros_danicus", parent=ids()["Chaetoceros"],
                         aphia_id=149120))  # fmt: skip
    assert events.index("lock") > events.index("fetch")
    assert events.count("lock") == 1


def test_publish_refetches_changed_aphia_ids_unless_recent(diatoms, worms_http):
    cs = create_changeset(
        author="a", tree=diatoms, base_rev=1,
        changes=[edit(ids()["Chaetoceros_didymus"], aphia_id=149120)],
    )  # fmt: skip
    worms_http.calls.clear()
    publish_changeset(cs, published_by="b")
    assert worms_http.calls == []  # fetched on save, under 10 minutes ago

    cs = create_changeset(
        author="a", tree=diatoms, base_rev=2, changes=[edit(ids()["Chaetoceros"], aphia_id=149122)]
    )
    WormsRecord.objects.filter(aphia_id=149122).update(
        fetched_at=WormsRecord.objects.get(aphia_id=149122).fetched_at - timedelta(hours=1)
    )
    worms_http.calls.clear()
    publish_changeset(cs, published_by="b")
    assert "/AphiaRecordByAphiaID/149122" in worms_http.calls
    assert "/AphiaRecordByAphiaID/148985" not in worms_http.calls  # unchanged: cache first


def test_warnings_never_block_publishing(diatoms):
    before = latest_rev("diatoms")
    publish(
        diatoms,
        move(ids()["Chaetoceros"], ids()["Chaetocerotaceae"], ids()["Dinophyceae"]),
        add("new:1", "dup", parent=ids()["Chromista"], aphia_id=149122),
    )
    assert latest_rev("diatoms") == before + 1


# --- 3.3 WoRMS down -------------------------------------------------------------------------


def test_publish_during_an_outage(diatoms, worms_http):
    worms_http.override(
        {"/AphiaRecordByAphiaID/110153": down, "/AphiaClassificationByAphiaID/110153": down}
    )
    revision = publish(
        diatoms, add("new:1", "Heterocapsa_triquetra", parent=ids()["Dinophyceae"],
                     aphia_id=110153),
    )  # fmt: skip
    assert revision.number == 2
    (change,) = Change.objects.filter(changeset=revision.changeset)
    assert change.checks == "unavailable"
    assert not WormsRecord.objects.filter(aphia_id=110153).exists()
    node_id = ids()["Heterocapsa_triquetra"]
    assert node_id not in current_warnings([node_id])
    from api.serializers import RevisionView

    detailed = RevisionView(diatoms, revision.number).detailed(node_id)
    assert (detailed["worms_data"], detailed["worms_warnings"]) == (None, [])
