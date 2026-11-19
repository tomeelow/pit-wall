# ADR-002: Hierarchical Bayesian tyre degradation (PyMC)

**Status:** accepted

## Context
Degradation varies by regulation era, track, Pirelli compound (C-number) and team. Per-stint OLS
fits are noisy, undefined for short stints, and give no usable uncertainty. The simulator needs
uncertainty in the parameters, not only in lap-to-lap noise, or its finishing-position
distributions are falsely narrow.

## Decision
- Fit a hierarchical model with partial pooling era → compound → track → team (see Phase 3 of the
  implementation plan), with an explicit fuel / race-lap term on a physics-informed prior.
- Use PyMC with the nutpie sampler; ArviZ for diagnostics.
- Export a fixed number of posterior draws per race; the simulator samples one draw per run.

## Consequences
- The model must beat per-stint OLS and driver-stint-median baselines leave-one-race-out. If it
  doesn't, that is reported and this ADR is revisited — the complexity has to earn its place.
- Sampler diagnostics (R̂, ESS, divergences) are a hard gate in the publishing pipeline.
- PyMC and nutpie are added in Phase 3, not before.
