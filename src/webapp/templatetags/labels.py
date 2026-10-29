from django import template

register = template.Library()


@register.filter
def label_of(labels: dict, ref) -> str:
    """A node's label from a {str(ref): label} map, else the ref itself."""
    if ref is None:
        return "top level"
    return labels.get(str(ref), str(ref))


@register.filter
def pair(value) -> str:
    """[old, new] as `old → new`."""
    old, new = value
    return f"{'—' if old is None else old} → {'—' if new is None else new}"
