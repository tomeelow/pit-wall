"""Race tables and fastest-lap traces → the replay file and one telemetry file per driver."""

import pandas as pd

from pitwall.export.contract import (
    SCHEMA_VERSION,
    FastestLap,
    Neutralisation,
    Replay,
    ReplayCar,
    TelemetryLap,
    TrackOutline,
)
from pitwall.ingest.storage import TABLES, RaceTables, dataset_fingerprint


def _ints(values: pd.Series) -> list[int]:
    return [int(v) for v in values.round()]


def telemetry_lap(trace: pd.DataFrame) -> TelemetryLap:
    first = trace.iloc[0]
    return TelemetryLap(
        schema_version=SCHEMA_VERSION,
        driver=str(first["driver"]),
        lap=int(first["lap"]),
        lap_time_s=float(first["lap_time_s"]),
        distance_m=_ints(trace["distance_m"]),
        time_ms=_ints(trace["time_s"] * 1000),
        speed_kmh=_ints(trace["speed_kmh"]),
        throttle=_ints(trace["throttle"]),
        brake=[int(b) for b in trace["brake"]],
        gear=_ints(trace["gear"]),
    )


def build_replay(
    tables: RaceTables, traces: pd.DataFrame, track: pd.DataFrame, telemetry_dir: str
) -> tuple[Replay, list[TelemetryLap]] | None:
    """None when the race has no location trace to draw the track from."""
    if track.empty:
        return None
    laps = [telemetry_lap(trace) for _, trace in traces.groupby("driver", sort=False)]
    laps.sort(key=lambda lap: lap.lap_time_s)

    state = tables.race_state.dropna(subset=["race_time_s"]).sort_values("lap")
    times = state.groupby("driver")["race_time_s"].apply(lambda s: [round(t, 3) for t in s])
    cars = [
        ReplayCar(driver=driver, lap_end_s=times[driver])
        for driver in tables.results["driver"]
        if driver in times
    ]
    reference = track.iloc[0]
    replay = Replay(
        schema_version=SCHEMA_VERSION,
        season=tables.event.season,
        round=tables.event.round,
        dataset_version=dataset_fingerprint(
            *(getattr(tables, name) for name in TABLES), traces, track
        ),
        track=TrackOutline(
            driver=str(reference["driver"]),
            lap=int(reference["lap"]),
            lap_time_s=float(reference["lap_time_s"]),
            x=_ints(track["x"]),
            y=_ints(track["y"]),
            t_ms=_ints(track["time_s"] * 1000),
        ),
        cars=cars,
        neutralisations=[
            Neutralisation(kind=row["kind"], start_lap=row["start_lap"], end_lap=row["end_lap"])
            for row in tables.neutralisations.to_dict("records")
        ],
        fastest_laps=[
            FastestLap(
                driver=lap.driver,
                lap=lap.lap,
                lap_time_s=lap.lap_time_s,
                telemetry_path=f"{telemetry_dir}/{lap.driver}.json",
            )
            for lap in laps
        ],
    )
    return replay, laps
