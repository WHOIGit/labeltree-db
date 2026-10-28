"""Writing nodes' current WoRMS warnings (spec: worms-placement-checks, "Warning
history storage"). Used by publish and drift, inside their transactions."""

from django.utils import timezone

from .models import NodeWarnings, current_warnings


def record_warnings(results: dict, now=None) -> int:
    """Add a NodeWarnings row for each node whose warnings differ from its newest
    row. `results` is {node_id: [warning] or None}; None (unavailable) keeps the
    node's current row. A node with no row yet and no warnings gets none.
    Returns the number of rows added."""
    now = now or timezone.now()
    known = {ref: ws for ref, ws in results.items() if ws is not None}
    current = current_warnings(known)
    rows = [
        NodeWarnings(node_id=ref, warnings=ws, computed_at=now)
        for ref, ws in known.items()
        if ws != current.get(ref, [])
    ]
    NodeWarnings.objects.bulk_create(rows)
    return len(rows)
