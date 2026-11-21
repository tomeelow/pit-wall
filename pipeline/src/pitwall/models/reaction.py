"""Stops brought forward by a safety car or VSC (ADR-004, as amended).

When a neutralisation starts, a car with a stop still to make may take it at once, while the stop
is cheap. P(it does) = logistic(intercept[kind] + tyre_age_per_10 * age / 10
+ race_left * share of the race left), per era. Fitted on every SC and VSC in the era's dry races
after lap 1, on the cars running at its first lap that made another stop: the outcome is whether
that stop came on its first `window_laps` laps.

Uncertainty: each draw is the penalised maximum-likelihood fit on a bootstrap resample of races
(the prior is the penalty). A race's draws come from the era's other races only: the reaction is to
random events, and the information-set rule keeps those out of their own race.
"""

import numpy as np
import pandas as pd

from pitwall.config import ReactionConfig
from pitwall.ingest.storage import RaceTables

KINDS = ("SC", "VSC")
COLUMNS = ("intercept_sc", "intercept_vsc", "tyre_age_per_10", "race_left")


def reaction_rows(tables: RaceTables, window_laps: int) -> pd.DataFrame:
    """One row per car running at the first lap of an SC or VSC with a stop still to make:
    kind, tyre_age, race_left, stopped."""
    laps = tables.laps
    if laps["compound_c"].isna().any():  # wet or mixed: other reasons to stop
        return pd.DataFrame(columns=["kind", "tyre_age", "race_left", "stopped"])
    total = tables.event.total_laps
    pits = laps[laps["pit_in"].astype(bool)]
    pit_laps = {str(d): g["lap"].to_numpy() for d, g in pits.groupby("driver")}
    rows = []
    for period in tables.neutralisations.to_dict("records"):
        start = int(period["start_lap"])
        if period["kind"] not in KINDS or start < 2:
            continue
        last = min(int(period["end_lap"]), start + window_laps - 1)
        for car in laps[laps["lap"] == start].to_dict("records"):
            mine = pit_laps.get(str(car["driver"]), np.array([], dtype=int))
            later = mine[mine >= start]
            if later.size == 0:
                continue
            rows.append(
                {
                    "kind": period["kind"],
                    "tyre_age": int(car["tyre_age"]),
                    "race_left": (total - start) / total,
                    "stopped": bool(later.min() <= last),
                }
            )
    return pd.DataFrame(rows, columns=["kind", "tyre_age", "race_left", "stopped"])


def design(rows: pd.DataFrame) -> np.ndarray:
    return np.column_stack(
        [
            (rows["kind"] == "SC").to_numpy(float),
            (rows["kind"] == "VSC").to_numpy(float),
            rows["tyre_age"].to_numpy(float) / 10,
            rows["race_left"].to_numpy(float),
        ]
    )


def fit_logistic(x: np.ndarray, y: np.ndarray, prior_sd: float, iterations: int = 50) -> np.ndarray:
    """Penalised maximum likelihood (Normal(0, prior_sd) on every coefficient), Newton steps."""
    beta = np.zeros(x.shape[1])
    penalty = np.eye(x.shape[1]) / prior_sd**2
    for _ in range(iterations):
        p = 1 / (1 + np.exp(-x @ beta))
        gradient = x.T @ (y - p) - penalty @ beta
        hessian = x.T @ (x * (p * (1 - p))[:, None]) + penalty
        step = np.linalg.solve(hessian, gradient)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    return beta


def draws(
    rows: pd.DataFrame, config: ReactionConfig, n: int, rng: np.random.Generator
) -> pd.DataFrame:
    """n draws of the coefficients: fits on bootstrap resamples of races (rows carry `race`)."""
    race_of = rows["race"].to_numpy()
    races = np.unique(race_of)
    groups = {race: np.flatnonzero(race_of == race) for race in races}
    x, y = design(rows), rows["stopped"].to_numpy(float)
    out = []
    for _ in range(n):
        index = np.concatenate([groups[r] for r in rng.choice(races, size=len(races))])
        out.append(fit_logistic(x[index], y[index], config.prior_sd))
    return pd.DataFrame(out, columns=list(COLUMNS))
