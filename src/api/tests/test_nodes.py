"""/nodes/{id} endpoints (spec: node-read-api).

taxonomy ids: 1 Chromista, 2 Bacillariophyceae, 3 Chaetocerotaceae, 4 Chaetoceros,
5 Chaetoceros_didymus, 6 other.
"""

from core.tests.helpers import add, deprecate, edit, move, publish

LITE_KEYS = ["id", "label", "version", "num_children", "children"]
DETAILED_KEYS = [
    "id", "version", "tree", "rev", "label", "description", "aliases", "aphia_id", "worms_data",
    "worms_warnings", "tree_depth", "num_children", "parent", "children", "created_in_rev",
    "deprecated_in_rev", "successors",
]  # fmt: skip


# --- 8.1 shapes -------------------------------------------------------------------------


def test_detailed_shape(get, taxonomy):
    _, node, _ = get("/nodes/5")
    assert list(node) == DETAILED_KEYS
    assert node["aliases"] == [{"id": node["aliases"][0]["id"], "alias": "Chaetoceros didymus"}]
    assert node["parent"] == {
        "id": 4, "label": "Chaetoceros", "version": 1, "num_children": 1, "children": None,
    }  # fmt: skip
    assert (node["tree_depth"], node["num_children"], node["children"]) == (4, 0, [])


def test_lite_children_are_unexpanded(get, taxonomy):
    _, node, _ = get("/nodes/4")
    assert [list(c) for c in node["children"]] == [LITE_KEYS]
    assert node["children"][0]["children"] is None


def test_top_level_node(get, taxonomy):
    _, node, _ = get("/nodes/1")
    assert node["parent"] is None and node["tree_depth"] == 0


def test_worms_fields_before_worms_integration(get, taxonomy):
    _, node, _ = get("/nodes/5")
    assert (node["aphia_id"], node["worms_data"], node["worms_warnings"]) == (149122, None, [])


def test_dropempty_on_nested_nodes(get, taxonomy):
    _, body, _ = get("/nodes/4/descendants?dropempty=true")
    leaf = body["node"]["children"][0]
    assert "children" not in leaf  # [] for an expanded leaf is empty too
    assert leaf["num_children"] == 0


# --- 8.2 get a node ----------------------------------------------------------------------


def test_node_at_past_revision(get, taxonomy):
    publish(taxonomy, edit(5, label="C_didymus"))
    _, node, _ = get("/nodes/5?rev=1")
    assert (node["label"], node["rev"], node["version"]) == ("Chaetoceros_didymus", 1, 1)
    _, node, _ = get("/nodes/5")
    assert (node["label"], node["rev"], node["version"]) == ("C_didymus", 2, 2)


def test_lifetime_fields_describe_the_whole_node(get, taxonomy):
    publish(taxonomy, add("new:1", "Ch_a", parent=4), deprecate(5, successors=["new:1"]))
    _, node, _ = get("/nodes/5?rev=1")
    assert (node["rev"], node["deprecated_in_rev"], node["successors"]) == (1, 2, [7])


def test_deprecation_record(get, taxonomy):
    publish(taxonomy, add("new:1", "Ch_a", parent=4), add("new:2", "Ch_b", parent=4))
    publish(taxonomy, deprecate(5, successors=[7, 8]))
    publish(taxonomy, edit(6, description="d"))
    status, body, _ = get("/nodes/5?rev=4")
    assert status == 200
    assert body == {
        "id": 5, "tree": "taxonomy", "rev": 4, "label": "Chaetoceros_didymus",
        "last_version": 1, "deprecated_in_rev": 3, "successors": [7, 8],
    }  # fmt: skip
    for path in ("/nodes/5/ancestors", "/nodes/5/descendants"):
        assert get(path)[1]["last_version"] == 1


def test_node_not_yet_created(get, taxonomy):
    publish(taxonomy, add("new:1", "late"))
    status, body, _ = get("/nodes/7?rev=1")
    assert status == 404 and body["error"] == "not_found"


# --- 8.3 ancestors and descendants ---------------------------------------------------------


def test_path_to_a_species(get, taxonomy):
    _, body, _ = get("/nodes/5/ancestors")
    assert body["node"]["label"] == "Chaetoceros_didymus" and body["node"]["children"] is None
    assert [a["label"] for a in body["ancestors"]] == [
        "Chromista", "Bacillariophyceae", "Chaetocerotaceae", "Chaetoceros",
    ]  # fmt: skip
    assert all(a["children"] is None for a in body["ancestors"])
    assert (body["tree"], body["rev"]) == ("taxonomy", 1)


def test_ancestors_of_top_level_node(get, taxonomy):
    assert get("/nodes/1/ancestors")[1]["ancestors"] == []


def test_descendants_depth_1(get, taxonomy):
    _, body, _ = get("/nodes/2/descendants?depth=1")
    (child,) = body["node"]["children"]
    assert child["label"] == "Chaetocerotaceae"
    assert child["children"] is None and child["num_children"] == 1


def test_full_subtree(get, taxonomy):
    _, body, _ = get("/nodes/1/descendants")
    labels, node = [], body["node"]
    while node["children"]:
        (node,) = node["children"]
        labels.append(node["label"])
    assert labels[-1] == "Chaetoceros_didymus" and node["children"] == []


def test_descendants_follow_revision(get, taxonomy):
    publish(taxonomy, move(4, 3, 6))
    assert get("/nodes/3/descendants?rev=1")[1]["node"]["num_children"] == 1
    assert get("/nodes/3/descendants")[1]["node"]["children"] == []


# --- 8.4 versions -------------------------------------------------------------------------------


def test_version_history_of_deprecated_node(get, taxonomy):
    publish(taxonomy, edit(5, description="x"))  # rev 2: v2
    publish(taxonomy, edit(6, description="y"))  # rev 3
    publish(taxonomy, edit(5, description="z"))  # rev 4: v3
    publish(taxonomy, deprecate(5))  # rev 5
    _, body, response = get("/nodes/5/versions")
    assert body == {
        "id": 5, "tree": "taxonomy", "created_in_rev": 1, "deprecated_in_rev": 5,
        "versions": [
            {"version": 1, "valid_from_rev": 1, "valid_to_rev": 2},
            {"version": 2, "valid_from_rev": 2, "valid_to_rev": 4},
            {"version": 3, "valid_from_rev": 4, "valid_to_rev": 5},
        ],
    }  # fmt: skip
    assert "X-Tree-Revision" not in response


def test_rev_outside_version_range(get, taxonomy):
    publish(taxonomy, edit(5, label="Cd"))  # rev 2: v2
    publish(taxonomy, edit(6, label="o"))  # rev 3
    publish(taxonomy, edit(5, label="Cd2"))  # rev 4: v3; v2 valid for 2-3
    assert get("/nodes/5/versions/2?rev=4")[0] == 400
    assert get("/nodes/5/versions/2?rev=1")[0] == 400
    assert get("/nodes/5/versions/9")[0] == 404


def test_children_change_within_one_version(get, taxonomy):
    publish(taxonomy, edit(4, description="genus"))  # rev 2: Chaetoceros v2
    publish(taxonomy, edit(5, label="C_didymus"))  # rev 3: child renamed, no bump
    publish(taxonomy, edit(4, description="Genus"))  # rev 4: v3
    _, at2, _ = get("/nodes/4/versions/2?rev=2")
    _, at3, _ = get("/nodes/4/versions/2?rev=3")
    assert at2["version"] == at3["version"] == 2
    assert at2["children"][0]["label"] == "Chaetoceros_didymus"
    assert at3["children"][0]["label"] == "C_didymus"
    _, default, response = get("/nodes/4/versions/2")
    assert default["rev"] == 3 and response["X-Tree-Revision"] == "3"
