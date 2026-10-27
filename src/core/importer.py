"""Import format: nested `{tree, nodes: [{label, aphia_id?, description?, aliases?, children?}]}`.

Only `label` is required and every other key is ignored, so content-shape and
detailed-shape API responses can be imported as they are. A file expands into
an ordinary changeset: `add` changes in one `import#n` group, parents before
children in file order, with placeholder ids.
"""


class ImportFormatError(ValueError):
    def __init__(self, position: str, detail: str):
        super().__init__(f"{position}: {detail}")
        self.position = position
        self.detail = detail


def _check_node(node, position):
    if not isinstance(node, dict):
        raise ImportFormatError(position, "a node must be an object")
    if not isinstance(node.get("label"), str):
        raise ImportFormatError(position, "node has no `label`")
    if not isinstance(node.get("description") or "", str):
        raise ImportFormatError(position, "`description` must be a string")
    aphia = node.get("aphia_id")
    if aphia is not None and (not isinstance(aphia, int) or isinstance(aphia, bool)):
        raise ImportFormatError(position, "`aphia_id` must be an integer")
    aliases = node.get("aliases") or []
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise ImportFormatError(position, "`aliases` must be a list of strings")
    if not isinstance(node.get("children") or [], list):
        raise ImportFormatError(position, "`children` must be a list")


def expand_import(data, *, parent=None, group: str = "import#1") -> list[dict]:
    """Expand an import file into `add` changes (flat change dicts).

    `parent` is an existing node id to import under, or None for top level.
    Raises ImportFormatError naming the offending node's position, e.g.
    `nodes[3].children[0]`.
    """
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise ImportFormatError("file", "expected an object with a `nodes` list")

    changes = []

    def walk(nodes, parent_ref, path):
        for i, node in enumerate(nodes):
            position = f"{path}[{i}]"
            _check_node(node, position)
            ref = f"new:{len(changes) + 1}"
            change = {"op": "add", "group": group, "node": ref, "label": node["label"]}
            change["parent"] = parent_ref
            if node.get("description"):
                change["description"] = node["description"]
            if node.get("aphia_id") is not None:
                change["aphia_id"] = node["aphia_id"]
            if node.get("aliases"):
                change["aliases"] = list(node["aliases"])
            changes.append(change)
            walk(node.get("children") or [], ref, f"{position}.children")

    walk(data["nodes"], parent, "nodes")
    return changes
