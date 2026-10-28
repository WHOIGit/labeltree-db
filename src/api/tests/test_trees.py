"""/trees endpoints (spec: tree-read-api).

taxonomy ids: 1 Chromista, 2 Bacillariophyceae, 3 Chaetocerotaceae, 4 Chaetoceros,
5 Chaetoceros_didymus, 6 other.
"""

import csv
import io

from django.utils import timezone

from core.importer import expand_import
from core.models import NodeAlias, NodeDescription
from core.tests.helpers import add, deprecate, edit, move, publish, publish_new_tree

# --- 9.1 tree info ---------------------------------------------------------------------------


def test_two_loaded_trees(get, tags, taxonomy):
    _, body, _ = get("/trees")
    assert [(t["id"], t["latest_rev"], t["num_nodes"]) for t in body["trees"]] == [
        ("NES2022_tags", 1, 18),
        ("taxonomy", 1, 6),
    ]
    assert set(body["trees"][0]) == {
        "id", "title", "description", "latest_rev", "published_at", "num_nodes",
    }  # fmt: skip


def test_tree_summary(get, taxonomy):
    _, body, _ = get("/trees/taxonomy")
    assert body | {"published_at": None} == {
        "id": "taxonomy", "title": "taxonomy", "description": "", "rev": 1, "latest_rev": 1,
        "published_at": None, "published_by": "bob", "author": "alice", "notes": "",
        "changeset": body["changeset"], "num_nodes": 6, "num_top_level": 2, "max_depth": 4,
    }  # fmt: skip


def test_polling_for_change(get, taxonomy):
    publish(taxonomy, edit(6, label="misc"), notes="rename other")
    _, body, _ = get("/trees/taxonomy")
    assert (body["rev"], body["latest_rev"], body["notes"]) == (2, 2, "rename other")
    _, body, _ = get("/trees/taxonomy?rev=1")
    assert (body["rev"], body["latest_rev"]) == (1, 2)


def test_unknown_tree(get):
    status, body, _ = get("/trees/nope")
    assert status == 404 and body["detail"] == "Tree nope does not exist."


# --- 9.2 revisions and changes ---------------------------------------------------------------


def test_history_order(get, taxonomy):
    publish(taxonomy, edit(6, aphia_id=1))
    publish(taxonomy, edit(6, aphia_id=2), edit(5, label="Cd"))
    _, body, _ = get("/trees/taxonomy/revisions")
    assert [(r["rev"], r["num_changes"]) for r in body["revisions"]] == [(3, 2), (2, 1), (1, 6)]
    assert body["count"] == 3


def test_revision_1_of_imported_tree(get, tags):
    _, body, _ = get("/trees/NES2022_tags/revisions/1/changes")
    assert len(body["changes"]) == 18
    assert {(c["op"], c["group"]) for c in body["changes"]} == {("add", "import#1")}
    assert [c["seq"] for c in body["changes"]] == list(range(1, 19))
    assert body["changes"][2] == {
        "seq": 3, "op": "add", "group": "import#1", "node": 3, "label": "Amphidinium_grazing",
        "parent": 2,
    }  # fmt: skip
    assert body["version_changes"] == [{"node": n, "from": None, "to": 1} for n in range(1, 19)]


def test_split_with_replacement_version_changes(get, taxonomy):
    publish(taxonomy, add("new:1", "Ch_x", parent=4), add("new:2", "Ch_y", parent=4))  # 7, 8
    publish(
        taxonomy,
        add("new:1", "Ch_a", parent=3, group="split#3"),
        add("new:2", "Ch_b", parent=3, group="split#3"),
        move(7, 4, "new:1", group="split#3"),
        move(8, 4, "new:2", group="split#3"),
        move(5, 4, "new:1", group="split#3"),
        deprecate(4, successors=["new:1", "new:2"], group="split#3"),
    )
    _, body, _ = get("/trees/taxonomy/revisions/3/changes")
    assert body["changes"][-1] == {
        "seq": 6, "op": "deprecate", "group": "split#3", "node": 4, "successors": [9, 10],
    }  # fmt: skip
    assert body["version_changes"] == [
        {"node": 3, "from": 1, "to": 2},
        {"node": 4, "from": 2, "to": None},
        {"node": 5, "from": 1, "to": 2},
        {"node": 7, "from": 1, "to": 2},
        {"node": 8, "from": 1, "to": 2},
        {"node": 9, "from": None, "to": 1},
        {"node": 10, "from": None, "to": 1},
    ]


def test_unknown_revision_changes(get, taxonomy):
    assert get("/trees/taxonomy/revisions/2/changes")[0] == 404


# --- 9.3 diff ------------------------------------------------------------------------------


def test_diff(get, taxonomy):
    publish(taxonomy, edit(5, label="C_didymus"))  # rev 2: rename
    publish(taxonomy, move(4, 3, 6), edit(4, aphia_id=1))  # rev 3: moved and edited
    publish(taxonomy, add("new:1", "tmp", parent=6))  # rev 4: 7 added
    publish(taxonomy, deprecate(7))  # rev 5: 7 deprecated in range
    publish(taxonomy, add("new:1", "kept", parent=6))  # rev 6: 8 added
    publish(taxonomy, edit(8, aphia_id=2))  # rev 7: 8 edited in range
    publish(taxonomy, deprecate(5, successors=[8]))  # rev 8
    _, body, _ = get("/trees/taxonomy/diff?from=1&to=8")
    assert body["added"] == [
        {"id": 8, "label": "kept", "version": 2, "num_children": 0, "children": None}
    ]
    assert body["deprecated"] == [
        {"id": 5, "label": "C_didymus", "deprecated_in_rev": 8, "successors": [8]}
    ]
    assert body["moved"] == [{"id": 4, "label": "Chaetoceros", "from_parent": 3, "to_parent": 6}]
    assert body["edited"] == [
        {"id": 4, "label": "Chaetoceros", "fields": {"aphia_id": [148985, 1]}}
    ]

    _, body, _ = get("/trees/taxonomy/diff?from=1&to=2")
    assert body["edited"] == [
        {"id": 5, "label": "C_didymus", "fields": {"label": ["Chaetoceros_didymus", "C_didymus"]}}
    ]


def test_diff_parameters(get, taxonomy):
    assert get("/trees/taxonomy/diff?from=1")[0] == 400
    assert get("/trees/taxonomy/diff?from=1&to=9")[0] == 404
    publish(taxonomy, edit(6, aphia_id=1))
    assert get("/trees/taxonomy/diff?from=2&to=1")[0] == 400


# --- 9.4 browsing and export -----------------------------------------------------------------


def structure(nodes):
    return [
        (n["label"], n.get("aphia_id"), n.get("description", ""), n.get("aliases", []),
         structure(n.get("children") or []))
        for n in nodes
    ]  # fmt: skip


def test_nodes_as_tree_reimports_identically(get, taxonomy):
    NodeDescription.objects.create(node_id=6, description="misc", added_by="x")
    _, body, _ = get("/trees/taxonomy/nodes_as_tree?dropempty=true")
    assert "description" not in body["nodes"][0]
    assert body["nodes"][1]["description"] == "misc"
    publish_new_tree("copy", *expand_import(body))
    _, copy, _ = get("/trees/copy/nodes_as_tree?dropempty=true")
    assert structure(copy["nodes"]) == structure(body["nodes"])
    assert {n["id"] for n in copy["nodes"]}.isdisjoint({n["id"] for n in body["nodes"]})


def test_nodes_as_tree_shape_and_depth(get, taxonomy):
    _, body, _ = get("/trees/taxonomy/nodes_as_tree?depth=2")
    chromista = body["nodes"][0]
    assert list(chromista) == [
        "id", "label", "version", "aphia_id", "description", "aliases", "num_children", "children",
    ]  # fmt: skip
    assert chromista["children"][0]["children"] is None
    _, body, _ = get("/trees/taxonomy/nodes_as_tree")
    didymus = body["nodes"][0]["children"][0]["children"][0]["children"][0]["children"][0]
    assert didymus["aliases"] == ["Chaetoceros didymus"]
    assert get("/trees/taxonomy/nodes_as_tree?depth=0")[0] == 400


def test_export(get, taxonomy):
    _, body, _ = get("/trees/taxonomy/export")
    chromista = body["nodes"][0]
    assert "parent" not in chromista and chromista["tree_depth"] == 0
    assert chromista["children"][0]["label"] == "Bacillariophyceae"
    assert "worms_data" in chromista["children"][0]
    _, body, _ = get("/trees/taxonomy/export?parents=true")
    assert body["nodes"][0]["parent"] is None
    assert body["nodes"][0]["children"][0]["parent"]["label"] == "Chromista"


def test_export_flat(get, taxonomy):
    publish(taxonomy, add("new:1", "Ch_b", parent=4))
    status, text, response = get("/trees/taxonomy/export_flat")
    assert status == 200 and response["Content-Type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert list(rows[0]) == [
        "id", "label", "version", "parent", "children", "tree_depth", "description", "aliases",
        "aphia_id", "worms_scientificname", "worms_rank", "worms_status", "worms_link",
        "worms_warnings", "created_in_rev",
    ]  # fmt: skip
    by_label = {r["label"]: r for r in rows}
    assert by_label["Chaetoceros"]["children"] == "5|7"
    assert by_label["Chaetoceros"]["parent"] == "3"
    assert by_label["Chaetoceros_didymus"]["aliases"] == "Chaetoceros didymus"
    assert by_label["Ch_b"]["created_in_rev"] == "2"
    assert [r["label"] for r in rows][:2] == ["Chromista", "Bacillariophyceae"]


# --- 9.5 lookups ---------------------------------------------------------------------------------


def test_renamed_label(get, taxonomy):
    publish(taxonomy, edit(6, label="L2"))
    assert get("/trees/taxonomy/nodes/other")[0] == 404
    assert get("/trees/taxonomy/nodes/L2")[1]["id"] == 6
    assert get("/trees/taxonomy/nodes/other?rev=1")[1]["id"] == 6
    assert get("/trees/taxonomy/nodes/OTHER")[0] == 404  # case-sensitive


def test_mixed_batch(get, taxonomy, tags):
    publish(taxonomy, deprecate(5))
    _, body, _ = get("/trees/taxonomy/nodes?ids=6,5,9999,10&labels=Chaetoceros,nope")
    nodes = body["nodes"]
    assert nodes[0]["label"] == "other" and "worms_data" in nodes[0]
    assert nodes[1]["last_version"] == 1 and nodes[1]["deprecated_in_rev"] == 2
    assert nodes[2] == {"id": 9999, "error": "not_found"}
    assert nodes[3] == {"id": 10, "error": "not_found"}  # node 10 is in NES2022_tags
    assert nodes[4]["id"] == 4
    assert nodes[5] == {"label": "nope", "error": "not_found"}
    assert get("/trees/taxonomy/nodes?ids=1,x")[0] == 400


# --- 9.6 search ----------------------------------------------------------------------------------


def test_prefix_match_with_path(get, taxonomy):
    _, body, _ = get("/trees/taxonomy/search?q=chaeto")
    first = body["results"][0]
    assert (first["label"], first["matched_on"]) == ("Chaetoceros", "label")
    assert first["path"] == "Chromista/Bacillariophyceae/Chaetocerotaceae/Chaetoceros"
    assert [r["label"] for r in body["results"]] == [
        "Chaetoceros", "Chaetocerotaceae", "Chaetoceros_didymus",
    ]  # fmt: skip


def test_ranking_exact_then_prefix_then_substring(get, taxonomy):
    _, body, _ = get("/trees/taxonomy/search?q=chaetoceros")
    assert [r["label"] for r in body["results"]][:2] == ["Chaetoceros", "Chaetoceros_didymus"]
    _, body, _ = get("/trees/taxonomy/search?q=didymus")
    assert [(r["label"], r["matched_on"]) for r in body["results"]] == [
        ("Chaetoceros_didymus", "label")
    ]


def test_underscore_and_space_are_equal(get, taxonomy):
    _, body, _ = get("/trees/taxonomy/search?q=chaetoceros%20didymus&method=exact")
    assert [r["label"] for r in body["results"]] == ["Chaetoceros_didymus"]


def test_alias_match(get, taxonomy):
    NodeAlias.objects.create(node_id=6, alias="L1", added_by="x", added_at=timezone.now())
    _, body, _ = get("/trees/taxonomy/search?q=L1")
    assert [(r["id"], r["matched_on"]) for r in body["results"]] == [(6, "alias")]


def test_exact_only(get, taxonomy):
    assert get("/trees/taxonomy/search?q=chaeto&method=exact")[1]["results"] == []


def test_fuzzy(get, taxonomy):
    _, body, _ = get("/trees/taxonomy/search?q=chaetocerus&method=fuzzy")
    assert body["results"][0]["label"] == "Chaetoceros"
    _, body, _ = get("/trees/taxonomy/search?q=chaetocerus")
    assert body["results"][0]["label"] == "Chaetoceros"  # falls through to fuzzy


def test_deprecated_nodes_excluded(get, taxonomy):
    publish(taxonomy, deprecate(5))
    assert get("/trees/taxonomy/search?q=didymus")[1]["results"] == []
    assert get("/trees/taxonomy/search?q=didymus&rev=1")[1]["results"][0]["id"] == 5


def test_search_by_aphia_id(get, taxonomy):
    _, body, _ = get("/trees/taxonomy/search?aphia_id=148985")
    assert [(r["label"], r["matched_on"]) for r in body["results"]] == [("Chaetoceros", "aphia_id")]


def test_search_limits_and_parameters(get, taxonomy):
    assert len(get("/trees/taxonomy/search?q=c&limit=2")[1]["results"]) == 2
    for bad in ("q=c&limit=101", "q=c&limit=0", "q=c&method=regex", "", "q=c&aphia_id=1"):
        assert get(f"/trees/taxonomy/search?{bad}")[0] == 400, bad


# --- WoRMS in search and flat export ----------------------------------------------------


def test_flat_export_worms_columns(get, taxonomy):
    from worms.warnings import record_warnings

    record_warnings(
        {5: [{"warning": "out_of_lineage", "detail": "x"}, {"warning": "duplicate_aphia",
                                                            "detail": "y"}]}
    )  # fmt: skip
    rows = {
        r["label"]: r for r in csv.DictReader(io.StringIO(get("/trees/taxonomy/export_flat")[1]))
    }
    didymus = rows["Chaetoceros_didymus"]
    assert (didymus["worms_scientificname"], didymus["worms_rank"], didymus["worms_status"]) == (
        "Chaetoceros didymus", "Species", "accepted",
    )  # fmt: skip
    assert didymus["worms_link"].endswith("id=149122")
    assert didymus["worms_warnings"] == "out_of_lineage|duplicate_aphia"
    assert rows["other"]["worms_scientificname"] == rows["other"]["worms_warnings"] == ""


def test_search_scientific_name_with_a_space(get, taxonomy):
    _, body, _ = get("/trees/taxonomy/search?q=Chaetoceros didymus")
    hits = [r for r in body["results"] if r["id"] == 5]
    assert len(hits) == 1 and hits[0]["matched_on"] == "label"


def test_search_worms_name_only(get, taxonomy):
    publish(taxonomy, add("new:1", "Thalassiosira_morphotype1", parent=4, aphia_id=148942))
    _, body, _ = get("/trees/taxonomy/search?q=rotula")
    (hit,) = body["results"]
    assert (hit["label"], hit["matched_on"]) == ("Thalassiosira_morphotype1", "worms")
