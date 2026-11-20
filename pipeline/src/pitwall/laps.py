"""The single definition of a clean lap. Every model consumes `lap_class`; none re-filters.

Changing a rule here changes every model downstream: treat it as a schema change.
"""

import numpy as np
import pandas as pd

from pitwall.config import ClassificationConfig

# First matching class wins, so a lap that is both an out-lap and under the safety car is an
# out-lap. `traffic` laps are kept apart because they train the traffic model.
LAP_CLASSES = (
    "lap1",
    "in_lap",
    "out_lap",
    "neutralised",
    "wet",
    "yellow",
    "traffic",
    "outlier",
    "clean",
)
TRACK_STATUSES = ("RED", "SC", "VSC", "YELLOW", "GREEN")  # worst first
WET = ("INTERMEDIATE", "WET")


def _overlaps(
    start: pd.Series, end: pd.Series, period_start: pd.Timestamp, period_end: pd.Timestamp
) -> pd.Series:
    return (start < period_end) & (end > period_start)


def _track_status(
    laps: pd.DataFrame,
    neutralisations: pd.DataFrame,
    yellows: pd.DataFrame,
    max_yellow: pd.Timedelta,
) -> tuple[pd.Series, pd.Series]:
    """Worst status during each lap, and whether it is the first lap after an SC or red flag."""
    start, end = laps["lap_start_utc"], laps["crossing_utc"]
    timed = start.notna() & end.notna()
    flags = {status: pd.Series(False, index=laps.index) for status in TRACK_STATUSES}
    restart = pd.Series(False, index=laps.index)
    for period in neutralisations.to_dict("records"):
        by_time = _overlaps(start, end, period["start_utc"], period["end_utc"])
        by_lap = laps["lap"].between(period["start_lap"], period["end_lap"])
        flags[period["kind"]] |= by_time.where(timed, by_lap)
        # The race restarts when an SC comes in or a red flag ends: each driver's next lap is a
        # restart lap. An SC ended by a red flag, or anything ended by the flag, has none.
        if period["kind"] in ("SC", "RED") and period["ended_by"] in ("end_message", "restart"):
            after = laps[timed & (start >= period["end_utc"])]
            first_after = after.groupby("driver")["lap"].transform("min") == after["lap"]
            restart |= first_after.reindex(laps.index, fill_value=False)
            restart |= ~timed & (laps["lap"] == period["end_lap"] + 1)
    for period in yellows.to_dict("records"):
        until = min(period["end_utc"], period["start_utc"] + max_yellow)
        flags["YELLOW"] |= timed & _overlaps(start, end, period["start_utc"], until)

    status = np.select([flags[s] for s in TRACK_STATUSES[:-1]], TRACK_STATUSES[:-1], "GREEN")
    return pd.Series(status, index=laps.index), restart


def classify_laps(
    laps: pd.DataFrame,
    race_state: pd.DataFrame,
    neutralisations: pd.DataFrame,
    yellows: pd.DataFrame,
    config: ClassificationConfig,
) -> pd.DataFrame:
    """Laps with `track_status` and `lap_class` added.

    - in_lap: a pit record on the lap, or the next lap is an out-lap (some sessions have no pit
      records at all).
    - neutralised: any part of the lap under SC, VSC or red flag, plus each driver's restart lap.
    - yellow: a local yellow was out anywhere on track during the lap. Marshal sectors are not
      mapped to the driver's position yet, so this is conservative. A yellow counts for at most
      `max_yellow_s` (some are never cleared in race control).
    - traffic: started the lap (crossed the line) within `traffic_gap_s` of the car physically
      ahead.
    - outlier: no lap time or no known compound, or slower than `outlier_factor` x the median of
      the driver's remaining laps in that stint.
    """
    keys = ["driver", "lap"]
    state = race_state[[*keys, "crossing_utc", "gap_ahead_s"]]
    merged = laps.merge(state, on=keys, how="left", validate="one_to_one")
    merged.index = laps.index
    merged = merged.sort_values(keys)
    by_driver = merged.groupby("driver")
    next_is_consecutive = by_driver["lap"].shift(-1) == merged["lap"] + 1
    prev_is_consecutive = by_driver["lap"].shift(1) == merged["lap"] - 1
    next_out = by_driver["pit_out"].shift(-1).astype("boolean").fillna(False)
    gap_at_start = by_driver["gap_ahead_s"].shift(1).where(prev_is_consecutive)

    max_yellow = pd.Timedelta(seconds=config.max_yellow_s)
    status, restart = _track_status(merged, neutralisations, yellows, max_yellow)
    unusable = merged["lap_time_s"].isna() | (merged["compound"] == "UNKNOWN")
    unusable |= merged["compound_c"].isna() & ~merged["compound"].isin(WET)
    rules = {
        "lap1": merged["lap"] == 1,
        "in_lap": merged["pit_in"] | (next_out & next_is_consecutive),
        "out_lap": merged["pit_out"],
        "neutralised": status.isin(["RED", "SC", "VSC"]) | restart,
        "wet": merged["compound"].isin(WET),
        "yellow": status == "YELLOW",
        "traffic": gap_at_start < config.traffic_gap_s,
        "outlier": unusable,
    }
    lap_class = pd.Series(
        np.select(list(rules.values()), list(rules), "clean"), index=merged.index
    ).astype(str)

    candidates = lap_class == "clean"
    median = (
        merged["lap_time_s"]
        .where(candidates)
        .groupby([merged["driver"], merged["stint"]])
        .transform("median")
    )
    lap_class[candidates & (merged["lap_time_s"] > median * config.outlier_factor)] = "outlier"
    return laps.assign(
        track_status=status.astype(str).reindex(laps.index),
        lap_class=lap_class.reindex(laps.index),
    )
