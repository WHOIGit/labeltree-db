"""What the page scripts need to know about the user, to enable or disable
controls. The API checks every action again."""

from accounts.models import OrgMember, Role


def user_info(user) -> dict:
    if not user.is_authenticated:
        return {"username": None, "superuser": False, "roles": {}}
    roles = {m.org_id: Role(m.role).label for m in OrgMember.objects.filter(user=user)}
    return {"username": user.get_username(), "superuser": user.is_superuser, "roles": roles}
