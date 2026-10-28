from django.core.management.base import BaseCommand

from core.models import Tree
from worms.drift import clear_status


class Command(BaseCommand):
    help = (
        "Clear drift-run status left by runs that are no longer running (their lock is "
        "free), e.g. after a restart. Run by start-django on startup."
    )

    def handle(self, *args, **options):
        for tree_id in Tree.objects.values_list("id", flat=True):
            if clear_status(tree_id):
                self.stdout.write(f"Cleared interrupted drift run on {tree_id}.")
