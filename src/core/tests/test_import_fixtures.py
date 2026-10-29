"""The server and browser import parsers agree on the shared fixtures
(core/tests/import_fixtures; the browser side is static/app/tests)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.importer import ImportFormatError, expand_import

FIXTURES = sorted((Path(__file__).parent / "import_fixtures").glob("*.json"))
STATIC_TESTS = Path(__file__).resolve().parents[2] / "static" / "app" / "tests"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_server_parser(path):
    case = json.loads(path.read_text())
    options = case["options"]
    if "error" in case:
        with pytest.raises(ImportFormatError) as info:
            expand_import(case["input"], **options)
        assert info.value.position == case["error"]
    else:
        assert expand_import(case["input"], **options) == case["expected"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is in the nix dev shell")
def test_browser_expanders():
    """Runs the browser's expander tests, including the same fixtures."""
    result = subprocess.run(
        ["node", "--test", *map(str, sorted(STATIC_TESTS.glob("*.test.mjs")))],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
