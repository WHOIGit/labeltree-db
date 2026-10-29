import pytest

pytestmark = pytest.mark.django_db(transaction=True)


def test_explore(site, taxonomy, drafter):
    site.login(drafter)
    page = site.open("/trees/taxonomy/")
    page.click("#edit-button")
    page.click("#new-draft")
    page.click("text=Expand all")
    site.row("Chaetoceros").locator(".kebab").click()
    page.click('#node-menu [data-action="child"]')
    page.fill("#f-label", "Chaetoceros_debilis")
    page.fill("#f-aphia", "149219")
    page.click("#f-submit")
    print("status", page.inner_text("#status"))
    page.click("#validate-button")
    page.wait_for_timeout(3000)
    page.screenshot(path="/tmp/explore.png", full_page=True)
    print("tabs", page.inner_text("#tabs"))
    print(
        "save disabled",
        page.is_disabled("#save-button"),
        page.get_attribute("#save-button", "title"),
    )
    page.click("#save-button")
    page.wait_for_timeout(1000)
    print("status", page.inner_text("#status"), page.inner_text("#draft-id"))
    print("errors", site.console.errors, site.console.failed)
