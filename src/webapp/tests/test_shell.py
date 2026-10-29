"""The web app shell: anonymous browsing, logins and CSP (spec: webapp, access-control)."""

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


def test_anonymous_browsing(site, taxonomy):
    page = site.open("/trees/taxonomy/")
    assert site.row("Chromista").is_visible()
    assert page.locator("#login-to-edit").is_visible()
    assert page.locator("#edit-button").count() == 0
    assert page.locator("#sync-button").count() == 0
    assert site.console.errors == [] and site.console.failed == []
