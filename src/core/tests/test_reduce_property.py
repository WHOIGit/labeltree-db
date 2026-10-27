"""Property: reduction preserves the final state and adds no errors.

Random change lists over the NES2022_tags tree, from a fixed seed so failures
reproduce. Labels come from a small pool so renames collide, swap and revert.
"""

import json
import random
from collections import Counter

import pytest

from core.engine import TreeState, apply_changes, reduce_changes, specs_from_dicts

from .helpers import TAGS, make_state

CASES = 500


def tags_state() -> TreeState:
    rows, next_id = [], iter(range(1, 1000))

    def walk(nodes, parent):
        for n in nodes:
            nid = next(next_id)
            rows.append((nid, n["label"], parent))
            walk(n.get("children", []), nid)

    walk(json.loads(TAGS.read_text())["nodes"], None)
    return make_state(rows, tree_id="NES2022_tags")


def random_changes(rng: random.Random, base: TreeState) -> list[dict]:
    labels = [n.label for n in base.nodes.values()][:6] + ["tmp", "a", "b", "c"]
    groups = [None, None, "g#1", "g#2"]
    # Track a rough current view so most changes are plausible; some won't be.
    current = base.copy()
    changes, placeholder = [], 0
    for _ in range(rng.randint(1, 10)):
        refs = list(current.nodes) or [None]
        node = rng.choice(refs)
        op = rng.choice(["add", "edit", "edit", "move", "move", "deprecate"])
        group = rng.choice(groups)
        if op == "add" or node is None:
            placeholder += 1
            change = {
                "op": "add",
                "node": f"new:{placeholder}",
                "label": rng.choice(labels),
                "parent": rng.choice(refs + [None]),
            }
        elif op == "edit":
            change = {"op": "edit", "node": node}
            if rng.random() < 0.8:
                change["label"] = rng.choice(labels + [current.nodes[node].label])
            if rng.random() < 0.3:
                change["description"] = rng.choice(["", "d1", "d2"])
            if rng.random() < 0.3 or len(change) == 2:
                change["aphia_id"] = rng.choice([None, 1, 2])
        elif op == "move":
            from_parent = current.nodes[node].parent
            if rng.random() < 0.1:
                from_parent = rng.choice(refs + [None])
            change = {
                "op": "move",
                "node": node,
                "from_parent": from_parent,
                "to_parent": rng.choice(refs + [None]),
            }
        else:
            change = {
                "op": "deprecate",
                "node": node,
                "successors": rng.sample(refs, k=min(len(refs), rng.randint(0, 2))),
            }
        change["group"] = group
        changes.append(change)
        current = apply_changes(current, specs_from_dicts([change])).state
    return changes


def error_kinds(result):
    return Counter((e["error"], e["node"]) for e in result.errors)


@pytest.mark.parametrize("batch", range(5))
def test_reduction_preserves_state_and_validity(batch):
    base = tags_state()
    rng = random.Random(f"reduce-{batch}")
    for case in range(CASES // 5):
        changes = specs_from_dicts(random_changes(rng, base))
        reduced = reduce_changes(base, changes)
        before, after = apply_changes(base, changes), apply_changes(base, reduced)
        context = f"batch {batch} case {case}: {[c.as_dict() for c in changes]}"

        assert after.state.contents() == before.state.contents(), context
        assert not (error_kinds(after) - error_kinds(before)), context
        assert len(reduced) <= len(changes), context
        assert [c.seq for c in reduced] == list(range(1, len(reduced) + 1)), context
        # Reduction is a fixpoint: reducing again changes nothing.
        assert reduce_changes(base, reduced) == reduced, context
