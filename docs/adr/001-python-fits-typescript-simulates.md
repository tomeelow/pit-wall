# ADR-001: Python fits, TypeScript simulates — one engine

**Status:** accepted

## Context
The Monte Carlo simulator must run in the browser (zero-cost hosting, ADR-003), so it has to be
JavaScript/TypeScript or WASM. Model fitting (Bayesian degradation, hazard models) is far better
served by the Python ecosystem (PyMC, ArviZ, pandas). Validation of the simulator against real
races runs in CI.

The tempting shortcut is a second, Python simulator for validation and notebooks. Two engines drift:
a rule fixed in one is missed in the other, and the engine whose calibration we publish is no longer
the engine users run.

## Decision
- Python (`pipeline/`) ingests, cleans, fits and exports parameters. It never simulates races.
- `web/src/sim/` is the only simulation engine: pure TypeScript, no DOM, seeded PRNG.
- CI validation (`web/scripts/backtest.ts`) runs that engine under Node against exported bundles.
- The two halves meet only through the export contract (pydantic → JSON Schema → generated TS types).
- Rust/WASM is reconsidered only if profiling shows TypeScript misses the performance budget.

## Consequences
- Notebook exploration of "what would the sim say" goes through the Node runner, not a Python port.
- Lint rules in `web/eslint.config.js` keep `src/sim/` free of `Math.random`, DOM and network access.
- Contract freshness is part of `make verify`, so the two halves cannot silently disagree on shape.
