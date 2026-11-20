# Implementation Plan: Pit Wall — F1 Race Strategy Lab

> **Goal:** a race strategy simulator you can interrogate. Pick a race and a driver and ask
> *"what if he had pitted 3 laps earlier?"*, *"one stop or two?"*, *"medium → hard or hard → medium?"*.
> The system runs thousands of Monte Carlo races and answers with a **distribution of finishing
> positions**, not a single number.
>
> **Headline constraint:** zero running cost. Models are fitted in GitHub Actions after each race
> weekend and published as static files; the Monte Carlo runs in the browser in a Web Worker.
> There is no server.
>
> **Scope of v1:** post-race analysis of 2023+ races. Live timing during a race is a paid OpenF1
> tier and is out of scope.

---

## Status

Update this table as phases land. It is the first thing to read when picking up work.

| Phase | Status | Notes |
|---|---|---|
| 0 — Setup, ADRs, contract skeleton | ☑ done | OpenF1 ingest verified on 2024 R1–R2; stint chart checked in the browser. Pages deploy runs from `main` once Pages is set to GitHub Actions |
| 1 — Ingestion | ☑ done | 90 races (2023 R1 – 2026 R20) ingested, 0 rejected; allocations sourced from Pirelli releases. Known source gaps listed under Phase 1 → Findings |
| 2 — Lap classification & race state | ☐ not started | |
| 3 — Tyre degradation model | ☐ not started | |
| 4 — Pit loss, SC/VSC, reliability | ☐ not started | |
| 5 — Traffic & overtaking | ☐ not started | |
| 6 — Simulation engine | ☐ not started | |
| 7 — Simulator validation | ☐ not started | |
| 8 — Strategy optimiser, counterfactuals, undercut | ☐ not started | |
| 9 — Strategy lab UI | ☐ not started | |
| 10 — Analytics: replay, telemetry, debrief | ☐ not started | |
| 11 — Post-weekend automation & publishing | ☐ not started | |
| 12 — Docs & polish | ☐ not started | |

**Build order note:** Phase 0 ends with a *walking skeleton* — one race ingested, a trivial
output (the race's stint chart) exported through the contract, loaded by the web app, and deployed to Pages. Every later
phase thickens a pipe that already runs end to end. Do not build the Bayesian model before the
export path exists.

---

## Architecture Overview

```
          ┌──────────────────────────────────────────────────────────┐
          │ GitHub Actions — cron after each race weekend + manual    │
          └────────────────────────────┬─────────────────────────────┘
                                       │
   ┌───────────────────────────────────┼──────────────────────────────────┐
   ▼                                   ▼                                  ▼
 Ingest (Python)               Fit models (Python)                 Validate (gates)
 • OpenF1 laps/stints/pits/    • tyre degradation (Bayesian)       • sampler diagnostics
   race control/intervals/     • pit loss per track                • held-out lap-time score
   location/car data           • SC/VSC hazard per track           • simulator calibration
 • Jolpica results/calendar    • traffic + overtake probability      (runs the TS engine
   │                           • reliability (DNF hazard)             under Node)
   ▼                                   │                                  │
 Clean laps + race-state               ▼                                  │
 snapshots per lap ─────────►  Export via versioned contract ◄────────────┘
                               (pydantic → JSON Schema → TS types)   gate fails → keep the
                                       │                             previously published params
                                       ▼
                         Static bundle on GitHub Pages
                         manifest.json · /races/{season}/{round}/… · /models/…
                                       │
                                       ▼
   ┌──────────────────────────── Browser ─────────────────────────────────┐
   │ UI (TypeScript)  ──postMessage──►  Web Worker pool: Monte Carlo engine│
   │  strategy lab · undercut · replay · telemetry compare · debrief       │
   └───────────────────────────────────────────────────────────────────────┘
```

**Core design principle:** Python *fits*, TypeScript *simulates*. There is exactly one simulation
engine and it lives in `web/src/sim/`. Validation in CI runs that same engine under Node — never a
Python re-implementation. Divergence between "the sim we validated" and "the sim users run" is the
bug class this split exists to prevent.

---

## Data Sources

| Data | What it gives us | Source | Access |
|---|---|---|---|
| Lap timing | Lap times, sector times, pit-out flag, speed traps | OpenF1 `/laps` | Free, no key, 2023+ |
| Stints | Compound per stint, `tyre_age_at_start` (used sets from quali matter) | OpenF1 `/stints` | Free, no key, 2023+ |
| Pit stops | Pit-lane duration per stop | OpenF1 `/pit` | Free |
| Race control | SC / VSC / red flag / yellow flag messages with timestamps and laps | OpenF1 `/race_control` | Free |
| Intervals | Gap to leader and to car ahead (~4 s cadence) | OpenF1 `/intervals` | Free |
| Position / location | x, y, z on track (~3.7 Hz) — replay and track outline | OpenF1 `/location` | Free |
| Car telemetry | Speed, throttle, brake, gear, RPM, DRS | OpenF1 `/car_data` | Free |
| Weather | Air/track temp, rain flag, wind | OpenF1 `/weather` | Free |
| Results & calendar | Classification (OpenF1 `/session_result`); grid, DNF reasons, calendar, multi-year history | OpenF1 + Jolpica (Ergast-compatible; Ergast itself is shut down) | Free |
| Compound allocation | Which Pirelli C-number is SOFT/MEDIUM/HARD at each event | Pirelli pre-race press releases | **Hand-maintained** `config/compound_allocation.yaml` |

### Notes that shape the design
- **OpenF1 is the backbone (ADR-006).** FastF1 now needs a paid F1TV subscription, so it is not
  used. The cost is history: OpenF1 starts in 2023, so SC/VSC statistics have only ~3–4 races per
  track and must pool hard across tracks (Phase 4). Jolpica adds results history and DNF reasons.
- **OpenF1 has no round numbers.** The round is the race's position among the season's
  non-cancelled `Race` sessions, sorted by start time (`find_race_session`).
- **OpenF1 is rate-limited** on the free tier. Throttle, cache every raw response on disk, and never
  re-fetch a finished session unless asked.
- **Compound labels are relative.** "SOFT" is C3 at one race and C5 at another. Degradation is a
  property of the C-number and the track, so the model keys on C-number. The allocation table has no
  free API — it is a YAML file and ingestion fails loudly if a race is missing from it.
- **Results get amended.** Post-race penalties change the classification hours or days later.
  Re-pull the most recent race on every run.
- **Regulation eras.** 2023–2025 is one car era; 2026 brought new chassis, power-unit and tyre
  regulations. Lap-time and degradation behaviour does not pool cleanly across that boundary —
  `era` is an explicit level in every model.
- **Team identity changes** (AlphaTauri → RB → Racing Bulls, Alfa Romeo → Sauber → Audi, new
  entries). Keep a `config/teams.yaml` mapping season-specific names to a stable `team_id`.

### Canonical tables (pipeline-internal, parquet)

```python
@dataclass
class Lap:
    season: int
    round: int
    session: str                 # "R" or "S" (sprint) — v1 models races; sprints are a later add
    driver: str                  # three-letter code, stable within a season
    team_id: str                 # stable across renames (config/teams.yaml)
    lap: int                     # 1-indexed, as in official timing
    lap_time_s: float | None
    compound: str                # SOFT/MEDIUM/HARD/INTERMEDIATE/WET as reported
    compound_c: int | None       # Pirelli C-number from the allocation table; None for wet tyres
    tyre_age: int                # laps on this set at the END of this lap, including pre-race use
    stint: int
    position: int | None
    gap_ahead_s: float | None    # to the car physically ahead, end of lap
    track_status: str            # GREEN / SC / VSC / RED / YELLOW (worst status during the lap)
    lap_class: str               # see Phase 2 — the single source of truth for "is this lap clean"
    dataset_version: str         # content hash of the inputs that produced this row
```

Plus `stints`, `pit_stops`, `neutralisations` (SC/VSC/red periods with start/end lap), `results`,
and `race_state` (one row per driver per lap — see Phase 2).

---

## Phase 0 — Setup, ADRs, Contract Skeleton

**Goal:** a monorepo with both toolchains, one verify command, the export contract, and a deployed
walking skeleton.

### Repository structure
```
pit-wall/
├── pipeline/                    # Python, uv
│   ├── src/pitwall/
│   │   ├── ingest/              # OpenF1 / Jolpica clients, raw cache
│   │   ├── laps/                # lap classification, race-state reconstruction
│   │   ├── models/              # degradation, pit loss, neutralisations, traffic, reliability
│   │   ├── export/              # pydantic contract models + writers
│   │   └── validate/            # model diagnostics, held-out scores, calibration gate
│   ├── tests/
│   └── pyproject.toml
├── web/                         # TypeScript, Vite, npm
│   ├── src/sim/                 # THE simulation engine (pure, no DOM, seeded RNG)
│   ├── src/worker/              # Web Worker entry + pool
│   ├── src/contract/            # generated types — do not hand-edit
│   ├── src/app/                 # UI
│   ├── scripts/backtest.ts      # runs the engine under Node for CI validation
│   └── tests/
├── contract/                    # generated JSON Schema (from pydantic)
├── config/                      # seasons, compound allocation, teams, regulations, thresholds, budgets
├── docs/
│   ├── implementation_plan.md   # this file
│   └── adr/                     # one file per decision
├── .github/workflows/           # ci.yml (on PR), weekend.yml (cron + dispatch)
├── Makefile                     # make verify, make contract, make ingest RACE=2025-05 …
└── README.md
```

### Tooling
Dependencies are added in the phase that first uses them (pandera in 1, PyMC/nutpie/ArviZ in 3,
hypothesis with the first property tests), not up front.

- **Pipeline (uv, Python 3.13):** requests, requests-cache, pandas, pyarrow, numpy (< 2.5 while on
  pandas 2.3), pydantic, pyyaml, loguru; dev: ruff, pyright, pytest, pandas-stubs, types-pyyaml,
  types-requests.
- **Web (npm, exact versions via `.npmrc`):** react; dev: vite, @vitejs/plugin-react, typescript 6.0
  (typescript-eslint does not support 7 yet), eslint, typescript-eslint, eslint-plugin-react-hooks,
  vitest, json-schema-to-typescript. CI runs Node 24 LTS.

`make verify` = ruff check + ruff format --check + pyright + pytest (pipeline) **and**
tsc --noEmit + eslint + vitest (web) **and** contract freshness (regenerate into a temp dir and
`diff` against the committed files).
CI runs exactly `make verify`.

### The export contract
- Pydantic models in `pipeline/src/pitwall/export/contract.py` are the source of truth.
- `make contract` writes `contract/*.schema.json` and generates `web/src/contract/*.ts` from them.
- Every published file carries `schema_version` (semver). The web app refuses a bundle whose major
  version it does not know, rather than mis-reading it.
- `manifest.json` at the bundle root lists races, model versions (git sha + dataset hash + fit date)
  and file sizes.

### ADRs to write before coding (`docs/adr/`)
1. **Python fits, TypeScript simulates — one engine.** The engine runs in the browser, so it is TS.
   Validation runs it under Node. No Python port "for quick checks". Rust/WASM only if profiling
   proves TS too slow.
2. **Hierarchical Bayesian degradation (PyMC) over per-stint OLS.** Per-stint fits are noisy and
   undefined for short stints; partial pooling across era × track × compound × team gives stable
   estimates with honest uncertainty, and posterior draws feed the simulator directly.
3. **Static bundle on GitHub Pages; durable storage in GitHub Releases.** Generated data is never
   committed. Each finalised race's processed bundle is uploaded as a release asset (one release
   per season); the Pages deploy assembles the site from release assets plus the freshly built app.
   Rejected: a data branch (bloats history), actions/cache alone (evicts after 7 days unused),
   paid object storage (breaks the zero-cost constraint).
4. **Open-loop opponents in v1.** In a counterfactual, other cars keep their actual strategies
   (shifted only where the rules force it). Reactive opponents are a later phase. The UI says so.
5. **Post-race only.** No paid OpenF1 tier, no live mode in v1.
6. **OpenF1 as the ingestion backbone** (added during Phase 0, when FastF1 turned out to need a
   paid F1TV subscription).

**Deliverable:** walking skeleton — one race ingested, its stint chart (per-driver compounds and
stint laps, used again by the Phase 9 race summary) exported through the contract, loaded and
plotted by the web app, deployed to Pages by CI.
`make verify` green.

---

## Phase 1 — Ingestion

**Goal:** reproducible, cached, validated canonical tables for every 2023+ race (and older seasons
where needed for SC statistics).

- `pitwall.ingest` wraps OpenF1 (and Jolpica, when results history is needed) behind small
  functions per table, each writing parquet under a configured data dir (never inside the repo).
- Raw API responses cached on disk (requests-cache, SQLite) with retry and backoff on 429/5xx.
- Join compound C-numbers from `config/compound_allocation.yaml`; map team names to `team_id`.
- **Validation (pandera) on every race:** one row per driver per lap; lap numbers contiguous per
  driver until retirement; lap times within plausible bounds for the track; every stint has a
  compound; every dry compound has a C-number; pit stops align with stint changes; neutralisation
  periods have both start and end.
- `dataset_fingerprint()` hashes the canonical tables; every downstream artefact records it.
- Log per race: row counts, missing laps, unmatched pit stops, races skipped and why.

**Deliverable:** `make ingest SEASON=2025` builds all races of a season idempotently; a validation
summary per season; tests for the C-number join, team mapping and a race with a red flag.

### Findings (from the first full ingest)

Validation errors block a race from being written; warnings land in
`.data/races/<season>/summary.json`. What the warnings showed, for Phases 2 and 4 to handle:

- **No pit records for 2023 R1–R6** in OpenF1. `pit_in` is all false there; Phase 2 must infer
  in-laps from `pit_out` and stint changes for those races, and Phase 4 must not fit pit loss on them.
- **2025 R6 (Miami): laps 2–24 missing for every driver.** Exclude the gap from anything that needs
  lap-to-lap continuity (race state, gaps, traffic).
- **Stints that start on the pit in-lap** in some sessions; `canonical_laps` moves those boundaries
  to the out-lap (pit record and `is_pit_out_lap` agree). Remaining mismatches (e.g. 2026 R16:
  stints split on lap 2 with the stop much later) are source errors and stay as warnings.
- **Pit records with no tyre change** under red flags (pit-lane queues, 20–40 min lane times) and
  for drive-throughs / repairs. Phase 4's pit-loss fit must filter by lane time and neutralisation.
- **Drivers out on lap 1** have one timed lap but `laps_completed = 0`; classification is right.
- Lap-time bounds are relative to the race median, so wet or mixed races (2024 R9, 2025 R12) flag
  fast dry laps as low outliers. Lap classification (Phase 2) owns the real thresholds.

---

## Phase 2 — Lap Classification & Race State (the foundation — read carefully)

Every model downstream is only as good as the decision "is this lap representative of pure pace?".
That decision is made **once**, here, in `classify_laps()`, and every model consumes `lap_class`.
No model re-implements its own filter.

### Lap classes
| Class | Rule (initial — tune with evidence, not to flatter a model) |
|---|---|
| `lap1` | Lap 1 — standing start, not representative |
| `in_lap` / `out_lap` | Pit entry / pit exit laps |
| `neutralised` | Any part of the lap under SC, VSC or red flag, plus the restart lap |
| `yellow` | Local yellow in a sector the driver passed through |
| `traffic` | Started the lap within the dirty-air threshold of the car ahead (initially < 1.5 s) |
| `wet` | Intermediate / wet compound, or rain flagged |
| `outlier` | Mistake laps: > X % slower than the driver's stint median after the above are removed |
| `clean` | Everything else — the only class the degradation model fits on |

`traffic` laps are not discarded — they are the training data for the traffic model (Phase 5).

### Race-state snapshots
For each race, one row per driver per lap with everything the simulator needs to **start a
counterfactual at that lap**: position, gap to leader, gap to car ahead, compound + C-number, tyre
age, stops made, dry compounds used so far, retired flag. This is exported per race and is the
initial condition for every "what if from lap N" query.

**Deliverable:** `classify_laps()` with tests covering each class, a race with SC + VSC, a race with
a red flag, and a driver who retires; a race-state snapshot table whose lap-N state reproduces the
official lap-N order.

---

## Phase 3 — Tyre Degradation Model

**Goal:** lap time as a function of tyre age, compound, track and fuel load, with uncertainty.

### The confounding problem (most important modelling point in this repo)
Within a stint, three things move together with every lap: **tyre age goes up, fuel load goes
down, and the track rubbers in.** Fit lap time against tyre age on raw laps and fuel burn-off
masquerades as *negative* degradation. They are separable only because tyre age resets at each
stop while fuel and track evolution do not — so the model must see multiple stints per race and
must carry an explicit race-lap term.

- Fuel effect: informative prior from physics (order of ~0.03 s per kg, ~1.5–1.8 kg per lap; values
  per era live in `config/regulations.yaml`, not in code). Track evolution is absorbed into the same
  race-lap term — state that they are not separately identified.
- Never fit degradation on lap times that have not had the race-lap effect modelled.

### Model (start simple, add structure only with evidence)
```
lap_time[i] = μ[race] + δ[race, driver]
            + β_fuel · fuel_load(lap[i])
            + κ[era, compound_c] (base compound offset, track-specific)
            + d[era, track, compound_c, team] · tyre_age[i]
            + ε[i],          ε ~ StudentT(ν, 0, σ[race])

d[era, track, c, team] ~ Normal(d[era, track, c], σ_team)
d[era, track, c]       ~ Normal(d[era, c],        σ_track)
d[era, c]              ~ Normal(prior by C-number, …)
```
- Student-t noise because residual outliers survive any filter.
- Linear degradation first. A cliff / quadratic term is added only if posterior predictive checks
  on long stints show systematic curvature — and then for all compounds, not hand-picked ones.
- Tyre warm-up (out-lap penalty) is a separate per-compound term fitted on `out_lap` laps, used by
  the undercut module.

### Evaluation
- **Leave-one-race-out:** fit without race X, predict its clean laps. Report MAE / RMSE in seconds
  against two baselines: (a) driver's stint median, (b) per-stint OLS slope. A Bayesian model that
  doesn't beat per-stint OLS out of sample is not worth its complexity — say so if it happens.
- Sampler diagnostics: R̂ < 1.01, ESS above threshold, zero divergences. Failing diagnostics fail
  the pipeline.
- Posterior predictive check plots per compound — published as artefacts.

### Export
Not point estimates: **N posterior draws** (e.g. 200) of the parameters relevant to each race. Each
Monte Carlo run samples one draw, so parameter uncertainty propagates into the finishing-position
distribution.

**Deliverable:** `models/degradation.py`, LORO backtest table vs both baselines, diagnostics report,
exported draws per race via the contract.

---

## Phase 4 — Pit Loss, Safety Car / VSC, Reliability

### Pit loss
- Per track: total time lost to a stop = (in-lap + out-lap) − 2 × representative green lap, split
  into pit-lane transit (deterministic per track) and stationary time (distribution with a fat right
  tail — slow stops happen).
- Under SC / VSC the relative loss is smaller because the field is slow; estimate the SC and VSC
  multipliers from data, not folklore.

### SC / VSC / red flag
- Per-track probability of at least one SC, VSC, red flag, plus timing: a lap-1 spike and a
  per-lap hazard afterwards. OpenF1 history starts in 2023, which is too few races per track for
  per-track rates alone: partial pooling toward the era-wide rate (Beta-Binomial or a small
  hierarchical model), possibly with track type (street / permanent) as a group level.
- Duration distribution (laps) per type.
- Effect in the sim: SC bunches the field (gaps compress to ~1 s, lapped cars handled per the
  sporting regs config), VSC scales lap times, red flag allows a free tyre change. v1 may exclude
  red-flag counterfactuals — document it if so.

### Reliability
- Per-lap DNF hazard by era (and team if the data supports it). Small, but without it the
  distribution of outcomes is too narrow.

**Deliverable:** fitted parameters exported per track, a validation table of predicted vs observed
SC rates per track (held-out seasons), tests for SC-period extraction from race control messages.

---

## Phase 5 — Traffic & Overtaking

- **Dirty-air time loss:** from `traffic` laps vs the same driver's clean-pace prediction, as a
  function of gap to the car ahead. Per track or track-type if data allows.
- **Overtake probability:** logistic model of `P(pass on this lap | pace delta, gap, track, DRS
  available)`, fitted on on-track position changes only — exclude changes caused by pit cycles,
  retirements, penalties and lap-1 chaos. Track is a random effect (Monaco ≠ Bahrain).
- **Defending cost:** time both cars lose in a fight — optional, add if calibration needs it.

**Validation:** predicted vs observed overtakes per track on held-out races; reliability diagram of
the pass probability.

**Deliverable:** `models/traffic.py`, exported per-track parameters, calibration plot.

---

## Phase 6 — Simulation Engine (TypeScript)

**Goal:** a pure, seeded, fast lap-by-lap race simulator.

### Shape
- `simulateRace(initialState, strategies, params, rng): RaceOutcome` — pure function, no DOM, no
  global state. Lives in `web/src/sim/`.
- Lap loop: for each car, lap time = pace + fuel + compound + degradation(draw) + noise; apply
  traffic loss from the car ahead; resolve overtakes; apply pit stops (pit loss sample, rejoin
  position); sample neutralisation events and apply them; sample DNFs.
- **Seeded PRNG only** (e.g. a small xoshiro/PCG implementation). `Math.random` is banned by lint
  rule in `web/src/sim/`.
- **Common random numbers:** when comparing strategies, every strategy sees the same sampled
  SC timing, noise and parameter draw for a given simulation index. Without CRN, strategy
  differences drown in simulation noise.
- Struct-of-arrays with typed arrays; no per-lap object allocation in the hot loop.
- **Regulations enforced, not assumed:** minimum stops / minimum distinct dry compounds per race
  from `config/regulations.yaml` (exported). A strategy violating them gets the real consequence
  (disqualification from classification), not a silent pass.

### Performance budget
10 000 races × 60 laps × 20 cars on a mid-range laptop in a few seconds across a worker pool
(`navigator.hardwareConcurrency − 1`). Benchmark in CI under Node; a regression beyond the budget
fails the job.

### Tests
- Determinism: same seed → identical outcome.
- Zero-noise replay: actual strategies, realised events, posterior mean pace → final order close to
  the actual result (mechanics sanity check, not proof of predictive skill).
- Invariants (property-based): positions are a permutation each lap; tyre age resets on stop; stops
  only increase; retired cars never re-enter; regulation check holds.

**Deliverable:** engine + worker pool + Node benchmark + test suite.

---

## Phase 7 — Simulator Validation (the honesty phase)

A simulator that produces confident-looking histograms is easy. A **calibrated** one is the point.

### The information-set rule
When the simulator evaluates a situation at lap N, it may only use information available at lap N.
Future random events — SCs, VSCs, red flags, DNFs, slow stops — are **sampled**, never replayed from
what actually happened. Replaying the real SC while evaluating a pit call made before it is
hindsight, and it makes every lucky decision look clever.

(Fitted pace and degradation for the race *are* estimated from the whole race. That is a known,
documented softening: teams have strong pace estimates from practice. It is stated in the UI and
README, not hidden.)

### Checks
- **Calibration:** for held-out races, start from lap 1 (and from mid-race snapshots), simulate with
  actual strategies, and check that the realised finishing position of each driver falls inside the
  simulated 50 % / 80 % intervals at those rates. Report coverage and a PIT histogram.
- **Baselines:** compare the log-score of the simulated position distribution against (a) "finish =
  grid", (b) "finish = position at lap N". The simulator must beat them from mid-race snapshots.
- **Segment breakdown:** per track type, dry vs mixed, races with vs without neutralisations. Report
  where the simulator is badly calibrated — that list goes in the README.

### Gate (consumed by Phase 11)
New parameters are published only if diagnostics pass and calibration coverage / log-score has not
materially regressed against the currently published version. Otherwise the previous parameters
stay live and the run reports why.

**Deliverable:** `web/scripts/backtest.ts` + `pipeline/src/pitwall/validate/`, a calibration report
published with the bundle, thresholds in `config/thresholds.yaml`.

---

## Phase 8 — Strategy Optimiser, Counterfactuals, Undercut

### Counterfactual query
`(race, driver, from_lap, alternative strategy)` → distribution of finishing positions for the
alternative **and** for the actual strategy, under CRN, from the race-state snapshot at `from_lap`.
Always show both — the answer is the difference.

### Optimiser
- Candidate generation: stop count 1–3, compound sequences that satisfy the regulations, pit-lap
  windows; constrained by tyre sets the driver actually had available if that data is reliable.
- **Successive halving** with CRN: evaluate all candidates with few runs, drop the clearly dominated,
  spend the budget on the contenders. Brute-forcing every candidate × 10 000 runs will not fit the
  in-browser budget.
- Objective is user-selectable: expected position, P(podium), P(points), P(beat rival X). Show the
  top candidates with their distributions, not one winner.

### Undercut / overcut module
Given attacker, defender, lap: P(attacker ahead after both have stopped) for "attacker pits now,
defender responds next lap" and the overcut mirror. Uses out-lap warm-up penalty, degradation of the
old set, pit-loss distribution, and rejoin traffic from the snapshot. Expose the components (gap,
tyre delta per lap, pit-loss spread) so the user sees *why*.

### Debrief: which decisions cost positions
For each pit decision in the actual race: expected-position regret vs the best alternative at that
lap, evaluated **ex ante** (future events sampled — "was it a good call?") and, separately,
**ex post** (realised events — "did it work out?"). Never merge the two numbers.

**Deliverable:** query API inside the engine package, optimiser with tests (it must recover a known
optimum on a synthetic race), undercut module with tests on hand-built scenarios.

---

## Phase 9 — Strategy Lab UI

1. Race + driver picker; race summary (actual strategies as a stint chart for all drivers).
2. Strategy editor: drag pit laps, choose compounds; rule violations shown inline.
3. Result view: finishing-position distribution actual vs alternative, P(gain), P(loss), with
   a sample-size note and the active assumptions (open-loop opponents, information-set rule).
4. Optimiser view: top-N strategies with distributions.
5. Undercut panel: attacker / defender / lap → probability + components.
6. Model card: model version, dataset hash, fit date, calibration coverage for this track.

Simulation always runs in the worker pool; the main thread never blocks. Progressive results
(update histograms as batches finish).

**Deliverable:** deployed UI that answers the three headline questions for any 2023+ race.

---

## Phase 10 — Analytics: Replay, Telemetry, Debrief

- **Replay on track map:** track outline from a fastest lap's location trace; car dots animated from
  downsampled location data (≈ 1–2 Hz, quantised integers, lazy-loaded per race). Timeline scrubber
  synced to lap, SC periods and pit stops.
- **Telemetry comparison:** two drivers, chosen laps (default: fastest). Align by **distance**, not
  time. Overlays of speed, throttle, brake, gear; delta-time trace; minisector map coloured by who
  was faster — "where exactly did he gain 0.2 s". Only selected laps are exported, not full-race
  telemetry.
- **Post-race debrief page:** Phase 8 decision regret per driver, ex ante vs ex post, with the
  biggest strategic swings of the race.

### Size budget
Per-race bundle limits live in `config/budgets.yaml` (e.g. race core < 1 MB gzipped, replay < 5 MB,
telemetry lazily per driver-lap). CI fails a bundle that exceeds them.

**Deliverable:** three analytics views, size budgets enforced.

---

## Phase 11 — Post-Weekend Automation & Publishing

```yaml
# .github/workflows/weekend.yml
on:
  schedule:
    - cron: "0 6 * * 1"     # Monday 06:00 UTC — after race weekends; a no-op otherwise
    - cron: "0 6 * * 3"     # Wednesday re-pull: catches amended classifications / late penalties
  workflow_dispatch:
    inputs: { season: {}, round: {} }
```

Steps: detect newly completed races (calendar from Jolpica) → ingest new race + re-pull the previous
one → classify laps → refit models → validate + gate → export → upload race bundle to the season
release → rebuild and deploy Pages.

- Idempotent: re-running for the same race produces the same dataset hash and does not duplicate
  release assets.
- Gate failure keeps the previous model parameters live; the new race's descriptive data (replay,
  telemetry, stint chart) still publishes, flagged "model not refreshed".
- Job summary: races processed, row counts, diagnostics, calibration delta, bundle sizes.

**Deliverable:** a weekend workflow that runs end to end on GitHub runners; every step also runnable
locally via `make`.

---

## Phase 12 — Docs & Polish

README: what it is in one paragraph; the architecture diagram; a GIF of a counterfactual; the
modelling story (fuel vs tyre confounding, partial pooling, CRN, information-set rule); the
calibration table **including where it fails**; data inventory and attribution; "not affiliated
with Formula 1" disclaimer; "what I'd do with more time" (reactive opponents, live mode, sprint
races, wet-weather strategy).

Blog post: one decision worth explaining (I'd pick the fuel/tyre confounding or ex-ante vs ex-post
debrief) + one surprising finding from real races.

---

## Common Pitfalls

**Fitting degradation on raw lap times.** Fuel burn-off hides tyre wear; you get near-zero or
negative degradation on hard tyres and conclude "no deg". Model the race-lap term.

**Relative compound labels.** Pooling "SOFT" across races pools C3 with C5. Key on C-number.

**Every model filtering laps its own way.** Then degradation, traffic and pit loss disagree about
what a lap is. One `classify_laps()`.

**Replaying future events in a counterfactual.** Hindsight dressed up as analysis. Sample them.

**Comparing strategies without common random numbers.** Differences of half a position vanish in
noise; the optimiser chases randomness.

**Two simulators.** A Python "reference" sim used for validation drifts from the TS sim users run.
One engine.

**Pooling across regulation eras.** 2026 cars are not 2024 cars. `era` is a model level.

**Pit-cycle position changes counted as overtakes.** Inflates overtake probability massively.

**Ignoring used tyre sets.** Drivers often start stints on sets used in qualifying —
`tyre_age_at_start` is not zero.

**Shipping full-race telemetry to the browser.** Hundreds of MB. Downsample, quantise, lazy-load.

**A confident histogram nobody checked.** Without coverage numbers the distribution is decoration.

---

## Phase Summary

| Phase | Key Deliverable |
|---|---|
| 0 — Setup | Monorepo, ADRs, contract, `make verify`, walking skeleton deployed |
| 1 — Ingestion | Cached, validated canonical tables for 2023+, dataset fingerprints |
| 2 — Laps & state | `classify_laps()`, per-lap race-state snapshots |
| 3 — Degradation | Hierarchical Bayesian model, LORO backtest vs baselines, posterior draws exported |
| 4 — Pit/SC/DNF | Pit loss, neutralisation hazards with partial pooling, reliability |
| 5 — Traffic | Dirty-air loss + overtake probability, calibrated |
| 6 — Engine | Seeded TS Monte Carlo, CRN, worker pool, perf budget in CI |
| 7 — Validation | Information-set rule, coverage + log-score vs baselines, publish gate |
| 8 — Strategy | Counterfactuals, optimiser, undercut, decision regret |
| 9 — UI | Strategy lab answering the headline questions |
| 10 — Analytics | Replay, telemetry comparison, debrief, size budgets |
| 11 — Automation | Post-weekend workflow, gated publish, Releases + Pages |
| 12 — Polish | README with calibration table, blog post |

---

## Tech Stack

| Layer | Tool | Why |
|---|---|---|
| Timing / telemetry | OpenF1 REST | Laps, stints, pits, intervals, race control, location, car data; free, no key, 2023+ |
| Results history | Jolpica | Ergast-compatible successor |
| HTTP | requests + requests-cache | Every raw response cached; retries on rate limits |
| Data processing | pandas + pyarrow (parquet) | Standard, sufficient at this data size |
| Validation | pandera | Schema + range checks per race |
| Bayesian modelling | PyMC + nutpie, ArviZ | Readable hierarchical models, fast NUTS, diagnostics |
| Contract | pydantic → JSON Schema → TS types | One source of truth across languages |
| Simulation | TypeScript in Web Workers | Runs where the user is; zero server cost |
| Frontend | Vite + React + TS | Fast build, typed |
| Charts | uPlot (telemetry), Observable Plot or D3 (distributions) | uPlot handles dense time series |
| Hosting | GitHub Pages + Releases | Free, no server |
| Orchestration | GitHub Actions | Free scheduled post-weekend runs |
| Python quality | ruff, pyright, pytest, hypothesis | Lint, types, property tests for invariants |
| Web quality | tsc, eslint, vitest | Same, for the engine and UI |
| Dependency mgmt | uv (Python), npm (web) | Lockfile-pinned; npm avoids an extra tool for one package |
