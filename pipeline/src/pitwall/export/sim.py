"""Per-race simulator inputs: the fitted models' draws, the actual strategies and the race state
after every lap, joined into one `SimRace` for the TypeScript engine.

A race the engine cannot simulate gets no file. Reasons: a model has no output for it, a car is on
wet or unknown tyres (no model covers them) until the last laps, or a car ran a C-number the
degradation fit does not cover. Wet or unknown tyres earlier in the race only move the first lap a
simulation may start from (SimRace.first_start_lap).
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from pitwall.config import Regulations, SimConfig
from pitwall.export.contract import (
    SCHEMA_VERSION,
    Car,
    Degradation,
    DirtyAirBin,
    Mechanics,
    Neutralisation,
    NeutralisationParams,
    PitLoss,
    PlannedStop,
    Rules,
    SimRace,
    Snapshot,
    Traffic,
)
from pitwall.ingest.storage import RaceTables
from pitwall.models import hazards

MODEL_FILES = (
    "degradation_draws.parquet",
    "hazard_draws.parquet",
    "events.json",
    "traffic_draws.parquet",
    "traffic.json",
    "warmup_draws.parquet",
)
WET = ("INTERMEDIATE", "WET")


class NotSimulable(Exception):
    pass


@dataclass(frozen=True)
class StintStart:
    lap: int
    compound_c: int | None  # None: wet or unknown tyres
    tyre_age: int  # laps on the set before this stint


def stint_starts(laps: pd.DataFrame) -> list[StintStart]:
    """One driver's stints, in order, wet and unknown ones included."""
    starts = []
    for _, group in laps.dropna(subset=["stint"]).sort_values("lap").groupby("stint", sort=True):
        first = group.iloc[0]
        known = group["compound_c"].dropna()
        # tyre_age counts the lap just completed, so the set had age - 1 laps beforehand.
        age_before = int(first["tyre_age"]) - 1 if pd.notna(first["tyre_age"]) else 0
        compound = int(known.iloc[0]) if len(known) == len(group) else None
        starts.append(StintStart(int(first["lap"]), compound, age_before))
    return starts


def snapshots(tables: RaceTables, drivers: list[str]) -> list[Snapshot]:
    stints = {d: stint_starts(tables.laps[tables.laps["driver"] == d]) for d in drivers}
    # Race time at the line of every lap a car completed. race_state flags a retirement on the
    # last lap completed, so that lap still counts: the car retires during the next one.
    time_at = {
        (str(r["driver"]), int(r["lap"])): float(r["race_time_s"])
        for r in tables.race_state.to_dict("records")
        if pd.notna(r["race_time_s"])
    }
    out = []
    for lap in range(1, tables.event.total_laps):
        times, compounds, ages, stint_laps, stops, used = [], [], [], [], [], []
        for d in drivers:
            # A stop at the end of `lap` has happened: the car leaves on the next lap's stint.
            started = [s for s in stints[d] if s.lap <= lap + 1]
            time = time_at.get((d, lap))
            current = started[-1] if started and time is not None else None
            done = max(0, lap - current.lap + 1) if current else 0
            times.append(time if current else None)
            compounds.append(current.compound_c if current else None)
            ages.append(current.tyre_age + done if current else None)
            stint_laps.append(done if current else None)
            stops.append(max(0, len(started) - 1))
            used.append(sorted({s.compound_c for s in started if s.compound_c is not None}))
        out.append(
            Snapshot(
                lap=lap,
                race_time_s=times,
                compound_c=compounds,
                tyre_age=ages,
                stint_laps=stint_laps,
                stops=stops,
                dry_compounds=used,
            )
        )
    return out


def _per_draw(frame: pd.DataFrame, column: str, n: int, decimals: int) -> list[float]:
    values = frame.sort_values("draw")[column].to_numpy(float)
    if len(values) != n:
        raise ValueError(f"expected {n} draws of {column}, found {len(values)}")
    return np.round(values, decimals).tolist()


def _wet_tyres_used(laps: pd.DataFrame, results: pd.DataFrame, min_dry: int) -> set[str]:
    """Drivers exempt from the two-dry-compound rule. Laps on wet sets show most; aligning OpenF1
    stints to pit records can fold a one-lap wet stint into the dry one around it (HUL, Bahrain
    2026). So in a race with wet running, a finisher classified on fewer dry C-numbers than the
    rule needs counts too: the stewards applied the exemption."""
    wet = set(laps.loc[laps["compound"].isin(WET), "driver"])
    if not wet:
        return wet
    dry = laps.dropna(subset=["compound_c"]).groupby("driver")["compound_c"].nunique()
    classified = results.loc[results["position"].notna(), "driver"]
    return wet | {d for d in classified if dry.get(d, 0) < min_dry}


def _first_start_lap(states: list[Snapshot], total_laps: int) -> int:
    """The first lap after which every running car is on a known dry set for the rest of the race.
    Raises NotSimulable when that leaves no lap to decide on (the app offers up to total - 2)."""
    blind = [
        s.lap
        for s in states
        for t, c in zip(s.race_time_s, s.compound_c, strict=True)
        if t is not None and c is None
    ]
    first = max(blind, default=0) + 1
    if first > total_laps - 2:
        raise NotSimulable(f"wet or unknown tyres until lap {first - 1} of {total_laps}")
    return first


def build_sim(
    path: Path, tables: RaceTables, regulations: Regulations, config: SimConfig
) -> SimRace:
    """Raises NotSimulable with the reason when the engine cannot run this race."""
    missing = [name for name in MODEL_FILES if not (path / name).exists()]
    if missing:
        raise NotSimulable(f"no {', '.join(missing)}")
    laps = tables.laps
    # A car with no time at the line on a lap it went on from would vanish from the simulation.
    state = tables.race_state
    last_lap = state.groupby("driver")["lap"].transform("max")
    untimed = state[state["race_time_s"].isna() & (state["lap"] < last_lap)]
    if not untimed.empty:
        raise NotSimulable(f"no race time for running cars on {untimed['lap'].nunique()} laps")

    n, decimals = config.draws, config.decimals
    deg = pd.read_parquet(path / "degradation_draws.parquet")
    deg = deg[deg["draw"] < n]
    compounds = sorted(int(c) for c in deg["compound_c"].unique())
    uncovered = sorted(set(laps["compound_c"].dropna().astype(int)) - set(compounds))
    if uncovered:
        raise NotSimulable(f"C{uncovered} not covered by the degradation model")

    era = regulations.era_of(tables.event.season)
    hazard = pd.read_parquet(path / "hazard_draws.parquet")
    hazard = hazard[(hazard["draw"] < n) & (hazard["phase"] == "running")]
    events = json.loads((path / "events.json").read_text())
    traffic_draws = pd.read_parquet(path / "traffic_draws.parquet")
    traffic_draws = traffic_draws[traffic_draws["draw"] < n]
    traffic = json.loads((path / "traffic.json").read_text())
    warm = pd.read_parquet(path / "warmup_draws.parquet")
    warm = warm[warm["draw"] < n]
    stint_laps = sorted(int(k) for k in warm["stint_lap"].unique())

    def per_draw(frame: pd.DataFrame, column: str) -> list[float]:
        return _per_draw(frame, column, n, decimals)

    def rate(kind: str, unit: str) -> list[float]:
        return per_draw(hazard[(hazard["kind"] == kind) & (hazard["unit"] == unit)], "rate")

    clean = laps[laps["lap_class"] == "clean"].groupby("compound_c").size()
    shared = deg.groupby("draw", as_index=False).first()
    one_driver = deg[deg["driver"] == deg["driver"].iloc[0]]
    field_pace = deg.groupby(["draw", "driver"])["pace_s"].first().groupby("draw").median()
    field_slope = deg.groupby(["compound_c", "draw"])["slope_s_per_lap"].median()

    def slope(driver: str, team: str, c: int) -> list[float]:
        for match in (deg["driver"] == driver, deg["team_id"] == team):
            rows = deg[match & (deg["compound_c"] == c)]
            if not rows.empty:
                return per_draw(rows[rows["driver"] == rows["driver"].iloc[0]], "slope_s_per_lap")
        return np.round(field_slope.loc[c].to_numpy(float), decimals).tolist()

    started = set(laps["driver"])
    results = tables.results[tables.results["driver"].isin(started)]
    rules = regulations.rules(tables.event.season, tables.event.round)
    wet = _wet_tyres_used(laps, results, rules.min_dry_compounds)
    cars = []
    for row in results.to_dict("records"):
        driver, team = str(row["driver"]), str(row["team_id"])
        own = deg[deg["driver"] == driver]
        pace = (
            per_draw(own[own["compound_c"] == own["compound_c"].iloc[0]], "pace_s")
            if not own.empty
            else np.round(field_pace.to_numpy(float), decimals).tolist()
        )
        stints = stint_starts(laps[laps["driver"] == driver])
        position = row["position"]
        cars.append(
            Car(
                driver=driver,
                team_id=team,
                pace_from="driver" if not own.empty else "field",
                pace_s=pace,
                slope_s_per_lap=[slope(driver, team, c) for c in compounds],
                dnf_rate_per_lap=rate(hazards.DNF, f"team:{era.name}:{team}"),
                # A stop onto wet or unknown tyres has no C-number to plan with. It comes before
                # first_start_lap, so no simulation replays it; snapshots still count it.
                stops=[
                    PlannedStop(lap=s.lap - 1, compound_c=s.compound_c, tyre_age=s.tyre_age)
                    for s in stints[1:]
                    if s.compound_c is not None
                ],
                finish_position=None if pd.isna(position) else int(position),
                retired_after_lap=int(row["laps_completed"]) if row["status"] == "DNF" else None,
                wet_tyres_used=driver in wet,
            )
        )
    states = snapshots(tables, [car.driver for car in cars])
    first_start_lap = _first_start_lap(states, tables.event.total_laps)

    lap_factor = events["neutralised_lap_factor"]
    durations = events["duration_laps"]
    return SimRace(
        schema_version=SCHEMA_VERSION,
        season=tables.event.season,
        round=tables.event.round,
        name=tables.event.name,
        era=era.name,
        total_laps=tables.event.total_laps,
        dataset_version=tables.fingerprint(),
        draws=n,
        rules=Rules(**rules.model_dump()),
        mechanics=Mechanics(follow_gap_s=config.follow_gap_s, restart_gap_s=config.restart_gap_s),
        compounds=compounds,
        degradation=Degradation(
            race_median_s=float(shared["race_median_s"].iloc[0]),
            race_fuel_kg=float(shared["race_fuel_kg"].iloc[0]),
            fuel_s_per_kg=per_draw(shared, "fuel_s_per_kg"),
            nu=per_draw(shared, "nu"),
            noise_sd_s=per_draw(shared, "noise_sd_s"),
            # The offset is per race and C-number: every driver's rows carry the same draws.
            offset_s=[
                per_draw(one_driver[one_driver["compound_c"] == c], "offset_s") for c in compounds
            ],
            warmup_s=[
                [
                    per_draw(warm[(warm["compound_c"] == c) & (warm["stint_lap"] == k)], "warmup_s")
                    for k in stint_laps
                ]
                for c in compounds
            ],
            race_clean_laps=[int(clean.get(c, 0)) for c in compounds],
            max_stint_laps=[
                events["max_stint_laps"].get(str(c), events["max_stint_laps_other"])
                for c in compounds
            ],
        ),
        pit_loss=PitLoss(
            transit_s=events["pit_transit_s"],
            stationary_s=events["stationary_s"],
            sc_factor=events["pit_condition_factor"]["SC"],
            vsc_factor=events["pit_condition_factor"]["VSC"],
        ),
        neutralisations=[
            NeutralisationParams(
                kind=kind,
                rate_per_lap=rate(kind, f"track:{tables.event.circuit_key}"),
                duration_laps=durations[kind],
                # A red flag stops the race; until the restart it runs like a safety car.
                lap_factor=lap_factor["SC" if kind == hazards.RED else kind],
            )
            for kind in hazards.KINDS
        ],
        traffic=Traffic(
            max_gap_s=traffic["max_gap_s"],
            drs_gap_s=traffic["drs_gap_s"],
            dirty_air=[
                DirtyAirBin(gap_upto_s=b["gap_upto_s"], loss_s=b["loss_s"])
                for b in traffic["dirty_air"]
            ],
            intercept=per_draw(traffic_draws, "intercept"),
            beta_gap_s=per_draw(traffic_draws, "beta_gap_s"),
            beta_pace_delta_s=per_draw(traffic_draws, "beta_pace_delta_s"),
            beta_within_drs=per_draw(traffic_draws, "beta_within_drs"),
        ),
        cars=cars,
        snapshots=states,
        first_start_lap=first_start_lap,
        realised=[
            Neutralisation(kind=r["kind"], start_lap=int(r["start_lap"]), end_lap=int(r["end_lap"]))
            for r in tables.neutralisations.to_dict("records")
        ],
    )
