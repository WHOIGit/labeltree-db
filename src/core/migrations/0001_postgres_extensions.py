from django.contrib.postgres.operations import BtreeGistExtension, TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    """Enable the PostgreSQL extensions the tree model relies on.

    btree_gist: exclusion constraint on (tree, label, revision range).
    pg_trgm: fuzzy label search.
    """

    initial = True

    dependencies = []

    operations = [
        BtreeGistExtension(),
        TrigramExtension(),
    ]
