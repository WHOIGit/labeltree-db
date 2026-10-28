import getpass
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Organization
from core.changesets import ChangesetError, NewTree, create_changeset, publish_changeset
from core.engine import TreeState, check_changes, specs_from_dicts
from core.importer import ImportFormatError, expand_import
from core.models import Tree
from worms import records
from worms.client import SCHEDULED_BACKOFF


class Command(BaseCommand):
    help = (
        "Import a label file as a new tree. The changeset is checked in memory first; "
        "it is saved and published as revision 1 only if it has no structural errors."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "file", type=Path, help="JSON import file, e.g. labeldata/NES2022_tags.json"
        )
        parser.add_argument("--tree", required=True, help="new tree id (slug)")
        parser.add_argument("--title", required=True)
        parser.add_argument(
            "--org", required=True, help="organization the tree belongs to (its id, e.g. amplify)"
        )
        parser.add_argument("--description", default="")
        parser.add_argument("--user", default=getpass.getuser(), help="author and publisher")
        parser.add_argument(
            "--notes", default=None, help="revision notes (default: 'Import of FILE')"
        )

    def handle(self, *args, file: Path, tree: str, title: str, org: str, description: str,
               user: str, notes, **options):  # fmt: skip
        try:
            data = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Can't read {file}: {exc}") from exc
        try:
            changes = expand_import(data)
        except ImportFormatError as exc:
            raise CommandError(f"Malformed import file at {exc.position}: {exc.detail}") from exc

        if not Organization.objects.filter(id=org).exists():
            raise CommandError(f"Organization {org} does not exist; create it in Django admin.")
        if Tree.objects.filter(id=tree).exists():
            raise CommandError(f"tree_exists: Tree {tree} already exists.")

        result = check_changes(TreeState(tree, 0), specs_from_dicts(changes))
        if result.errors:
            for e in result.errors:
                self.stderr.write(f"  change {e['seq']} ({e['node']}): {e['error']}: {e['detail']}")
            raise CommandError(
                f"Import aborted with {len(result.errors)} structural error(s); nothing was stored."
            )

        # Publishing reads cached WoRMS records only, so fetch the file's first, as
        # the web app's fetch step does. Failures leave those checks unavailable.
        aphia_ids = {n.aphia_id for n in result.state.nodes.values() if n.aphia_id is not None}
        client = records.default_client(backoff=SCHEDULED_BACKOFF)
        try:
            failed = records.get_records(aphia_ids, client=client).failed
        finally:
            client.close()
        for aphia_id, error in sorted(failed.items()):
            self.stderr.write(f"  WoRMS record {aphia_id} not fetched: {error}")

        changeset = create_changeset(
            author=user,
            changes=changes,
            new_tree=NewTree(tree, title, org, description),
            notes=notes if notes is not None else f"Import of {file.name}",
        )
        try:
            revision = publish_changeset(changeset, published_by=user)
        except ChangesetError as exc:
            raise CommandError(f"{exc.error}: {exc.detail}") from exc

        state = result.state
        self.stdout.write(
            self.style.SUCCESS(
                f"Published tree {tree} revision {revision.number} from changeset {changeset.pk}: "
                f"{len(state.nodes)} nodes, {len(state.child_ids(None))} top-level, "
                f"max depth {state.max_depth()}."
            )
        )
