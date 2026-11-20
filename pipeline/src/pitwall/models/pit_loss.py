"""Time lost to a pit stop, per track and track condition (plan Phase 4).

A stop's loss is the time its in-lap and out-lap took beyond what the driver would have done
running normally on those two laps. "Normally" is the median lap of the cars that were neither
pitting nor on an out-lap on the same lap, plus the driver's own median gap to that field on their
clean laps. Comparing against the field on the same laps makes one definition work under green,
safety car and VSC alike: under a safety car the field is slow too, so the loss is smaller.

Tyre age is not corrected for: the in-lap runs on older tyres than the field's and the out-lap on
newer ones, so the loss is net of both. The two partly cancel; what remains is about slope x
(in-lap age - 2 x field age), under a second for typical stints. The simulator applies this loss on
top of its own tyre model, so the out-lap's fresh-tyre gain is counted once there and only
approximately removed here.

The loss splits into pit-lane transit (deterministic per track) and stationary time (a fat-tailed
distribution of the crews' work). OpenF1 reports stationary time from mid-2024 only.
"""

import numpy as np
import pandas as pd

from pitwall.config import PitLossConfig
from pitwall.ingest.storage import RaceTables


def _condition(found: set) -> str | None:
    """A stop's track condition from its in- and out-lap. A red flag is a free tyre change, not a
    pit stop; a stop that saw a safety car on either lap is a safety-car stop."""
    if "RED" in found:
        return None
    return "SC" if "SC" in found else "VSC" if "VSC" in found else "GREEN"


def stop_losses(tables: RaceTables, config: PitLossConfig) -> pd.DataFrame:
    """One row per tyre stop of one race whose loss can be measured."""
    columns = ["track", "driver", "team_id", "lap", "condition", "lane_s", "stop_s", "loss_s"]
    laps, pits = tables.laps, tables.pits
    if pits.empty:
        return pd.DataFrame(columns=columns)
    times = laps.pivot(index="lap", columns="driver", values="lap_time_s")
    normal = laps[~laps["pit_in"] & ~laps["pit_out"] & (laps["lap"] > 1)]
    field = normal.groupby("lap")["lap_time_s"].agg(["median", "count"])
    field = field.loc[field["count"] >= config.min_field_cars, "median"]
    clean = laps[laps["lap_class"] == "clean"].join(field.rename("field"), on="lap")
    gap = (clean["lap_time_s"] - clean["field"]).groupby(clean["driver"]).median()
    by_lap = laps.set_index(["driver", "lap"])
    max_lane = config.max_lane_factor * pits["lane_s"].median()

    rows = []
    for stop in pits.to_dict("records"):
        driver, lap, lane_s = str(stop["driver"]), int(stop["lap"]), float(stop["lane_s"])
        in_lap, out_lap = (driver, lap), (driver, lap + 1)
        if out_lap not in by_lap.index or in_lap not in by_lap.index:
            continue
        if by_lap.loc[in_lap, "stint"] == by_lap.loc[out_lap, "stint"]:
            continue  # no tyre change: drive-through, repair or retirement
        condition = _condition(
            {by_lap.loc[in_lap, "track_status"], by_lap.loc[out_lap, "track_status"]}
        )
        reference = field.reindex([lap, lap + 1])
        if (
            condition is None
            or driver not in gap.index
            or reference.isna().any()
            or not lane_s <= max_lane
        ):
            continue
        took = times.loc[[lap, lap + 1], driver].sum()
        rows.append(
            {
                "track": tables.event.circuit_key,
                "driver": driver,
                "team_id": by_lap.loc[in_lap, "team_id"],
                "lap": lap,
                "condition": condition,
                "lane_s": lane_s,
                "stop_s": stop["stop_s"],
                "loss_s": took - reference.sum() - 2 * gap[driver],
            }
        )
    return pd.DataFrame(rows, columns=columns)


def track_losses(stops: pd.DataFrame) -> pd.DataFrame:
    """Per track: median green loss, its transit part (loss minus stationary time, where OpenF1
    has it) and the number of green stops."""
    green = stops[stops["condition"] == "GREEN"]
    timed = green.dropna(subset=["stop_s"])
    return pd.DataFrame(
        {
            "green_loss_s": green.groupby("track")["loss_s"].median(),
            "transit_s": (timed["loss_s"] - timed["stop_s"]).groupby(timed["track"]).median(),
            "stops": green.groupby("track").size(),
        }
    )


def condition_factors(stops: pd.DataFrame) -> dict[str, float]:
    """Loss under SC and VSC as a fraction of the same track's median green loss, pooled over
    tracks (median of per-stop ratios). Pass one era's stops: the factors differ by era."""
    green = stops[stops["condition"] == "GREEN"].groupby("track")["loss_s"].median()
    ratio = stops["loss_s"] / stops["track"].map(green)
    return {kind: float(ratio[stops["condition"] == kind].median()) for kind in ("SC", "VSC")}


def neutralised_pace(tables: RaceTables) -> pd.DataFrame:
    """Lap time under SC and VSC relative to the race's median clean lap, for cars not pitting."""
    laps = tables.laps
    clean = laps.loc[laps["lap_class"] == "clean", "lap_time_s"].median()
    running = laps[~laps["pit_in"] & ~laps["pit_out"] & laps["track_status"].isin(["SC", "VSC"])]
    return pd.DataFrame(
        {"kind": running["track_status"], "factor": running["lap_time_s"].to_numpy() / clean}
    )


def stationary_times(stops: pd.DataFrame) -> np.ndarray:
    """Every measured stationary time: the empirical distribution keeps the slow-stop tail."""
    return np.sort(stops["stop_s"].dropna().to_numpy())
