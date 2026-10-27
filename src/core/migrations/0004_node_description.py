import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def copy_descriptions(apps, schema_editor):
    """Each node's last-version description becomes its first NodeDescription entry,
    credited to the author of the changeset that published that version."""
    NodeVersion = apps.get_model("core", "NodeVersion")
    NodeDescription = apps.get_model("core", "NodeDescription")
    TreeRevision = apps.get_model("core", "TreeRevision")
    latest = (
        NodeVersion.objects.exclude(description="")
        .order_by("node_id", "-version")
        .distinct("node_id")
    )
    entries = []
    for nv in latest:
        revision = TreeRevision.objects.select_related("changeset").get(
            tree_id=nv.tree_id, number=nv.valid_from_rev
        )
        entries.append(
            NodeDescription(
                node_id=nv.node_id,
                description=nv.description,
                added_by=revision.changeset.author,
                added_at=revision.published_at,
            )
        )
    NodeDescription.objects.bulk_create(entries)


class Migration(migrations.Migration):
    """Descriptions become unversioned: moved from NodeVersion to NodeDescription."""

    dependencies = [
        ("core", "0003_node_id_sequence"),
    ]

    operations = [
        migrations.CreateModel(
            name="NodeDescription",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("description", models.TextField(blank=True)),
                ("added_by", models.CharField(max_length=150)),
                ("added_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "node",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="descriptions",
                        to="core.node",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["node", "-added_at"], name="nodedescription_latest_idx")
                ],
            },
        ),
        migrations.RunPython(copy_descriptions, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="nodeversion",
            name="description",
        ),
    ]
