import getpass

from django.core.management.base import BaseCommand, CommandError

from core.models import Tree
from worms.sync import SyncBusy, run_job


class Command(BaseCommand):
    help = (
        "Sync cached WoRMS records and re-check warnings: every AphiaID in a tree "
        "(sync_tree), only its uncached AphiaIDs (--new, sync_new), or every cached and "
        "used AphiaID in all trees (--all, sync_all). Runs in the foreground, so cron can "
        "schedule it, with long retries. Exits non-zero if any AphiaID failed (after "
        "writing the warnings it could) or another sync overlaps. Never edits a tree."
    )

    def add_arguments(self, parser):
        parser.add_argument("tree", nargs="?", help="tree id, e.g. NES2022_taxonomy")
        parser.add_argument("--new", action="store_true", help="only AphiaIDs not yet cached")
        parser.add_argument("--all", action="store_true", help="every tree and cached record")
        parser.add_argument("--user", default=getpass.getuser(), help="who started the sync")

    def handle(self, *args, tree, new, user, **options):
        everything = options["all"]
        if everything == (tree is not None) or (everything and new):
            raise CommandError("Give a tree (optionally with --new), or --all.")
        if tree is not None and not Tree.objects.filter(id=tree).exists():
            raise CommandError(f"Tree {tree} does not exist.")
        kind = "sync_all" if everything else "sync_new" if new else "sync_tree"
        try:
            status = run_job(kind, tree=tree, started_by=user, scheduled=True)
        except SyncBusy as exc:
            raise CommandError(str(exc)) from exc

        where = "all trees" if everything else tree
        rows = sum(c["rows_added"] for c in status["checked"])
        self.stdout.write(
            f"{kind} on {where}: fetched {status['done']} of {status['total']} AphiaIDs, "
            f"{rows} node(s) with changed warnings."
        )
        if status["failed"]:
            for failure in status["failed"]:
                self.stderr.write(
                    f"  {failure['aphia_id']}: {failure['reason']}: {failure['detail']}"
                )
            raise CommandError(f"{len(status['failed'])} AphiaID(s) failed.")
