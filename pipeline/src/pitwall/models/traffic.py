"""Traffic: time lost following another car, and the chance of passing it (plan Phase 5).

Both are learned from pairs: a car and the car directly ahead of it in the running order at the
start of a lap, on the same lap. A pair's lap is usable when it can only be decided on track:
neither car pits, retires or starts the race on it, and the lap is green, dry and has no yellow.
Position changes from pit cycles, retirements and penalties never enter the data.

Pace comes from the degradation model's exported draws (posterior means): the free-air lap time
the simulator would give that car on that lap.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import nutpie
import pandas as pd
import pymc as pm
import pytensor.tensor as pt
import xarray as xr
from nutpie.compile_pymc import CompiledPyMCModel
from pydantic import BaseModel

from pitwall.config import TrafficConfig
from pitwall.ingest.storage import RaceTables, dataset_fingerprint
from pitwall.models.degradation import fuel_kg
from pitwall.models.sampling import Diagnostics, sample, zero_sum_deviation

# Lap classes on which a pass can only have happened on track, with nothing neutralising racing.
RACING = ("clean", "traffic", "outlier")


def predicted_laps(tables: RaceTables, draws: pd.DataFrame) -> pd.Series:
    """Free-air lap time of every lap in `tables.laps`; NaN where the degradation model has no
    parameters for the driver or the C-number."""
    terms = ["pace_s", "offset_s", "slope_s_per_lap"]
    means = draws.groupby(["driver", "compound_c"])[terms].mean()
    laps = tables.laps.join(means, on=["driver", "compound_c"])
    fuel = fuel_kg(laps["lap"], tables.event.total_laps, float(draws["race_fuel_kg"].iloc[0]))
    return (
        float(draws["race_median_s"].iloc[0])
        + laps["pace_s"]
        + laps["offset_s"]
        + laps["slope_s_per_lap"] * laps["tyre_age"]
        + float(draws["fuel_s_per_kg"].mean()) * fuel
    )


def lap_pairs(tables: RaceTables, predicted: pd.Series) -> pd.DataFrame:
    """One row per car per lap that started the lap directly behind another car on the same lap.

    gap_s: time behind that car at the start of the lap. pace_delta_s: how much faster the car
    behind is predicted to be on this lap (positive: faster). excess_s: the car behind's lap time
    over its own free-air prediction. passed: it was ahead at the end of the lap. usable: the lap
    could only be decided on track."""
    laps = tables.laps.assign(predicted=predicted)
    state = tables.race_state[["driver", "lap", "position", "interval_s"]]
    lap = laps.merge(state, on=["driver", "lap"], how="inner")
    lap["racing"] = lap["lap_class"].isin(RACING) & ~lap["pit_in"] & ~lap["pit_out"]
    lap["racing"] &= lap["track_status"] == "GREEN"

    start = state.assign(lap=state["lap"] + 1).rename(
        columns={"position": "start_position", "interval_s": "gap_s"}
    )
    behind = lap.merge(start, on=["driver", "lap"], how="inner")
    behind = behind[behind["start_position"] > 1]
    ahead_start = start[["driver", "lap", "start_position"]].rename(
        columns={"driver": "ahead", "start_position": "ahead_start"}
    )
    behind = behind.assign(ahead_start=behind["start_position"] - 1).merge(
        ahead_start, on=["lap", "ahead_start"], how="inner"
    )
    ahead_lap = lap[["driver", "lap", "position", "predicted", "racing"]].rename(
        columns={
            "driver": "ahead",
            "position": "ahead_position",
            "predicted": "ahead_predicted",
            "racing": "ahead_racing",
        }
    )
    pairs = behind.merge(ahead_lap, on=["ahead", "lap"], how="inner")
    return pd.DataFrame(
        {
            "track": tables.event.circuit_key,
            "lap": pairs["lap"],
            "driver": pairs["driver"],
            "ahead": pairs["ahead"],
            "gap_s": pairs["gap_s"],
            "pace_delta_s": pairs["ahead_predicted"] - pairs["predicted"],
            "excess_s": pairs["lap_time_s"] - pairs["predicted"],
            "passed": pairs["position"] < pairs["ahead_position"],
            "usable": pairs["racing"]
            & pairs["ahead_racing"]
            & (pairs["lap"] > 1)
            & pairs["gap_s"].notna()
            & pairs["predicted"].notna()
            & pairs["ahead_predicted"].notna(),
        }
    ).reset_index(drop=True)


def dirty_air(pairs: pd.DataFrame, bins: list[float]) -> pd.DataFrame:
    """Median time lost per lap by gap to the car ahead, from laps where that car is predicted to
    be at least as fast: then the car behind is not held up, and what it loses is the air."""
    free = pairs[pairs["usable"] & ~pairs["passed"] & (pairs["pace_delta_s"] <= 0)]
    gap = pd.cut(free["gap_s"], bins, include_lowest=True)
    table = free.groupby(gap, observed=True)["excess_s"].agg(loss_s="median", laps="size")
    table.index = pd.Index([interval.right for interval in table.index], name="gap_upto_s")
    return table.reset_index()


def reliability(predicted: np.ndarray, observed: np.ndarray, bins: list[float]) -> pd.DataFrame:
    """Calibration table: mean predicted probability vs observed frequency per probability bin."""
    frame = pd.DataFrame({"p": predicted, "y": observed.astype(float)})
    groups = frame.groupby(pd.cut(frame["p"], bins, include_lowest=True), observed=True)
    table = groups.agg(predicted=("p", "mean"), observed=("y", "mean"), laps=("y", "size"))
    table.index = table.index.astype(str)
    return table.round(4)


FEATURES = ("gap_s", "pace_delta_s", "within_drs")


def training_pairs(pairs: pd.DataFrame, config: TrafficConfig) -> pd.DataFrame:
    """Usable pairs close enough to be modelled, with the DRS / overtake-mode flag."""
    close = pairs[pairs["usable"] & (pairs["gap_s"] <= config.max_gap_s)]
    return close.assign(within_drs=(close["gap_s"] <= config.drs_gap_s).astype(float))


@dataclass(frozen=True)
class PassFit:
    eras: dict[str, int]
    tracks: dict[int, int]
    centre: np.ndarray  # feature means the model was fitted around
    posterior: xr.Dataset  # dims: (sample, ...)
    diagnostics: Diagnostics
    passed: bool

    @property
    def samples(self) -> int:
        return self.posterior.sizes["sample"]

    def terms(self, era: str, track: int, rng: np.random.Generator) -> pd.DataFrame:
        """Per draw: the logit at zero gap and equal pace for this track (an unseen track gets a
        fresh deviation), and the era's coefficient per feature."""
        e = self.eras[era]
        i = self.tracks.get(track)
        deviation = (
            self.posterior["track"].to_numpy()[:, i]
            if i is not None
            else self.posterior["track_sd"].to_numpy() * rng.standard_normal(self.samples)
        )
        beta = self.posterior["beta"].to_numpy()[:, e, :]
        intercept = self.posterior["intercept"].to_numpy()[:, e] - beta @ self.centre
        return pd.DataFrame(
            {"intercept": intercept + deviation}
            | {f"beta_{name}": beta[:, k] for k, name in enumerate(FEATURES)}
        )

    def probability(self, rows: pd.DataFrame, draws: int, rng: np.random.Generator) -> np.ndarray:
        """Posterior-mean pass probability of each row (era, track and features), over `draws`
        evenly spaced posterior draws."""
        picks = np.linspace(0, self.samples - 1, draws).round().astype(int)
        total = np.zeros(len(rows))
        for era, track in rows[["era", "track"]].drop_duplicates().itertuples(index=False):
            group = rows[(rows["era"] == era) & (rows["track"] == track)]
            terms = self.terms(str(era), int(track), rng).iloc[picks]
            x = group[list(FEATURES)].to_numpy(float)
            logit = (
                terms["intercept"].to_numpy()[:, None]
                + terms[[f"beta_{name}" for name in FEATURES]].to_numpy() @ x.T
            )
            total[rows.index.get_indexer(group.index)] = (1 / (1 + np.exp(-logit))).mean(axis=0)
        return total


class PassModel:
    """logit P(pass) = intercept[era] + track[track] + beta[era] . (features - centre).
    Compiled once; refitted with any rows given zero weight (their likelihood removed)."""

    def __init__(self, rows: pd.DataFrame, config: TrafficConfig) -> None:
        self.rows, self.config = rows.reset_index(drop=True), config
        self.eras = {e: i for i, e in enumerate(sorted(self.rows["era"].unique()))}
        self.tracks = {int(t): i for i, t in enumerate(sorted(self.rows["track"].unique()))}
        era = self.rows["era"].map(self.eras).to_numpy()
        track = self.rows["track"].map(self.tracks).to_numpy()
        x = self.rows[list(FEATURES)].to_numpy(float)
        # Centred, or the intercept (at zero gap) trades off with the gap and DRS coefficients.
        self.centre = x.mean(axis=0)
        x = x - self.centre
        prior = config.priors
        with pm.Model() as model:
            weight = pm.Data("weight", np.ones(len(self.rows)))
            intercept = pm.Normal(
                "intercept", prior.intercept.mean, prior.intercept.sd, shape=len(self.eras)
            )
            beta = pm.Normal("beta", 0, prior.coefficient_sd, shape=(len(self.eras), len(FEATURES)))
            track_sd = pm.HalfNormal("track_sd", prior.track_sd)
            # Track deviations sum to zero, or their mean trades off with the era intercepts.
            deviation = zero_sum_deviation(
                "track_z", track_sd, np.zeros(len(self.tracks), dtype=int), segments=1
            )
            pm.Deterministic("track", deviation)
            logit = intercept[era] + deviation[track] + (beta[era] * x).sum(axis=1)
            y = self.rows["passed"].to_numpy(float)
            # Bernoulli log-likelihood, weighted so that masked rows contribute nothing.
            pm.Potential("likelihood", (weight * (y * logit - pt.softplus(logit))).sum())
        compiled = nutpie.compile_pymc_model(model)
        assert isinstance(compiled, CompiledPyMCModel)  # the PyMC variant can swap data
        self.compiled = compiled

    def fit(self, masked: np.ndarray | None = None) -> PassFit:
        weight = np.ones(len(self.rows)) if masked is None else (~masked).astype(float)
        posterior, diagnostics = sample(self.compiled.with_data(weight=weight), self.config.sampler)
        return PassFit(
            self.eras,
            self.tracks,
            self.centre,
            posterior,
            diagnostics,
            diagnostics.passes(self.config.gate),
        )


def gap_baseline(train: pd.DataFrame, rows: pd.DataFrame, bins: list[float]) -> np.ndarray:
    """Baseline pass probability: the training pass rate in the row's era and gap bin."""

    def gap(frame: pd.DataFrame) -> pd.Series:
        return pd.cut(frame["gap_s"], bins, include_lowest=True)

    rate = train.groupby(["era", gap(train)], observed=True)["passed"].mean()
    keys = pd.MultiIndex.from_arrays([rows["era"], gap(rows)])
    return rate.reindex(keys).to_numpy(float)


def validate_season(
    model: PassModel, season: np.ndarray, rng: np.random.Generator, draws: int
) -> tuple[pd.DataFrame, PassFit]:
    """Fit without the rows flagged in `season`; predict them with the model and the baseline."""
    fit = model.fit(season)
    held = model.rows[season]
    bins = model.config.dirty_air_bins
    predictions = held.assign(
        model=fit.probability(held, draws, rng),
        baseline=gap_baseline(model.rows[~season], held, bins),
    )
    return predictions, fit


def scores(predictions: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Log loss and Brier score, model against baseline, overall or per group. Lower is better."""
    y = predictions["passed"].astype(float)
    frame = predictions.assign(all="all")
    for column in ("model", "baseline"):
        p = predictions[column].clip(1e-6, 1 - 1e-6)
        frame[f"log_loss_{column}"] = -(y * np.log(p) + (1 - y) * np.log(1 - p))
        frame[f"brier_{column}"] = (p - y) ** 2
    grouped = frame.groupby(by or ["all"], observed=True)
    columns = ["log_loss_model", "log_loss_baseline", "brier_model", "brier_baseline"]
    table = grouped[columns].mean()
    table["passes"] = grouped["passed"].sum()
    table["expected_model"] = grouped["model"].sum()
    table["laps"] = grouped.size()
    return table.round(4)


class DirtyAir(BaseModel):
    gap_upto_s: float
    loss_s: float
    laps: int


class RaceTraffic(BaseModel):
    """What the simulator needs besides the pass-model draws."""

    max_gap_s: float
    drs_gap_s: float
    dirty_air: list[DirtyAir]


class TrafficCard(BaseModel):
    dataset_version: str
    git_sha: str
    fitted_at: datetime
    pairs: int
    passes: int
    diagnostics: Diagnostics
    passed: bool
    # Per era: mean and 90 % interval of each coefficient, on the original feature scale.
    coefficients: dict[str, dict[str, list[float]]]
    track_logit: dict[str, float]  # circuit: posterior-mean deviation from its era
    dirty_air: dict[str, list[DirtyAir]]


def dirty_air_table(pairs: pd.DataFrame, bins: list[float]) -> list[DirtyAir]:
    return [
        DirtyAir(gap_upto_s=float(g), loss_s=round(float(loss), 3), laps=int(n))
        for g, loss, n in dirty_air(pairs, bins).itertuples(index=False)
    ]


def model_card(
    fit: PassFit, rows: pd.DataFrame, pairs: pd.DataFrame, config: TrafficConfig, git_sha: str
) -> TrafficCard:
    rng = np.random.default_rng(0)
    coefficients = {}
    for era in fit.eras:
        terms = fit.terms(era, -1, rng)  # an unseen track: the era's own level
        coefficients[era] = {
            name: [round(float(v), 3) for v in (draws.mean(), *np.quantile(draws, [0.05, 0.95]))]
            for name, draws in terms.items()
        }
    names = rows.groupby("track")["circuit"].first()
    track = fit.posterior["track"].mean("sample").to_numpy()
    return TrafficCard(
        dataset_version=dataset_fingerprint(rows),
        git_sha=git_sha,
        fitted_at=datetime.now(UTC),
        pairs=len(rows),
        passes=int(rows["passed"].sum()),
        diagnostics=fit.diagnostics,
        passed=fit.passed,
        coefficients=coefficients,
        track_logit={
            str(names[t]): round(float(track[i]), 3)
            for t, i in sorted(fit.tracks.items(), key=lambda item: track[item[1]])
        },
        dirty_air={
            str(era): dirty_air_table(group, config.dirty_air_bins)
            for era, group in pairs.groupby("era")
        },
    )
