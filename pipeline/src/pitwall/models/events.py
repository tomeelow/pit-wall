"""Per-race pit-loss and random-event parameters for the simulator, and their validation.

What a race's parameters may learn from (the information-set rule):
- Pit-lane transit and the SC/VSC factors are physical properties, fitted on every race of the
  era. This is the same documented softening as pace. The factors are per era: 2026 changed how
  much a stop under a safety car saves (0.68x green in 2023-2025, 0.94x in 2026).
- Random events are not. Stationary times, neutralisation durations and the event rates for a
  race come from every *other* race.
- Neither is the stint cap: how long stints get on a C-number comes from the era's other races.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from pydantic import BaseModel

from pitwall.config import EventsConfig, Regulations, StintCapConfig
from pitwall.ingest.storage import RaceTables, dataset_fingerprint
from pitwall.models import hazards, pit_loss
from pitwall.models.degradation import race_id
from pitwall.models.sampling import Diagnostics


class EventParameters(BaseModel):
    pit_loss_s: float  # median green loss: transit plus a typical stop
    pit_transit_s: float  # loss without the stationary time
    pit_loss_from: str  # "track", or "era" for a track without measured stops
    pit_condition_factor: dict[str, float]  # loss under SC / VSC relative to green
    stationary_s: list[float]  # empirical, slow stops included
    neutralised_lap_factor: dict[str, float]  # lap time under SC / VSC over a clean lap
    duration_laps: dict[str, list[int]]  # observed durations of each neutralisation kind
    # Longest stint the strategy search proposes, per C-number seen in the era's other races, and
    # for any other C-number; None with no other race in the era to learn from.
    max_stint_laps: dict[str, int]
    max_stint_laps_other: int | None


def completed_stints(tables: RaceTables) -> pd.DataFrame:
    """Laps of every dry stint ended by a stop or by the flag (compound_c, laps). Stints ended by
    a retirement say nothing about how long the tyres could go."""
    laps = tables.laps.dropna(subset=["compound_c"])
    finished = set(tables.results.loc[tables.results["status"] == "Finished", "driver"])
    last_lap = tables.laps.groupby("driver")["lap"].max()
    stints = laps.groupby(["driver", "stint"]).agg(
        compound_c=("compound_c", "last"),
        laps=("lap", "size"),
        end=("lap", "max"),
        pitted=("pit_in", "last"),
    )
    drivers = stints.index.get_level_values("driver")
    flag = (stints["end"].to_numpy() == last_lap.loc[drivers].to_numpy()) & drivers.isin(finished)
    done = stints[stints["pitted"].astype(bool).to_numpy() | flag]
    return done[["compound_c", "laps"]].astype(int).reset_index(drop=True)


def _upper(laps: pd.Series, cap: StintCapConfig) -> int:
    return int(np.ceil(np.quantile(laps, cap.quantile)))


def stint_caps(stints: pd.DataFrame, cap: StintCapConfig) -> tuple[dict[str, int], int | None]:
    """Per C-number with at least min_stints stints, and for all of them together."""
    if stints.empty:
        return {}, None
    per_c = {
        str(c): _upper(group["laps"], cap)
        for c, group in stints.groupby("compound_c")
        if len(group) >= cap.min_stints
    }
    return per_c, _upper(stints["laps"], cap)


@dataclass(frozen=True)
class History:
    """Everything the event models learn from, across all ingested races."""

    races: dict[str, RaceTables]
    stops: pd.DataFrame  # pit_loss.stop_losses + race, era
    paces: pd.DataFrame  # pit_loss.neutralised_pace + race, era
    periods: pd.DataFrame  # neutralisations + race
    rows: pd.DataFrame  # hazard rows
    stints: pd.DataFrame  # completed_stints + race, era
    stint_cap: StintCapConfig

    @classmethod
    def of(
        cls, tables: list[RaceTables], config: EventsConfig, regulations: Regulations
    ) -> "History":
        races = {race_id(t.event.season, t.event.round): t for t in tables}
        stops, paces, periods, rows, stints = [], [], [], [], []
        for race, t in races.items():
            era = regulations.era_of(t.event.season)
            stops.append(pit_loss.stop_losses(t, config.pit_loss).assign(race=race, era=era.name))
            paces.append(pit_loss.neutralised_pace(t).assign(race=race, era=era.name))
            periods.append(t.neutralisations.assign(race=race))
            stints.append(completed_stints(t).assign(race=race, era=era.name))
            rows += [
                hazards.neutralisation_rows(t, race, era),
                hazards.retirement_rows(t, race, era),
            ]
        non_empty = [s for s in stops if not s.empty]
        return cls(
            races=races,
            stops=pd.concat(non_empty, ignore_index=True),
            paces=pd.concat(paces, ignore_index=True),
            periods=pd.concat(periods, ignore_index=True),
            rows=pd.concat(rows, ignore_index=True),
            stints=pd.concat(stints, ignore_index=True),
            stint_cap=config.stint_cap,
        )

    def parameters(self, race: str, era: str) -> EventParameters:
        track = self.races[race].event.circuit_key
        tracks = pit_loss.track_losses(self.stops)
        others = self.stops[(self.stops["race"] != race) & (self.stops["era"] == era)]
        stationary = pit_loss.stationary_times(others)
        source = "track" if track in tracks.index else "era"
        at = tracks.to_dict("index")[track] if source == "track" else tracks.median().to_dict()
        loss, transit = float(at["green_loss_s"]), float(at["transit_s"])
        if np.isnan(transit):  # no stationary times at this track (2023 and early 2024)
            transit = loss - float(np.median(stationary))
        periods = self.periods[self.periods["race"] != race]
        durations = periods["end_lap"] - periods["start_lap"] + 1
        caps, other_cap = stint_caps(
            self.stints[(self.stints["race"] != race) & (self.stints["era"] == era)],
            self.stint_cap,
        )
        return EventParameters(
            pit_loss_s=round(float(loss), 3),
            pit_transit_s=round(float(transit), 3),
            pit_loss_from=source,
            pit_condition_factor={
                k: round(v, 3)
                for k, v in pit_loss.condition_factors(self.stops[self.stops["era"] == era]).items()
            },
            stationary_s=[round(float(s), 2) for s in stationary],
            neutralised_lap_factor={
                str(k): round(float(v), 3)
                for k, v in self.paces[self.paces["era"] == era]
                .groupby("kind")["factor"]
                .median()
                .items()
            },
            duration_laps={
                kind: sorted(durations[periods["kind"] == kind].astype(int).tolist())
                for kind in hazards.KINDS
            },
            max_stint_laps=caps,
            max_stint_laps_other=other_cap,
        )


def race_hazards(
    fit: hazards.RateFit, tables: RaceTables, era: str, n: int, rng: np.random.Generator
) -> pd.DataFrame:
    """`n` rate draws for the race's track (SC, VSC, red flag) and each of its teams (DNF)."""
    picks = np.linspace(0, len(fit.posterior["sample"]) - 1, n).round().astype(int)
    units = [(kind, f"track:{tables.event.circuit_key}") for kind in hazards.KINDS]
    teams = sorted(set(tables.results["team_id"]))
    units += [(hazards.DNF, f"team:{era}:{team}") for team in teams]
    frames = [
        pd.DataFrame(
            {
                "draw": np.arange(n),
                "kind": kind,
                "phase": phase,
                "unit": unit,
                "rate": fit.rate(era, kind, phase, unit, rng)[picks],
            }
        )
        for kind, unit in units
        for phase in hazards.PHASES
    ]
    return pd.concat(frames, ignore_index=True)


def validate_season(
    model: hazards.RateModel, history: History, season: int, rng: np.random.Generator
) -> tuple[pd.DataFrame, hazards.RateFit]:
    """Hold out one season: per race and kind, the model's and the baseline's probability of at
    least one event, and whether there was one. The baseline is the share of training races of
    the same era with at least one."""
    rows = model.rows
    held = rows["race"].map(lambda r: history.races[r].event.season == season).to_numpy()
    fit = model.fit(held)
    per_race = rows.groupby(["race", "era", "kind", "unit"], as_index=False)["events"].sum()
    train = per_race[~per_race["race"].isin(rows.loc[held, "race"])]
    baseline = train.assign(any=train["events"] > 0).groupby(["era", "kind"])["any"].mean()
    out = []
    for race, era, kind, unit, events in per_race.itertuples(index=False):
        tables = history.races[race]
        if tables.event.season != season or kind == hazards.DNF:
            continue
        laps = int(tables.laps["lap"].max())
        out.append(
            {
                "race": race,
                "track": tables.event.circuit,
                "kind": kind,
                "observed": int(events > 0),
                "model": float(hazards.p_any(fit, era, kind, unit, laps, rng).mean()),
                "baseline": float(baseline[(era, kind)]),
            }
        )
    return pd.DataFrame(out), fit


def scores(predictions: pd.DataFrame) -> pd.DataFrame:
    """Brier score and log loss per kind, model against baseline. Lower is better."""

    def by_kind(column: str) -> pd.DataFrame:
        p = predictions[column].clip(1e-6, 1 - 1e-6)
        y = predictions["observed"]
        frame = pd.DataFrame(
            {
                "kind": predictions["kind"],
                "brier": (p - y) ** 2,
                "log_loss": -(y * np.log(p) + (1 - y) * np.log(1 - p)),
            }
        )
        return frame.groupby("kind").mean().add_suffix(f"_{column}")

    table = by_kind("model").join(by_kind("baseline"))
    table["races"] = predictions.groupby("kind").size()
    table["observed_rate"] = predictions.groupby("kind")["observed"].mean()
    return table.round(3)


class EventsCard(BaseModel):
    dataset_version: str
    git_sha: str
    fitted_at: datetime
    races: int
    diagnostics: Diagnostics
    passed: bool
    # Events per lap (running) or per start (lap1), median and 90 % interval, per era.
    rates: dict[str, dict[str, list[float]]]
    stops: dict[str, int]
    pit_condition_factor: dict[str, dict[str, float]]  # per era
    stationary_quantiles_s: dict[str, float]


def model_card(history: History, fit: hazards.RateFit, git_sha: str) -> EventsCard:
    base = fit.posterior["base"].to_numpy()
    rates: dict[str, dict[str, list[float]]] = {}
    for (era, kind, phase), i in fit.index.base.items():
        q = np.exp(np.quantile(base[:, i], [0.05, 0.5, 0.95]))
        rates.setdefault(era, {})[f"{kind}/{phase}"] = [round(float(v), 5) for v in q]
    stationary = pit_loss.stationary_times(history.stops)
    return EventsCard(
        dataset_version=dataset_fingerprint(history.rows, history.stops),
        git_sha=git_sha,
        fitted_at=datetime.now(UTC),
        races=len(history.races),
        diagnostics=fit.diagnostics,
        passed=fit.passed,
        rates=rates,
        stops={str(k): int(v) for k, v in history.stops["condition"].value_counts().items()},
        pit_condition_factor={
            str(era): {k: round(v, 3) for k, v in pit_loss.condition_factors(stops).items()}
            for era, stops in history.stops.groupby("era")
        },
        stationary_quantiles_s={
            f"q{int(q * 100):02d}": round(float(np.quantile(stationary, q)), 2)
            for q in (0.05, 0.5, 0.9, 0.99)
        },
    )
