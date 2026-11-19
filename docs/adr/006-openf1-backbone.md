# ADR-006: OpenF1 as the ingestion backbone

**Status:** accepted

## Context
The plan assumed FastF1 as the backbone: the richest lap table and 2018+ history. In Phase 0 the F1
live-timing archive FastF1 reads (`livetiming.formula1.com/static/…`) returned HTTP 401 without
sign-in. FastF1 3.9 signs in with an F1 account, and its documentation
(https://docs.fastf1.dev/api_reference/accounts_auth.html) states that an active **F1TV Access
subscription (or higher)** is required for most data. That would make the project depend on a paid
subscription and put personal account credentials into CI.

OpenF1 serves 2023+ laps, stints (with `tyre_age_at_start`), pits, race control, intervals,
position, location, car data, weather and results with no key.

## Decision
- OpenF1 is the ingestion backbone. FastF1 is not a dependency.
- Jolpica (Ergast-compatible, keyless) is added when results history or DNF reasons are needed.
- Every raw response is cached on disk (requests-cache, SQLite) with retry and backoff on 429/5xx,
  respecting OpenF1's free-tier rate limit.
- OpenF1 has no round numbers: the round is the race's position among the season's non-cancelled
  `Race` sessions sorted by start time.

## Consequences
- No secrets anywhere in the project; the zero-cost goal holds for data as well as hosting.
- History starts in 2023. Per-track SC/VSC rates rest on 3–4 races per track, so Phase 4 pools
  strongly across tracks. This is the main price of the decision.
- Telemetry comparison (Phase 10) uses OpenF1 `car_data` (~3.7 Hz) and has to compute distance
  itself instead of using FastF1's distance-aligned telemetry helpers.
- If OpenF1 changes its free tier, FastF1 with an F1TV subscription is the known alternative.
