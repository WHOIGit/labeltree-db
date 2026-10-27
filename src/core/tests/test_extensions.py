import pytest
from django.db import connection


@pytest.mark.django_db
def test_postgres_extensions_installed():
    with connection.cursor() as cursor:
        cursor.execute("SELECT extname FROM pg_extension")
        installed = {row[0] for row in cursor.fetchall()}
    assert {"btree_gist", "pg_trgm"} <= installed
