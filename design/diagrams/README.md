# labeltree-db diagrams

Sources for the diagrams in the design docs. Each diagram is explained where
it is used:

| Diagram | Used in |
|---|---|
| `01-system-overview.mmd` | [README](../../README.md) |
| `02-data-model.d2` | [backend.md](../backend.md) |
| `03-changeset-lifecycle.mmd` | [webapp.md](../webapp.md#changesets-and-concurrency) |
| `04-node-merge-and-split-options/04a–d` | [webapp.md](../webapp.md#merge-and-split) |
| `05-consumer-lookups.mmd` | [api.md](../api.md#consumer-guide) |
| `06-worms-sync.mmd` | [worms.md](../worms.md#worms-jobs-and-syncs) |

Colour key used throughout: **green** = new node, **yellow** = node version
increased or warning raised, **grey dashed** = deprecated node, **blue** =
event or change description.

## Rendering

### Mermaid (`.mmd`)

The diagrams render in any Mermaid-aware viewer, such as VS Code with a Mermaid
extension or https://mermaid.live. To export them with the Mermaid CLI:

```bash
# on NixOS, use: "nix-shell -p mermaid-cli" to set environment
mmdc -i diagramX.mmd -o diagramX.png -s 4 -b white
# where -s is resolution, 3-4 is good for print
#       -b is background color
#       -w is page width in pixels
# Bulk command (04a-d live in 04-node-merge-and-split-options/):
for f in *.mmd 04-*/*.mmd; do mmdc -i "$f" -o "${f%.mmd}.png" -s 4 -b white; done
```

### D2 (`02-data-model.d2`)

An ER diagram in [D2](https://d2lang.com/tour/sql-tables/), so edges connect
specific columns. Render with the ELK layout. D2's own PNG export needs
Playwright, which fails to install on NixOS, so rasterise the SVG with headless
Chromium (it honours the fonts D2 embeds; `rsvg-convert` doesn't, and the text
overlaps):

```bash
nix-shell -p d2 --run 'd2 --layout elk 02-data-model.d2 02-data-model.svg'
# width/height come from the SVG header
nix-shell -p chromium --run 'chromium --headless --no-sandbox --hide-scrollbars \
  --force-device-scale-factor=2 --window-size=3376,1367 \
  --screenshot=$PWD/02-data-model.png file://$PWD/02-data-model.svg'
```
