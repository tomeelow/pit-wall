"""Tyre warm-up: extra time on the first laps of a stint, per era, C-number and lap of the stint
(plan Phase 8).

The degradation model is linear in tyre age and fitted on clean laps, so it misses what a set does
while it comes in. Two sources, both measured against the degradation fit's free-air prediction:
- stint lap 1, the out-lap: green out-laps only. The pit loss (Phase 4) already holds the average
  out-lap, so each out-lap is centred on its race's median out-lap. That also cancels the pit-exit
  time, which is per track. What remains is how much slower or faster this C-number's out-lap is.
- stint laps 2 .. `stint_laps`: the residual of clean laps.

Each cell is the median over the era's laps; a cell with fewer than `min_laps` laps is 0 (no
evidence of a difference). Uncertainty comes from a bootstrap over races, one resample per draw.
Fitted on every race, the race simulated included: the documented pace softening.
"""

import numpy as np
import pandas as pd
from pydantic import BaseModel

from pitwall.config import WarmupConfig
from pitwall.ingest.storage import RaceTables
from pitwall.models.traffic import predicted_laps


def warmup_laps(tables: RaceTables, draws: pd.DataFrame, stint_laps: int) -> pd.DataFrame:
    """The race's laps that measure warm-up: compound_c, stint_lap and residual_s."""
    laps = tables.laps.assign(residual_s=tables.laps["lap_time_s"] - predicted_laps(tables, draws))
    first = laps.groupby(["driver", "stint"])["lap"].transform("min")
    laps = laps.assign(stint_lap=laps["lap"] - first + 1).dropna(subset=["residual_s"])
    out = laps[
        (laps["lap_class"] == "out_lap") & (laps["track_status"] == "GREEN") & (laps["lap"] > 1)
    ]
    out = out.assign(residual_s=out["residual_s"] - out["residual_s"].median(), stint_lap=1)
    early = laps[(laps["lap_class"] == "clean") & laps["stint_lap"].between(2, stint_laps)]
    columns = ["compound_c", "stint_lap", "residual_s"]
    return pd.concat([out[columns], early[columns]], ignore_index=True).astype(
        {"compound_c": int, "stint_lap": int}
    )


def _cells(laps: pd.DataFrame, min_laps: int) -> pd.Series:
    grouped = laps.groupby(["compound_c", "stint_lap"])["residual_s"]
    return grouped.median().where(grouped.size() >= min_laps, 0.0)


def fit(laps: pd.DataFrame, config: WarmupConfig) -> pd.DataFrame:
    """Bootstrap draws of one era's warm-up from its laps (with a `race` column): draw,
    compound_c, stint_lap, warmup_s, for every C-number in the laps and every stint lap."""
    races = laps["race"].unique()
    by_race = {race: group for race, group in laps.groupby("race")}
    index = pd.MultiIndex.from_product(
        [sorted(laps["compound_c"].unique()), range(1, config.stint_laps + 1)],
        names=["compound_c", "stint_lap"],
    )
    rng = np.random.default_rng(config.seed)
    frames = []
    for d in range(config.draws):
        sample = pd.concat([by_race[r] for r in rng.choice(races, size=len(races))])
        cells = _cells(sample, config.min_laps).reindex(index, fill_value=0.0)
        frames.append(cells.rename("warmup_s").reset_index().assign(draw=d))
    return pd.concat(frames, ignore_index=True)[["draw", "compound_c", "stint_lap", "warmup_s"]]


class Cell(BaseModel):
    compound_c: int
    stint_lap: int
    laps: int
    median_s: float
    p05_s: float
    p95_s: float


class ModelCard(BaseModel):
    era: str
    races: int
    git_sha: str
    cells: list[Cell]


def model_card(era: str, laps: pd.DataFrame, draws: pd.DataFrame, git_sha: str) -> ModelCard:
    counts = laps.groupby(["compound_c", "stint_lap"]).size()
    spread = draws.groupby(["compound_c", "stint_lap"])["warmup_s"]
    summary = pd.DataFrame(
        {"median": spread.median(), "p05": spread.quantile(0.05), "p95": spread.quantile(0.95)}
    )
    return ModelCard(
        era=era,
        races=laps["race"].nunique(),
        git_sha=git_sha,
        cells=[
            Cell(
                compound_c=int(row["compound_c"]),
                stint_lap=int(row["stint_lap"]),
                laps=int(counts.get((row["compound_c"], row["stint_lap"]), 0)),
                median_s=round(float(row["median"]), 3),
                p05_s=round(float(row["p05"]), 3),
                p95_s=round(float(row["p95"]), 3),
            )
            for row in summary.reset_index().to_dict("records")
        ],
    )
