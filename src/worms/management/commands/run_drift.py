import getpass

from django.core.management.base import BaseCommand, CommandError

from core.models import Tree
from worms.drift import DriftBusy, run_drift


class Command(BaseCommand):
    help = (
        "Re-fetch every AphiaID in a tree's latest revision from WoRMS and update its "
        "nodes' warnings. Runs in the foreground, so cron can schedule it; exits non-zero "
        "if the run fails or another run on the tree is active. Never edits the tree."
    )

    def add_arguments(self, parser):
        parser.add_argument("tree", help="tree id, e.g. NES2022_taxonomy")
        parser.add_argument("--user", default=getpass.getuser(), help="who started the run")

    def handle(self, *args, tree: str, user: str, **options):
        if not Tree.objects.filter(id=tree).exists():
            raise CommandError(f"Tree {tree} does not exist.")
        try:
            result = run_drift(tree, user)
        except DriftBusy as exc:
            raise CommandError(str(exc)) from exc
        if not result["ok"]:
            raise CommandError(
                f"Drift run on {tree} failed after {result['done']} of {result['total']} "
                f"AphiaIDs: {result['reason']}: {result['detail']}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Drift run on {tree} revision {result['checked_rev']}: re-fetched "
                f"{result['total']} AphiaIDs, {result['rows_added']} node(s) with changed warnings."
            )
        )
