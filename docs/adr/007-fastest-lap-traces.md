# ADR-007: Fastest-lap traces instead of full-race location and car data

**Status:** accepted

## Context
Phase 10 needs a track map with moving cars (replay) and a two-driver telemetry comparison. The plan
assumed car dots animated from each car's downsampled location feed and telemetry for chosen laps.

OpenF1 has no server-side downsampling. Measured on Monza 2024, one driver's full-race `location`
is 4.5 MB (36,000 points) and `car_data` 5.7 MB. Every driver of the 90 races ingested so far would
be about 18 GB of raw responses to cache, and at the free tier's 30 requests a minute, hours of
downloads, repeated wherever the cache is cold. A date window over one lap is about 80 KB.

## Decision
- **Telemetry:** each driver's fastest lap run at pace (lap class `clean` or `traffic`), fetched
  from `car_data` with a `date>`/`date<` window over the lap. Distance integrates speed from the
  line; each lap is scaled to the race's median lap length so that corners line up across drivers.
  One file per driver-lap, loaded when it is picked.
- **Replay:** one `location` window, over the race's fastest lap, gives the track outline and how
  far round the lap that car was at each moment. Every car is placed on that path by its own
  official lap times: a car that has run 40 % of its current lap's time sits where the reference
  car was at 40 % of its lap. Neutralisations come from race control; tyres and stops from the
  stint table.
- `pitwall ingest` fetches the traces for each new race; `pitwall ingest-traces` fills them in for
  races stored before. Uncached requests pause `openf1_min_interval_s` (config) to stay inside the
  rate limit.
- Bundle files are held to `config/budgets.yaml`; `pitwall export` fails when one is over.

## Consequences
- About 21 requests and 200 KB of raw cache per race instead of about 200 MB. A replay file is
  about 8 KB gzipped, a telemetry lap about 3 KB.
- Inside a lap, a replay position is an estimate. Pit in-laps and out-laps are drawn on track at
  the car's (slower) lap time, so a car in the pit lane appears to crawl round the circuit. The
  screen states this, and the timing at each line is exact.
- Telemetry covers fastest laps only. Comparing other laps (the lap before a stop, a restart) needs
  one more windowed request per lap; the contract already holds any lap, so this is a pipeline
  change, not a schema change.
- A driver whose fastest lap has no car data in OpenF1 is left out of the comparison and logged.
