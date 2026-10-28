"""Who may do what on a tree (spec: access-control).

Every tree belongs to one organization, and roles are held per organization:
reader < drafter < approver < owner, stored as one OrgMember row per user and
organization, applying to all its trees. Superusers are site admins and count
as owner in every organization.
"""

from .models import OrgMember, Role


class NotAuthenticated(Exception):
    """No logged-in user or valid token: 401."""


class Forbidden(Exception):
    """Logged in, but the role is missing: 403."""


def org_role(user, org_id: str) -> Role | None:
    """The user's role in an organization; owner for superusers, None for non-members."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return Role.OWNER
    role = OrgMember.objects.filter(user=user, org_id=org_id).values_list("role", flat=True)
    return Role(role[0]) if role else None


def tree_role(user, tree_id: str) -> Role | None:
    """The user's role on a tree: their role in the tree's organization."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return Role.OWNER
    role = OrgMember.objects.filter(user=user, org__trees__id=tree_id).values_list(
        "role", flat=True
    )
    return Role(role[0]) if role else None


def require_login(user):
    if not user.is_authenticated:
        raise NotAuthenticated("Log in or send an API token.")


def _check(role: Role | None, minimum: Role, where: str):
    if role is None or role < minimum:
        raise Forbidden(f"This needs the {minimum.label} role in {where}.")


def require(user, tree_id: str, minimum: Role):
    """Raise unless the user holds at least `minimum` in the tree's organization."""
    require_login(user)
    _check(tree_role(user, tree_id), minimum, f"the organization of tree {tree_id}")


def require_org(user, org_id: str, minimum: Role):
    """Raise unless the user holds at least `minimum` in the organization."""
    require_login(user)
    _check(org_role(user, org_id), minimum, f"organization {org_id}")


def require_superuser(user):
    require_login(user)
    if not user.is_superuser:
        raise Forbidden("Only site admins may do this.")
