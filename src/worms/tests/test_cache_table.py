"""The database cache is shared between server processes (WoRMS job status relies on it)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.cache import cache
from django.db import connection

SRC = Path(__file__).resolve().parents[2]


def run_in_other_process(code: str) -> str:
    """Run `code` in a fresh Django process against the test database."""
    env = {**os.environ, "POSTGRES_DB": connection.settings_dict["NAME"]}
    result = subprocess.run(
        [sys.executable, "manage.py", "shell", "--no-imports", "-c", code],
        cwd=SRC, env=env, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return result.stdout.strip()


@pytest.mark.django_db(transaction=True)
def test_value_written_here_is_read_in_another_process():
    cache.set("worms-job:probe", {"active": True, "done": 120, "total": 175})
    out = run_in_other_process(
        "from django.core.cache import cache; print(cache.get('worms-job:probe')['done'])"
    )
    assert out == "120"


@pytest.mark.django_db(transaction=True)
def test_value_written_in_another_process_is_read_here():
    run_in_other_process("from django.core.cache import cache; cache.set('worms-job:probe', 'x')")
    assert cache.get("worms-job:probe") == "x"
    cache.delete("worms-job:probe")
