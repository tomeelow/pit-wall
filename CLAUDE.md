# CLAUDE.md

Guidance for Claude when working in this repository.

## Project context

**Pit Wall** is an F1 race strategy lab. Pick a race and a driver and ask "what if he had pitted
3 laps earlier?", "one stop or two?", "medium → hard or hard → medium?". The system runs thousands
of Monte Carlo races and answers with a **distribution of finishing positions**, not one number.
Around that core: tyre degradation, traffic/overtaking, SC/VSC, undercut/overcut models, plus race
replay, telemetry comparison and a post-race strategy debrief.

Data: **OpenF1** (laps, stints, pits, intervals, race control, location, car data, results; free,
no key, 2023+) and **Jolpica** for results history. FastF1 is not used: it now needs a paid F1TV
subscription (ADR-006). v1 is **post-race analysis only** — live OpenF1 data is a paid tier and is
out of scope.

Deployment costs **zero**: GitHub Actions fits models after each race weekend and publishes static
files; the simulator runs in the browser in Web Workers. There is no server.

The roadmap and current phase live in `docs/implementation_plan.md` — read its **Status** table
before starting work and update it when a phase lands. Decisions live in `docs/adr/`.

Three things distinguish this project and must not be quietly dropped:

1. **Distributions, not answers.** Every strategy result is a distribution with parameter
   uncertainty propagated (posterior draws), compared against the driver's actual strategy.
2. **The simulator is calibrated, and the calibration is published** — including where it fails.
3. **Hindsight is not analysis.** Counterfactuals from lap N use only what was knowable at lap N.

## Core principles

- **Concise over clever.** Smallest amount of code that solves the problem clearly.
- **No premature abstraction.** Don't add layers, factories, or config switches until a second
  concrete use case exists.
- **Best practices, not ceremony.** Idiomatic Python and idiomatic TypeScript; don't import patterns
  from one into the other.
- **Readable beats compact.** Concise is not the same as obfuscated.
- **Delete more than you add.** When refactoring, the diff should usually shrink.

## Architecture boundaries

- **Python fits, TypeScript simulates.** `pipeline/` ingests, cleans, fits and exports parameters.
  `web/src/sim/` is the **only** simulation engine. CI validation runs that engine under Node.
  Never write a Python simulator "for a quick check" — two engines drift, and then the one you
  validated is not the one users run.
- **The contract is the only bridge.** Pydantic models in `pipeline/src/pitwall/export/contract.py`
  are the source of truth → `make contract` generates JSON Schema and TS types. Never hand-edit
  `web/src/contract/`. A breaking change bumps the major `schema_version`.
- **`web/src/sim/` is pure.** No DOM, no `fetch`, no global state, no `Math.random`. Inputs in,
  outcome out.
- **The main thread never simulates.** All Monte Carlo work goes through the worker pool.
- These boundaries are enforced where possible: `web/eslint.config.js` bans `Math.random`, DOM and
  network globals, and UI/worker imports inside `src/sim/`; `make contract-check` fails on stale
  generated contract files.

## Git workflow

- **Branch per change.** Never commit features or fixes directly to `main`. Use `feat/<slug>`,
  `fix/<slug>`, `chore/<slug>`, `docs/<slug>`.
- **One concern per branch.** If scope grows, split.
- **Commit messages: short, imperative, descriptive. No filler.**
  - Good: `feat: add OpenF1 stints ingestion with C-number join`
  - Good: `fix: exclude VSC restart lap from clean-lap set`
  - Good: `chore: pin pymc and nutpie`
  - Bad: `updates`, `WIP`, `various changes`, `fixed stuff`
- **Squash noisy histories before merging.** Keep `main` linear and readable.
- **Never commit generated data, caches or model outputs.** The OpenF1 response cache,
  parquet tables and exported bundles stay out of git; finalised race bundles go to GitHub Releases (ADR-003).
- **Never commit secrets or `.env`.** None are needed today (OpenF1 and Jolpica are keyless); keep
  it that way unless an ADR says otherwise.

## Code quality

- **One verify command:** `make verify` (ruff, ruff format --check, pyright, pytest; tsc, eslint,
  vitest; contract freshness). CI runs exactly this. Run it before calling anything done.
- **Python:** type hints on public functions; `ruff` + `ruff format`; `pyright`; `pytest`
  (+ `hypothesis` for invariants). Dependencies via `uv`, pinned.
- **TypeScript:** `strict` on; `eslint`; `vitest`. Dependencies via `npm` with exact versions
  (`.npmrc`), lockfile committed. CI runs Node 24 LTS.
- **Configuration:** YAML in `config/` for seasons, compound allocation, team mapping, regulations
  (min stops, fuel figures per era), thresholds and size budgets. No magic numbers in model or sim
  code — a fuel coefficient or a traffic threshold in code is a bug.
- **Logging over print.** `loguru` in the pipeline. Log per-race row counts, dropped laps by class,
  sampler diagnostics, dataset hashes and bundle sizes — not dataframes.
- **Tests where it matters:** lap classification, race-state reconstruction, C-number/team joins,
  the degradation model's handling of fuel, every simulator invariant, the optimiser on a synthetic
  race with a known optimum, and calibration metrics. Not required for notebooks.
- **Notebooks are scratch space** (`pipeline/notebooks/`). Mature logic moves into the package.
  Nothing imports from a notebook.

## Domain rules

### One definition of a clean lap
`classify_laps()` in `pitwall.laps` is the single source of truth for lap classes (`lap1`, `in_lap`,
`out_lap`, `neutralised`, `yellow`, `traffic`, `wet`, `outlier`, `clean`). Every model consumes
`lap_class`; none re-filters laps its own way. Changing a class rule changes every model — treat it
as a schema change.

### Tyre degradation: separate fuel from wear (the most important modelling rule)
Within a stint tyre age rises while fuel load falls and the track rubbers in. Fitting lap time on
tyre age alone makes fuel burn-off look like *negative* degradation.

- Every lap-time model carries an explicit race-lap / fuel term with a physics-informed prior from
  `config/regulations.yaml`.
- Degradation is fitted on `clean` laps only.
- Compounds are keyed by **Pirelli C-number**, never by SOFT/MEDIUM/HARD (relative per event).
- `tyre_age` includes laps run before the stint (used sets from qualifying).
- `era` is a model level. 2023–2025 and 2026+ are different cars; don't pool across the boundary
  without an era term.

### The information-set rule (this repo's leakage rule)
When evaluating a situation at lap N, the simulator may only use information available at lap N.

- Future SCs, VSCs, red flags, DNFs and slow stops are **sampled**, never replayed from reality,
  in any ex-ante evaluation.
- The debrief reports **ex ante** ("was it a good call?") and **ex post** ("did it work out?")
  separately. Never merge them into one number.
- Pace parameters fitted on the whole race are a known, documented softening of this rule. Keep it
  visible in the UI and README; don't extend it to random events.

### Simulation discipline
- **Seeded PRNG only.** Same seed → identical outcome; there is a test for it.
- **Common random numbers** whenever strategies are compared: simulation index *i* sees the same
  noise, events and parameter draw under every strategy.
- **Sample a posterior draw per run.** Point estimates make the distribution falsely narrow.
- **Regulations are enforced from config,** not assumed. A rule-breaking strategy gets the real
  consequence.
- **Opponents are open-loop in v1** (they keep their actual strategies). Every result view states
  this assumption.
- **Overtakes are on-track position changes only** — pit cycles, retirements and penalties are
  excluded from the overtake model's training data.

### Data
- **Cache every raw response; respect OpenF1 rate limits.** Never re-pull a finished season
  without being asked.
- **Classifications get amended** by post-race penalties — the weekend workflow re-pulls the
  previous race.
- **Validate on ingestion** (`pandera`): contiguous laps per driver, plausible lap times, a
  compound and C-number for every dry stint, pits aligned with stint changes, neutralisations
  with start and end.
- **Fingerprint datasets.** Every fitted model and exported bundle records its dataset hash and git
  sha; the UI model card shows them.
- **Time:** OpenF1 timestamps are UTC; keep them UTC. Laps are 1-indexed as in official
  timing. Times in seconds (float), distances in metres.
- **Size budgets** in `config/budgets.yaml` are enforced in CI. Telemetry and location data are
  downsampled, quantised and lazy-loaded; full-race telemetry never ships to the browser.

### Evaluation
- **Out-of-sample or it didn't happen.** Degradation is scored leave-one-race-out against
  driver-stint-median and per-stint OLS baselines. If the Bayesian model doesn't beat OLS, report it.
- **Simulator calibration:** coverage of 50 % / 80 % intervals on held-out races, PIT histogram,
  log-score vs "finish = grid" and "finish = position at lap N". Report per segment (track type,
  dry vs mixed, with vs without neutralisations).
- **Report failures.** Where the simulator is miscalibrated goes in the README. Don't tune the
  reported segments to flatter it.
- **Gated publishing.** New parameters go live only if sampler diagnostics pass (R̂, ESS,
  divergences) and calibration has not materially regressed. A failed gate keeps the previous
  parameters live.

### Legal
Unofficial project, not affiliated with Formula 1. No F1 logos, team logos or official branding;
attribute OpenF1 and Jolpica.

## Ask before acting

When unsure, stop and ask. Specifically:

- Changing lap-class rules, the canonical table schemas, or the contract's major version
- Adding a model term, covariate or data source (especially anything pooling across eras)
- Changing the information-set rule, the CRN setup, or the open-loop opponent assumption
- Changing the publish gate or its thresholds
- Editing `config/compound_allocation.yaml` from memory — C-numbers come from Pirelli's published
  allocations; ask for or cite the source
- Anything that re-pulls or rebuilds whole seasons, or deletes/overwrites release assets
- New dependencies, or anything that would add running cost or a server
- Anything that rewrites git history on shared branches
