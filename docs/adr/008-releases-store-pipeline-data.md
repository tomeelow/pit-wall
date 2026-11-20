# ADR-008: Releases store the pipeline's data; the site is rebuilt from it

**Status:** accepted. Replaces ADR-003's "each finalised race bundle is uploaded as a release asset";
the rest of ADR-003 stands.

## Context
ADR-003 put each race's exported bundle in a per-season GitHub Release and had the Pages deploy
assemble the site from those assets. A bundle is derived output: when the contract or the exporter
changes, every published bundle is stale, and rebuilding it needs the canonical race tables and the
model parameters it was exported from. Those would then have to be stored somewhere too, or pulled
from OpenF1 again, which the project does not do for finished seasons. They are small: the 90 races
of 2023-2026 take 46 MB with their traces and parameters, and the models 2.4 MB.

## Decision
- One release per season, `data-<season>`, holds each race's directory as
  `race-<season>-<round>.tar.gz` (canonical tables, fastest-lap traces, and the model parameters
  exported to it) and the season's validation summary. A `models` release holds `.data/models`.
- Uploads replace an asset of the same name (`gh release upload --clobber`): publishing twice
  never duplicates an asset.
- The deploy downloads the store (`make data-pull`) and exports the bundle itself, so every deploy
  serves every race through the current code and contract. Export takes about 15 s for 90 races.
- The weekend workflow (`make weekend PUBLISH=1`) pulls the store, ingests the season's new races,
  pulls the previous race again with the cache bypassed (amended classifications), and, if
  anything changed, refits every model and runs every gate. All parameters publish together or not
  at all: a failed gate puts back the parameters that were live before the run, and only the
  changed races' descriptive data is uploaded. A new race then has no simulation until a run whose
  gates pass.
- The raw OpenF1 cache stays in `actions/cache`: it is a cache, and everything in the store is
  derived from it.

## Consequences
- A code or contract change reaches every published race on the next deploy, with no re-pull.
- The deploy depends on GitHub Releases being reachable, and on the store having been seeded once
  (`make data-push` from a machine holding the data).
- A refit replaces every race's parameters, so a passing run uploads all race assets (about 50 MB).
- The canonical tables in the store are the project's record of each race. Losing them would mean
  pulling finished seasons from OpenF1 again.
