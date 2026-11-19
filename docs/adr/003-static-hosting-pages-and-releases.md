# ADR-003: Static bundle on GitHub Pages, durable storage in GitHub Releases

**Status:** accepted

## Context
Running cost must be zero and there is no server. The site needs the web app plus a growing
collection of per-race data bundles (race summary, model parameters, replay and telemetry extracts).
Regenerating every past race on every deploy is slow and hammers the upstream APIs.

## Decision
- Generated data is never committed to git.
- Each finalised race bundle is uploaded as an asset of a per-season GitHub Release.
- The Pages deploy assembles the site from the release assets plus the freshly built web app,
  using `actions/deploy-pages` (artifact-based, no `gh-pages` branch).

### Rejected
- **Data branch** — bloats repository history with binary churn.
- **`actions/cache` as the store** — entries are evicted after 7 days without access.
- **Object storage (R2, S3)** — adds an account and breaks the zero-cost constraint at scale.

## Consequences
- Publishing must be idempotent: re-running a race replaces its asset, never duplicates it.
- Until Phase 11 the walking skeleton ingests its race directly in the deploy workflow; the
  Releases store arrives with post-weekend automation.
- Bundle size budgets (`config/budgets.yaml`) matter: Pages has a 1 GB site limit.
