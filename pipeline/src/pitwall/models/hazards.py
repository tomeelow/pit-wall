"""Rates of random race events: safety car, VSC, red flag and retirement (plan Phase 4).

    events ~ Poisson(exposure * exp(base[era, family] + unit_sd[family] * z[unit, family]
                                    + position[era] * position))

A family is an event kind in one phase. `lap1` counts events that start on the opening lap
(exposure: one per race, or one per car for retirements); `running` counts events that start
later (exposure: laps at risk). Units are tracks for neutralisations and teams for retirements.
`position` is where a car runs, from the front of the running order (-0.5) to the back (+0.5),
for later retirements only (0 elsewhere): cars in the pack collide more than cars in front, which
a team's rate alone cannot tell apart. A team's rate is then its rate in mid-field. A lap is placed
by where the car ran a few laps before it (`lag`): a car about to retire often drops back first,
and that would credit its fall to the position it fell to.
OpenF1 starts in 2023, so a track has only three or four races: its rate is pulled towards its
era's, and an unseen track or team gets a fresh deviation, which makes its rate wider.

The information-set rule applies: a race's simulation must not learn from its own safety cars or
retirements, so the rates exported for a race come from a fit with that race masked out.
"""

from dataclasses import dataclass

import numpy as np
import nutpie
import pandas as pd
import pymc as pm
import xarray as xr
from nutpie.compile_pymc import CompiledPyMCModel

from pitwall.config import Era, HazardConfig
from pitwall.ingest.neutralisations import RED, SC, VSC
from pitwall.ingest.storage import RaceTables
from pitwall.models.sampling import Diagnostics, sample

DNF = "DNF"
KINDS = (SC, VSC, RED)
PHASES = ("lap1", "running")
COLUMNS = ["race", "era", "kind", "phase", "unit", "events", "exposure", "position"]


def neutralisation_rows(tables: RaceTables, race: str, era: Era) -> pd.DataFrame:
    """Per kind and phase: periods that started, and the laps they could have started on. A lap
    under any neutralisation is not at risk of another one starting."""
    periods = tables.neutralisations
    distance = int(tables.laps["lap"].max())
    covered = np.zeros(distance + 1, dtype=bool)
    for start, end in periods[["start_lap", "end_lap"]].itertuples(index=False):
        covered[int(start) : int(end) + 1] = True
    at_risk = int((~covered[2:]).sum())
    rows = []
    for kind in KINDS:
        starts = periods.loc[periods["kind"] == kind, "start_lap"]
        rows.append((kind, "lap1", int((starts <= 1).sum()), 1.0))
        rows.append((kind, "running", int((starts >= 2).sum()), float(at_risk)))
    unit = f"track:{tables.event.circuit_key}"
    return pd.DataFrame(
        [(race, era.name, kind, phase, unit, n, e, 0.0) for kind, phase, n, e in rows],
        columns=COLUMNS,
    )


def running_share(race_state: pd.DataFrame) -> pd.DataFrame:
    """Each car's place after each lap among the cars that completed it, from the front (-0.5)
    to the back (+0.5): (driver, lap, position). A car has a row for every lap it completed."""
    by_lap = race_state.groupby("lap")["position"]
    rank = by_lap.rank(method="first")
    field = by_lap.transform("size")
    share = (rank - 1) / (field - 1).clip(lower=1) - 0.5
    return race_state[["driver", "lap"]].assign(position=share.to_numpy())


def retirement_rows(tables: RaceTables, race: str, era: Era, bins: int, lag: int) -> pd.DataFrame:
    """Per team: cars out on the opening lap. And per team and band of running position: later
    retirements, and laps raced after lap 1, each lap placed by where the car ran `lag` laps
    before it began (after lap 1 at the earliest). Every retirement counts, mechanical or not:
    OpenF1 gives no reason."""
    cars = tables.results[tables.results["status"] != "DNS"]
    done = cars["laps_completed"].fillna(0).astype(int)
    out = cars["status"] == DNF
    unit = "team:" + era.name + ":" + cars["team_id"]
    lap1 = (
        pd.DataFrame({"unit": unit, "events": (out & (done == 0)).astype(int), "exposure": 1.0})
        .groupby("unit", as_index=False)
        .sum()
        .assign(phase="lap1", position=0.0)
    )
    # A car that retires after completing k laps was at risk on laps 2 .. k + 1; one that
    # finished, on laps 2 .. its last.
    last = np.where(out, done + 1, done)
    laps = pd.DataFrame(
        {"driver": cars["driver"], "unit": unit, "lap": [range(2, n + 1) for n in last]}
    ).explode("lap")
    laps = laps.dropna(subset=["lap"]).astype({"lap": int})
    retired_on = dict(zip(cars["driver"], np.where(out & (done >= 1), done + 1, -1), strict=True))
    laps["events"] = (laps["lap"] == laps["driver"].map(retired_on)).astype(int)
    laps["at"] = np.maximum(laps["lap"] - 1 - lag, 1)
    share = running_share(tables.race_state).rename(columns={"lap": "at"})
    laps = laps.merge(share, on=["driver", "at"], how="left")
    laps["position"] = laps["position"].fillna(0.0)  # no race state for that lap: mid-field
    laps["band"] = np.minimum(((laps["position"] + 0.5) * bins).astype(int), bins - 1)
    running = (
        laps.groupby(["unit", "band"], as_index=False)
        .agg(events=("events", "sum"), exposure=("lap", "size"), position=("position", "mean"))
        .drop(columns="band")
        .assign(phase="running")
    )
    rows = pd.concat([lap1, running], ignore_index=True)
    return rows.assign(race=race, era=era.name, kind=DNF)[COLUMNS]


@dataclass(frozen=True)
class Index:
    """Integer codes for the model's groups, built from the training rows."""

    era: dict[tuple[str], int]
    family: dict[tuple[str, str], int]
    base: dict[tuple[str, str, str], int]
    unit: dict[tuple[str, str, str], int]

    @classmethod
    def of(cls, rows: pd.DataFrame) -> "Index":
        def codes(columns: list[str]) -> dict:
            keys = rows[columns].drop_duplicates().sort_values(columns).itertuples(index=False)
            return {tuple(key): i for i, key in enumerate(keys)}

        return cls(
            era=codes(["era"]),
            family=codes(["kind", "phase"]),
            base=codes(["era", "kind", "phase"]),
            unit=codes(["unit", "kind", "phase"]),
        )

    def rows(self, rows: pd.DataFrame, name: str, columns: list[str]) -> np.ndarray:
        lookup = getattr(self, name)
        return np.array([lookup[tuple(key)] for key in rows[columns].itertuples(index=False)])


@dataclass(frozen=True)
class RateFit:
    index: Index
    posterior: xr.Dataset  # dims: (sample, group)
    diagnostics: Diagnostics
    passed: bool

    def rate(
        self, era: str, kind: str, phase: str, unit: str, rng: np.random.Generator
    ) -> np.ndarray:
        """Posterior draws of events per unit of exposure. An unseen unit gets a fresh deviation."""
        base = self.posterior["base"].to_numpy()[:, self.index.base[(era, kind, phase)]]
        sd = self.posterior["unit_sd"].to_numpy()[:, self.index.family[(kind, phase)]]
        i = self.index.unit.get((unit, kind, phase))
        z = self.posterior["z"].to_numpy()[:, i] if i is not None else rng.standard_normal(len(sd))
        return np.exp(base + sd * z)

    def position(self, era: str) -> np.ndarray:
        """Posterior draws of the change in log retirement rate from the front to the back."""
        return self.posterior["position"].to_numpy()[:, self.index.era[(era,)]]


class RateModel:
    """Compiled once; refitted with any set of rows masked out (their likelihood removed)."""

    def __init__(self, rows: pd.DataFrame, config: HazardConfig) -> None:
        self.rows, self.config = rows.reset_index(drop=True), config
        self.index = index = Index.of(self.rows)
        family_of_unit = index.rows(
            pd.DataFrame(list(index.unit), columns=["unit", "kind", "phase"]),
            "family",
            ["kind", "phase"],
        )
        base_of_row = index.rows(self.rows, "base", ["era", "kind", "phase"])
        unit_of_row = index.rows(self.rows, "unit", ["unit", "kind", "phase"])
        era_of_row = index.rows(self.rows, "era", ["era"])
        prior = config.priors
        with pm.Model() as model:
            events = pm.Data("events", self.rows["events"].to_numpy())
            exposure = pm.Data("exposure", self.rows["exposure"].to_numpy())
            base = pm.Normal("base", prior.log_rate.mean, prior.log_rate.sd, shape=len(index.base))
            unit_sd = pm.HalfNormal("unit_sd", prior.unit_sd, shape=len(index.family))
            z = pm.Normal("z", 0, 1, shape=len(index.unit))
            position = pm.Normal("position", 0, prior.position_sd, shape=len(index.era))
            log_rate = (
                base[base_of_row]
                + unit_sd[family_of_unit][unit_of_row] * z[unit_of_row]
                + position[era_of_row] * self.rows["position"].to_numpy()
            )
            pm.Poisson("observed", mu=exposure * log_rate.exp(), observed=events)
        compiled = nutpie.compile_pymc_model(model)
        assert isinstance(compiled, CompiledPyMCModel)  # the PyMC variant can swap data
        self.compiled = compiled

    def fit(self, masked: np.ndarray | None = None) -> RateFit:
        keep = np.ones(len(self.rows), bool) if masked is None else ~masked
        compiled = self.compiled.with_data(
            events=np.where(keep, self.rows["events"], 0),
            exposure=np.where(keep, self.rows["exposure"], 0.0),
        )
        posterior, diagnostics = sample(compiled, self.config.sampler)
        return RateFit(self.index, posterior, diagnostics, diagnostics.passes(self.config.gate))


def p_any(
    fit: RateFit, era: str, kind: str, unit: str, laps: int, rng: np.random.Generator
) -> np.ndarray:
    """Draws of the probability that a race of `laps` laps sees at least one `kind` event, ex ante:
    every lap after the first is at risk."""
    lap1 = fit.rate(era, kind, "lap1", unit, rng)
    running = fit.rate(era, kind, "running", unit, rng)
    return 1 - np.exp(-(lap1 + running * (laps - 1)))
