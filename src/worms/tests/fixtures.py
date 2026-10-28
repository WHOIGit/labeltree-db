"""Recorded WoRMS HTTP responses, so tests never call WoRMS.

`worms_http.json` maps a request path (with query string) to the raw response
WoRMS gave: `{"status": 200, "body": ...}`. `FixtureTransport` serves them. An
unrecorded request fails the test if `strict`, else gets `204 No Content` (WoRMS
has no such record), so made-up AphiaIDs in tests are harmless. src/conftest.py
installs a non-strict transport for every test.

To (re-)record, from src/ with network access:

    python -m worms.tests.fixtures 149122 148985 ... --search Chaetoceros --taxonomy

`--taxonomy` adds every AphiaID in labeldata/NES2022_taxonomy.json. Recording
merges into the existing file.
"""

import json
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parent / "worms_http.json"


def load() -> dict:
    return json.loads(FIXTURES.read_text()) if FIXTURES.exists() else {}


def _key(request: httpx.Request) -> str:
    path = request.url.path.removeprefix("/rest")
    return f"{path}?{request.url.query.decode()}" if request.url.query else path


class FixtureTransport(httpx.BaseTransport):
    """Serves recorded responses. `overrides` (same keys) replace or add responses;
    a callable value is called with the request. `calls` lists every key requested."""

    _recorded = None

    def __init__(self, overrides: dict | None = None, *, strict: bool = True):
        if FixtureTransport._recorded is None:
            FixtureTransport._recorded = load()
        self.responses = {**FixtureTransport._recorded, **(overrides or {})}
        self.strict = strict
        self.calls: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        key = _key(request)
        self.calls.append(key)
        if key not in self.responses:
            if self.strict:
                raise AssertionError(f"No recorded WoRMS response for {key}")
            return httpx.Response(204)
        entry = self.responses[key]
        if callable(entry):
            return entry(request)
        if entry["status"] == 204:
            return httpx.Response(204)
        return httpx.Response(entry["status"], json=entry["body"])


def _record(paths: list[str]):
    import time

    data = load()
    with httpx.Client(base_url="https://www.marinespecies.org/rest", timeout=30) as http:
        for path in paths:
            if path in data:
                continue
            response = http.get(path)
            response.raise_for_status()
            body = response.json() if response.status_code == 200 else None
            for raw in body if isinstance(body, list) else [body]:
                if isinstance(raw, dict):
                    raw.pop("citation", None)  # long, and never used
            data[path] = {"status": response.status_code, "body": body}
            print(response.status_code, path)
            time.sleep(0.2)
    save(data)


def save(data: dict):
    """One response per line, so re-recording gives readable diffs."""
    lines = [
        f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
        for k, v in sorted(data.items())
    ]
    FIXTURES.write_text("{\n" + ",\n".join(lines) + "\n}\n")


def _taxonomy_ids() -> list[int]:
    from core.tests.helpers import LABELDATA

    ids = []

    def walk(nodes):
        for node in nodes:
            if node.get("aphia_id") is not None:
                ids.append(node["aphia_id"])
            walk(node.get("children") or [])

    walk(json.loads((LABELDATA / "NES2022_taxonomy.json").read_text())["nodes"])
    return ids


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("aphia_ids", nargs="*", type=int)
    parser.add_argument("--search", action="append", default=[])
    parser.add_argument("--taxonomy", action="store_true")
    args = parser.parse_args()
    ids = args.aphia_ids + (_taxonomy_ids() if args.taxonomy else [])
    paths = []
    for aphia_id in dict.fromkeys(ids):
        paths += [f"/AphiaRecordByAphiaID/{aphia_id}", f"/AphiaClassificationByAphiaID/{aphia_id}"]
    for name in args.search:
        paths.append(f"/AphiaRecordsByName/{name}?like=true&marine_only=false&offset=1")
    _record(paths)
