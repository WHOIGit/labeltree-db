import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

MODELS = [
    "tree",
    "treerevision",
    "node",
    "nodeversion",
    "nodealias",
    "successor",
    "changeset",
    "change",
]


@pytest.mark.parametrize("model", MODELS)
def test_changelist_loads(admin_client, model):
    response = admin_client.get(reverse(f"admin:core_{model}_changelist"))
    assert response.status_code == 200


@pytest.mark.parametrize("model", [m for m in MODELS if m != "nodealias"])
def test_versioned_tables_are_read_only(admin_client, model):
    response = admin_client.get(reverse(f"admin:core_{model}_add"))
    assert response.status_code == 403


def test_aliases_are_editable(admin_client):
    response = admin_client.get(reverse("admin:core_nodealias_add"))
    assert response.status_code == 200
