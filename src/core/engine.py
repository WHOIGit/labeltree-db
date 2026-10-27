"""Changeset engine: tree state, apply, version diff and reduction.

Everything here works on an in-memory TreeState and never writes to the
database, so the import command, validation, draft save and publish all share
one code path. Node references are real ids (int) or placeholders ("new:1") for
nodes added in the changeset being checked.
"""

import re
from collections import Counter
from dataclasses import dataclass, field, replace

from django.db.models import Q

from .labels import is_machine_safe

NodeRef = int | str

OPS = ("add", "edit", "move", "deprecate")
EDIT_FIELDS = ("label", "description", "aphia_id")
_PLACEHOLDER_RE = re.compile(r"^new:\d+$")


def is_placeholder(ref) -> bool:
    return isinstance(ref, str) and _PLACEHOLDER_RE.fullmatch(ref) is not None


def is_node_ref(ref) -> bool:
    return (isinstance(ref, int) and not isinstance(ref, bool)) or is_placeholder(ref)


def ref_sort_key(ref):
    """Real ids in id order, then placeholders in number order."""
    if isinstance(ref, int):
        return (0, ref)
    if is_placeholder(ref):
        return (1, int(ref.split(":")[1]))
    return (2, str(ref))


# --- Tree state ---------------------------------------------------------------


@dataclass
class NodeState:
    id: NodeRef
    label: str
    parent: NodeRef | None
    description: str = ""
    aphia_id: int | None = None
    # Version at the base revision; None for a node added in the changeset.
    version: int | None = None

    def content(self):
        return (self.label, self.parent, self.description, self.aphia_id)


class TreeState:
    """The nodes of one tree at one revision, with label and children indexes."""

    def __init__(self, tree_id: str, rev: int, nodes=()):
        self.tree_id = tree_id
        self.rev = rev
        self.nodes: dict[NodeRef, NodeState] = {}
        self.by_label: dict[str, NodeRef] = {}
        self._children: dict[NodeRef | None, set[NodeRef]] = {}
        # Placeholders ever added in this state, so one can't be added twice.
        self.used_placeholders: set[str] = set()
        for node in nodes:
            self.insert(node)

    def copy(self) -> TreeState:
        new = TreeState(self.tree_id, self.rev)
        new.nodes = {ref: replace(n) for ref, n in self.nodes.items()}
        new.by_label = dict(self.by_label)
        new._children = {ref: set(kids) for ref, kids in self._children.items()}
        new.used_placeholders = set(self.used_placeholders)
        return new

    # mutation

    def insert(self, node: NodeState):
        self.nodes[node.id] = node
        self.by_label[node.label] = node.id
        self._children.setdefault(node.parent, set()).add(node.id)

    def remove(self, ref: NodeRef):
        node = self.nodes.pop(ref)
        del self.by_label[node.label]
        self._children[node.parent].discard(ref)

    def relabel(self, ref: NodeRef, label: str):
        node = self.nodes[ref]
        del self.by_label[node.label]
        node.label = label
        self.by_label[label] = ref

    def reparent(self, ref: NodeRef, parent: NodeRef | None):
        node = self.nodes[ref]
        self._children[node.parent].discard(ref)
        node.parent = parent
        self._children.setdefault(parent, set()).add(ref)

    # queries

    def __contains__(self, ref) -> bool:
        return ref in self.nodes

    def child_ids(self, ref: NodeRef | None) -> list[NodeRef]:
        """Children in id order; ref=None gives the top-level nodes."""
        return sorted(self._children.get(ref, ()), key=ref_sort_key)

    def child_set(self, ref: NodeRef | None) -> frozenset:
        return frozenset(self._children.get(ref, ()))

    def num_children(self, ref: NodeRef) -> int:
        return len(self._children.get(ref, ()))

    def ancestor_ids(self, ref: NodeRef) -> list[NodeRef]:
        """From the top-level node down to the immediate parent."""
        path = []
        parent = self.nodes[ref].parent
        while parent is not None:
            path.append(parent)
            parent = self.nodes[parent].parent
        path.reverse()
        return path

    def depth(self, ref: NodeRef) -> int:
        return len(self.ancestor_ids(ref))

    def max_depth(self) -> int:
        deepest = 0
        stack = [(ref, 0) for ref in self.child_ids(None)]
        while stack:
            ref, depth = stack.pop()
            deepest = max(deepest, depth)
            stack.extend((kid, depth + 1) for kid in self._children.get(ref, ()))
        return deepest

    def contents(self) -> dict:
        """Everything that defines the tree's content, for state comparisons."""
        return {ref: node.content() for ref, node in self.nodes.items()}


def load_state(tree_id: str, rev: int) -> TreeState:
    """The tree as of revision `rev`: node versions with valid_from_rev <= rev < valid_to_rev."""
    from .models import NodeVersion

    rows = (
        NodeVersion.objects.filter(tree_id=tree_id, valid_from_rev__lte=rev)
        .filter(Q(valid_to_rev__isnull=True) | Q(valid_to_rev__gt=rev))
        .values_list("node_id", "label", "parent_id", "description", "aphia_id", "version")
    )
    return TreeState(
        tree_id,
        rev,
        (
            NodeState(id=n, label=lb, parent=p, description=d, aphia_id=a, version=v)
            for n, lb, p, d, a, v in rows
        ),
    )


# --- Changes -------------------------------------------------------------------


@dataclass
class ChangeSpec:
    """One atomic change: op, payload of its arguments, and the macro group it belongs to."""

    seq: int
    op: str
    payload: dict = field(default_factory=dict)
    group: str | None = None

    @property
    def node(self):
        return self.payload.get("node") if isinstance(self.payload, dict) else None

    def as_dict(self) -> dict:
        """Flat API form: {seq, op, group, ...payload}."""
        return {"seq": self.seq, "op": self.op, "group": self.group, **self.payload}


def specs_from_dicts(changes) -> list[ChangeSpec]:
    """Build specs from flat dicts ({op, group?, seq?, ...payload}), numbering seq from 1."""
    specs = []
    for seq, change in enumerate(changes, start=1):
        if not isinstance(change, dict):
            specs.append(ChangeSpec(seq=seq, op=None, payload=None))
            continue
        payload = {k: v for k, v in change.items() if k not in ("op", "group", "seq")}
        specs.append(
            ChangeSpec(seq=seq, op=change.get("op"), payload=payload, group=change.get("group"))
        )
    return specs


def renumber(changes: list[ChangeSpec]) -> list[ChangeSpec]:
    return [replace(c, seq=i) for i, c in enumerate(changes, start=1)]


def _error(change: ChangeSpec, code: str, detail: str) -> dict:
    return {"seq": change.seq, "error": code, "node": change.node, "detail": detail}


def _payload_problem(change: ChangeSpec) -> str | None:
    """Shape problems that make a change unreadable, reported as `invalid_change`."""
    p = change.payload
    if change.op not in OPS:
        return f"Unknown op {change.op!r}."
    if not isinstance(p, dict) or "node" not in p:
        return "Payload must be an object with `node`."
    if not is_node_ref(p["node"]):
        return f"Node reference {p['node']!r} is neither a node id nor a placeholder."
    allowed = {
        "add": {"node", "label", "parent", "description", "aphia_id", "aliases"},
        "edit": {"node", *EDIT_FIELDS},
        "move": {"node", "from_parent", "to_parent"},
        "deprecate": {"node", "successors"},
    }[change.op]
    if extra := set(p) - allowed:
        return f"Unexpected fields for {change.op}: {', '.join(sorted(extra))}."
    refs = []
    if change.op == "add":
        if "label" not in p or "parent" not in p:
            return "`add` needs `label` and `parent`."
        refs.append(p["parent"])
        if not isinstance(p.get("aliases", []), list) or not all(
            isinstance(a, str) for a in p.get("aliases", [])
        ):
            return "`aliases` must be a list of strings."
    elif change.op == "edit":
        if not any(f in p for f in EDIT_FIELDS):
            return "`edit` needs at least one of label, description, aphia_id."
    elif change.op == "move":
        if "from_parent" not in p or "to_parent" not in p:
            return "`move` needs `from_parent` and `to_parent`."
        refs += [p["from_parent"], p["to_parent"]]
    elif change.op == "deprecate":
        if not isinstance(p.get("successors", []), list):
            return "`successors` must be a list."
        refs += p.get("successors", [])
    if any(r is not None and not is_node_ref(r) for r in refs):
        return "Node references must be node ids, placeholders or null."
    if "description" in p and not isinstance(p["description"], str):
        return "`description` must be a string."
    aphia = p.get("aphia_id")
    if aphia is not None and (not isinstance(aphia, int) or isinstance(aphia, bool)):
        return "`aphia_id` must be an integer or null."
    return None


def _check_label(state: TreeState, change: ChangeSpec, label, node: NodeRef) -> dict | None:
    if not is_machine_safe(label):
        return _error(change, "invalid_label", f"Label {label!r} is not machine-safe.")
    holder = state.by_label.get(label)
    if holder is not None and holder != node:
        return _error(change, "label_in_use", f"Label {label} is already used by node {holder}.")
    return None


def _apply_one(state: TreeState, change: ChangeSpec) -> dict | None:
    """Apply one change to `state` in place, or return its structural error unchanged."""
    if problem := _payload_problem(change):
        return _error(change, "invalid_change", problem)
    p = change.payload
    node = p["node"]

    if change.op == "add":
        if not is_placeholder(node) or node in state.used_placeholders:
            return _error(change, "invalid_change", f"{node} must be a new, unused placeholder.")
        parent = p["parent"]
        if parent is not None and parent not in state:
            return _error(
                change, "parent_not_in_tree", f"Parent {parent} is not in tree {state.tree_id}."
            )
        if err := _check_label(state, change, p["label"], node):
            return err
        state.used_placeholders.add(node)
        state.insert(
            NodeState(
                id=node,
                label=p["label"],
                parent=parent,
                description=p.get("description") or "",
                aphia_id=p.get("aphia_id"),
            )
        )
        return None

    if node not in state:
        return _error(change, "node_not_in_tree", f"Node {node} is not in tree {state.tree_id}.")

    if change.op == "edit":
        if "label" in p and (err := _check_label(state, change, p["label"], node)):
            return err
        if "label" in p:
            state.relabel(node, p["label"])
        if "description" in p:
            state.nodes[node].description = p["description"]
        if "aphia_id" in p:
            state.nodes[node].aphia_id = p["aphia_id"]
        return None

    if change.op == "move":
        to_parent = p["to_parent"]
        if to_parent is not None and to_parent not in state:
            return _error(
                change, "parent_not_in_tree", f"Parent {to_parent} is not in tree {state.tree_id}."
            )
        current = state.nodes[node].parent
        if p["from_parent"] != current:
            return _error(
                change,
                "from_parent_mismatch",
                f"Node {node}'s parent is {current}, not {p['from_parent']}.",
            )
        if to_parent is not None and (to_parent == node or node in state.ancestor_ids(to_parent)):
            return _error(change, "cycle", f"Moving node {node} under {to_parent} creates a cycle.")
        state.reparent(node, to_parent)
        return None

    # deprecate
    if kids := state.child_ids(node):
        return _error(
            change,
            "has_children",
            f"Node {node} still has children: {', '.join(map(str, kids))}.",
        )
    state.remove(node)
    return None


def _successor_error(final: TreeState, change: ChangeSpec) -> dict | None:
    node = change.node
    for successor in change.payload.get("successors", []):
        if successor == node:
            return _error(change, "invalid_successor", f"Node {node} can't succeed itself.")
        if successor not in final:
            return _error(
                change,
                "invalid_successor",
                f"Successor {successor} is not in tree {final.tree_id} after this changeset.",
            )
    return None


@dataclass
class ApplyResult:
    state: TreeState
    errors: list[dict]


def apply_changes(base: TreeState, changes: list[ChangeSpec]) -> ApplyResult:
    """Apply changes in order to a copy of `base`.

    Each change is checked against the state the earlier valid changes left. A
    failing change is skipped and later changes are still checked.
    """
    state = base.copy()
    errors = []
    deprecations = []
    for change in changes:
        if err := _apply_one(state, change):
            errors.append(err)
        elif change.op == "deprecate":
            deprecations.append(change)
    # Successors are checked against the tree after the whole changeset, so a
    # successor may be added later, but not removed earlier or later.
    for change in deprecations:
        if err := _successor_error(state, change):
            errors.append(err)
    errors.sort(key=lambda e: e["seq"])
    return ApplyResult(state, errors)


# --- Version changes -------------------------------------------------------------


@dataclass(frozen=True)
class VersionChange:
    node: NodeRef
    from_version: int | None  # None: added
    to_version: int | None  # None: deprecated

    def as_dict(self) -> dict:
        return {"node": self.node, "from": self.from_version, "to": self.to_version}


def version_changes(before: TreeState, after: TreeState) -> list[VersionChange]:
    """Net per-node comparison: a node's version increases (at most once) if its
    label, description, aphia_id, parent or set of immediate children differs."""
    result = []
    for ref in sorted(before.nodes.keys() | after.nodes.keys(), key=ref_sort_key):
        old, new = before.nodes.get(ref), after.nodes.get(ref)
        if old is None:
            result.append(VersionChange(ref, None, 1))
        elif new is None:
            result.append(VersionChange(ref, old.version, None))
        elif old.content() != new.content() or before.child_set(ref) != after.child_set(ref):
            result.append(VersionChange(ref, old.version, old.version + 1))
    return result


# --- Reduction -----------------------------------------------------------------
#
# Reduction rewrites the change list per node, whatever the groups: groups only
# label changes for reviewers. Every candidate rewrite is checked by
# reduce_changes before it is kept.


def _without(changes, *indexes):
    drop = set(indexes)
    return [c for i, c in enumerate(changes) if i not in drop]


def _merged(changes, i: int, j: int, new: ChangeSpec):
    """Replace changes i < j with `new`: at j (preferred), then at i."""
    later = list(changes)
    later[j] = new
    del later[i]
    yield later
    earlier = list(changes)
    earlier[i] = new
    del earlier[j]
    yield earlier
    # A move placed early may need its new parent's add brought forward too.
    target = new.payload.get("to_parent") if new.op == "move" else None
    if is_placeholder(target):
        k = next(
            (k for k in range(i + 1, j) if changes[k].op == "add" and changes[k].node == target),
            None,
        )
        if k is not None:
            hoisted = list(earlier)
            hoisted.insert(i, hoisted.pop(k))
            yield hoisted


def _next_of(changes, i, ops):
    """Index of the next readable change after i with the same node and one of `ops`."""
    for j in range(i + 1, len(changes)):
        c = changes[j]
        if c.op in ops and c.node == changes[i].node and not _payload_problem(c):
            return j
    return None


def _collapse_candidates(changes):
    """deprecate X [.., S, ..] followed by deprecate S [T..] -> X's successors take S's place."""
    for i, c in enumerate(changes):
        if c.op != "deprecate" or _payload_problem(c):
            continue
        successors = c.payload.get("successors", [])
        for s in successors:
            later = next(
                (
                    d
                    for d in changes[i + 1 :]
                    if d.op == "deprecate" and d.node == s and not _payload_problem(d)
                ),
                None,
            )
            if later is None or not later.payload.get("successors"):
                continue
            expanded = []
            for ref in successors:
                for r in later.payload["successors"] if ref == s else [ref]:
                    if r not in expanded and r != c.node:
                        expanded.append(r)
            if expanded != successors:
                new = replace(c, payload={**c.payload, "successors": expanded})
                yield [new if k == i else x for k, x in enumerate(changes)]


def _merge_candidates(changes):
    for i, c in enumerate(changes):
        if _payload_problem(c):
            continue
        p = c.payload
        if c.op == "edit" and (j := _next_of(changes, i, ("edit",))) is not None:
            merged = {**p, **{k: v for k, v in changes[j].payload.items() if k != "node"}}
            yield from _merged(changes, i, j, replace(changes[j], payload=merged))
        elif c.op == "move" and (j := _next_of(changes, i, ("move",))) is not None:
            merged = {**changes[j].payload, "from_parent": p["from_parent"]}
            yield from _merged(changes, i, j, replace(changes[j], payload=merged))
        elif c.op == "add" and (j := _next_of(changes, i, ("edit", "move"))) is not None:
            later = changes[j]
            if later.op == "edit":
                folded = {**p, **{k: v for k, v in later.payload.items() if k != "node"}}
            else:
                folded = {**p, "parent": later.payload["to_parent"]}
            yield from _merged(changes, i, j, replace(later, op="add", payload=folded))


def _drop_candidates(base: TreeState, changes):
    for i, c in enumerate(changes):
        if _payload_problem(c):
            continue
        p = c.payload
        # Edits and moves of a node deprecated later are moot. Drop them, or bring
        # the deprecate forward to their place (e.g. before a split moving the node).
        if c.op in ("edit", "move") and (j := _next_of(changes, i, ("deprecate",))) is not None:
            yield _without(changes, i)
            earlier = [
                x for k, x in enumerate(changes) if k != j and not (k > i and x.node == c.node)
            ]
            earlier[i] = changes[j]
            yield earlier
        # A node added and deprecated in the same changeset never existed.
        if c.op == "add" and (j := _next_of(changes, i, ("deprecate",))) is not None:
            between = [k for k in range(i + 1, j) if changes[k].node == c.node]
            yield _without(changes, i, j, *between)
        if c.op == "edit" and p["node"] in base:
            old = base.nodes[p["node"]]
            same = [f for f in EDIT_FIELDS if f in p and p[f] == getattr(old, f)]
            if same:
                kept = {k: v for k, v in p.items() if k not in same}
                if len(kept) == 1:  # only `node` left
                    yield _without(changes, i)
                else:
                    yield [replace(c, payload=kept) if k == i else x for k, x in enumerate(changes)]
        if c.op == "move" and p["from_parent"] == p["to_parent"]:
            yield _without(changes, i)


def _candidates(base: TreeState, changes: list[ChangeSpec]):
    """Candidate rewrites, each a full change list. Successor collapses come first,
    so a successor that is a new node isn't dropped before its chain is followed."""
    yield from _collapse_candidates(changes)
    yield from _merge_candidates(changes)
    yield from _drop_candidates(base, changes)


def _key(changes) -> tuple:
    return tuple((c.op, c.group, repr(c.payload)) for c in changes)


def reduce_changes(base: TreeState, changes: list[ChangeSpec]) -> list[ChangeSpec]:
    """Reduce a change list per node, renumbering seq from 1.

    A candidate rewrite is kept only if the rewritten list applies to the same
    final state and introduces no new errors, so reduction never changes the
    changeset's result and never breaks e.g. a label swap via a temporary label.
    """
    original = apply_changes(base, changes)
    target = original.state.contents()
    allowed = Counter((e["error"], e["node"]) for e in original.errors)

    current = list(changes)
    # Never revisit a list: successor collapses through a cycle (A -> B -> A)
    # would otherwise rewrite each other forever.
    seen = {_key(current)}
    progress = True
    while progress:
        progress = False
        for candidate in _candidates(base, current):
            if _key(candidate) in seen:
                continue
            seen.add(_key(candidate))
            result = apply_changes(base, candidate)
            new_errors = Counter((e["error"], e["node"]) for e in result.errors) - allowed
            if not new_errors and result.state.contents() == target:
                current = candidate
                progress = True
                break
    return renumber(current)


# --- Checking ------------------------------------------------------------------


@dataclass
class CheckResult:
    reduced: list[ChangeSpec]
    errors: list[dict]
    state: TreeState
    version_changes: list[VersionChange]

    @property
    def ok(self) -> bool:
        return not self.errors


def check_changes(base: TreeState, changes: list[ChangeSpec]) -> CheckResult:
    """Reduce, then apply: the structural check run by import, save and publish.

    Errors refer to the reduced list's `seq`. An empty reduced list is an
    `empty_changeset` error.
    """
    reduced = reduce_changes(base, changes)
    result = apply_changes(base, reduced)
    errors = list(result.errors)
    if not reduced:
        errors.append(
            {
                "seq": None,
                "error": "empty_changeset",
                "node": None,
                "detail": "The changeset has no changes left after reduction.",
            }
        )
    return CheckResult(reduced, errors, result.state, version_changes(base, result.state))
