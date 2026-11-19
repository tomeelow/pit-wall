# ADR-005: Post-race analysis only in v1

**Status:** accepted

## Context
OpenF1 historical data (2023+) is free; live data during a session is a paid tier. A live mode would also need an always-on component, contradicting the
zero-cost static architecture (ADR-003).

## Decision
v1 analyses completed races only. Data is pulled after each race weekend by GitHub Actions. No paid
data tiers and no live mode.

## Consequences
- The UI never implies live data.
- The race-state snapshot design (Phase 2) keeps a live mode possible later: a live feed would only
  have to produce the same snapshot shape.
