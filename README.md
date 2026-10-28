# labeltree-db

Source-of-truth service for AMPLIfy label hierarchies. Consumers such as
roi-db, amplify-datasetman and annotation tools reference labels by node id and
pull trees, labels, aliases and WoRMS AphiaIDs from its REST API.

Proposed stack: Django + django-ninja, PostgreSQL, Docker Compose. A
management web app for editing trees lives in the same Django project.

## Goals

1. **Stable references.** A label can always be resolved by its node id, even
   after the node is renamed, moved within its tree, or deprecated (removed,
   with optional successors). Non-taxon labels such as `detritus` or
   `bubble` are ordinary nodes.
2. **History.** Past states of a tree remain queryable as the tree
   changes over time.
3. **WoRMS anchoring.** A node may carry a WoRMS AphiaID. Its placement is
   checked against WoRMS; WoRMS disagreements show up as warnings.

## How it works

Four core tables:

- `tree`: title
- `tree_revision`: one per published edit to a tree
- `node`: a permanent, globally unique id, its tree, and the revisions in
  which it was created and deprecated
- `node_version`: the node's versioned data (label, parent, AphiaID) and
  the range of tree revisions the node version data is valid for

Descriptions and aliases are unversioned: they are kept per node with their
history, and reads always show the current ones.

Edits are drafted as a **changeset**: an ordered list of atomic changes
(`add`, `edit`, `move`, `deprecate`). When an approver publishes a changeset,
it becomes the next tree revision, and each node it touches gets a new node
version. Because every tree revision is the results of list of atomic changes, 
a tree's history is easy to audit.

A node id plus a tree revision gives exactly one node version, with that
revision's parent and children. Consumers store `(node_id, tree_rev)` and 
can therefor always get the current or historic label and label parent/children 
relationships.

![System overview](design/diagrams/01-system-overview.png)

## Loading a tree

A label file (see [import format](design/webapp.md#import-format)) is loaded as
a new tree with the `import_tree` management command. It checks the whole
import first and stores nothing if any label is a duplicate or not
machine-safe; otherwise it publishes the file as the tree's revision 1.

In `nix develop`, with the database running (`db-start`) and migrated:

```sh
cd src
python manage.py import_tree ../labeldata/NES2022_tags.json --tree NES2022_tags --title "NES2022 tags" --org amplify
```

`--org` is the [organization](#users-organizations-and-tokens) the tree belongs
to; it must exist. Other options: `--description`, `--notes` (revision notes,
default `Import of <file>`) and `--user` (author and publisher, default the
current OS user).

Importing a tree with AphiaIDs fetches their WoRMS records before publishing,
so it needs access to marinespecies.org. If WoRMS can't be reached, the import
still succeeds, lists the AphiaIDs it couldn't fetch, and the next sync fills
in their warnings.

## Users, organizations and tokens

Reading trees and nodes needs no login. Everything else needs a user with a
[role](design/api.md#authentication-and-roles) in the tree's organization:
`reader` < `drafter` < `approver` < `owner`, each including the ones below and
applying to every tree of the organization. Every tree belongs to one
organization; the existing trees are in `amplify` (AMPLIfy). Superusers are
site admins: they are owners in every organization and manage users and
organizations in Django admin at `/admin/`. A superuser is created on start
from `DJANGO_SUPERUSER_USERNAME` and `DJANGO_SUPERUSER_PASSWORD`.

To set up an organization and its first owner, in Django admin:

1. **Organizations → Add organization**: a slug id and a name. (`amplify`
   already exists.)
2. **Users → Add user**, unless they already have an account.
3. **Org members → Add org member**: pick the user and organization, role
   `owner`.

Owners then add and promote the other members on the organization's page, and
create new trees in it. To move a tree to another organization, change its
organization on the tree's admin page.

Scripts that write authenticate with an API token:

1. **Api tokens → Add api token**: pick the user the script acts as, and name
   the token after the script.
2. Copy the key from the message shown after saving. It is shown only once;
   only a hash is stored.
3. Send it with every request:

   ```sh
   curl -H "Authorization: Token <key>" https://labeltree.example.org/api/v1/orgs/amplify/members
   ```

The token acts with its user's roles. To revoke it, select it in **Api
tokens** and run **Revoke selected tokens**.

## WoRMS syncs

A [sync](design/worms.md#worms-jobs-and-syncs) re-fetches a tree's AphiaIDs
from WoRMS into the record cache and updates its nodes' WoRMS warnings. It
never edits the tree. Run it from `src/`:

```sh
python manage.py worms_sync NES2022_taxonomy --user cron   # every AphiaID in the tree
python manage.py worms_sync NES2022_taxonomy --new         # only those not cached yet
python manage.py worms_sync --all                          # every tree and cached record
```

It runs in the foreground, retrying WoRMS for up to a few minutes. An AphiaID
that still fails is skipped; the sync writes the warnings it can, lists the
failures and exits non-zero, so cron mail reports them. It also exits non-zero
if another sync on the tree (or a `--all` sync) is active. `--user` is recorded
as who started it (default the current OS user).

In the API, `POST /api/v1/worms/jobs` starts the same syncs in the background,
`GET /api/v1/worms/jobs?tree=` and `GET /api/v1/worms/jobs/{job}` show their
progress, and `GET /api/v1/worms/warnings?tree=` lists the nodes with warnings.

To run it nightly on the production host, add a crontab entry there, using the
deploy directory and image from `deploy.sh`:

```
# m h dom mon dow  command
30 3 * * *  cd /srv/labeltree-db && IMAGE=registry.example.org/amplify/labeltree-db:latest docker compose exec -T web python manage.py worms_sync NES2022_taxonomy --user cron
```

## Design documents

- [Backend](design/backend.md): data model, versioning rules, atomic changes
- [API](design/api.md): read and write endpoints, auth and roles, consumer guide
- [Web app](design/webapp.md): changeset workflow, merge and split, import
- [WoRMS](design/worms.md): placement checks, syncs and the warnings report, WoRMS caching
- [Roadmap](design/roadmap.md): open questions and future work

Diagram sources and rendering instructions are in
[`design/diagrams/`](design/diagrams/).

### Design Highlights

#### Backend Data model 

![Data Model](design/diagrams/02-data-model.png)

#### Web App Mockup

Check out the interactive [web app mockup](design/mockups/webapp-mockup.html)
of the tree browser and draft editor (local only).

![Web app mockup](design/mockups/webapp-mockup-snapshot.png)

#### API Consumer Interaction Diagram
![API-Consumer Interaction](design/diagrams/05-consumer-lookups.png)
