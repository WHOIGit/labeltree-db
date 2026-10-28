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
python manage.py import_tree ../labeldata/NES2022_tags.json --tree NES2022_tags --title "NES2022 tags"
```

Options: `--description`, `--notes` (revision notes, default `Import of <file>`)
and `--user` (author and publisher, default the current OS user).

Importing a tree with AphiaIDs fetches their WoRMS records, so it needs access
to marinespecies.org. If WoRMS can't be reached, the import still succeeds and
the next drift run fills in the warnings.

## WoRMS drift runs

A [drift run](design/worms.md#drift-reports) re-fetches every AphiaID in a
tree's latest revision from WoRMS and updates its nodes' WoRMS warnings. It
never edits the tree. Run it from `src/`:

```sh
python manage.py run_drift NES2022_taxonomy --user cron
```

It runs in the foreground and exits non-zero if WoRMS keeps failing or another
run on the tree is active. `--user` is recorded as who started the run (default
the current OS user). `POST /api/v1/trees/{tree}/drift` starts the same run in
the background; `GET /api/v1/trees/{tree}/drift/status` shows its progress and
`GET /api/v1/trees/{tree}/drift` lists the nodes with warnings.

To run it nightly on the production host, add a crontab entry there, using the
deploy directory and image from `deploy.sh`:

```
# m h dom mon dow  command
30 3 * * *  cd /srv/labeltree-db && IMAGE=registry.example.org/amplify/labeltree-db:latest docker compose exec -T web python manage.py run_drift NES2022_taxonomy --user cron
```

## Design documents

- [Backend](design/backend.md): data model, versioning rules, atomic changes
- [API](design/api.md): read and write endpoints, auth and roles, consumer guide
- [Web app](design/webapp.md): changeset workflow, merge and split, import
- [WoRMS](design/worms.md): placement checks, drift reports, WoRMS caching
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
