# Roadmap

Open questions and possible future work.

- **Rank as a node field.** Whether to add `rank`, and if so where it comes
  from: WoRMS for anchored nodes and free text otherwise, free text always, or
  WoRMS only. It would allow ranks on unanchored nodes, e.g. `morphotype`.
- **References to sources other than WoRMS** (e.g. AlgaeBase, NCBI), which
  would turn `aphia_id` into a list of typed references.
- **Historical WoRMS states.** The live WoRMS API has no history, so it can't
  say what WoRMS looked like on a past date. If that's ever needed, e.g. to
  re-check an old revision against WoRMS as it was then, dated snapshots exist
  outside the API: periodic WoRMS exports in Darwin Core Archive (DwC-A) format,
  and archived WoRMS versions in GBIF ChecklistBank.
- **Aliases at a past revision.** `NODE_ALIAS` keeps added/removed times, so
  `?rev=` responses could return the aliases current when that revision was
  published, instead of today's.
- **Performance fallbacks**, only if needed:
  - a `CHANGE_EFFECT` table filled at publish, to map node versions to the
    changes that produced them ([backend.md](backend.md#reading-a-revision))
  - a per-revision ancestor/descendant table for deep subtree queries
    ([backend.md](backend.md#why-not-mptt-or-treebeard))
  - a `POST` variant of `GET /trees/{tree}/nodes` for long id lists
