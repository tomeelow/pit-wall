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
[ADR-006](docs/adr/006-openf1-backbone.md)). Ingest a race, export the bundle and run the app:

```bash
make ingest SEASON=2024 ROUND=1
```

```bash
make export
```

```bash
make dev
```

The deploy workflow needs GitHub Pages set to deploy from GitHub Actions.

## Data sources

[OpenF1](https://openf1.org), with [Jolpica](https://github.com/jolpica/jolpica-f1) planned for
results history.

Unofficial project, not affiliated with Formula 1, the FIA or any team.
