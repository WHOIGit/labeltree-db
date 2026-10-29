"""Organizations and their members (spec: access-control).

Every tree belongs to one organization, and roles are held there. Anyone may
list organizations and their trees; any member may list the members; only
owners (and site admins) change them. An organization with an owner keeps at
least one, except when a site admin acts.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse
from ninja import Router, Schema

from accounts.models import Organization, OrgMember, Role
from accounts.roles import require_org

from .conventions import APIError, bad_parameter, not_found, respond

router = Router(tags=["orgs"])


class MemberIn(Schema):
    role: str


class NewMemberIn(Schema):
    username: str
    role: str


def parse_role(name: str) -> Role:
    try:
        return Role.named(name)
    except ValueError:
        names = ", ".join(r.label for r in Role)
        raise bad_parameter(f"role must be one of {names}.") from None


def get_org(org_id: str) -> Organization:
    try:
        return Organization.objects.get(pk=org_id)
    except Organization.DoesNotExist:
        raise not_found(f"Organization {org_id} does not exist.") from None


def org_body(org: Organization) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "trees": [t.id for t in sorted(org.trees.all(), key=lambda t: t.id)],
    }


def member_body(member: OrgMember) -> dict:
    return {"username": member.user.get_username(), "role": Role(member.role).label}


def get_user(username: str):
    try:
        return get_user_model().objects.get(username=username)
    except get_user_model().DoesNotExist:
        raise not_found(f"User {username} does not exist.") from None


def _keep_an_owner(request, org_id: str, username: str, new_role: Role | None):
    """Refuse when the change would leave an organization that has owners without one.

    Locks the organization's member rows, so two owners stepping down at once
    can't both succeed.
    """
    members = list(
        OrgMember.objects.select_for_update().filter(org_id=org_id).select_related("user")
    )
    if request.user.is_superuser:
        return
    owners = {m.user.get_username() for m in members if m.role == Role.OWNER}
    if username in owners and (new_role is None or new_role < Role.OWNER) and len(owners) == 1:
        raise APIError(409, "last_owner", f"{username} is the last owner of organization {org_id}.")


@router.get("", auth=None)
def list_orgs(request):
    orgs = Organization.objects.prefetch_related("trees")
    return respond(request, {"orgs": [org_body(o) for o in orgs]})


@router.get("/{org_id}", auth=None)
def org_detail(request, org_id: str):
    return respond(request, org_body(get_org(org_id)))


@router.get("/{org_id}/members")
def list_members(request, org_id: str):
    org = get_org(org_id)
    require_org(request.user, org.id, Role.READER)
    members = OrgMember.objects.filter(org=org).select_related("user")
    return respond(request, {"org": org.id, "members": [member_body(m) for m in members]})


@router.post("/{org_id}/members")
def add_member(request, org_id: str, body: NewMemberIn):
    """Add a user; 409 already_member if they are one (change roles with PUT)."""
    org = get_org(org_id)
    require_org(request.user, org.id, Role.OWNER)
    role = parse_role(body.role)
    user = get_user(body.username)
    member, created = OrgMember.objects.get_or_create(user=user, org=org, defaults={"role": role})
    if not created:
        raise APIError(
            409, "already_member",
            f"{body.username} is already {Role(member.role).label} in organization {org.id}.",
        )  # fmt: skip
    response = respond(request, {"org": org.id, **member_body(member)})
    response.status_code = 201
    return response


@router.put("/{org_id}/members/{username}")
def set_member(request, org_id: str, username: str, body: MemberIn):
    org = get_org(org_id)
    require_org(request.user, org.id, Role.OWNER)
    role = parse_role(body.role)
    user = get_user(username)
    with transaction.atomic():
        _keep_an_owner(request, org.id, username, role)
        member, _ = OrgMember.objects.update_or_create(user=user, org=org, defaults={"role": role})
    return respond(request, {"org": org.id, **member_body(member)})


@router.delete("/{org_id}/members/{username}")
def remove_member(request, org_id: str, username: str):
    org = get_org(org_id)
    require_org(request.user, org.id, Role.OWNER)
    with transaction.atomic():
        _keep_an_owner(request, org.id, username, None)
        deleted, _ = OrgMember.objects.filter(org=org, user__username=username).delete()
    if not deleted:
        raise not_found(f"{username} is not a member of organization {org.id}.")
    return HttpResponse(status=204)
