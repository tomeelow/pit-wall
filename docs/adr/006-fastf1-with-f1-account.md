# ADR-006: FastF1 as the ingestion backbone, authenticated with an F1 account

**Status:** accepted

## Context
The plan assumed FastF1 could read the F1 live-timing archive anonymously. As of 2026-11-19 the
archive (`livetiming.formula1.com/static/…`) returns HTTP 401 without a sign-in, and FastF1 3.9
authenticates with an F1 account and sends the F1TV subscription token. Without it FastF1 only logs
a warning and loads an empty session.

OpenF1 still serves 2023+ laps, stints, pits, race control, intervals, location and car data with no
key. It was considered as the backbone and set aside for now: FastF1 has the richer lap table and
2018+ history, which matters for per-track safety-car statistics (2023+ gives only 3–4 races per
track).

FastF1's documentation (https://docs.fastf1.dev/api_reference/accounts_auth.html) states that an
active **F1TV Access subscription (or higher)** is required for most data. A free account is not
enough. This is a recurring cost: hosting stays free, data access does not.

## Decision
- FastF1 stays the backbone; OpenF1 fills the fields it serves better (see the plan's data table).
- Credentials are secrets. Locally, sign in once with
  `uv run python -m fastf1 auth f1tv --authenticate`; FastF1 stores the token in the user data dir,
  outside the repo. In CI, `F1_USERNAME` and `F1_PASSWORD` are GitHub Actions secrets passed only
  to the ingest step.
- Ingestion fails loudly when timing data is missing instead of exporting an empty race.

## Consequences
- The project's zero-cost goal now covers hosting only; data access needs a paid F1TV subscription.
- The CI pipeline depends on a personal account. If sign-in breaks (expired password, changed flow
  upstream, lapsed subscription), ingestion stops; already-published bundles keep working.
- The FastF1 cache is kept between CI runs so finished sessions are downloaded once.
- If authenticated access becomes unworkable, OpenF1 is the fallback for 2023+ and this ADR is
  superseded.
