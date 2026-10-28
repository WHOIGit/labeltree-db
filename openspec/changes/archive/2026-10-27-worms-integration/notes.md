# Notes

## Live import of NES2022_taxonomy (task 6.2, 2026-10-28)

Run in the Compose environment against live WoRMS:

```sh
docker compose exec -T web python manage.py import_tree /labeldata/NES2022_taxonomy.json \
  --tree NES2022_taxonomy --title "NES2022 taxonomy"
docker compose exec -T web python manage.py run_drift NES2022_taxonomy --user cron
```

- Revision 1: 245 nodes, 6 top-level, max depth 5; 175 anchored nodes, all with
  `worms_data`. The import fetched each AphiaID's record and lineage once
  (350 calls); publish reused them because they were under 10 minutes old.
- A drift run re-fetches all 175 in about 40 s. `POST .../drift` returned `202`, a
  second `POST` during the run `409`, and status showed live progress.
- WoRMS is intermittently slow: one run stopped with `worms_unreachable` after 15
  of 175 AphiaIDs when a single request took 46 s and then returned `500`; the
  same request answered in 0.2 s moments later. The run wrote nothing, as
  specified, and the next run succeeded. Drift runs now retry four times, after
  10 s, 30 s, 1 min and 2 min (lookups and saves keep two retries after 1 s and
  2 s), well beyond a hiccup like this one.

### Warnings found

No `out_of_lineage`, `unknown_aphia` or `duplicate_aphia`: all 170 anchored
nodes with an anchored ancestor sit inside their WoRMS lineage. 13 nodes get
`unaccepted_aphia`:

| Node | AphiaID | WoRMS status | Accepted AphiaID |
|---|---|---|---|
| Asterionellopsis_glacialis | 149139 | unassessed | 148955 Asterionella glacialis |
| Chaetoceros_throndsenii | 163137 | unassessed | 163143 Miraltia throndsenii |
| Leptocylindrus_mediterraneus | 149230 | unassessed | 163261 Lauderia mediterranea |
| Dactyliosolen_blavyanus | 179786 | unassessed | 975336 Guinardia blavyana var. blavyana |
| Dactyliosolen_fragilissimus | 149310 | unassessed | 985165 Rhizosolenia fragilissima f. fragilissima |
| Guinardia_delicatula | 149112 | unassessed | 149114 Rhizosolenia delicatula |
| Guinardia_flaccida | 149132 | unassessed | 160530 Rhizosolenia flaccida |
| Guinardia_striata | 149113 | unassessed | 163243 Eucampia striata |
| Thalassiosira_rotula | 148942 | junior subjective synonym | 149102 Thalassiosira gravida |
| Tintinnidium_mucicola | 247944 | superseded combination | 1800184 Antetintinnidium mucicola |
| Emiliania_huxleyi | 115104 | unaccepted | 236056 Gephyrocapsa huxleyi |
| Lingulodinium_polyedra | 233592 | superseded combination | 1778370 Lingulaulax polyedra |
| Heterocapsa_triquetra | 110153 | unaccepted | 1346683 Kryptoperidinium triquetrum |

8 of the 13 are `unassessed` names for which WoRMS still gives a different
accepted name. Several of those "accepted" names look like older combinations
(e.g. *Guinardia delicatula* → *Rhizosolenia delicatula*), which is WoRMS data
worth a curator's look rather than an automatic rename.

The same 13 warnings, from recorded responses, are the expected fixture of the
task 6.1 test (`src/worms/tests/expected_taxonomy_warnings.json`).
