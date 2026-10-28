"""Checks on save and publish, and warning history (spec: worms-placement-checks).

Saves and publishes read cached records only; the helpers' `publish` caches the
AphiaIDs its changes set first, as the web app's fetch step does."""

import httpx
import pytest

from core import changesets
from core.changesets import create_changeset, latest_rev, publish_changeset, update_changeset
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


def test_save_never_calls_worms(diatoms, worms_http):
    worms_http.calls.clear()
    cs = create_changeset(
        author="a", tree=diatoms, base_rev=1,
        changes=[add("new:1", "Heterocapsa_triquetra", parent=ids()["Dinophyceae"],
                     aphia_id=110153),
                 edit(ids()["Chaetoceros_didymus"], label="Cd")],
    )  # fmt: skip
    first, second = cs.changes.order_by("seq")
    assert first.checks == "unavailable"  # 110153 isn't cached
    assert second.checks == []
    update_changeset(cs, notes="again")
    assert worms_http.calls == []


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


def test_publish_without_worms(diatoms, worms_http):
    """WoRMS is unreachable, and the draft's AphiaIDs are all cached."""
    worms_http.transport.responses = {}
    worms_http.strict()
    worms_http.calls.clear()
    cs = create_changeset(
        author="a", tree=diatoms, base_rev=1,
        changes=[move(ids()["Chaetoceros"], ids()["Chaetocerotaceae"], ids()["Dinophyceae"]),
                 add("new:1", "dup", parent=ids()["Chromista"], aphia_id=149122)],
    )  # fmt: skip
    revision = publish_changeset(cs, published_by="b")
    assert revision.number == 2 and worms_http.calls == []
    assert warnings_of("Chaetoceros") == ["out_of_lineage"]
    assert warnings_of("dup") == ["duplicate_aphia"]


def test_publish_uses_the_cached_record(diatoms, worms_http):
    """No re-fetch at publish: a record is as fresh as the last fetch or sync."""
    old = WormsRecord.objects.get(aphia_id=149122)
    cs = create_changeset(
        author="a", tree=diatoms, base_rev=1, changes=[edit(ids()["Chaetoceros"], label="C")]
    )
    worms_http.calls.clear()
    publish_changeset(cs, published_by="b")
    assert worms_http.calls == []
    assert WormsRecord.objects.get(aphia_id=149122).fetched_at == old.fetched_at


def test_warnings_never_block_publishing(diatoms):
    before = latest_rev("diatoms")
    publish(
        diatoms,
        move(ids()["Chaetoceros"], ids()["Chaetocerotaceae"], ids()["Dinophyceae"]),
        add("new:1", "dup", parent=ids()["Chromista"], aphia_id=149122),
    )
    assert latest_rev("diatoms") == before + 1


# --- Records not cached ----------------------------------------------------------------------


def test_publish_during_an_outage(diatoms, worms_http):
    """The fetch step fails (see helpers.publish), so 110153 is never cached."""
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
