"""Acceptance: NES2022_taxonomy imported against recorded WoRMS responses.

The expected warnings are in `expected_taxonomy_warnings.json` ({label: [warning]}
for every node with warnings). Regenerate after an intended change with
`UPDATE_ACCEPTANCE=1 pytest src/worms/tests/test_taxonomy_import.py`, then review the diff.
"""

import json
import os
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from api.serializers import RevisionView
from core.models import Tree
from core.tests.helpers import LABELDATA
from worms.models import WormsRecord, current_warnings

EXPECTED = Path(__file__).parent / "expected_taxonomy_warnings.json"

pytestmark = pytest.mark.django_db


def test_import_taxonomy(worms_http):
    worms_http.strict()  # every WoRMS response must be recorded
    call_command(
        "import_tree", str(LABELDATA / "NES2022_taxonomy.json"), "--tree", "NES2022_taxonomy",
        "--title", "NES2022 taxonomy", "--user", "importer", stdout=StringIO(),
    )  # fmt: skip
    tree = Tree.objects.get(id="NES2022_taxonomy")
    view = RevisionView(tree, 1)
    view.preload()
    assert len(view.state.nodes) == 245 and tree.revisions.get().number == 1

    anchored = [ref for ref, n in view.state.nodes.items() if n.aphia_id is not None]
    assert len(anchored) == 175
    assert all(view.detailed(ref)["worms_data"] for ref in anchored)
    # one record and one lineage per AphiaID, fetched once for save and publish together
    assert len(worms_http.calls) == 2 * 175
    assert WormsRecord.objects.count() == 175

    warnings = current_warnings(view.state.nodes)
    found = {
        view.state.nodes[ref].label: [w["warning"] for w in ws]
        for ref, ws in sorted(warnings.items())
        if ws
    }
    if os.environ.get("UPDATE_ACCEPTANCE"):
        EXPECTED.write_text(json.dumps(dict(sorted(found.items())), indent=2) + "\n")
    assert found == json.loads(EXPECTED.read_text())
