# Proposal

## Why

Downstream AMPLIfy apps (roi-db, amplify-datasetman, annotation tools) need a
single source of truth for label hierarchies that they can reference by stable
node id and query as of any past revision. Nothing is built yet; the design in
`design/` is settled enough to build the core: the versioned tree model, the
changeset engine that produces every revision, and the read API that consumers
pull from. The first concrete goal is serving the `NES2022_tags` example tree
through the read API.

## What Changes

- New Django + django-ninja service on PostgreSQL, run with Docker Compose.
- Versioned data model: trees, tree revisions, nodes and node versions, with
  revision-range validity, version-bump rules, labels, deprecation and
  successors.
- Changeset engine: ordered atomic changes (`add`, `edit`, `move`,
  `deprecate`), placeholder ids, op reduction at save, structural validation,
  and publish, which requires `base_rev` to be the latest revision and creates
  exactly one new revision.
- A tree only exists once it has a revision: a changeset with no `base_rev`
  carries the new tree's id and title, and publishing it creates the tree and
  revision 1 together.
- Import: the nested content-shape format expands into one group of `add`
  changes; a management command imports a file as a new tree and publishes it.
- Node aliases: stored, unversioned, returned on nodes and searched. Writing
  them through the API comes in a later change.
- Read API under `/api/v1`: node and tree endpoints, the lite, content and
  detailed shapes, deprecation records, diff, export, label lookup and search.
- Read endpoints are open (no authentication) until access control arrives in
  `webapp-and-write-api`. `worms_data` is `null` and `worms_warnings` is `[]`
  until `worms-integration`.

## Capabilities

### New Capabilities

- `tree-versioning`: trees, revisions, nodes and node versions; label rules;
  what bumps a node version; deprecation and successors; reading a revision.
- `changesets`: atomic changes and their preconditions, placeholder ids, op
  reduction, structural errors, changeset states, and publishing a revision
  (including a tree's first revision).
- `tree-import`: the import file format and its expansion into an `import#n`
  group of `add` changes, and importing a file as a new tree.
- `node-aliases`: alias storage and history, uniqueness, and how aliases appear
  on nodes and in search.
- `node-read-api`: `/nodes/{id}` endpoints, node shapes, deprecation records,
  ancestors, descendants and version history.
- `tree-read-api`: `/trees` endpoints: tree info, revision history, revision
  changes, diff, browsing and export, label lookup and search.
- `api-conventions`: base path, error body and status codes, `?rev` handling,
  `?dropempty`, caching headers and pagination shared by all endpoints.

### Modified Capabilities

(none)

## Impact

- New codebase: Django project, PostgreSQL schema and migrations, Docker
  Compose setup, test suite.
- New public read API at `/api/v1`, unauthenticated for now.
- `labeldata/NES2022_tags.json` becomes the first loaded tree and the
  acceptance data set. `NES2022_taxonomy` is loaded after
  `worms-integration`.
