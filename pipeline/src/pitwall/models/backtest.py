"""Leave-one-race-out backtest of the degradation model against two baselines (plan Phase 3).

Each held-out stint is a forecast, as on the pit wall: every method sees only the stint's first
`anchor_laps` clean laps and predicts the rest. The model brings what it learned from other races
(degradation, fuel); the level comes from the anchor laps.

- `median`: the anchor laps' median, held flat.
- `ols`: a straight line through the anchor laps (lap time on lap number), extrapolated.
- `model`: posterior-mean of anchor level + slope * tyre_age + fuel_effect * fuel_kg.
"""

import numpy as np
import pandas as pd

from pitwall.config import BacktestConfig
from pitwall.models.degradation import Fit

METHODS = ("median", "ols", "model")
HORIZONS = [0, 5, 10, 20, 100]


def _shape(laps: pd.DataFrame, slope: np.ndarray, fuel: np.ndarray) -> np.ndarray:
    """(draws, laps): the part of each lap time the model predicts beyond the stint's level."""
    age, kg = laps["tyre_age"].to_numpy(), laps["fuel_kg"].to_numpy()
    return slope[:, None] * age + fuel[:, None] * kg


def forecast_stints(
    held_out: pd.DataFrame, fit: Fit, config: BacktestConfig, rng: np.random.Generator
) -> pd.DataFrame:
    """One row per forecast lap of every held-out stint long enough to forecast.

    `held_out` is one race's `training_laps`; `fit` must not have seen that race. Stints on a
    C-number the fit does not cover are not forecast."""
    if held_out["race"].isin(fit.laps["race"]).any():
        raise ValueError("the fit has seen the held-out race")
    fuel = fit.posterior["fuel_effect"].to_numpy()
    rows = []
    for (driver, stint), laps in held_out.groupby(["driver", "stint"]):
        laps = laps.sort_values("lap")
        anchor, target = laps.iloc[: config.anchor_laps], laps.iloc[config.anchor_laps :]
        first = laps.iloc[0]
        if len(target) < config.min_forecast_laps or not fit.covers(int(first["compound_c"])):
            continue
        slope = fit.slope(int(first["track"]), int(first["compound_c"]), first["team"], rng)
        level = (anchor["lap_time_s"].to_numpy() - _shape(anchor, slope, fuel)).mean(axis=1)
        ols = np.polynomial.Polynomial.fit(anchor["lap"], anchor["lap_time_s"], 1)
        rows.append(
            pd.DataFrame(
                {
                    "race": first["race"],
                    "driver": driver,
                    "stint": stint,
                    "compound_c": first["compound_c"],
                    "lap": target["lap"].to_numpy(),
                    "laps_ahead": target["lap"].to_numpy() - anchor["lap"].iloc[-1],
                    "actual": target["lap_time_s"].to_numpy(),
                    "median": anchor["lap_time_s"].median(),
                    "ols": ols(target["lap"].to_numpy()),
                    "model": (level[:, None] + _shape(target, slope, fuel)).mean(axis=0),
                }
            )
        )
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def score(forecasts: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """MAE and RMSE (s) per method, overall or per group."""
    errors = forecasts.assign(
        **{m: forecasts[m] - forecasts["actual"] for m in METHODS},
        horizon=pd.cut(forecasts["laps_ahead"], HORIZONS),
        all="all",
    )
    grouped = errors.groupby(by or ["all"], observed=True)
    table = pd.concat(
        {
            **{f"mae_{m}": grouped[m].apply(lambda e: e.abs().mean()) for m in METHODS},
            **{f"rmse_{m}": grouped[m].apply(lambda e: np.sqrt((e**2).mean())) for m in METHODS},
            "laps": grouped.size(),
        },
        axis=1,
    )
    return table.round(3)
