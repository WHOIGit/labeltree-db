"""Browser tests: Playwright against Django's live server.

Chromium comes from the nix dev shell (PLAYWRIGHT_BROWSERS_PATH), launched by
path, since the Python playwright's own browser revision differs. Pages are
checked for console errors and CSP violations.
"""

import glob
import os

import pytest
from django.conf import settings
from django.test import Client

from api.tests.conftest import make_user
from core.models import Tree
from core.tests.helpers import add, publish_new_tree

# Playwright's sync API runs an event loop; the test's own ORM calls are still sync.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    found = glob.glob(
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "") + "/chromium-*/chrome-linux*/chrome"
    )
    if not found:
        pytest.skip("No Chromium in PLAYWRIGHT_BROWSERS_PATH; run inside nix develop.")
    return {**browser_type_launch_args, "executable_path": found[0]}


class Console:
    """Console errors and failed requests of a page."""

    def __init__(self, page):
        self.errors = []
        page.on(
            "console",
            lambda m: (
                m.type == "error"
                and "Failed to load resource" not in m.text
                and self.errors.append(m.text)
            ),
        )
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        # Failed requests by URL; tests that expect a refusal check `failed` themselves.
        self.failed = []
        page.on("response", lambda r: r.status >= 400 and self.failed.append(f"{r.status} {r.url}"))


@pytest.fixture
def console(page):
    return Console(page)


@pytest.fixture
def site(live_server, page, console):
    """Helpers bound to the live server and the page."""
    return Site(live_server.url, page, console)


class Site:
    def __init__(self, url, page, console):
        self.url, self.page, self.console = url, page, console

    def login(self, user):
        client = Client()
        client.force_login(user)
        cookie = client.cookies[settings.SESSION_COOKIE_NAME]
        self.page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie.value, "url": self.url}]
        )

    def open(self, path):
        self.page.goto(self.url + path)
        self.page.wait_for_load_state("networkidle")
        return self.page

    def row(self, label):
        return self.page.locator(f'.trow[data-label="{label}"]')


@pytest.fixture
def taxonomy(transactional_db):
    """Chromista > Bacillariophyceae > Chaetocerotaceae > Chaetoceros (148985) >
    Chaetoceros_didymus (149122); other > box. Records cached."""
    publish_new_tree(
        "taxonomy",
        add("new:1", "Chromista", aphia_id=7),
        add("new:2", "Bacillariophyceae", parent="new:1", aphia_id=148899),
        add("new:3", "Chaetocerotaceae", parent="new:2", aphia_id=148984),
        add("new:4", "Chaetoceros", parent="new:3", aphia_id=148985),
        add("new:5", "Chaetoceros_didymus", parent="new:4", aphia_id=149122,
            aliases=["Chaetoceros didymus"]),
        add("new:6", "other"),
        add("new:7", "box", parent="new:6"),
    )  # fmt: skip
    return Tree.objects.get(id="taxonomy")


@pytest.fixture
def drafter(transactional_db):
    return make_user("drafter1", roles={"amplify": "drafter"})


@pytest.fixture
def approver(transactional_db):
    return make_user("approver1", roles={"amplify": "approver"})
