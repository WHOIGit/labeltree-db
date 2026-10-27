from django.db import migrations


class Migration(migrations.Migration):
    """Global node id sequence, drawn from only when a changeset is published."""

    dependencies = [
        ("core", "0002_tree_model"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE SEQUENCE core_node_id_seq START 1",
            reverse_sql="DROP SEQUENCE core_node_id_seq",
        ),
    ]
