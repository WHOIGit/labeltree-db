from django.core.management.base import BaseCommand

from worms.sync import clear_jobs


class Command(BaseCommand):
    help = (
        "Mark WoRMS syncs that are no longer running (their lock is free) as interrupted, "
        "e.g. after a restart. Run by start-django on startup."
    )

    def handle(self, *args, **options):
        if cleared := clear_jobs():
            self.stdout.write(f"Marked {cleared} interrupted WoRMS sync(s).")
