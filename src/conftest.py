"""Shared test setup: no test ever calls WoRMS."""

import pytest

from worms import records
from worms.client import WormsClient
from worms.tests.fixtures import FixtureTransport


class WormsHTTP:
    """Recorded WoRMS responses for the test. `override` replaces or adds responses
    (see FixtureTransport); `calls` lists the requested paths."""

    def __init__(self):
        self.transport = FixtureTransport(strict=False)
        self.waits = []

    def override(self, responses: dict):
        self.transport.responses.update(responses)

    def strict(self):
        self.transport.strict = True

    @property
    def calls(self):
        return self.transport.calls

    def client(self, **options):
        return WormsClient(transport=self.transport, **options)


@pytest.fixture(autouse=True)
def worms_http(monkeypatch):
    http = WormsHTTP()
    monkeypatch.setattr(records, "default_client", http.client)
    # Any other client built without a transport gets the recorded one too.
    original = WormsClient.__init__

    def init(self, *, transport=None, sleep=None, **options):
        original(
            self, transport=transport or http.transport, sleep=sleep or http.waits.append,
            **options,
        )  # fmt: skip

    monkeypatch.setattr(WormsClient, "__init__", init)
    return http
