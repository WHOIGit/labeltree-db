"""The service's own snapshot of the WoRMS records it uses (spec: worms-records).

A fetched record whose content (record or lineage) differs from the cached rows
for its AphiaID becomes a new row; an unchanged one only bumps `fetched_at`. The
newest row is the one fetched most recently, and older rows are kept, so the
record a node was checked against stays available.
"""

from django.db import models


class WormsRecord(models.Model):
    aphia_id = models.IntegerField()
    # Name, rank, status, valid_AphiaID, url, modified ... and `lineage`: the
    # classification as [{AphiaID, rank, scientificname}], top level first, ending
    # with the record; null for a search hit whose lineage isn't fetched yet.
    # `record` is null when WoRMS has no record for the AphiaID.
    record = models.JSONField(null=True, blank=True)
    # SHA-256 of `record` (including lineage), for de-duplication.
    content_hash = models.CharField(max_length=64)
    worms_modified = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["aphia_id", "content_hash"], name="wormsrecord_content_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["aphia_id", "-fetched_at"], name="wormsrecord_newest_idx"),
        ]

    def __str__(self):
        name = (self.record or {}).get("scientificname", "(no WoRMS record)")
        return f"{self.aphia_id} {name}"

    @property
    def complete(self) -> bool:
        """Usable for checks: a full record with its lineage, or a known absence."""
        return self.record is None or self.record.get("lineage") is not None


class NodeWarnings(models.Model):
    """A node's WoRMS warnings over time. A row is added only when the warnings
    differ from the node's newest row (including [] when they clear); the newest
    row is the node's current set. Warnings are never versioned."""

    node = models.ForeignKey("core.Node", on_delete=models.PROTECT, related_name="warning_rows")
    # [{warning, detail}], in the order of worms.checks.WARNINGS
    warnings = models.JSONField()
    computed_at = models.DateTimeField()

    class Meta:
        verbose_name_plural = "node warnings"
        indexes = [models.Index(fields=["node", "-computed_at"], name="nodewarnings_newest_idx")]

    def __str__(self):
        return f"{self.node_id}: {', '.join(w['warning'] for w in self.warnings) or 'none'}"


def current_warnings(node_ids) -> dict[int, list[dict]]:
    """The newest warning row per node; nodes without rows are absent."""
    rows = (
        NodeWarnings.objects.filter(node_id__in=list(node_ids))
        .order_by("node_id", "-computed_at", "-id")
        .distinct("node_id")
        .values_list("node_id", "warnings")
    )
    return dict(rows)
