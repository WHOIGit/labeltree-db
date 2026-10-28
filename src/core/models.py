"""Versioned label trees.

A tree's state at revision r is every NodeVersion of that tree with
valid_from_rev <= r < valid_to_rev (null valid_to_rev = current). Revision
numbers are stored as plain ints, not foreign keys, because range comparisons
are numeric and always within one tree. Nothing is ever deleted.
"""

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import IntegerRangeField, RangeOperators
from django.db import models
from django.db.models import F, Func, Q
from django.utils import timezone


class Tree(models.Model):
    id = models.SlugField(primary_key=True, max_length=100)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    def __str__(self):
        return self.id


class TreeRevision(models.Model):
    tree = models.ForeignKey(Tree, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    changeset = models.OneToOneField("Changeset", on_delete=models.PROTECT, related_name="revision")
    published_at = models.DateTimeField()
    published_by = models.CharField(max_length=150)
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tree", "number"], name="treerevision_tree_number_uniq"
            ),
        ]
        ordering = ["tree", "number"]

    def __str__(self):
        return f"{self.tree_id}@{self.number}"


class Node(models.Model):
    # Assigned from the core_node_id_seq sequence at publish, global across trees.
    id = models.BigIntegerField(primary_key=True)
    tree = models.ForeignKey(Tree, on_delete=models.PROTECT, related_name="nodes")
    created_in_rev = models.PositiveIntegerField()
    # Null while in the tree; otherwise the first revision it is absent from.
    deprecated_in_rev = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return str(self.id)


class IntRange(Func):
    """int4range(lower, upper): a null upper bound is unbounded."""

    function = "int4range"
    output_field = IntegerRangeField()


class NodeVersion(models.Model):
    node = models.ForeignKey(Node, on_delete=models.PROTECT, related_name="versions")
    # Denormalised from node.tree so revision reads and label lookups need no join.
    tree = models.ForeignKey(Tree, on_delete=models.PROTECT, related_name="+")
    version = models.PositiveIntegerField()
    valid_from_rev = models.PositiveIntegerField()
    valid_to_rev = models.PositiveIntegerField(null=True, blank=True)
    label = models.CharField(max_length=255)
    parent = models.ForeignKey(
        Node, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    aphia_id = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["tree", "valid_from_rev"], name="nodeversion_tree_from_idx"),
            models.Index(fields=["parent", "valid_from_rev"], name="nodeversion_parent_from_idx"),
            models.Index(fields=["tree", "label"], name="nodeversion_tree_label_idx"),
            models.Index(fields=["aphia_id"], name="nodeversion_aphia_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["node", "version"], name="nodeversion_node_version_uniq"
            ),
            models.UniqueConstraint(
                fields=["node"],
                condition=Q(valid_to_rev__isnull=True),
                name="nodeversion_one_open_version",
            ),
            models.CheckConstraint(
                condition=Q(valid_to_rev__isnull=True) | Q(valid_to_rev__gt=F("valid_from_rev")),
                name="nodeversion_nonempty_range",
            ),
            # Safety net behind the engine's own check: no two versions in one
            # tree hold the same label over overlapping revision ranges.
            ExclusionConstraint(
                name="nodeversion_label_unique_per_rev",
                index_type="gist",
                expressions=[
                    (F("tree"), RangeOperators.EQUAL),
                    (F("label"), RangeOperators.EQUAL),
                    (IntRange(F("valid_from_rev"), F("valid_to_rev")), RangeOperators.OVERLAPS),
                ],
            ),
        ]

    def __str__(self):
        return f"{self.node_id} v{self.version}"


class NodeAlias(models.Model):
    """Unversioned search aid; removal marks the row instead of deleting it."""

    node = models.ForeignKey(Node, on_delete=models.PROTECT, related_name="aliases")
    alias = models.TextField()
    added_by = models.CharField(max_length=150)
    added_at = models.DateTimeField()
    removed_by = models.CharField(max_length=150, null=True, blank=True)  # noqa: DJ001 null = current
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "node aliases"
        constraints = [
            models.UniqueConstraint(
                fields=["node", "alias"],
                condition=Q(removed_at__isnull=True),
                name="nodealias_current_uniq",
            ),
        ]

    def __str__(self):
        return self.alias


class NodeDescription(models.Model):
    """Unversioned description history; the newest entry is the node's description.

    Setting "" clears it. Entries are never changed or deleted.
    """

    node = models.ForeignKey(Node, on_delete=models.PROTECT, related_name="descriptions")
    description = models.TextField(blank=True)
    added_by = models.CharField(max_length=150)
    added_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["node", "-added_at"], name="nodedescription_latest_idx")]

    def __str__(self):
        return self.description[:50]


def current_descriptions(node_ids) -> dict[int, str]:
    """The newest description per node; nodes without entries are absent."""
    rows = (
        NodeDescription.objects.filter(node_id__in=list(node_ids))
        .order_by("node_id", "-added_at", "-id")
        .distinct("node_id")
        .values_list("node_id", "description")
    )
    return dict(rows)


class Successor(models.Model):
    deprecated_node = models.ForeignKey(
        Node, on_delete=models.PROTECT, related_name="successor_links"
    )
    successor_node = models.ForeignKey(Node, on_delete=models.PROTECT, related_name="+")
    # Keeps the order given in the deprecate change.
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["deprecated_node", "successor_node"], name="successor_pair_uniq"
            ),
        ]
        ordering = ["deprecated_node", "position"]

    def __str__(self):
        return f"{self.deprecated_node_id} -> {self.successor_node_id}"


class Changeset(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"
        DISCARDED = "discarded"

    # Null for a new-tree changeset until it is published.
    tree = models.ForeignKey(
        Tree, on_delete=models.PROTECT, null=True, blank=True, related_name="changesets"
    )
    new_tree_id = models.SlugField(max_length=100, null=True, blank=True)  # noqa: DJ001
    new_tree_title = models.CharField(max_length=200, blank=True, default="")
    new_tree_description = models.TextField(blank=True, default="")
    state = models.CharField(max_length=10, choices=State.choices, default=State.DRAFT)
    # Null for a new-tree changeset.
    base_rev = models.PositiveIntegerField(null=True, blank=True)
    author = models.CharField(max_length=150)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(tree__isnull=False) | Q(new_tree_id__isnull=False),
                name="changeset_has_tree_or_new_tree",
            ),
        ]

    def __str__(self):
        return f"changeset {self.pk} ({self.state})"

    @property
    def tree_key(self):
        """The tree this changeset targets: existing or proposed."""
        return self.tree_id or self.new_tree_id


class Change(models.Model):
    class Op(models.TextChoices):
        ADD = "add"
        EDIT = "edit"
        MOVE = "move"
        DEPRECATE = "deprecate"

    changeset = models.ForeignKey(Changeset, on_delete=models.PROTECT, related_name="changes")
    seq = models.PositiveIntegerField()
    op = models.CharField(max_length=10, choices=Op.choices)
    group = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001 null = ungrouped
    payload = models.JSONField()
    # WoRMS warnings this change would cause, [{warning, node, detail}], or
    # "unavailable" if WoRMS couldn't be reached; refreshed on save and publish.
    checks = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["changeset", "seq"], name="change_changeset_seq_uniq"),
        ]
        ordering = ["changeset", "seq"]

    def __str__(self):
        return f"{self.changeset_id}#{self.seq} {self.op}"
