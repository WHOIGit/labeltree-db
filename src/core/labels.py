import re

from django.db import connection

LABEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
_LABEL_RE = re.compile(LABEL_PATTERN)


def is_machine_safe(label) -> bool:
    """True if `label` is usable as a node label: no spaces, slashes or leading punctuation."""
    return isinstance(label, str) and _LABEL_RE.fullmatch(label) is not None


def allocate_node_ids(count: int) -> list[int]:
    """Draw `count` new node ids from the global sequence. Ids are never reused."""
    if count == 0:
        return []
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval('core_node_id_seq') FROM generate_series(1, %s)", [count])
        return [row[0] for row in cursor.fetchall()]
