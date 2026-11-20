"""Hierarchical tyre degradation, fitted per regulation era (ADR-002, plan Phase 3).

    lap_time - race_median = level[race] + pace[race, driver] + offset[race, C]
                             + slope[track, C, team] * tyre_age + fuel_effect * fuel_kg(lap)
                             + StudentT(nu, 0, noise[race])

    slope[track, C, team] = slope[track, C] + team deviation (sd team_sd)
    slope[track, C]       = slope[C] + track deviation (sd track_sd)

Track deviations sum to zero within each C-number, team deviations within each track and
C-number, so `slope[C]` is the average over the tracks the era raced that C-number on.

Fuel burn-off and track evolution move together with every lap and are not separately
identified: `fuel_effect` absorbs both. Tyre wear is separable from them only because tyre age
resets at each stop while the race lap does not.

Offsets are relative: they sum to zero across C-numbers in the era, and each race's deviations sum
to zero across the C-numbers it used. A race's overall level lives in `level`, and drivers spread
around it in `pace`. Without that split the level leaks into the offsets: the C-number with the
fewest laps absorbs it (2025 Monaco's C6 took +9 s).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import nutpie
import pandas as pd
import pymc as pm
import xarray as xr
from pydantic import BaseModel

from pitwall.config import DegradationConfig, Era, NormalPrior
from pitwall.ingest.storage import RaceTables, dataset_fingerprint
from pitwall.models.sampling import Diagnostics, sample, zero_sum_deviation

GROUPS: dict[str, tuple[str, ...]] = {
    "c": ("compound_c",),
    "race": ("race",),
    "race_driver": ("race", "driver"),
    "race_c": ("race", "compound_c"),
    "track_c": ("track", "compound_c"),
    "track_c_team": ("track", "compound_c", "team"),
}
AGE_BINS = [0, 5, 10, 15, 20, 30, 100]


def race_id(season: int, round_: int) -> str:
    return f"{season}-{round_:02d}"


def fuel_kg(lap: pd.Series, total_laps: int, race_fuel_kg: float) -> pd.Series:
    """Fuel on board at mid-lap, burning linearly over the scheduled distance."""
    return race_fuel_kg * (1 - (lap - 0.5) / total_laps)


def training_laps(races: list[RaceTables], era: Era) -> pd.DataFrame:
    """Clean laps of the era's races, with the covariates the model uses."""
    frames = []
    for tables in races:
        if tables.event.season not in era.seasons:
            raise ValueError(f"{tables.event.season} R{tables.event.round} is not in {era.name}")
        laps = tables.laps[tables.laps["lap_class"] == "clean"]
        if laps.empty:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "race": race_id(tables.event.season, tables.event.round),
                    "track": tables.event.circuit_key,
                    "driver": laps["driver"].astype(str),
                    "team": laps["team_id"].astype(str),
                    "stint": laps["stint"].astype("int64"),
                    "compound_c": laps["compound_c"].astype("int64"),
                    "lap": laps["lap"].astype("int64"),
                    "tyre_age": laps["tyre_age"].astype("int64"),
                    "lap_time_s": laps["lap_time_s"],
                    "fuel_kg": fuel_kg(laps["lap"], tables.event.total_laps, era.race_fuel_kg),
                    "race_median_s": laps["lap_time_s"].median(),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def drop_sparse_compounds(laps: pd.DataFrame, min_races: int) -> tuple[pd.DataFrame, list[int]]:
    """Laps on C-numbers raced in at least `min_races` races, and the C-numbers left out."""
    races = laps.groupby("compound_c")["race"].nunique()
    sparse = sorted(int(c) for c in races.index[races < min_races])
    kept = laps[~laps["compound_c"].isin(sparse)].reset_index(drop=True)
    return kept, sparse


@dataclass(frozen=True)
class Groups:
    """Every group the model has a parameter for (`positions`: key → parameter position) and
    each training lap's position in them (`codes`)."""

    positions: dict[str, dict[tuple, int]]
    codes: dict[str, np.ndarray]

    @classmethod
    def of(cls, laps: pd.DataFrame) -> "Groups":
        positions: dict[str, dict[tuple, int]] = {}
        codes = {}
        for name, columns in GROUPS.items():
            found: dict[tuple, int] = {}
            keys = laps[list(columns)].itertuples(index=False, name=None)
            codes[name] = np.array([found.setdefault(key, len(found)) for key in keys])
            positions[name] = found
        return cls(positions, codes)

    def find(self, name: str, *key: object) -> int | None:
        return self.positions[name].get(key)

    def keys(self, name: str) -> list[tuple]:
        return list(self.positions[name])

    def parent(self, child: str, parent: str) -> np.ndarray:
        """Position of each `child` group's parent group."""
        columns = [GROUPS[child].index(column) for column in GROUPS[parent]]
        lookup = self.positions[parent]
        return np.array([lookup[tuple(key[i] for i in columns)] for key in self.positions[child]])

    def coords(self) -> dict[str, range]:
        return {name: range(len(found)) for name, found in self.positions.items()}


def build_model(
    laps: pd.DataFrame, groups: Groups, config: DegradationConfig, fuel: NormalPrior
) -> pm.Model:
    p, g = config.priors, groups
    with pm.Model(coords=g.coords()) as model:
        fuel_effect = pm.Normal("fuel_effect", fuel.mean, fuel.sd)

        slope_c = pm.Normal("slope_c", p.slope_s_per_lap.mean, p.slope_s_per_lap.sd, dims="c")
        track_sd = pm.HalfNormal("slope_track_sd", p.slope_track_sd)
        team_sd = pm.HalfNormal("slope_team_sd", p.slope_team_sd)
        track_of = g.parent("track_c", "c")
        slope_track = slope_c[track_of] + zero_sum_deviation(
            "slope_track_z", track_sd, track_of, len(g.positions["c"])
        )
        team_of = g.parent("track_c_team", "track_c")
        slope_team = slope_track[team_of] + zero_sum_deviation(
            "slope_team_z", team_sd, team_of, len(g.positions["track_c"])
        )
        pm.Deterministic("slope_track", slope_track, dims="track_c")
        pm.Deterministic("slope_team", slope_team, dims="track_c_team")

        offset_c = pm.ZeroSumNormal("offset_c", p.compound_offset_sd, dims="c")
        offset_race_sd = pm.HalfNormal("offset_race_sd", p.compound_track_sd)
        deviation = zero_sum_deviation(
            "offset_race_z", offset_race_sd, g.parent("race_c", "race"), len(g.positions["race"])
        )
        offset_race = offset_c[g.parent("race_c", "c")] + deviation
        pm.Deterministic("offset_race", offset_race, dims="race_c")

        level = pm.Normal("level", 0, p.race_level_sd, dims="race")
        pace_sd = pm.HalfNormal("pace_sd", p.pace_sd)
        pace = pm.Normal("pace", 0, pace_sd, dims="race_driver")
        noise = pm.HalfNormal("noise_sd", p.noise_sd, dims="race")
        nu = pm.Gamma("nu", 2, 0.1)

        mu = (
            level[g.codes["race"]]
            + pace[g.codes["race_driver"]]
            + offset_race[g.codes["race_c"]]
            + slope_team[g.codes["track_c_team"]] * laps["tyre_age"].to_numpy()
            + fuel_effect * laps["fuel_kg"].to_numpy()
        )
        pm.StudentT(
            "lap_time",
            nu=nu,
            mu=mu,
            sigma=noise[g.codes["race"]],
            observed=(laps["lap_time_s"] - laps["race_median_s"]).to_numpy(),
        )
    return model


@dataclass(frozen=True)
class Fit:
    era: Era
    laps: pd.DataFrame
    groups: Groups
    posterior: xr.Dataset  # dims: (sample, group)
    diagnostics: Diagnostics
    passed: bool

    @property
    def samples(self) -> int:
        return self.posterior.sizes["sample"]

    def _draws(self, name: str, position: int) -> np.ndarray:
        return self.posterior[name].isel({self.posterior[name].dims[-1]: position}).to_numpy()

    def _scalar(self, name: str) -> np.ndarray:
        return self.posterior[name].to_numpy()

    def slope(self, track: int, c: int, team: str, rng: np.random.Generator) -> np.ndarray:
        """Degradation draws (s/lap) for a team on a C-number at a track. A group the fit has not
        seen gets a fresh draw from its parent's distribution, so unseen means wider."""
        g = self.groups
        if (i := g.find("track_c_team", track, c, team)) is not None:
            return self._draws("slope_team", i)
        team_noise = self._scalar("slope_team_sd") * rng.standard_normal(self.samples)
        if (i := g.find("track_c", track, c)) is not None:
            return self._draws("slope_track", i) + team_noise
        track_noise = self._scalar("slope_track_sd") * rng.standard_normal(self.samples)
        return self._draws("slope_c", self._compound(c)) + track_noise + team_noise

    def offset(self, race: str, c: int, rng: np.random.Generator) -> np.ndarray:
        if (i := self.groups.find("race_c", race, c)) is not None:
            return self._draws("offset_race", i)
        noise = self._scalar("offset_race_sd") * rng.standard_normal(self.samples)
        return self._draws("offset_c", self._compound(c)) + noise

    def pace(self, race: str, driver: str) -> np.ndarray | None:
        """A driver's pace relative to the race's median clean lap: race level plus their own."""
        i = self.groups.find("race_driver", race, driver)
        if i is None:
            return None
        return self._draws("level", self.groups.positions["race"][(race,)]) + self._draws("pace", i)

    def covers(self, c: int) -> bool:
        return self.groups.find("c", c) is not None

    def _compound(self, c: int) -> int:
        if (i := self.groups.find("c", c)) is None:
            raise KeyError(f"C{c} has no clean laps in era {self.era.name}")
        return i

    def fitted(self) -> np.ndarray:
        """Posterior-mean lap time of every training lap (the model is linear in parameters)."""
        mean = self.posterior.mean("sample")
        codes, laps = self.groups.codes, self.laps
        return (
            laps["race_median_s"].to_numpy()
            + mean["level"].to_numpy()[codes["race"]]
            + mean["pace"].to_numpy()[codes["race_driver"]]
            + mean["offset_race"].to_numpy()[codes["race_c"]]
            + mean["slope_team"].to_numpy()[codes["track_c_team"]] * laps["tyre_age"].to_numpy()
            + float(mean["fuel_effect"]) * laps["fuel_kg"].to_numpy()
        )


def fit(laps: pd.DataFrame, era: Era, config: DegradationConfig, fuel: NormalPrior) -> Fit:
    groups = Groups.of(laps)
    model = build_model(laps, groups, config, fuel)
    posterior, diagnostics = sample(nutpie.compile_pymc_model(model), config.sampler)
    return Fit(era, laps, groups, posterior, diagnostics, diagnostics.passes(config.gate))


def residuals_by_age(fit: Fit) -> pd.DataFrame:
    """Median residual by C-number and tyre-age bin: systematic curvature on long stints is the
    evidence a cliff or quadratic term would need. Median, because the noise is heavy-tailed."""
    laps = fit.laps.assign(residual=fit.laps["lap_time_s"] - fit.fitted())
    laps["age_bin"] = pd.cut(laps["tyre_age"], AGE_BINS).astype(str)
    return (
        laps.groupby(["compound_c", "age_bin"], observed=True)["residual"]
        .agg(laps="size", median_s="median")
        .reset_index()
    )


def race_draws(
    fit: Fit,
    tables: RaceTables,
    compounds: list[int],
    n: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """`n` posterior draws of every parameter the simulator needs for one race: per driver and
    allocated C-number. Drivers without a clean lap have no pace, and C-numbers the era's fit
    does not cover have no parameters: both are left out."""
    race = race_id(tables.event.season, tables.event.round)
    picks = np.linspace(0, fit.samples - 1, n).round().astype(int)
    race_laps = fit.laps[fit.laps["race"] == race]
    shared = {
        "draw": np.arange(n),
        "fuel_s_per_kg": fit._scalar("fuel_effect")[picks],
        "nu": fit._scalar("nu")[picks],
        "race_median_s": race_laps["race_median_s"].iloc[0],
        "race_fuel_kg": fit.era.race_fuel_kg,
    }
    noise = fit._draws("noise_sd", fit.groups.positions["race"][(race,)])[picks]
    rows = []
    for driver, team in tables.results[["driver", "team_id"]].itertuples(index=False):
        pace = fit.pace(race, driver)
        if pace is None:
            continue
        for c in filter(fit.covers, compounds):
            rows.append(
                pd.DataFrame(
                    shared
                    | {
                        "driver": driver,
                        "team_id": team,
                        "compound_c": c,
                        "pace_s": pace[picks],
                        "offset_s": fit.offset(race, c, rng)[picks],
                        "slope_s_per_lap": fit.slope(tables.event.circuit_key, c, team, rng)[picks],
                        "noise_sd_s": noise,
                    }
                )
            )
    return pd.concat(rows, ignore_index=True)


class AgeResidual(BaseModel):
    compound_c: int
    age_bin: str
    laps: int
    median_s: float


class Summary(BaseModel):
    mean: float
    q05: float
    q95: float


class ModelCard(BaseModel):
    era: str
    dataset_version: str
    git_sha: str
    fitted_at: datetime
    races: int
    laps: int
    excluded_compounds: list[int]
    diagnostics: Diagnostics
    passed: bool
    fuel_effect_s_per_kg: Summary
    slope_s_per_lap: dict[str, Summary]
    residuals_by_age: list[AgeResidual]


def model_card(fit: Fit, git_sha: str, excluded_compounds: list[int]) -> ModelCard:
    def summary(values: np.ndarray) -> Summary:
        q05, q95 = np.quantile(values, [0.05, 0.95])
        return Summary(mean=round(float(values.mean()), 4), q05=round(q05, 4), q95=round(q95, 4))

    return ModelCard(
        era=fit.era.name,
        dataset_version=dataset_fingerprint(fit.laps),
        git_sha=git_sha,
        fitted_at=datetime.now(UTC),
        races=fit.laps["race"].nunique(),
        laps=len(fit.laps),
        excluded_compounds=excluded_compounds,
        diagnostics=fit.diagnostics,
        passed=fit.passed,
        fuel_effect_s_per_kg=summary(fit._scalar("fuel_effect")),
        slope_s_per_lap={
            f"C{c}": summary(fit._draws("slope_c", i))
            for (c,), i in fit.groups.positions["c"].items()
        },
        residuals_by_age=[
            AgeResidual(compound_c=c, age_bin=b, laps=n, median_s=round(m, 3))
            for c, b, n, m in residuals_by_age(fit).itertuples(index=False)
        ],
    )
