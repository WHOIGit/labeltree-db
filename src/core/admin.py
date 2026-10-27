from django.contrib import admin

from .models import Change, Changeset, Node, NodeAlias, NodeVersion, Successor, Tree, TreeRevision


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
    list_display = ["id", "title"]


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
    list_display = ["id", "tree", "new_tree_id", "state", "base_rev", "author", "updated_at"]
    list_filter = ["state", "tree"]


@admin.register(Change)
class ChangeAdmin(ReadOnlyAdmin):
    list_display = ["changeset", "seq", "op", "group"]


@admin.register(NodeAlias)
class NodeAliasAdmin(admin.ModelAdmin):
    """Editable so an operator can correct an alias until the alias API exists."""

    list_display = ["alias", "node", "added_by", "added_at", "removed_by", "removed_at"]
    search_fields = ["alias"]
    raw_id_fields = ["node"]
