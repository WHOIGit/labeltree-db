from django.contrib import admin

from .models import (
    Change,
    Changeset,
    Node,
    NodeAlias,
    NodeDescription,
    NodeVersion,
    Successor,
    Tree,
    TreeRevision,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Versioned data only changes by publishing a changeset."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Tree)
class TreeAdmin(ReadOnlyAdmin):
    """Only a tree's organization can change here, by a site admin; its content
    changes by publishing."""

    list_display = ["id", "title", "org"]
    list_filter = ["org"]
    fields = ["id", "title", "description", "org"]
    readonly_fields = ["id", "title", "description"]

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TreeRevision)
class TreeRevisionAdmin(ReadOnlyAdmin):
    list_display = ["tree", "number", "published_at", "published_by", "changeset"]
    list_filter = ["tree"]


@admin.register(Node)
class NodeAdmin(ReadOnlyAdmin):
    list_display = ["id", "tree", "created_in_rev", "deprecated_in_rev"]
    list_filter = ["tree"]


@admin.register(NodeVersion)
class NodeVersionAdmin(ReadOnlyAdmin):
    list_display = ["node", "version", "label", "parent", "valid_from_rev", "valid_to_rev"]
    list_filter = ["tree"]
    search_fields = ["label"]


@admin.register(Successor)
class SuccessorAdmin(ReadOnlyAdmin):
    list_display = ["deprecated_node", "successor_node", "position"]


@admin.register(Changeset)
class ChangesetAdmin(ReadOnlyAdmin):
    list_display = [
        "id", "tree", "new_tree_id", "new_tree_org", "state", "base_rev", "author", "updated_at",
    ]  # fmt: skip
    list_filter = ["state", "tree"]


@admin.register(Change)
class ChangeAdmin(ReadOnlyAdmin):
    list_display = ["changeset", "seq", "op", "group"]


@admin.register(NodeAlias)
class NodeAliasAdmin(admin.ModelAdmin):
    """Editable for repairs by site admins; curators use the alias endpoints."""

    list_display = ["alias", "node", "added_by", "added_at", "removed_by", "removed_at"]
    search_fields = ["alias"]
    raw_id_fields = ["node"]


@admin.register(NodeDescription)
class NodeDescriptionAdmin(admin.ModelAdmin):
    """New entries only: the history is kept, and saving "" clears a description."""

    list_display = ["node", "description", "added_by", "added_at"]
    search_fields = ["description"]
    raw_id_fields = ["node"]
    fields = ["node", "description"]

    def has_change_permission(self, request, obj=None):
        return obj is None

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.added_by = request.user.get_username()
        super().save_model(request, obj, form, change)
