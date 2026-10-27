"""Changeset lifecycle: save (reduce, then store), discard, rebase and publish.

Publishing is the only way tree data changes. It runs in one transaction that
first takes a per-tree advisory lock, so concurrent publishes on a tree are
refused instead of queued, and a crashed publish never leaves the tree locked.
"""

from dataclasses import dataclass

from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from .engine import (
    ChangeSpec,
    CheckResult,
    TreeState,
    check_changes,
    is_placeholder,
    load_state,
    reduce_changes,
    specs_from_dicts,
)
from .labels import allocate_node_ids
from .models import Change, Changeset, Node, NodeAlias, NodeVersion, Successor, Tree, TreeRevision


class ChangesetError(Exception):
    """A refused changeset operation. `error` is the machine-readable code."""

    def __init__(self, error: str, detail: str, errors: list[dict] | None = None):
        super().__init__(detail)
        self.error = error
        self.detail = detail
        self.errors = errors or []


@dataclass
class NewTree:
    id: str
    title: str
    description: str = ""


def latest_rev(tree_id: str) -> int | None:
    return TreeRevision.objects.filter(tree_id=tree_id).aggregate(m=Max("number"))["m"]


def base_state(changeset: Changeset) -> TreeState:
    if changeset.base_rev is None:
        return TreeState(changeset.new_tree_id, 0)
    return load_state(changeset.tree_id, changeset.base_rev)


def stored_specs(changeset: Changeset) -> list[ChangeSpec]:
    return [
        ChangeSpec(seq=c.seq, op=c.op, payload=c.payload, group=c.group)
        for c in changeset.changes.order_by("seq")
    ]


def _store_changes(changeset: Changeset, specs: list[ChangeSpec]):
    changeset.changes.all().delete()
    Change.objects.bulk_create(
        Change(changeset=changeset, seq=s.seq, op=s.op, group=s.group, payload=s.payload)
        for s in specs
    )


def _require_draft(changeset: Changeset):
    if changeset.state != Changeset.State.DRAFT:
        raise ChangesetError(
            "not_draft", f"Changeset {changeset.pk} is {changeset.state}, not a draft."
        )


def _check_base_rev(tree_id: str, base_rev):
    latest = latest_rev(tree_id)
    if not isinstance(base_rev, int) or not 1 <= base_rev <= (latest or 0):
        raise ChangesetError(
            "invalid_base_rev", f"Tree {tree_id} has no revision {base_rev}; latest is {latest}."
        )


# --- Save, discard, rebase -----------------------------------------------------


@transaction.atomic
def create_changeset(
    *,
    author: str,
    changes: list[dict],
    tree: Tree | None = None,
    base_rev: int | None = None,
    new_tree: NewTree | None = None,
    notes: str = "",
) -> Changeset:
    """Save a new draft: either against `tree` at `base_rev`, or for `new_tree`."""
    if (tree is None) == (new_tree is None):
        raise ValueError("Give exactly one of tree or new_tree.")
    if tree is not None:
        _check_base_rev(tree.id, base_rev)
        changeset = Changeset(tree=tree, base_rev=base_rev, author=author, notes=notes)
    else:
        changeset = Changeset(
            new_tree_id=new_tree.id,
            new_tree_title=new_tree.title,
            new_tree_description=new_tree.description,
            author=author,
            notes=notes,
        )
    changeset.save()
    _store_changes(changeset, reduce_changes(base_state(changeset), specs_from_dicts(changes)))
    return changeset


@transaction.atomic
def update_changeset(
    changeset: Changeset, *, changes: list[dict] | None = None, notes=None, base_rev=None
) -> Changeset:
    """Replace a draft's changes, notes or base revision; changes are reduced on save."""
    changeset = Changeset.objects.select_for_update().get(pk=changeset.pk)
    _require_draft(changeset)
    if base_rev is not None:
        if changeset.tree_id is None:
            raise ChangesetError("invalid_base_rev", "A new-tree changeset has no base revision.")
        _check_base_rev(changeset.tree_id, base_rev)
        changeset.base_rev = base_rev
    if notes is not None:
        changeset.notes = notes
    changeset.save()
    specs = specs_from_dicts(changes) if changes is not None else stored_specs(changeset)
    _store_changes(changeset, reduce_changes(base_state(changeset), specs))
    return changeset


@transaction.atomic
def discard_changeset(changeset: Changeset) -> Changeset:
    changeset = Changeset.objects.select_for_update().get(pk=changeset.pk)
    _require_draft(changeset)
    changeset.state = Changeset.State.DISCARDED
    changeset.save()
    return changeset


def rebase_changeset(changeset: Changeset) -> CheckResult:
    """Move a draft onto the latest revision and recheck it. Returns the check result."""
    if changeset.tree_id is None:
        raise ChangesetError("invalid_base_rev", "A new-tree changeset has no base revision.")
    changeset = update_changeset(changeset, base_rev=latest_rev(changeset.tree_id))
    return check_changeset(changeset)


def check_changeset(changeset: Changeset) -> CheckResult:
    """Structural check of a stored changeset against its own base revision."""
    return check_changes(base_state(changeset), stored_specs(changeset))


# --- Publish -------------------------------------------------------------------


def _take_publish_lock(tree_key: str):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", [f"publish:{tree_key}"])
        if not cursor.fetchone()[0]:
            raise ChangesetError(
                "publish_in_progress", f"Another publish on tree {tree_key} is in progress."
            )


def _rewrite(value, ids: dict):
    if isinstance(value, list):
        return [_rewrite(v, ids) for v in value]
    return ids.get(value, value) if is_placeholder(value) else value


def _rewrite_payload(payload: dict, ids: dict) -> dict:
    refs = ("node", "parent", "from_parent", "to_parent", "successors")
    return {k: _rewrite(v, ids) if k in refs else v for k, v in payload.items()}


def publish_changeset(changeset: Changeset, *, published_by: str, notes=None) -> TreeRevision:
    """Publish a draft as its tree's next revision (or a new tree's revision 1).

    Refused with ChangesetError: publish_in_progress, not_draft, tree_exists,
    stale_base, or structural (with the per-change errors, including
    empty_changeset).
    """
    with transaction.atomic():
        # First statement of the transaction; released when it commits or rolls back.
        _take_publish_lock(changeset.tree_key)
        changeset = Changeset.objects.select_for_update().get(pk=changeset.pk)
        _require_draft(changeset)

        if changeset.tree_id is None:
            if Tree.objects.filter(pk=changeset.new_tree_id).exists():
                raise ChangesetError("tree_exists", f"Tree {changeset.new_tree_id} already exists.")
            number = 1
        else:
            latest = latest_rev(changeset.tree_id)
            if changeset.base_rev != latest:
                raise ChangesetError(
                    "stale_base",
                    f"Base revision {changeset.base_rev} is behind latest revision {latest}.",
                )
            number = latest + 1

        base = base_state(changeset)
        result = check_changes(base, stored_specs(changeset))
        if result.errors:
            raise ChangesetError(
                "structural",
                f"The changeset has {len(result.errors)} structural error(s).",
                result.errors,
            )
        return _write_revision(changeset, base, result, number, published_by, notes)


def _write_revision(changeset, base, result: CheckResult, number, published_by, notes):
    now = timezone.now()
    if changeset.tree_id is None:
        tree = Tree.objects.create(
            id=changeset.new_tree_id,
            title=changeset.new_tree_title,
            description=changeset.new_tree_description,
        )
    else:
        tree = changeset.tree

    adds = [c for c in result.reduced if c.op == "add"]
    ids = dict(zip([c.node for c in adds], allocate_node_ids(len(adds)), strict=True))
    final = result.state

    def real(ref):
        return ids.get(ref, ref)

    revision = TreeRevision.objects.create(
        tree=tree,
        number=number,
        changeset=changeset,
        published_at=now,
        published_by=published_by,
        notes=changeset.notes if notes is None else notes,
    )
    Node.objects.bulk_create(Node(id=ids[c.node], tree=tree, created_in_rev=number) for c in adds)

    # Close superseded versions before opening new ones, so a label handed
    # from one node to another never overlaps in the exclusion constraint.
    closing = [real(vc.node) for vc in result.version_changes if vc.from_version is not None]
    NodeVersion.objects.filter(node_id__in=closing, valid_to_rev__isnull=True).update(
        valid_to_rev=number
    )
    NodeVersion.objects.bulk_create(
        NodeVersion(
            node_id=real(vc.node),
            tree=tree,
            version=vc.to_version,
            valid_from_rev=number,
            label=final.nodes[vc.node].label,
            parent_id=real(final.nodes[vc.node].parent),
            description=final.nodes[vc.node].description,
            aphia_id=final.nodes[vc.node].aphia_id,
        )
        for vc in result.version_changes
        if vc.to_version is not None
    )

    published = [
        ChangeSpec(seq=c.seq, op=c.op, group=c.group, payload=_rewrite_payload(c.payload, ids))
        for c in result.reduced
    ]
    deprecates = [c for c in published if c.op == "deprecate"]
    Node.objects.filter(id__in=[c.node for c in deprecates]).update(deprecated_in_rev=number)
    Successor.objects.bulk_create(
        Successor(deprecated_node_id=c.node, successor_node_id=s, position=i)
        for c in deprecates
        for i, s in enumerate(c.payload.get("successors", []))
    )
    NodeAlias.objects.bulk_create(
        NodeAlias(node_id=c.node, alias=alias, added_by=changeset.author, added_at=now)
        for c in published
        if c.op == "add"
        for alias in dict.fromkeys(c.payload.get("aliases", []))
    )

    _store_changes(changeset, published)
    changeset.tree = tree
    changeset.state = Changeset.State.PUBLISHED
    changeset.save()
    return revision
