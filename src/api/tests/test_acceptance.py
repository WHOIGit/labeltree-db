"""Acceptance on NES2022_tags (task 10.1).

Imports the tags tree, publishes a second revision (rename, move, deprecate
with successor), and compares read responses with the JSON fixtures in
`acceptance/`. Timestamps and changeset ids vary between runs and are masked.

Regenerate the fixtures after an intended change with
`UPDATE_ACCEPTANCE=1 pytest src/api/tests/test_acceptance.py`, then review the diff.

NES2022_tags ids (file order): 2 interaction, 5 external_pennate, 9 organism_state,
12 fusing, 13 infected, 14 mating, 15 stress, 16 parasite.
"""

import json
import os
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from core.models import Tree
from core.tests.helpers import TAGS, deprecate, edit, move, publish

FIXTURES = Path(__file__).parent / "acceptance"
MASKED = {"published_at", "changeset"}

REQUESTS = {
    "trees": "/trees",
    "tree": "/trees/NES2022_tags",
    "node_moved": "/nodes/13",
    "node_deprecated": "/nodes/12",
    "node_deprecated_at_rev1": "/nodes/12?rev=1",
    "ancestors": "/nodes/13/ancestors",
    "descendants": "/nodes/9/descendants",
    "versions": "/nodes/9/versions",
    "revisions": "/trees/NES2022_tags/revisions",
    "changes": "/trees/NES2022_tags/revisions/2/changes",
    "diff": "/trees/NES2022_tags/diff?from=1&to=2",
    "export": "/trees/NES2022_tags/export",
    "search_prefix": "/trees/NES2022_tags/search?q=infect",
    "search_renamed": "/trees/NES2022_tags/search?q=pennate",
}


def mask(value):
    if isinstance(value, dict):
        return {k: "<masked>" if k in MASKED else mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


@pytest.fixture
def two_revisions():
    call_command(
        "import_tree", str(TAGS), tree="NES2022_tags", title="NES2022 tags", user="op",
        stdout=StringIO(),
    )  # fmt: skip
    publish(
        Tree.objects.get(id="NES2022_tags"),
        edit(5, label="external_pennate_diatom"),
        move(13, 9, 16),
        deprecate(12, successors=[14]),
        notes="Rename, move infected under parasite, fold fusing into mating",
        author="dana",
        published_by="op",
    )


@pytest.mark.parametrize("name", REQUESTS)
def test_acceptance(get, two_revisions, name):
    status, body, _ = get(REQUESTS[name])
    assert status == 200
    path = FIXTURES / f"{name}.json"
    if os.environ.get("UPDATE_ACCEPTANCE"):
        FIXTURES.mkdir(exist_ok=True)
        path.write_text(json.dumps(mask(body), indent=2) + "\n")
    assert mask(body) == json.loads(path.read_text())
