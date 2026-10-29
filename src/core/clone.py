"""Cloning a published revision as a new tree (spec: tree-import).

A clone is the revision's `/export` imported into an empty tree: one `import#1`
group of `add` changes carrying the revision's labels, AphiaIDs and structure,
and the current descriptions and aliases. It is a stand-alone new-tree
changeset; publishing it creates revision 1 of the new tree with new node ids.
The web app builds the same changes in the browser; this is for tests and
management use.
"""

from .changesets import NewTree, create_changeset
from .engine import load_state
from .importer import expand_import
from .models import Changeset, NodeAlias, current_descriptions


def clone_changes(tree_id: str, rev: int) -> list[dict]:
    """The `add` changes that rebuild revision `rev` of a tree as a new tree."""
    state = load_state(tree_id, rev)
    descriptions = current_descriptions(state.nodes)
    aliases = {}
    for node, alias in (
        NodeAlias.objects.filter(node_id__in=list(state.nodes), removed_at__isnull=True)
        .order_by("id")
        .values_list("node_id", "alias")
    ):
        aliases.setdefault(node, []).append(alias)

    def nested(ref):
        node = state.nodes[ref]
        return {
            "label": node.label, "aphia_id": node.aphia_id,
            "description": descriptions.get(ref, ""), "aliases": aliases.get(ref, []),
            "children": [nested(child) for child in state.child_ids(ref)],
        }  # fmt: skip

    return expand_import({"nodes": [nested(ref) for ref in state.child_ids(None)]})


def clone_as_new_tree(tree_id: str, rev: int, new_tree: NewTree, *, author: str) -> Changeset:
    """Save a new-tree draft cloning revision `rev` of `tree_id`."""
    return create_changeset(
        author=author, changes=clone_changes(tree_id, rev), new_tree=new_tree,
        notes=f"Clone of {tree_id} revision {rev}.",
    )  # fmt: skip
