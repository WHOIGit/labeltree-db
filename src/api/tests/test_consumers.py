"""Read-only consumers keep working without credentials (task 8.2): the calls
roi-db and datasetman make (design/api.md, Consumer guide), against both
NES2022 trees. Writes, validation and jobs need a login."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.test import Client

from core.tests.helpers import LABELDATA, TAGS, ids_by_label, org

pytestmark = pytest.mark.django_db


@pytest.fixture
def trees():
    for tree, path in (
        ("NES2022_tags", TAGS),
        ("NES2022_taxonomy", LABELDATA / "NES2022_taxonomy.json"),
    ):
        call_command(
            "import_tree",
            str(path),
            tree=tree,
            title=tree,
            org=org(),
            stdout=StringIO(),
            stderr=StringIO(),
        )


def read_calls(tree: str, label: str, node: int) -> list[str]:
    return [
        "/trees",
        f"/trees/{tree}",
        f"/trees/{tree}/revisions",
        f"/trees/{tree}/nodes/{label}",
        f"/trees/{tree}/nodes/{label}?rev=1",
        f"/trees/{tree}/search?q={label[:5]}",
        f"/trees/{tree}/nodes?ids={node}",
        f"/trees/{tree}/diff?from=1&to=1",
        f"/trees/{tree}/nodes_as_tree",
        f"/trees/{tree}/export",
        f"/trees/{tree}/export_flat",
        f"/nodes/{node}",
        f"/nodes/{node}/ancestors",
        f"/nodes/{node}/descendants?rev=1",
        f"/nodes/{node}/versions",
        f"/nodes/{node}/aliases",
        f"/nodes/{node}/description",
        f"/nodes/{node}/warning_history",
        f"/worms/warnings?tree={tree}",
        "/orgs",
    ]


@pytest.mark.parametrize(
    "tree,label", [("NES2022_tags", "interaction"), ("NES2022_taxonomy", "Chaetoceros")]
)
def test_reads_need_no_credentials(trees, tree, label):
    node = ids_by_label(tree)[label]
    client = Client()
    for path in read_calls(tree, label, node):
        response = client.get(f"/api/v1{path}")
        assert response.status_code == 200, path


@pytest.mark.parametrize(
    "tree,label", [("NES2022_tags", "interaction"), ("NES2022_taxonomy", "Chaetoceros")]
)
def test_writes_validation_and_jobs_need_a_login(trees, tree, label, worms_http):
    node = ids_by_label(tree)[label]
    changes = [{"op": "edit", "node": node, "label": "x"}]
    calls = [
        ("post", "/changesets/validate", {"tree": tree, "base_rev": 1, "changes": changes}),
        ("post", "/changesets", {"tree": tree, "base_rev": 1, "changes": changes}),
        ("get", f"/changesets?tree={tree}", None),
        ("post", "/worms/jobs", {"kind": "sync_tree", "tree": tree}),
        ("post", "/worms/jobs", {"kind": "fetch", "org": "amplify", "aphia_ids": [1]}),
        ("post", f"/nodes/{node}/aliases", {"alias": "x"}),
        ("put", f"/nodes/{node}/description", {"description": "x"}),
        ("get", "/worms/search?name=Chaetoceros", None),
    ]
    worms_http.calls.clear()
    for method, path, body in calls:
        kwargs = {"data": body, "content_type": "application/json"} if body is not None else {}
        response = getattr(Client(), method)(f"/api/v1{path}", **kwargs)
        assert response.status_code == 401, path
    assert worms_http.calls == []
