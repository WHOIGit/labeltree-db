"""Login rate limiting (django-axes) behind the reverse proxy."""

import pytest
from axes.models import AccessAttempt
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db

PROXY = "172.17.0.1"  # what gunicorn sees as REMOTE_ADDR behind Apache


@pytest.fixture
def staff():
    return User.objects.create_user("curator1", password="right-pw", is_staff=True)


def login(password, forwarded_for, username="curator1"):
    client = Client(REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=forwarded_for)
    response = client.post(reverse("admin:login"), {"username": username, "password": password})
    return response.status_code, client


def logged_in(client):
    return client.get(reverse("admin:index")).status_code == 200


def test_locked_out_after_five_failures(staff):
    statuses = [login("wrong", "128.128.1.5")[0] for _ in range(5)]
    assert statuses == [200, 200, 200, 200, 429]  # the fifth failure locks out
    status, client = login("right-pw", "128.128.1.5")
    assert status == 429 and not logged_in(client)


def test_other_addresses_are_not_locked_out(staff):
    for _ in range(5):
        login("wrong", "128.128.1.5")
    status, client = login("right-pw", "128.128.9.9")
    assert status == 302 and logged_in(client)


def test_success_resets_the_count(staff):
    for _ in range(4):
        login("wrong", "128.128.1.5")
    assert login("right-pw", "128.128.1.5")[0] == 302
    assert not AccessAttempt.objects.exists()


def test_spoofed_forwarded_for_counts_against_the_proxy(staff):
    """A client-supplied X-Forwarded-For entry can't spread failures over addresses."""
    for i in range(5):
        login("wrong", f"6.6.6.{i}, 128.128.1.5")
    assert AccessAttempt.objects.get().ip_address == PROXY
    assert login("right-pw", "6.6.6.99, 128.128.1.5")[0] == 429
