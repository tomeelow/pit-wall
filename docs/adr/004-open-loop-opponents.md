# ADR-004: Open-loop opponents in v1

**Status:** accepted

## Context
In a counterfactual ("what if VER pitted on lap 18?") other teams would have reacted — covering an
undercut, extending to overcut. Modelling that requires a policy model for every team, which the data
for a single season barely supports and which is hard to validate.

## Decision
In v1 every other car keeps its actual strategy (same compounds, same pit laps), adjusted only where
the sporting regulations force it (e.g. a required stop that did not happen yet). Only the target
driver's strategy changes.

## Consequences
- Counterfactual results understate the cost of moves that rivals would have covered. Every result
  view states the assumption.
- Reactive opponents are a candidate for a later phase; they will need their own validation before
  replacing this behaviour.
- 2026-11-21: stops brought forward under a sampled safety car or VSC were built and validated (draft
  PR 20). Calibration did not improve beyond refit noise, so this decision stands. See the plan's
  "After review" section.
