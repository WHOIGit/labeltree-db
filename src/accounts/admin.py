from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone

from .models import ApiToken, Organization, OrgMember, Role, User, new_key

admin.site.register(User, UserAdmin)


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """Site admins issue and revoke tokens. The key is shown once, after adding."""

    list_display = ["name", "user", "created_at", "last_used_at", "revoked_at"]
    list_filter = ["revoked_at"]
    search_fields = ["name", "user__username"]
    readonly_fields = ["created_at", "last_used_at"]
    actions = ["revoke"]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ["user", "name"]
        return ["user", "name", "created_at", "last_used_at", "revoked_at"]

    def get_readonly_fields(self, request, obj=None):
        return [*self.readonly_fields, "user"] if obj is not None else []

    def save_model(self, request, obj, form, change):
        if not change:
            key, obj.key_hash = new_key()
            self.message_user(
                request,
                f"Token key for {obj.user}: {key}  (copy it now; it is not shown again)",
                messages.WARNING,
            )
        super().save_model(request, obj, form, change)

    @admin.action(description="Revoke selected tokens")
    def revoke(self, request, queryset):
        count = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f"Revoked {count} token(s).")


class OrgMemberInline(admin.TabularInline):
    model = OrgMember
    raw_id_fields = ["user"]
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Site admins create organizations; owners manage members on its page."""

    list_display = ["id", "name"]
    inlines = [OrgMemberInline]

    def get_readonly_fields(self, request, obj=None):
        return ["id"] if obj is not None else []


@admin.register(OrgMember)
class OrgMemberAdmin(admin.ModelAdmin):
    """For repairs, such as an organization left with no owner."""

    list_display = ["org", "user", "role_name"]
    list_filter = ["org", "role"]
    search_fields = ["user__username"]
    raw_id_fields = ["user"]

    @admin.display(description="role", ordering="role")
    def role_name(self, obj):
        return Role(obj.role).label
