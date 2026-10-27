"""Builders for in-memory engine tests."""

import os
from dataclasses import replace
from pathlib import Path

from core.engine import NodeState, TreeState, apply_changes, specs_from_dicts, version_changes

# Example trees; compose mounts them at /labeldata, since only src/ is in the container.
LABELDATA = Path(os.environ.get("LABELDATA_DIR", Path(__file__).resolve().parents[3] / "labeldata"))
TAGS = LABELDATA / "NES2022_tags.json"


def make_state(nodes, tree_id="t", rev=1) -> TreeState:
    """nodes: (id, label, parent[, version]) tuples; version defaults to 1."""
    return TreeState(
        tree_id,
        rev,
        [
            NodeState(id=n[0], label=n[1], parent=n[2], version=n[3] if len(n) > 3 else 1)
            for n in nodes
        ],
    )


def add(node, label, parent=None, group=None, **extra):
    return {"op": "add", "group": group, "node": node, "label": label, "parent": parent, **extra}


def edit(node, group=None, **fields):
    return {"op": "edit", "group": group, "node": node, **fields}


def move(node, from_parent, to_parent, group=None):
    return {
        "op": "move",
        "group": group,
        "node": node,
        "from_parent": from_parent,
        "to_parent": to_parent,
    }


def deprecate(node, successors=(), group=None):
    return {"op": "deprecate", "group": group, "node": node, "successors": list(successors)}


def specs(*changes):
    return specs_from_dicts(changes)


def advance(state: TreeState, *changes):
    """Apply changes as the next revision, bumping versions like publish does.

    Returns (new_state, {node: (from, to)}). Placeholders keep their refs.
    """
    result = apply_changes(state, specs(*changes))
    assert result.errors == [], result.errors
    bumps = version_changes(state, result.state)
    new = result.state.copy()
    new.rev = state.rev + 1
    for vc in bumps:
        if vc.to_version is not None:
            new.nodes[vc.node] = replace(new.nodes[vc.node], version=vc.to_version)
    return new, {vc.node: (vc.from_version, vc.to_version) for vc in bumps}


# --- Database helpers -------------------------------------------------------------


def publish(tree, *changes, author="alice", notes="", published_by="bob"):
    """Save a draft on `tree`'s latest revision and publish it."""
    from core.changesets import create_changeset, latest_rev, publish_changeset

    cs = create_changeset(
        author=author, changes=list(changes), tree=tree, base_rev=latest_rev(tree.id), notes=notes
    )
    return publish_changeset(cs, published_by=published_by)


def publish_new_tree(tree_id, *changes, title=None, author="alice", published_by="bob"):
    from core.changesets import NewTree, create_changeset, publish_changeset

    cs = create_changeset(
        author=author, changes=list(changes), new_tree=NewTree(tree_id, title or tree_id)
    )
    return publish_changeset(cs, published_by=published_by)


def ids_by_label(tree_id, rev=None):
    from core.changesets import latest_rev
    from core.engine import load_state

    return dict(load_state(tree_id, rev or latest_rev(tree_id)).by_label)
