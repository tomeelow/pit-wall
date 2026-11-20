"""Race state at every line crossing: the initial condition for a counterfactual from lap N.

Timing positions are decided at the control line, so the state is rebuilt from when each driver
completed each lap. Laps OpenF1 does not report (e.g. a gap in the data) have no row.
"""

from collections.abc import Hashable
from typing import Any

import pandas as pd

DRY = ("SOFT", "MEDIUM", "HARD")


def line_crossings(laps: pd.DataFrame) -> pd.Series:
    """When each lap ended, aligned with `laps`. The next lap's start is the exact crossing;
    a driver's last lap (or one before a gap in the data) falls back to start + lap time."""
    ordered = laps.sort_values(["driver", "lap"])
    by_driver = ordered.groupby("driver")
    next_start = by_driver["lap_start_utc"].shift(-1)
    consecutive = by_driver["lap"].shift(-1) == ordered["lap"] + 1
    own_end = ordered["lap_start_utc"] + pd.to_timedelta(ordered["lap_time_s"], unit="s")
    return next_start.where(consecutive, own_end).reindex(laps.index)


def _physical_gaps(crossings: pd.DataFrame) -> list[float]:
    """Seconds since any other car crossed the line, i.e. the gap to the car physically ahead
    (which may be a lap up or down)."""
    gaps: list[float] = []
    last: dict[Hashable, Any] | None = None
    other: dict[Hashable, Any] | None = None  # last crossing by a driver other than `last`'s
    for row in crossings.to_dict("records"):
        ahead = last if last is not None and last["driver"] != row["driver"] else other
        gaps.append(
            (row["crossing_utc"] - ahead["crossing_utc"]).total_seconds()
            if ahead is not None
            else float("nan")
        )
        if last is not None and last["driver"] != row["driver"]:
            other = last
        last = row
    return gaps


def _dry_compounds_used(laps: pd.DataFrame) -> list[str]:
    """Comma-separated dry compounds a driver has raced on up to and including each lap."""
    used: list[str] = []
    seen: dict[str, set[str]] = {}
    for row in laps.to_dict("records"):
        compounds = seen.setdefault(row["driver"], set())
        if row["compound"] in DRY:
            compounds.add(row["compound"])
        used.append(",".join(c for c in DRY if c in compounds))
    return used


def build_race_state(laps: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """One row per driver per completed lap: running order, gaps and tyre state at the line."""
    state = laps.assign(crossing_utc=line_crossings(laps)).sort_values(["driver", "lap"])
    race_start = state.loc[state["lap"] == 1, "lap_start_utc"].min()

    timed = state.dropna(subset=["crossing_utc"]).sort_values(["lap", "crossing_utc"])
    position = timed.groupby("lap").cumcount() + 1
    leader = timed.groupby("lap")["crossing_utc"].transform("min")
    interval = timed.groupby("lap")["crossing_utc"].diff()
    by_time = timed.sort_values("crossing_utc")
    physical = pd.Series(_physical_gaps(by_time), index=by_time.index)

    dnf = set(results.loc[results["status"] == "DNF", "driver"])
    last_lap = state.groupby("driver")["lap"].transform("max")
    return pd.DataFrame(
        {
            "driver": state["driver"].astype(str),
            "lap": state["lap"].astype("int64"),
            "crossing_utc": state["crossing_utc"],
            "race_time_s": (state["crossing_utc"] - race_start).dt.total_seconds(),
            "position": position.reindex(state.index).astype("Int64"),
            "gap_to_leader_s": (timed["crossing_utc"] - leader)
            .dt.total_seconds()
            .reindex(state.index),
            "interval_s": interval.dt.total_seconds().reindex(state.index),
            "gap_ahead_s": physical.reindex(state.index),
            "stint": state["stint"],
            "compound": state["compound"],
            "compound_c": state["compound_c"],
            "tyre_age": state["tyre_age"],
            "stops": (state["stint"] - 1).astype("Int64"),
            "in_pit": state["pit_in"],
            "dry_compounds_used": _dry_compounds_used(state),
            "retired": state["driver"].isin(dnf) & (state["lap"] == last_lap),
        }
    ).reset_index(drop=True)


def position_agreement(
    race_state: pd.DataFrame, positions: pd.DataFrame, lag_s: float
) -> float | None:
    """Share of driver-laps whose position matches OpenF1's position feed just after the line
    (the feed lags the crossing by up to `lag_s`). None when the feed is empty."""
    timed = race_state.dropna(subset=["crossing_utc", "position"])
    if positions.empty or timed.empty:
        return None
    probe = timed.assign(
        utc=timed["crossing_utc"] + pd.Timedelta(seconds=lag_s), driver=timed["driver"]
    ).sort_values("utc")
    feed = (
        positions.rename(columns={"position": "feed_position"})
        .astype({"driver": str})
        .sort_values("utc")
    )
    matched = pd.merge_asof(probe, feed, on="utc", by="driver", direction="backward")
    known = matched.dropna(subset=["feed_position"])
    return float((known["position"] == known["feed_position"]).mean()) if len(known) else None
