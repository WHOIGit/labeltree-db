"""The table behind Django's database cache (settings.CACHES), so `migrate` alone
sets up a deployment and the test database."""

from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


def drop_cache_table(apps, schema_editor):
    schema_editor.execute("DROP TABLE IF EXISTS django_cache")


class Migration(migrations.Migration):
    dependencies = [("worms", "0001_worms_record")]

    operations = [migrations.RunPython(create_cache_table, drop_cache_table)]
