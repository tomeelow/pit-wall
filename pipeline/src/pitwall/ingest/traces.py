"""Fastest-lap traces from OpenF1: each driver's car data on their fastest lap, and the location
trace of the race's fastest lap for the track map.

Full-race car data and location run to about 10 MB per driver; a date window over one lap is
about 80 KB (ADR-007). Telemetry is therefore exported for fastest laps only, and the replay places
cars from lap timing along the reference lap rather than from their own location feed.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from pitwall.ingest.openf1 import Client, Records
from pitwall.ingest.storage import RaceTables, race_dir

# Laps a driver ran at pace: in traffic still counts, as long as nothing else was wrong with it.
TRACE_CLASSES = ("clean", "traffic")

TRACE_COLUMNS = {
    "driver": "string",
    "lap": "int64",
    "lap_time_s": "float64",
    "time_s": "float64",
    "distance_m": "float64",
    "speed_kmh": "float64",
    "throttle": "float64",
    "brake": "bool",
    "gear": "int64",
}
TRACK_COLUMNS = {
    "driver": "string",
    "lap": "int64",
    "lap_time_s": "float64",
    "time_s": "float64",
    "x": "int64",
    "y": "int64",
}


def fastest_laps(laps: pd.DataFrame) -> pd.DataFrame:
    """Each driver's fastest lap run at pace, fastest first."""
    timed = laps[laps["lap_class"].isin(TRACE_CLASSES) & laps["lap_time_s"].notna()]
    best = timed.loc[timed.groupby("driver")["lap_time_s"].idxmin()]
    return best.sort_values("lap_time_s").reset_index(drop=True)


def _window(start: pd.Timestamp, lap_time_s: float) -> dict[str, str]:
    end = start + pd.Timedelta(seconds=lap_time_s)
    return {"date>": start.isoformat(), "date<": end.isoformat()}


def _seconds_from(start: pd.Timestamp, samples: pd.DataFrame) -> pd.Series:
    return (pd.to_datetime(samples["date"], utc=True, format="ISO8601") - start).dt.total_seconds()


def lap_trace(samples: Records, start: pd.Timestamp, lap_time_s: float) -> pd.DataFrame:
    """One lap's car data → channels by time and distance from the line. The trace runs from the
    line (time 0) to the line (lap_time_s), holding the first and last samples' channels there;
    distance integrates speed (trapezoid) from 0."""
    frame = pd.DataFrame(samples)
    frame["time_s"] = _seconds_from(start, frame)
    frame = frame[(frame["time_s"] > 0) & (frame["time_s"] < lap_time_s)].sort_values("time_s")
    frame = pd.concat(
        [
            frame.iloc[[0]].assign(time_s=0.0),
            frame,
            frame.iloc[[-1]].assign(time_s=lap_time_s),
        ],
        ignore_index=True,
    )
    speed_ms = frame["speed"].to_numpy(dtype=float) / 3.6
    step = np.diff(frame["time_s"].to_numpy()) * (speed_ms[1:] + speed_ms[:-1]) / 2
    return pd.DataFrame(
        {
            "time_s": frame["time_s"],
            "distance_m": np.concatenate([[0.0], np.cumsum(step)]),
            "speed_kmh": frame["speed"].astype(float),
            "throttle": frame["throttle"].clip(0, 100).astype(float),
            "brake": frame["brake"] > 0,
            "gear": frame["n_gear"].astype("int64"),
        }
    )


def align_distance(traces: pd.DataFrame) -> pd.DataFrame:
    """Integrated speed drifts by a few tens of metres a lap, differently per car. Scale every lap
    to the median lap length so that a corner falls at one distance for every driver."""
    totals = traces.groupby(["driver", "lap"])["distance_m"].transform("max")
    length = traces.groupby(["driver", "lap"])["distance_m"].max().median()
    return traces.assign(distance_m=traces["distance_m"] * length / totals)


def fetch_traces(client: Client, tables: RaceTables) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Car data on every driver's fastest lap, and the location trace of the fastest of them."""
    key = tables.event.session_key
    drivers = client.get("drivers", session_key=key)
    numbers = {d["name_acronym"]: d["driver_number"] for d in drivers}
    best = fastest_laps(tables.laps)
    traces = []
    for row in best.to_dict("records"):
        start, lap_time = row["lap_start_utc"], row["lap_time_s"]
        samples = client.get(
            "car_data",
            session_key=key,
            driver_number=numbers[row["driver"]],
            **_window(start, lap_time),
        )
        if len(samples) < 2:
            logger.warning("{} lap {}: no car data", row["driver"], row["lap"])
            continue
        traces.append(
            lap_trace(samples, start, lap_time).assign(
                driver=row["driver"], lap=row["lap"], lap_time_s=lap_time
            )
        )
    trace_table = align_distance(pd.concat(traces, ignore_index=True)) if traces else pd.DataFrame()

    track = pd.DataFrame()
    if not best.empty:
        reference = best.iloc[0]
        start, lap_time = reference["lap_start_utc"], reference["lap_time_s"]
        location = pd.DataFrame(
            client.get(
                "location",
                session_key=key,
                driver_number=numbers[reference["driver"]],
                **_window(start, lap_time),
            )
        )
        if not location.empty:
            track = location.assign(
                time_s=_seconds_from(start, location),
                driver=reference["driver"],
                lap=reference["lap"],
                lap_time_s=lap_time,
            ).sort_values("time_s")
    return _typed(trace_table, TRACE_COLUMNS), _typed(track, TRACK_COLUMNS)


def _typed(frame: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in columns.items()})
    return frame[list(columns)].astype(columns).reset_index(drop=True)


def write_traces(
    data_dir: Path, tables: RaceTables, traces: pd.DataFrame, track: pd.DataFrame
) -> None:
    out = race_dir(data_dir, tables.event.season, tables.event.round)
    traces.to_parquet(out / "traces.parquet", index=False)
    track.to_parquet(out / "track.parquet", index=False)


def read_traces(path: Path) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """A race's traces, or None until `pitwall ingest-traces` has fetched them."""
    if not (path / "traces.parquet").exists():
        return None
    return pd.read_parquet(path / "traces.parquet"), pd.read_parquet(path / "track.parquet")
