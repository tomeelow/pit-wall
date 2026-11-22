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
| 2 — Lap classification & race state | ☑ done | 90 races rebuilt, 50.5 % of 100,749 laps clean; race-state order matches OpenF1's position feed on ≥ 98 % of driver-laps in every race. Simplifications and data quirks under Phase 2 → Findings |
| 3 — Tyre degradation model | ☑ done | Both era fits pass the gate; draws per race in `.data`. LORO: model beats the flat-median baseline only modestly (MAE 0.725 vs 0.758 s); details and the weak-OLS caveat under Phase 3 → Findings |
| 4 — Pit loss, SC/VSC, reliability | ☑ done | Pit loss per track (green 19–28 s; SC/VSC factors per era: 0.68/0.84× in 2023–25, ~0.95× in 2026), SC/VSC/red/DNF rates per race with that race masked out; per-track rates barely beat era-wide. 2026 rebuilt with VSCs. Phase 4 → Findings |
| 5 — Traffic & overtaking | ☑ done | Dirty air only matters within 0.5 s (0.47 s/lap); pass model (gap, pace delta, within 1 s, track) beats the gap-only baseline out of sample (log loss 0.134 vs 0.173) and is well calibrated 1–70 %; under-predicts passes from 1.5–3 s back. Phase 5 → Findings |
| 6 — Simulation engine | ☑ done | Seeded TS engine with CRN, worker pool and contract 0.2.0 sim inputs for 76/90 races; 10 000 × 60 × 20 in 1.5 s on one thread (CI budget 6 s); zero-noise replay misses the result by 1.24 positions vs 2.33 for the lap-1 order. Open-loop stops under sampled SCs fatten ex-ante tails — Phase 7's first question. Phase 6 → Findings |
| 7 — Simulator validation | ☑ done | 75 dry races × 4 start laps × 1,000 ex-ante runs: coverage 0.48 / 0.78 at 50 / 80 %, log score −1.93 vs −2.38 for the order at the start lap; beats both baselines in every segment. Overconfident from 75 % distance (0.44 / 0.71) and after real neutralisations; Miami 2025 refused (race-time gap). Phase 7 → Findings |
| 8 — Strategy optimiser, counterfactuals, undercut | ☑ done | Counterfactual, optimiser (successive halving, recovers a known optimum), undercut and debrief in `web/src/sim`; tyre warm-up fitted (≤ 0.64 s, barely moves calibration). Undercut beats the base rate on 181 real pairs (Brier 0.185 vs 0.205). Full search 4 s on one thread. Debrief prefers later stops (open-loop rivals, linear wear). Phase 8 → Findings |
| 9 — Strategy lab UI | ☑ done | Rim theme, dark first (light on request). Race, What if, Optimise, Undercut and Model card screens, all simulation on the worker pool, view kept in the URL; editor rule check mirrors the engine's DSQ test. Calibration is shown per segment: no per-track scores are exported yet. Phase 9 → Findings |
| 10 — Analytics: replay, telemetry, debrief | ☑ done | Replay, Telemetry and Debrief screens. Fastest-lap car data and one lap of location per race (ADR-007) instead of full-race traces; cars placed on the replay by official lap times. Debrief runs on demand in the browser, ex ante and ex post in separate tables. `pitwall export` fails over the budgets in `config/budgets.yaml`. Phase 10 → Findings |
| 11 — Post-weekend automation & publishing | ☑ done | `weekend` workflow (Mon and Wed 06:00 UTC, or by hand) runs `make weekend PUBLISH=1`: new races, the previous race again, refit, gates, export, upload. GitHub Releases store the races and models and every deploy rebuilds from them (ADR-008). A failed gate keeps the previous parameters live. Phase 11 → Findings |
| 12 — Docs & polish | ☑ done | README rewritten: one-paragraph pitch, live link, a What if GIF (Hungary 2024), Mermaid architecture, the modelling story, the calibration table with its failures, data inventory, what's next. Write-up on fuel vs wear in `docs/blog/`. Phase 12 → Findings |

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

### Findings (from the first full classification)

Implemented in `pitwall.laps` (classes), `pitwall.race_state` (snapshots) and `pitwall.prepare`
(runs both after validation). Thresholds live in `config/pipeline.yaml` → `classification`.

- **Race state is rebuilt from line crossings** (next lap's `date_start`, else start + lap time).
  `check_prepared` compares it with OpenF1's `/position` feed 1 s after each crossing: every race
  agrees on ≥ 98 % of driver-laps (lowest 2025 R6, 98.1 %); below `min_position_agreement` (0.95)
  is a warning.
- **Class shares across 90 races / 100,749 laps:** clean 50.5 %, traffic 29.2 %, neutralised
  4.9 %, wet 3.6 %, in-lap 3.3 %, yellow 3.2 %, out-lap 3.2 %, lap1 1.8 %, outlier 0.3 %. Clean
  laps sit within 0.992–1.013 × their stint median (5–95 %).
- **`yellow` is time-based for every driver.** Marshal sectors are not mapped to track position
  yet, so any local yellow anywhere marks the lap for the whole field — conservative.
- **Some sector yellows are never cleared** in race control (11 races, e.g. 2023 R4, 2025 R6,
  2025 R15). A yellow counts for at most `max_yellow_s` (900 s) and is reported as a warning;
  before the cap three of these races had zero clean laps.
- **2026 red flags are text-only** ("RED FLAG - RACE SUSPENDED", no Track RED flag). A red starts
  on that text, a Track RED flag or `SESSION ABORTED`; it ends at `SESSION STARTED` or an SC
  restart. `TRACK CLEAR` during a suspension does not end it (2026 R13 previously read as SC to
  the flag).
- **2026 abbreviates VSC** ("VSC DEPLOYED" / "VSC ENDING"). The parser missed all 25 VSC periods
  in 2026 until this was fixed; most of those laps were already excluded as `yellow` (2026 clean
  laps: 11,829 → 11,819 after the fix), so the Phase 3 fit is unaffected. The 2026 races were rebuilt
  from the response cache with the fix, and 2026 was refitted.
- **In-laps are inferred** from the next lap being an out-lap, which covers 2023 R1–R6 (no pit
  records).
- **`wet` comes from the compound only**; there is no rain flag in the classification.
- **Rolling restarts behind the safety car** after a red flag have no SC messages; those slow laps
  fall to `outlier`, not `neutralised`.
- **2024 R21 (São Paulo)** is 80 % wet and has no clean laps — correct.
- `race_state` is a canonical table now; exporting it to the web contract is Phase 6 work.

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

### Findings (first fit, 2023 R1 – 2026 R20)

**Fits.** One model per era (`make fit`, nutpie, 4 × 1000/1000, `target_accept` 0.95). Both pass the
gate:

| Era | Clean laps | Races | Left out | max R̂ | ESS bulk / tail | Divergences | fuel effect (s/kg) |
|---|---|---|---|---|---|---|---|
| 2023–2025 | 39,041 | 69 | C6 (one race) | 1.007 | 1047 / 1522 | 0 | 0.0291 (0.0289–0.0293) |
| 2026 | 11,819 | 20 | — | 1.005 | 1305 / 937 | 0 | 0.0438 |

- **Zero-sum deviations.** Deviations are zero-sum within their parent:
  - track slopes within each C-number;
  - team slopes within each track and C-number;
  - race offsets within each race.

  Each group of k uses k − 1 free normals in a Helmert basis. With plain non-centred deviations,
  a parent and the mean of its few children traded off along a ridge. The synthetic test fit then
  landed either side of R̂ 1.01 depending on seed and platform, and CI failed on it. The table shows
  the refit: slopes moved by under 0.002 s/lap, and the 2023–25 bulk ESS rose from 749.

- Fuel effect is near the physics prior in 2023–25. In 2026 the data identify fuel_effect × race fuel
  mass; the 70 kg figure is **unverified** (secondary source; the FIA regulations cap energy flow,
  not race fuel mass), so read 0.044 s/kg as "≈ 3.1 s over a race" (2023–25: ≈ 3.2 s).
- Era-level slopes (s/lap), 2023–25: C1 0.047, C2 0.037, C3 0.054, C4 0.054, C5 0.068. 2026: C1
  0.070, C2 0.049, C3 0.078, C4 0.062, C5 0.033. These are not "C5 wears least in 2026". Each C-number
  is raced at a different set of tracks, and the era level averages over those tracks. Use the
  track-level slopes.
- A C-number needs clean laps from ≥ `min_compound_races` (2) races. With only one race, its offset
  and slope cannot be separated from that race's level. Before this rule (and a per-race level
  term), C6 got a −0.23 s/lap slope and a +9 s offset.
- **No curvature:** median residual by tyre-age bin is ≈ 0 for every compound in the 30+ lap bin.
  Linear degradation stays.
- **Warm-up is visible:** 2023–25 C2 is −0.11 s in the first 5 laps; 2026 C4 is +0.16 s and C5
  +0.10 s. Warm-up and the out-lap term move to the undercut module (Phase 8; see Phase 4 →
  Findings).
- Posterior predictive checks so far are the residual-by-age table in each model card, not plots.
- Draws: 200 per race in `.data/races/*/degradation_draws.parquet` for every race except 2024 R21,
  which has no clean laps. They are not in the contract yet; that is Phase 6.

**Leave-one-race-out** (`make backtest`, 15 races in config, ~2 h locally). Every held-out stint
is a forecast: each method sees only the stint's first 3 clean laps and predicts the rest.

| Method | MAE (s) | RMSE (s) |
|---|---|---|
| stint median of anchor laps (flat) | 0.758 | 1.096 |
| OLS through anchor laps | 2.938 | 5.003 |
| **model** (anchor level + posterior slope and fuel) | **0.725** | **1.014** |

7,482 laps; 531 stints.

- **The model beats OLS by a wide margin, but that is a weak test.** A line through 3 noisy laps
  extrapolates its noise (RMSE 9.3 s at 20+ laps ahead). The honest comparison is the flat median.
- **Against the flat median, the gain is small:** −4 % MAE and −7 % RMSE overall. By horizon:
  - ≤ 5 laps ahead: 0.449 vs 0.458;
  - 20+ laps ahead: 1.200 vs 1.289.

  The model is better on 55 % of stints. It is worse in 6 of the 15 held-out races (2024-12,
  2025-07, 2025-14, 2025-16, 2026-06, 2026-13). The reason: fuel burn-off (≈ −0.06 s/lap) roughly
  cancels wear (≈ +0.05 s/lap), so most stints are close to flat. Most of the forecast error is
  lap-to-lap noise that no pace model removes.
- What the model adds is the split into wear and fuel. Flat-median and OLS baselines cannot provide
  this, and a strategy simulator needs it: changing stint length changes tyre age without changing
  the fuel curve.
- The backtest refits use a lighter sampler (500/500) to keep the run to ~2 h. R̂ was 1.010–1.022
  and bulk ESS 295–632, below the publish gate. That is enough for the posterior means scored here.
  These refits are never published.
- Not yet tested: a non-Bayesian baseline using the training races' pooled slope per C-number. It
  would show whether the hierarchy (track and team levels) earns its keep, not just the fuel/wear
  split.

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

### Findings (first fit, 2023 R1 – 2026 R20)

Code: `pitwall.models.pit_loss`, `pitwall.models.hazards` and `pitwall.models.events`.
Commands: `make fit-events` and `make validate-events`. Thresholds and priors are under
`config/pipeline.yaml` → `events`.

Outputs per race in `.data/races/*/`:
- `events.json`: pit loss, SC/VSC factors, stationary times and durations;
- `hazard_draws.parquet`: 200 rate draws for the track and for each team.

Not in the contract yet; that is Phase 6.

**Pit loss**
- 2,250 tyre stops measured: 1,903 green, 190 under SC, 157 under VSC.
- Excluded:
  - stops without a tyre change;
  - stops whose lane time is over 1.5 × the race median (penalties and queues);
  - red flags;
  - 2023 R1–R6, which have no pit records.
- A stop's loss is (in-lap + out-lap) minus the field's median lap on those same laps, minus twice
  the driver's usual gap to the field. Comparing against the field on the same laps handles fuel,
  track evolution and safety cars in one definition.
- The measured loss is net of tyre age: the in-lap runs older tyres than the field and the
  out-lap newer ones. The bias is under about 1 s; see the module docstring before using the loss
  in the simulator.
- Median green loss per track runs from 19.0 s at Spa to 28.3 s at Lusail. Monaco is 20.1 s,
  Singapore 26.1 s and Imola 27.6 s.
  - Transit (loss minus stationary time) uses stops with OpenF1 stationary times, which start
    mid-2024.
  - Other tracks take the loss minus the era's median stationary time.
  - An unseen track takes the median across tracks (`pit_loss_from: "era"`).
- **Under SC and VSC, per era** (median loss over the same track's green loss):

  | Era | SC | VSC | SC / VSC stops |
  |---|---|---|---|
  | 2023–25 | 0.68× | 0.84× | 129 / 49 |
  | 2026 | 0.94× | 0.96× | 61 / 108 |

  - Both are smaller discounts than the "half price" folklore. The measured loss is relative to
    cars that stayed out on the same laps, and part of an SC lap often runs at green speed before
    the field bunches.
  - **In 2026 a neutralisation saves almost nothing.** These factors were pooled across eras until
    the 2026 VSCs were recovered (0.82 / 0.84 pooled). They are now per era, as the era rule
    requires.
  - The 2026 cause is not established. Candidates are the new cars' slower neutralised pace
    relative to their pit lane, and the procedures.
- **Stationary time:** 1,103 timed stops. Median 2.8 s, 90th percentile 5.5 s, 99th 14.4 s. The
  simulator samples from all of them, so slow stops come with them.
- **Lap time under SC / VSC** (cars not pitting), per era, over the race's median clean lap:
  2023–25 1.48× / 1.24×, 2026 1.41× / 1.19×.
- Crew speed is not modelled per team: one distribution per era.
- **Per-compound warm-up is not modelled yet; it moves to Phase 8.** The pit loss already
  contains the average out-lap warm-up. Phase 3's residuals show the per-compound part is
  ±0.1–0.16 s over the first laps of a stint. Its only consumer is the undercut module, so it is
  fitted there, on `out_lap` and early-stint laps.

**SC / VSC / red flag / DNF rates**
- One Poisson model (nutpie):
  - families are kind × phase: `lap1`, and `running` (per lap at risk, laps under any
    neutralisation excluded);
  - an era level per family;
  - a partially pooled deviation per track (neutralisations) or per team and era (DNF).
- Every retirement counts as a DNF. OpenF1 gives no reason, so crashes are included, and their
  link to safety cars is not modelled (the hazards are independent).
- **Information-set rule:** each race's exported rates come from a refit with that race's rows
  masked out (exposure 0). The race's own SCs, red flags and DNFs never inform its simulation.
  This takes 90 refits, about 5 min in total, each gated.
  - Stationary times and durations also exclude the race itself.
  - Transit and the SC/VSC factors use every race, the same documented softening as pace.
- **Sampler:** `unit_sd` is HalfNormal(0.5).
  - The track-to-track spread of 11 red flags is not identifiable. With HalfNormal(1), the
    red-flag spread formed a funnel that failed the gate (R̂ 1.013).
  - At 0.5, a track can still run at about 2.7× its era's rate at two sd.
  - Settings: 1500 tune / 2000 draws, target 0.98.
  - Result: all 90 masked fits pass. Worst R̂ 1.006, minimum ESS 1063, no divergences.
- Era medians, 2023–25:

  | Event | Lap 1 | Per lap afterwards |
  |---|---|---|
  | SC | 0.13 | 0.0085 |
  | VSC | 0.010 | 0.0077 |
  | Red flag | 0.032 | 0.0016 |
  | DNF | 0.018 per car | 0.0016 per car |

  2026 differs in two ways:
  - 0.0029 DNFs per car-lap: the new power units retire cars more often.
  - 0.022 VSCs per lap, about 3× the 2023–25 rate (25 VSCs in 20 races). Race control reaches for
    the VSC much more often under the 2026 rules.

**Validation** (`validate-events`: leave one season out, 2023–2025; 70 races). The metric is the
probability of at least one event per race, ex ante. The baseline is the share of the same era's
training races with at least one.

| Kind | Observed rate | Brier model / baseline | Log loss model / baseline |
|---|---|---|---|
| SC | 0.47 | 0.250 / 0.263 | 0.693 / 0.720 |
| VSC | 0.39 | 0.237 / 0.240 | 0.667 / 0.673 |
| Red flag | 0.11 | 0.108 / 0.105 | 0.380 / 0.375 |

- **The per-track rates barely beat the era-wide rate.** For red flags they are marginally worse.
  With 2–3 races per track, a track's history is mostly noise, and partial pooling rightly keeps
  tracks near their era. An SC log loss of 0.693 = ln 2 means that whether a given race will see a
  safety car is close to a coin flip, and nothing in this data predicts it much better.
- The simulator should therefore treat SC timing as genuinely uncertain. That is what the
  distribution of outcomes is for.
- Per track, observed vs expected counts are in `.data/models/events/validation.md`. No track is
  far outside its expectation over 2–3 races.
- Street vs permanent circuit is the obvious next covariate. It was not added: the per-track terms,
  which would absorb it, show little signal.

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

### Findings (first fit, 2023 R1 – 2026 R20)

Code: `pitwall.models.traffic`. Commands: `make fit-traffic` (run after `make fit`, because pace
comes from the degradation draws) and `make validate-traffic`. Settings are under
`config/pipeline.yaml` → `traffic`.

Outputs per race in `.data/races/*/`:
- `traffic_draws.parquet`: 200 draws of the track's intercept and the era's coefficients;
- `traffic.json`: the era's dirty-air table and the gap thresholds.

Not in the contract yet; that is Phase 6.

**Data: lap pairs.** Each row is a car and the car directly ahead of it in the running order at the
start of a lap, on the same lap. 92,401 pairs. A pair's lap is usable only if it can be decided on
track:
- neither car pits (in-lap or out-lap);
- the lap is green: no SC, VSC, red flag or yellow;
- it is dry and not lap 1;
- both cars have a free-air pace prediction from the degradation draws.

So pit cycles, retirements, penalties and lap-1 chaos never enter the data. The pass model trains
on 41,823 usable pairs within 3 s at the start of the lap (2,594 passes).

**Dirty air.** This is the time lost relative to the car's own free-air prediction. It is measured
only on laps where the car ahead is predicted to be at least as fast, so the car behind is not being
held up:

| Gap at start (s) | 2023–25 loss (s/lap) | 2026 loss (s/lap) |
|---|---|---|
| ≤ 0.5 | 0.47 | 0.37 |
| 0.5–2.0 | 0.05–0.06 | −0.05–0.02 |
| > 2.0 | ≈ 0 | ≈ 0 |

- Pure aero loss only matters very close behind.
- Across all traffic laps, the raw excess is much larger: 0.60 / 0.30 / 0.17 s in the first three
  bins. That is cars held up behind slower ones. The simulator gets that from the pass model, by
  keeping a car behind until it passes, not from this table.
- Dirty air is per era, not per track. The per-track bins are too thin.

**Pass model.** The probability that the car behind is ahead at the end of the lap:

    logit P = intercept[era] + track[track] + beta[era] · (gap, pace delta, within 1 s)

- **Features:** gap is in seconds at the start of the lap. Pace delta is predicted free-air lap time
  ahead minus behind. "Within 1 s" stands for DRS in 2023–25 and overtake mode in 2026.
- **Track effects** are partially pooled and zero-sum. The era intercepts are shared across tracks.
- **Fit:** nutpie, 4 × 2000 draws. Features are centred: without that, the intercept (at zero gap)
  traded off with the gap and DRS slopes, R̂ 1.015.
- Full fit: R̂ 1.005, ESS 1119, no divergences.
- **Coefficients** (logit, per second):

  | Era | Gap | Pace delta |
  |---|---|---|
  | 2023–25 | −4.06 | +1.82 |
  | 2026 | −3.70 | +1.23 |

  2026 passes depend less on raw pace.
- **"Within 1 s" is negative (−1.0).** It absorbs the curvature that a straight line in gap misses.
  The extra pass chance from being within a second is in the steep gap slope, not in this term.
- **Track effects** run from Monaco −3.4 (about 30× lower odds), Madring −1.2 and Singapore −0.8 to
  Yas Marina +1.0, Austin +0.8 and Shanghai +0.8.
- **Information set:** the pass model is fitted on every race, including the one being simulated.
  This is the same documented softening as pace: passability is a property of track and cars, not
  a sampled random event. A masked refit per race would take about 80 minutes. Validation below
  holds out whole seasons, so the reported calibration does not benefit from it.

**Validation** (`validate-traffic`, leave one season out, 2023–2025; 33,538 held-out pairs). The
baseline is the training pass rate in the same era and gap bin.

| | Model | Baseline |
|---|---|---|
| Log loss | 0.134 | 0.173 |
| Brier | 0.037 | 0.048 |
| Passes expected / observed | 1,985 / 1,978 | — |

- **The model beats the baseline in every held-out season**, and the per-track log loss beats it at
  23 of 24 tracks.
- **Reliability is good from 1 % to 70 %.** Mean predicted vs observed frequency per bin:
  - 0.015 / 0.013
  - 0.071 / 0.062
  - 0.142 / 0.144
  - 0.385 / 0.391
  - 0.687 / 0.693
- **Miscalibration 1 — long gaps.** Pairs 1.5–3 s apart pass more than predicted: 52 passes
  against 19 expected, over 12,875 pairs. A logit linear in gap is too steep in its tail, so
  passes there (mistakes, incidents) are under-sampled.
- **Miscalibration 2 — some tracks.** Monaco has 13 passes against 25 expected, and Monza 81
  against 106: the model is too generous. Mexico City has 124 against 95: too stingy. With 3
  races per track, these are partly noise.
- The calibration "plot" is the reliability table in `.data/models/traffic/validation.md`. A
  rendered figure comes with the model card in the UI.
- **Defending cost:** not modelled. Add it only if Phase 7 calibration needs it.

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

### Findings (first build, 2023 R1 – 2026 R20)

**Inputs.** `make export` now writes `races/{season}/{round}.sim.json` (contract `SimRace`, schema
0.2.0) next to each race file. The manifest's `sim_path` is null for a race the engine cannot run.
Each file holds:
- 200 paired draws of the degradation, event and traffic models;
- the actual strategies;
- the race state after every lap;
- the realised neutralisations;
- the race's rules.

Code: `pitwall.export.sim`.

About 200 KB per race, 15 MB for all of them. The browser loads one at a time; budgets come in
Phase 10.

**82 of 90 races are simulable.** The 8 that are not:

| Reason | Races |
|---|---|
| Wet or unknown tyres until the last laps (2023 R6, R13; 2025 R1; 2026 R20) | 4 |
| C6, which the degradation fit does not cover (2025 R8, R10) | 2 |
| No degradation draws (2024 R21) | 1 |
| Race times missing (2025 R6) | 1 |

**Partial races (2026-11, contract 0.7.0).** Wet or unknown tyres earlier in a race only move
`SimRace.first_start_lap`: the first lap after which every running car is on a known dry set for
the rest of the race. The engine refuses earlier starts; the app, the debrief and the calibration
backtest skip them. Seven races gained a simulation this way: 2024 R9 (from lap 47 of 70), 2024
R12 (39 of 52), 2025 R12 (44 of 52), 2025 R13 (1 of 44, wet on lap 1 only), 2026 R5 (3 of 68),
2026 R16 (9 of 55) and 2026 R19 (6 of 71, Stroll's last stint has no compound in OpenF1).
`Car.wet_tyres_used` waives the two-dry-compound rule (Art. 30.5) for a car with laps on wet sets.
Ingestion no longer moves a one-lap stint off its pit lap when the next stint starts on the out-lap:
in 2026 R16 four cars fitted inters on the grid during the suspended start and pitted for slicks
after lap 2, and the alignment had folded that lap into the dry stint before it. Those grid
changes are not stops: a stint change in the first `sim.grid_change_laps` (2) laps with neither a
pit record nor an out-lap counts towards neither `Snapshot.stops` nor `Car.stops`. That covers the
Bahrain grid, the lap-1 inters-to-slicks change OpenF1 gives every car in 2025 R13 (they pitted
on laps 11–13), and single-lap stint artifacts in 2023 R8 and 2026 R11, R17–R19; later unmarked
changes stay stops, since OpenF1 lacks pit data for some races (2026 R1). Canada 2023 replays
worse without TSU's phantom lap-2 stop (mean error 1.33 → 1.67); calibration moves by 0.0002 in
log score. Rain itself is never sampled,
and the first laps on a drying track are modelled as dry. Recalibrated with the new races: 81
races scored (2025 R12 starts too late for any start point), overall log score −1.938 (was
−1.930), coverage 0.486 / 0.785; the gate passes.

**Two fallbacks:**
- A driver without a clean lap (an early retirement) gets the field-median pace of each draw,
  flagged `pace_from: "field"`.
- An unknown tyre on lap 1 is ignored, because simulations start after lap 1.

**Rules come from `config/regulations.yaml`, with sources:**
- two dry compounds per era;
- Monaco 2025/26: at least two stops;
- Qatar 2023: 18-lap stints. Qatar 2025: 25-lap stints;
- tyre changes under a red flag are free.

A strategy that breaks a rule is disqualified. No actual strategy in the 76 races breaks one.

**The engine's two physical constants are measured,** in `config/pipeline.yaml` → `sim`:
- Follow gap 0.2 s: the closest a car stuck behind another crosses the line (5th percentile).
- Restart gap 0.5 s: the median interval when a safety car ends.

**Engine** (`web/src/sim/`).

The code:
- `prepare` turns a race and a start lap into the start state and checks every plan.
- `simulateRace` runs one race on typed arrays, with no allocation in the lap loop.
- `runSimulations` is the Monte Carlo loop. Simulation i uses posterior draw i mod 200.
- `SimPool` (`web/src/worker/`) splits runs across `hardwareConcurrency − 1` workers and merges
  them back in run order.

Each lap:
1. A neutralisation may start.
2. Each car gets its free-air lap time and Student-t noise (none under a neutralisation), plus the
   pit loss on its in-lap.
3. Cars resolve against the one directly ahead in start-of-lap order:
   - dirty air applies within 3 s;
   - the pass model decides whether the car gets by;
   - a car that does not get by crosses at least 0.2 s behind.
4. Retirements are sampled.
5. When a safety car or red flag ends, the field closes to the restart gap.

**Common random numbers.** Every random number is drawn before a simulation runs and tied to a
car and lap, or to a lap: lap noise, pass, retirement and stop-time uniforms per car and lap, and
event and duration uniforms per lap. Simulation i therefore sees the same numbers under every
strategy and every split across workers. Tests check this.

**Modes:**
- `sampled`: ex ante. Neutralisations and retirements are drawn from their rates.
- `realised`: ex post and replays. They happen when they did.
- Without noise: no lap noise, the median stop time, and a pass when P > 0.5.

A neutralisation running at the start lap is known, but its end is not: the remaining length is
drawn from the observed durations longer than the time already run.

**Simplifications:**
- Simulations start after lap 1; there is no start model.
- Lapped traffic and blue flags are ignored.
- The field closes up at the restart, not lap by lap.
- A red flag runs like a safety car plus a free tyre change.
- Retirements are independent of neutralisations.
- Stops without a tyre change are not modelled.
- There is no defending cost.

**Speed:** 10,000 races × 60 laps × 20 cars in 1.5 s on one thread (Apple silicon), about 6,500
races/s, about the same on real races.
- `make bench` (part of `make verify`) fails above 6 s, from `config/budgets.yaml`.
- The engine runs unbundled under Node 24 through type stripping: `.ts` imports and
  `erasableSyntaxOnly`.
- The scripts declare the few Node globals they use instead of adding `@types/node`. Phase 7's
  backtest may justify the dependency; that needs a decision.

**Tests:**
- seeded RNG moments;
- determinism;
- common random numbers, and identical results from chunked and pooled runs;
- invariants over 40 random races and strategies:
  - positions are a permutation each lap;
  - tyre age resets to the fitted set's age on a stop and otherwise rises by one;
  - stops only increase;
  - retired cars never return;
  - the rule check holds;
- rule disqualifications and plan validation;
- mechanics:
  - pit loss is exact, scaled under a safety car and free under a red flag;
  - safety-car compression;
  - pass frequency matches the pass model;
  - neutralisation and retirement rates match the inputs;
  - an ongoing neutralisation is handled at the start lap;
- exporter tests in the pipeline.

**Zero-noise replay** (`make replay`). Each race uses the actual strategies, realised events,
posterior-mean parameters and no noise, starting after lap 1.

| | Replay | Order after lap 1 |
|---|---|---|
| Mean position error, 1,360 finishers in 76 races | 1.24 | 2.33 |
| Finishers in exactly the right place | 39 % | — |
| Races where the replay is closer | 65 (9 worse, 2 tied) | — |

The median race is off by 1.20 positions. The worst races are Austria 2024 (2.80; the Verstappen
and Norris collision), Singapore 2025 (2.70) and Baku 2026 (2.63). Free red-flag tyre changes took
Monaco 2026 from 4.88 to 2.00. This checks the mechanics only; it is not predictive skill.

**What Phase 7 must look at first: open-loop strategies under sampled safety cars.**
- Example: in ex ante runs of Monza 2025 from lap 30, Norris (second in reality) finishes 10th or
  worse in about 10 % of runs.
- Cause: a sampled safety car closes up the field, then his planned green-flag stop on lap 46 costs
  the full pit loss. A real team would have stopped under the safety car.
- With realised events the tail disappears (94 % P2).
- It widens every ex ante distribution in which a safety car is sampled before a planned stop.
- Making strategies react, such as pitting under a safety car inside the stop window, changes the
  open-loop assumption (ADR-004), so it needs a decision.

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

### Findings (first calibration, 75 dry races, 2023 R1 – 2026 R20)

**How it runs.** Run `make export`, then `make validate-sim`, then `make export` again. The second
export publishes the accepted calibration.
- `make validate-sim` calls `web/scripts/backtest.ts`. That script runs the TypeScript engine under
  Node on every simulable race in the bundle.
- Each race is simulated 1,000 times from four start laps: after lap 1, and at 25 %, 50 % and 75 %
  of distance.
- Every run is ex ante with the actual strategies. Safety cars, VSCs, red flags, retirements and
  stop times are sampled.
- The whole run takes about 50 s.
- Outputs go to `.data/models/sim/`: `validation.md`, `validation.parquet` (one row per entry) and
  `calibration.json`.
- A run that fails the gate writes `calibration.rejected.json` instead, so the accepted file stays
  live.
- `make export` copies the accepted file to the bundle as `calibration.json` (contract 0.3.0,
  `Manifest.calibration_path`).
- Code: `pitwall.validate.simulator`, `web/src/sim/backtest.ts`.

**What is scored.** One entry is one car running at a start lap: 5,713 entries in all.
- Its outcome is its official place, or "not classified" as one extra, worst category.
- The engine classifies a car that retires after covering 90 % of the laps (`classified_fraction`
  in `config/regulations.yaml`).
- **Coverage** uses the randomised PIT, F(y − 1) + U·P(y), which is uniform when the forecast is
  calibrated. The share inside [0.25, 0.75] should be 50 % and inside [0.1, 0.9] 80 %.
- **Interval coverage** uses the simulated central 50 % / 80 % interval of places. Places are
  discrete, so it should hold *at least* that often. It reads above nominal even for a calibrated
  forecast; PIT coverage is the calibration measure.
- **Log score:** mean log P(outcome), with counts smoothed by 0.5. It is compared with two
  baselines, each learnt per start fraction from every other race (leave one race out):
  - P(outcome | place at the start lap);
  - P(outcome | place after lap 1), which stands in for "finish = grid" because simulations start
    after lap 1.

| Segment | Races | Entries | Coverage 50 / 80 | Interval 50 / 80 | Log score | Start-lap order | Lap-1 order |
|---|---|---|---|---|---|---|---|
| All | 75 | 5,713 | 0.483 / 0.783 | 0.674 / 0.854 | **−1.93** | −2.38 | −2.60 |
| From after lap 1 | 75 | 1,492 | 0.515 / 0.834 | 0.679 / 0.897 | **−2.10** | −2.59 | −2.59 |
| From 25 % | 75 | 1,443 | 0.503 / 0.812 | 0.670 / 0.868 | **−2.03** | −2.56 | −2.60 |
| From 50 % | 75 | 1,409 | 0.476 / 0.776 | 0.677 / 0.841 | **−1.88** | −2.36 | −2.61 |
| From 75 % | 75 | 1,369 | 0.436 / 0.705 | 0.668 / 0.804 | **−1.69** | −1.98 | −2.58 |
| 2023–2025 | 59 | 4,438 | 0.476 / 0.775 | 0.664 / 0.845 | **−1.93** | −2.39 | −2.60 |
| 2026 | 16 | 1,275 | 0.511 / 0.811 | 0.707 / 0.885 | **−1.92** | −2.34 | −2.58 |
| No neutralisation after the start | 61 | 3,232 | 0.517 / 0.821 | 0.731 / 0.890 | **−1.68** | −2.26 | −2.55 |
| Neutralisation after the start | 52 | 2,481 | 0.439 / 0.734 | 0.599 / 0.807 | **−2.25** | −2.54 | −2.66 |
| Passing hard (tercile of the pass-model intercept) | 27 | 2,064 | 0.475 / 0.773 | 0.664 / 0.846 | **−1.97** | −2.36 | −2.57 |
| Passing medium | 23 | 1,710 | 0.509 / 0.800 | 0.690 / 0.863 | **−1.91** | −2.34 | −2.55 |
| Passing easy | 25 | 1,939 | 0.470 / 0.779 | 0.670 / 0.854 | **−1.91** | −2.44 | −2.66 |

The PIT histogram, in 10 bins, is close to flat with a slight U shape:
0.112, 0.097, 0.095, 0.095, 0.099, 0.100, 0.089, 0.100, 0.109, 0.105.

**Reading it:**
- The simulator beats both baselines in every segment and from every start lap.
- Overall it is calibrated to within 2 points at both levels.
- From early start laps (after lap 1, 25 %) it is calibrated or slightly underconfident.

**Where it is miscalibrated.** These go in the README.
- **Late in the race it is overconfident.** From 75 % distance, coverage is 0.44 / 0.71. It still
  beats the order at the start lap, but by less (−1.69 vs −1.98). A few laps of open-loop racing
  leave too little spread: no late reactive stops, no defending, no driver errors.
- **After a real neutralisation it is overconfident.** Coverage is 0.44 / 0.73 when a safety car,
  VSC or red flag actually happened after the start lap. Ex ante that event is only sampled, so
  this is partly the price of the information-set rule.
- There is also a leakage in the other direction. The actual strategies were chosen in reaction to
  the real safety cars, but here they run against sampled ones.
- **Phase 6's worry did not dominate.** Open-loop stops paying full pit loss under a sampled safety
  car fatten some individual tails, as in the Monza 2025 example. Overall the forecasts are not
  underconfident, and the neutralised segment errs the other way. Reactive stops (an ADR-004
  change) remain a candidate for the late-race overconfidence, not a calibration emergency.

**Scope and softenings:**
- **Dry running only.** Mixed races are simulated only from after the rain (Phase 6 → partial
  races), so the plan's "dry vs mixed" segment has no mixed side. Track type is approximated by how
  easy passing is.
- **Race-state gap.** Miami 2025 is refused by the exporter: OpenF1 race times are missing on lap 1
  and from lap 25. A car with no time at the line on a lap it went on from would vanish from the
  simulation, so the exporter now refuses such races. A possible Phase 2 follow-up is to rebuild
  those times from lap times.
- **Pace softening.** Event and retirement rates for a race come from fits without it. Pace,
  degradation and the pass model are fitted on every race including the one simulated: the
  documented pace softening. So these numbers are not fully out of sample for pace.

**Gate** (`config/thresholds.yaml` → `simulator`; accepted after review, 2026-11-21):
- From 50 % distance, every start fraction must beat the order at the start lap on log score.
- Against the accepted calibration, the overall log score may not fall by more than 0.02.
- Against the accepted calibration, neither coverage may move more than 3 points further from
  nominal.
- The first run passed. Phase 11 will call this gate after each weekend's refit; the sampler
  diagnostics stay gated in each model's own fit.

**Tests:**
- PIT coverage is nominal for a calibrated forecast and low for an overconfident one.
- Central intervals are right at exact tail boundaries. This test found a float bug.
- The baselines never learn from the race they score.
- Entries cover only the cars running at the start lap, with the right outcomes.
- Gate pass and fail cases.
- The bundle publishes only a calibration that matches the contract.
- `finishCounts` places each car once per run, and a car already out is never classified.
- `startLaps` maps fractions to laps.
- The backtest script runs on Node's type stripping, still without `@types/node`.

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
- The per-compound warm-up term is fitted here, on `out_lap` and early-stint laps (moved from
  Phases 3–4). The Phase 4 pit loss already contains the average warm-up, so this term is the
  compound's deviation from it.

### Debrief: which decisions cost positions
For each pit decision in the actual race: expected-position regret vs the best alternative at that
lap, evaluated **ex ante** (future events sampled — "was it a good call?") and, separately,
**ex post** (realised events — "did it work out?"). Never merge the two numbers.

**Deliverable:** query API inside the engine package, optimiser with tests (it must recover a known
optimum on a synthetic race), undercut module with tests on hand-built scenarios.

### Findings (first build, 2023 R1 – 2026 R20)

**Where it lives.** Everything is in `web/src/sim/`, so nothing outside the one engine simulates:
- `strategy.ts`:
  - objectives;
  - distributions;
  - paired comparisons;
  - `counterfactual`.
- `candidates.ts`: candidate plans.
- `optimise.ts`: successive halving.
- `undercut.ts`: undercut and overcut.
- `debrief.ts`: regret per pit decision.

Searches take an `Evaluate` function:
- `inProcess(race)` in Node and tests;
- `SimPool.run(race, query, first)` in the browser. The pool now takes a start offset, so later
  rounds reuse the runs already done.

The search settings are in `config/pipeline.yaml` → `sim.strategy` and are published in the
manifest (`Manifest.strategy`). Contract 0.4.0.

**Counterfactual.** `(race, car, from_lap, plan)` returns the distributions of the actual and the
alternative plan under common random numbers, plus the paired difference:
- share of runs ahead and behind;
- mean places gained, with its standard error.

A plan that breaks a rule gets the real consequence: a disqualification. Every other car keeps
its actual plan (ADR-004). The car's own plan is open loop too: it cannot react to a sampled
safety car.

**Objectives:**
- expected position;
- P(podium);
- P(points). Points places come from `config/regulations.yaml` (`points_places`, sourced).
- P(beat car X).

Podium and points count only classified results. Simulation outcomes now carry the 90 %
classification flag.

**Candidates:**
- 0–3 stops in all: 1–3 stops cover 94 % of dry-race finishers. More are reactive.
- Every planned stint, the last included, is at least 5 laps: the 5th percentile of final stints in
  dry races. Shorter stints are damage or safety-car stops that an open-loop plan cannot express.
- Any of the race's allocated C-numbers, on a new set. Which sets a driver really had left is not
  in the data, so this is optimistic for sets.
- Only plans that satisfy the race's rules.
- Pit laps are one lap apart while the plans fit in 1,500. Fewer stops come first, and the next
  stop count spreads its pit laps until it fits. In practice, 3-stop plans are coarse.

**Optimiser:** successive halving under common random numbers:
- 16 runs for every candidate;
- each round keeps the best third (never fewer than 5) and triples the runs, up to 2,000;
- ties on the objective are broken on expected position;
- finalists and the actual plan are then scored together on the same 2,000 runs.

The test builds a race whose best plan is known by hand: two identical cars that never meet, and
fixed stop times. The optimiser finds that plan under both "beat car X" and expected position,
with fewer runs than brute force.

**Tyre warm-up** (`make fit-warmup`, `pitwall.models.warmup`). The plan moved this term here.
- It is per era, C-number and lap of the stint (1–4), measured against the degradation fit:
  - **Out-lap:** green out-laps only, centred on the race's median out-lap. The pit loss already
    holds the average out-lap and the pit-exit time, which is per track.
  - **Stint laps 2–4:** clean-lap residuals.
- A cell with fewer than 40 laps is 0.
- 200 bootstrap resamples of races serve as draws.
- It is fitted on every race, the simulated race included: the pace softening.
- The engine adds it on green laps.

| Era | Cell | Laps | Median (5–95 %) |
|---|---|---|---|
| 2023–25 | C5 out-lap | 88 | +0.64 s (0.31–1.22) |
| 2023–25 | C1 out-lap | 238 | +0.16 s (0.07–0.24) |
| 2023–25 | C2 out-lap / laps 2 / 3 | 290 / 210 / 191 | −0.14 / −0.21 / −0.12 s |
| 2026 | C4 stint laps 2 / 3 / 4 | 91 / 101 / 106 | +0.24 / +0.19 / +0.17 s |
| 2026 | C5 stint laps 3 / 4 | 73 / 69 | +0.13 / +0.21 s |

Every other cell is within ±0.1 s. The calibration barely moves with the term in the engine (log
score −1.931 vs −1.930, coverage 0.484 / 0.784), and the gate passed. A schema bump no longer
loses the gate's comparison: it reads only the accepted overall score.

**Undercut / overcut** (`make undercut-check`). Attacker and defender stop on consecutive laps;
everyone else keeps their plan. The answer, P(attacker ahead), is read when the second car has
finished its out-lap. The engine charges the whole pit loss on the in-lap, so the out-lap adds
only the new set's pace and warm-up. The result also exposes its components:
- the gap;
- the pace delta;
- the tyre delta on the attacker's out-lap;
- the green pit loss (10 / 50 / 90 %);
- the warm-up of both new sets.

Out-of-sample check: every real pair of cars adjacent within 3 s, stopping on consecutive green
laps (181 pairs in 75 races). Predicted with the events as they happened, against the real order
after both out-laps:

| Pairs | n | Worked | Brier (module) | Brier (base rate from the other races) |
|---|---|---|---|---|
| Undercut (car behind stops first) | 109 | 36 % | **0.211** | 0.235 |
| Overcut (car ahead stops first) | 72 | 19 % | **0.146** | 0.161 |
| All | 181 | 29 % | **0.185** | 0.205 |

| Predicted | n | Mean predicted | Observed |
|---|---|---|---|
| 0–0.2 | 67 | 0.12 | 0.10 |
| 0.2–0.4 | 53 | 0.29 | 0.28 |
| 0.4–0.6 | 36 | 0.51 | 0.50 |
| 0.6–0.8 | 21 | 0.70 | 0.48 |
| 0.8–1.0 | 4 | 0.85 | 0.75 |

- It is calibrated up to 0.6, and overconfident above it on few pairs.
- Without the warm-up term the Brier score is 0.187 instead of 0.185. The term is real but small.
- Pace is fitted on the race itself, so this check is out of sample for the decision, not for pace.

**Debrief** (`make debrief RACES=… DRIVERS=…`). Each actual stop is judged from the race state at
the end of the lap before its in-lap, ex ante and ex post separately. Each mode reports two
numbers, both measured on 1,000 runs the searches never saw:
- **stop regret:** the best plan found, against the best plan that makes this stop (same lap, same
  set) and plays the rest well. It charges the decision only.
- **plan regret:** the whole actual plan from that lap, later stops included.

The searches always include the actual plan, and every plan that makes the actual stop and then
continues from the real race state after it. So a stop outside the candidate grid is still found,
such as a 3-lap stint ended by a free red-flag tyre change. The first version charged each
decision with the later ones and missed off-grid stops, which gave negative regrets. Tests cover
both.

A sample of 44 decisions by the top five of six races:

| Decision | Ex ante: stop / plan regret | Ex post: stop / plan regret | Reading |
|---|---|---|---|
| Monza 2026, RUS / NOR / PIA stop on lap 3 under the red flag | 0.09 / 0.52 / 0.91 | 0.00 | Right in hindsight, unknowable before it |
| Silverstone 2026, LEC lap 25, then lap 48 under the SC | 0.01 / 1.13 | 0.00 / 0.38 | The first stop was right; the cost is the later stop |
| Silverstone 2026, NOR / HAM late stop under the SC | 1.02 / 0.73 | 1.11 / 1.23 | A 2026 SC stop is barely cheaper (×0.94) |
| Monza 2024, PIA second stop, lap 38 | 1.05 | 1.31 | Best was no second stop, as Leclerc won |
| Monza 2025, VER lap 37 | 0.00 | 0.00 | — |
| Monza 2023 / 2024, every top-five first stop | 0.28 – 0.76 | 0.40 – 0.88 | Best is 6–12 laps later |

**The debrief prefers later stops, systematically.** In almost every first-stop decision of the
sample the best plan stops later than the team did. Two causes are known:
- Opponents are open loop (ADR-004). An early stop that covers a rival's undercut is worth
  nothing when the rival cannot undercut.
- Wear is linear with no cliff (Phase 3). Long stints cost nothing extra at the end.

Until one of these changes, the debrief's "stop later" verdicts on first stops are not evidence of
a mistake. The UI must say so next to them.

**Speed** (one thread, Node, Apple silicon):
- A full search from lap 1 covers about 1,200–1,350 candidates and 86–95k simulated races, in
  3.5–4.1 s. The worker pool (`hardwareConcurrency − 1`) divides that.
- One debrief decision runs four searches plus the holdout runs: 1–18 s, about 8.5 s on average.
- A whole field's debrief (about 40 decisions) belongs in the weekend pipeline (Phase 11), not in
  the browser.

**Open for decisions:**
- reactive stops under a safety car, for the target car and for rivals (ADR-004);
- a wear cliff (Phase 3).

Both would change the debrief's main bias.

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

### Findings

- **Look.** Rim (Hallmark theme), dark first, chosen against public views of team tools
  (Catapult RaceWatch, ATLAS): near-black, dense tables, colour spent on data (tyres, gains),
  not on chrome. One accent marks the primary action, the selection and the current tab.
- **Coverage.** The race view works for all 90 races; the strategy tools need a sim bundle, which
  75 races have (Phases 6 and 7 list which are left out and why); the others say so instead of
  failing.
- **One rule check.** `checkRules` (`web/src/sim/rules.ts`) is the engine's own legality test read
  from the race state; a test holds it to the engine's DSQ verdicts. A rule-breaking plan still
  runs and gets its real consequence, as the engine gives it.
- **Ex ante and ex post stay apart.** What if and Undercut let the viewer choose events drawn at
  random (the default: what was knowable) or as they happened; the result states which.
  Optimise searches ex ante only.
- **Not yet:** calibration for *this track* — the calibration file has segments (era, passing,
  start, neutralised), not per-race scores, so the model card shows those and says so. Debrief
  screens belong to Phase 10.

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

### Findings

- **Fastest laps, not full-race traces** ([ADR-007](adr/007-fastest-lap-traces.md)). Full-race
  location and car data would be about 18 GB of raw responses; one windowed lap is about 80 KB.
  Telemetry covers each driver's fastest lap at pace. The replay draws the outline from the race's
  fastest lap and moves every car along it on its own official lap times, so positions at the
  line are exact and positions inside a lap are estimates (pit laps most of all); the screen says
  so.
- **Distance.** Integrated speed puts Monza 2024 at 5,743 m against the official 5,793 m; laps are
  scaled to the race's median length so corners line up across drivers.
- **Debrief on demand.** Decision regret runs in the browser on the worker pool, per driver or for
  the whole field (Bahrain 2023: 75 s for 20 drivers on a 10-core laptop), and fills the biggest-swings tables as
  drivers finish. Worst calls (ex ante) and worst outcomes (ex post) are separate tables.
- **Coverage and size.** 88 of 90 races have a replay; 1,734 telemetry laps in all. São Paulo 2024
  was wet, so no lap counts as at pace; OpenF1 has no location for Monaco 2026's reference lap.
  Miami 2025 has telemetry but no race times (Phase 7), so its replay says so instead of drawing.
  Drivers without a lap at pace (early retirements) have no telemetry. Largest files, gzipped:
  race and sim 67 KB, replay 9.6 KB, telemetry lap 3.9 KB, far inside the budgets. Raw cache:
  160 MB after the backfill.

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

### Findings

- **The store holds data, not bundles** ([ADR-008](adr/008-releases-store-pipeline-data.md)).
  Releases `data-2023` … `data-2026` hold each race's tables, traces and parameters (90 races,
  46 MB), and `models` the fitted models. The deploy pulls them and exports the bundle itself
  (about 15 s), so a code or contract change reaches every race without a re-pull. Pull and push
  round-trip byte for byte; uploads replace assets of the same name.
- **Calendar from OpenF1, not Jolpica.** A round is finished once its race session ended
  `min_hours_after_race` ago; the sessions endpoint is already in the cache and OpenF1 is the
  only source the pipeline ingests.
- **What changed decides what runs.** The previous race is pulled again with the cache bypassed
  and compared by dataset fingerprint. With nothing new or amended, nothing refits or uploads: a
  run after São Paulo 2026 with no amendment took 82 s and published nothing.
- **Refit cost.** On a 10-core laptop: degradation 19 min (2023-2025 era 15 min, 2026 5 min),
  events 6 min, traffic 1 min, warm-up 4 s; the calibration backtest 1 min. The job allows 5 hours
  for slower runners.
- **Draws are not bit-reproducible.** A refit on unchanged data with the same seeds gives
  different draws; the cause (nutpie's threaded chains is the likely one) is not pinned down.
  Posterior medians move by a small fraction of a posterior sd, and the calibration segments the
  README quotes are unchanged to the percent. The dataset hash is
  reproducible; the parameters are reproducible only in distribution.
- **Not yet:** the debrief for the whole field runs in the browser on demand, not in the workflow.

---

## Phase 12 — Docs & Polish

README: what it is in one paragraph; the architecture diagram; a GIF of a counterfactual; the
modelling story (fuel vs tyre confounding, partial pooling, CRN, information-set rule); the
calibration table **including where it fails**; data inventory and attribution; "not affiliated
with Formula 1" disclaimer; "what I'd do with more time" (reactive opponents, live mode, sprint
races, wet-weather strategy).

Blog post: one decision worth explaining (I'd pick the fuel/tyre confounding or ex-ante vs ex-post
debrief) + one surprising finding from real races.

### Findings

- **The surprising finding** for the write-up ([docs/blog/fuel-and-tyres.md](blog/fuel-and-tyres.md)).
  Of the 2,316 stints with 10 or more clean laps, a line through lap time against tyre age is
  negative in 44 % (median +0.006 s/lap): taken naively, tyres get faster with age. With fuel
  separated, the model's wear slope for the same driver and C-number has a median of +0.05 s/lap
  and is negative in 5 %.
- **The GIF** is recorded from the dev server in headless Chromium over the DevTools protocol and
  put together with Pillow, both outside the project. It is 88 KB, so it lives in `docs/media/`.
- **Jolpica is attributed but not used yet.** The site footer credits it as CLAUDE.md asks; the
  README says it is planned.

---

## After review (2026-11-21)

Decisions on the questions left open by Phases 7, 8 and 3.

### Stint cap instead of a wear cliff
- Wear stays linear: the residuals show no curvature, and a cliff term would be fitted on stints
  teams ended before any cliff. Instead the strategy search never proposes a stint longer than the
  95th percentile of stints completed on that C-number (ended by a stop or the flag, not a
  retirement) in the era's *other* races; a C-number with fewer than 30 such stints uses the era's
  stints. Settings: `config/pipeline.yaml` → `events.stint_cap`; fitted by `make fit-events` into
  `events.json`, exported as `Degradation.max_stint_laps` (contract 0.6.0). A running stint
  already past its cap may still stop at the first lap the other bounds allow.
- Caps for 2023-25, from the other races of Monza 2024: C1 39, C2 42, C3 42, C4 38, C5 34 laps.
- The cap binds in 58 of 75 simulable races and removes 3.8 % of the leader's lap-1 candidates,
  mostly one-stops whose stints run past anything raced.
- **It does not explain the debrief's preference for later stops.** On Monza 2023, 2024 and 2025
  (top five, 18 decisions) every verdict is unchanged: the later stops the search prefers are
  7-14 laps later and well inside the cap. That leaves open-loop rivals as the likelier cause.
- Calibration is unchanged (it runs the actual strategies, which the cap does not touch).

### Reactive stops under a safety car: tried, not shipped
- Built as agreed (draft PR 20): on the first lap of a sampled SC or VSC, every car with a planned
  stop still to make may take it at once. P = logistic(kind + tyre age + share of race left), per
  era, learnt from the other races, with bootstrap draws. The fit is clear: 67-71 % of such cars
  stop on an SC's first two laps, 23 % under a VSC; +1.2 log-odds per 10 laps of tyre age
  (2023-25); less likely with more race left.
- The condition for shipping was better calibration after a neutralisation without a worse overall
  score. It moved by no more than refit noise: after a real neutralisation, coverage 0.442 / 0.732
  → 0.445 / 0.740 and log score −2.2569 → −2.2571; from 75 % distance unchanged (0.435 / 0.708 →
  0.435 / 0.709); overall log score −1.9297 → −1.9313. So opponents stay open loop (ADR-004).
- Likely reason: the backtest runs the real plans, which already hold the stops made under the
  real safety cars; under a sampled one a car can only bring forward a stop it was making anyway.
  The overconfidence after real neutralisations comes from not anticipating them, which is the
  information-set rule working as intended, not something a reaction to sampled events fixes.
- The late-race overconfidence (from 75 %) remains unexplained by reactive stops; defending and
  driver errors are the remaining candidates.

### Other decisions
- The calibration gate thresholds (Phase 7) are accepted as they are.
- The site credits OpenF1 only until Jolpica data is used.

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
