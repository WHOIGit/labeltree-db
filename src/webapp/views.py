"""Web app pages (spec: webapp).

Pages are server-rendered frames. The tree browser and draft editor is one
Alpine.js page that talks to /api/v1 with the session; the other pages render
their data here and use small Alpine components for their few actions. Page
data a script needs is passed with `json_script`, never inline script.

Anyone may browse trees, revisions and node pages. Drafts, organization
members and the user's own page need a login and, for drafts, a role in the
tree's organization.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404
from django.shortcuts import redirect, render

from accounts.models import Organization, OrgMember, Role
from accounts.roles import Forbidden, org_role, require, require_org
from api.changesets import changeset_body
from core.changesets import changeset_etag, latest_rev
from core.models import Changeset, Node, NodeAlias, Tree
from worms.models import NodeWarnings

from .roles import user_info


def forbidden(request, exc: Forbidden):
    return render(request, "webapp/forbidden.html", {"reason": str(exc)}, status=403)


def tree_list() -> list[dict]:
    """Trees grouped by organization, for the tree picker."""
    groups = []
    for org in Organization.objects.prefetch_related("trees").order_by("name"):
        trees = sorted(org.trees.all(), key=lambda t: t.id)
        if trees:
            groups.append(
                {"org": org.id, "name": org.name,
                 "trees": [{"id": t.id, "title": t.title} for t in trees]}
            )  # fmt: skip
    return groups


def home(request):
    first = Tree.objects.order_by("org__name", "id").first()
    if first is None:
        return render(request, "webapp/empty.html", {"user_info": user_info(request.user)})
    return redirect("tree", tree_id=first.id)


def _browser(request, *, tree: Tree | None, draft: Changeset | None):
    data = {
        "user": user_info(request.user),
        "trees": tree_list(),
        "orgs": [{"id": o.id, "name": o.name} for o in Organization.objects.order_by("name")],
        "tree": tree.id if tree else None,
        "org": tree.org_id if tree else draft.new_tree_org_id,
        "latest_rev": latest_rev(tree.id) if tree else None,
        "draft": draft.pk if draft else None,
        "new_tree": None,
    }
    if draft is not None and draft.tree_id is None:
        data["new_tree"] = {
            "id": draft.new_tree_id, "title": draft.new_tree_title, "org": draft.new_tree_org_id,
        }  # fmt: skip
    return render(request, "webapp/browser.html", {"page": data, "user_info": data["user"]})


def tree_page(request, tree_id: str):
    try:
        tree = Tree.objects.get(pk=tree_id)
    except Tree.DoesNotExist:
        raise Http404(f"Tree {tree_id} does not exist.") from None
    return _browser(request, tree=tree, draft=None)


def _changeset(cs: int) -> Changeset:
    try:
        return Changeset.objects.select_related("tree").get(pk=cs)
    except Changeset.DoesNotExist:
        raise Http404(f"Changeset {cs} does not exist.") from None


def _require_reader(request, changeset: Changeset):
    if changeset.tree_id is not None:
        require(request.user, changeset.tree_id, Role.READER)
    else:
        require_org(request.user, changeset.new_tree_org_id, Role.READER)


@login_required
def edit_page(request, cs: int):
    """The draft editor on one changeset, for drafts on a tree and new-tree drafts."""
    changeset = _changeset(cs)
    try:
        _require_reader(request, changeset)
    except Forbidden as exc:
        return forbidden(request, exc)
    return _browser(request, tree=changeset.tree, draft=changeset)


@login_required
def drafts_page(request, tree_id: str):
    try:
        tree = Tree.objects.get(pk=tree_id)
        require(request.user, tree.id, Role.READER)
    except Tree.DoesNotExist:
        raise Http404(f"Tree {tree_id} does not exist.") from None
    except Forbidden as exc:
        return forbidden(request, exc)
    changesets = (
        Changeset.objects.filter(tree=tree, state__in=["draft", "discarded"])
        .annotate(num_changes=Count("changes"))
        .order_by("-id")
    )
    context = {
        "tree": tree,
        "latest_rev": latest_rev(tree.id),
        "open": [c for c in changesets if c.state == "draft"],
        "discarded": [c for c in changesets if c.state == "discarded"],
        "user_info": user_info(request.user),
    }
    return render(request, "webapp/drafts.html", context)


def _grouped(changes: list[dict]) -> list[dict]:
    """Consecutive changes of one group under one header; ungrouped ones alone."""
    items = []
    for change in changes:
        group = change["group"]
        if group and items and items[-1]["group"] == group:
            items[-1]["changes"].append(change)
        else:
            items.append({"group": group, "changes": [change]})
    return items


@login_required
def review_page(request, cs: int):
    changeset = _changeset(cs)
    try:
        _require_reader(request, changeset)
    except Forbidden as exc:
        return forbidden(request, exc)
    body = changeset_body(changeset)
    validation = body.get("validation")
    labels = _labels(changeset, body)
    page = {
        "id": changeset.pk, "tree": changeset.tree_id, "state": changeset.state,
        "etag": changeset_etag(changeset), "base_rev": changeset.base_rev,
        "latest_rev": validation["latest_rev"] if validation else None,
        "notes": changeset.notes, "user": user_info(request.user),
        "org": changeset.tree.org_id if changeset.tree else changeset.new_tree_org_id,
        "ok": bool(validation and validation["ok"]),
    }  # fmt: skip
    context = {
        "cs": changeset, "body": body, "validation": validation,
        "items": _grouped(body["changes"]), "labels": labels, "page": page,
        "user_info": page["user"],
    }  # fmt: skip
    return render(request, "webapp/review.html", context)


def _labels(changeset: Changeset, body: dict) -> dict:
    """Labels for the node ids and placeholders a review shows."""
    from core.engine import load_state

    labels = {}
    if changeset.tree_id and changeset.base_rev:
        state = load_state(changeset.tree_id, changeset.base_rev)
        labels = {str(ref): n.label for ref, n in state.nodes.items()}
    for change in body["changes"]:
        if change["op"] == "add":
            labels[str(change["node"])] = change.get("label", "")
    return labels


def node_page(request, node_id: int):
    from api.serializers import RevisionView, deprecation_record

    try:
        node = Node.objects.select_related("tree").get(pk=node_id)
    except Node.DoesNotExist:
        raise Http404(f"Node {node_id} does not exist.") from None
    rev = latest_rev(node.tree_id)
    if node.deprecated_in_rev is None:
        view = RevisionView(node.tree, rev)
        view.preload([node.id])
        detail = view.detailed(node.id)
    else:
        detail = deprecation_record(node, rev)
    successors = []
    if node.deprecated_in_rev is not None:
        for link in node.successor_links.select_related("successor_node").order_by("position"):
            succ = link.successor_node
            last = succ.versions.order_by("-version").first()
            successors.append({"id": succ.id, "label": last.label if last else str(succ.id)})
    context = {
        "node": node,
        "detail": detail,
        "versions": node.versions.order_by("-version").select_related("parent"),
        "warning_history": NodeWarnings.objects.filter(node=node).order_by("-computed_at", "-id"),
        "aliases": NodeAlias.objects.filter(node=node).order_by("removed_at", "-added_at"),
        "successors": successors,
        "latest_rev": rev,
        "user_info": user_info(request.user),
    }
    return render(request, "webapp/node.html", context)


def org_page(request, org_id: str):
    try:
        org = Organization.objects.get(pk=org_id)
    except Organization.DoesNotExist:
        raise Http404(f"Organization {org_id} does not exist.") from None
    role = org_role(request.user, org.id)
    members = []
    if role is not None:
        members = [
            {"username": m.user.get_username(), "role": Role(m.role).label}
            for m in OrgMember.objects.filter(org=org).select_related("user")
        ]
    page = {
        "org": org.id, "members": members, "can_manage": role == Role.OWNER,
        "me": request.user.get_username() if request.user.is_authenticated else None,
        "roles": [r.label for r in Role],
    }  # fmt: skip
    context = {
        "org": org,
        "trees": org.trees.order_by("id"),
        "is_member": role is not None,
        "page": page,
        "user_info": user_info(request.user),
    }
    return render(request, "webapp/org.html", context)


@login_required
def me(request):
    memberships = OrgMember.objects.filter(user=request.user).select_related("org")
    context = {
        "memberships": [
            {"org": m.org, "role": Role(m.role).label} for m in memberships.order_by("org__name")
        ],
        "all_orgs": Organization.objects.order_by("name") if request.user.is_superuser else [],
        "user_info": user_info(request.user),
    }
    return render(request, "webapp/me.html", context)
