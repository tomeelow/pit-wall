# Pit Wall

A race strategy lab for Formula 1. Pick a race and a driver and ask "what if he had pitted three
laps earlier?" or "one stop or two?". The answer is a distribution of finishing positions from
thousands of simulated races, not a single number.

Models are fitted in GitHub Actions after each race weekend and published as static files; the
simulator runs in your browser. There is no server.

> Early days: Phase 0 (walking skeleton) of [the implementation plan](docs/implementation_plan.md).
> The site currently shows each driver's tyre strategy for an ingested race.

## Layout

| Path | What |
|---|---|
| `pipeline/` | Python (uv): ingest, fit, export |
| `web/` | TypeScript (Vite + React): UI and, later, the simulation engine |
| `contract/` | JSON Schema of the exported files, generated from `pipeline/src/pitwall/export/contract.py` |
| `config/` | Pipeline configuration |
| `docs/` | Implementation plan and ADRs |

## Setup

Needs [uv](https://docs.astral.sh/uv/), Node 22.12+ (CI uses 24) and npm.

```bash
make setup
```

```bash
make verify
```

### Data

Race data comes from [OpenF1](https://openf1.org) (free, no key, 2023+; see
[ADR-006](docs/adr/006-openf1-backbone.md)). Ingest every finished race of a season (or one
race with `ROUND=`), export the bundle and run the app:

```bash
make ingest SEASON=2024
```

```bash
make export
```

```bash
make dev
```

Each race is validated before it is written; `.data/races/<season>/summary.json` lists every
race's errors (race not written) and warnings (data quirks, e.g. missing pit records). Compound
C-numbers come from Pirelli's published allocations in `config/compound_allocation.yaml`, with the
press releases cited per season.

Ingest also fetches each driver's fastest-lap car data and one lap of track location for the
replay and telemetry views ([ADR-007](docs/adr/007-fastest-lap-traces.md)); `make ingest-traces`
fills them in for races stored earlier. `make export` fails if a file is over the size budgets in
`config/budgets.yaml`.

The deploy workflow needs GitHub Pages set to deploy from GitHub Actions.

## Simulator calibration

`make validate-sim` (after `make export`) backtests the simulator. It covers every simulable race,
from four points in the race, with the actual strategies and sampled safety cars and retirements.
It scores whether the real result falls inside the simulated intervals as often as it should. A
second `make export` publishes the accepted report. Full numbers are under Phase 7 →
Findings in the [plan](docs/implementation_plan.md).

Where it is **not** well calibrated:
- **The last quarter of a race:** too confident. The real place falls inside the 50 % / 80 %
  intervals 44 % / 71 % of the time.
- **Races where a safety car, VSC or red flag actually happened** after the point simulated from:
  too confident (44 % / 73 %). Ex ante those events are only sampled.
- **Wet or mixed races:** not simulated at all. Neither is Miami 2025, where timing data is missing.

Known softening: pace and degradation are fitted on the whole race, the simulated one included.
Random events (safety cars, retirements) never are. Opponents keep their actual strategies
(open loop).

## Strategy tools: known weaknesses

- **The debrief prefers later stops.** Rivals cannot react, so covering an undercut is worth
  nothing. Tyre wear is linear, with no cliff. Its "should have stopped later" verdicts on first
  stops are therefore not evidence of a mistake.
- **Plans cannot react either.** A stop the team made because a safety car came out is judged, ex
  ante, as a planned green-flag stop.
- **Undercut probabilities above 0.6 are too confident** on the few real pairs seen: predicted
  0.70, happened 0.48. `make undercut-check` has the full table.
- **Search assumptions:**
  - Every compound counts as available new; which sets a driver had left is not in the data.
  - Compounds the race barely ran are not proposed.

## Data sources

[OpenF1](https://openf1.org), with [Jolpica](https://github.com/jolpica/jolpica-f1) planned for
results history.

Unofficial project, not affiliated with Formula 1, the FIA or any team.
