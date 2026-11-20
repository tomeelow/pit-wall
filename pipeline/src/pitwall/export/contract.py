"""The export contract: the only interface between the pipeline and the web app.

`make contract` turns these models into JSON Schema (contract/) and TypeScript types
(web/src/contract/). Bump SCHEMA_VERSION on every change; bump the major on breaking ones.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.json_schema import GenerateJsonSchema

SchemaVersion = Literal["0.4.0"]
SCHEMA_VERSION: SchemaVersion = "0.4.0"

Compound = Literal["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Stint(_Contract):
    stint: int
    compound: Compound
    start_lap: int
    end_lap: int
    tyre_age_at_start: int | None


class DriverRace(_Contract):
    driver: str
    team: str
    position: int | None
    status: str
    stints: list[Stint]


class Race(_Contract):
    schema_version: SchemaVersion
    season: int
    round: int
    name: str
    total_laps: int
    dataset_version: str
    drivers: list[DriverRace]


class RaceEntry(_Contract):
    season: int
    round: int
    name: str
    path: str
    # None when the race cannot be simulated; the pipeline log says why.
    sim_path: str | None
    dataset_version: str


class StrategySettings(_Contract):
    """Strategy search: candidate plans for one car and successive halving over them."""

    max_stops: int
    min_stint_laps: int  # every planned stint
    max_candidates: int  # pit laps spread out until the candidates fit
    min_race_clean_laps: int  # a C-number with fewer in the race is not proposed
    first_runs: int
    eta: int  # each round keeps the best 1/eta and gives them eta times the runs
    keep: int  # candidates reported, and the fewest a round keeps
    max_runs: int
    holdout_runs: int  # fresh runs on which the debrief scores the chosen strategy


class Manifest(_Contract):
    schema_version: SchemaVersion
    git_sha: str
    generated_at: datetime
    races: list[RaceEntry]
    calibration_path: str | None  # None until the simulator has been validated
    strategy: StrategySettings


# Simulator inputs (Phase 6). Every list named per draw has SimRace.draws entries, and draw i of
# every model goes together. Lists named per compound follow SimRace.compounds.

NeutralisationKind = Literal["SC", "VSC", "RED"]


class Rules(_Contract):
    """What every finishing strategy must satisfy; breaking a rule is a disqualification. A stop
    under a red flag costs nothing when red_flag_free_tyre_change is set. A car that retires is
    still classified if it covered classified_fraction of the race's laps (rounded down)."""

    min_dry_compounds: int
    min_stops: int
    max_stint_laps: int | None
    red_flag_free_tyre_change: bool
    classified_fraction: float
    points_places: int


class Mechanics(_Contract):
    follow_gap_s: float  # closest a car stuck behind another crosses the line
    restart_gap_s: float  # gap between consecutive cars when a safety car or red flag ends


class Degradation(_Contract):
    """Free-air lap time = race_median_s + pace_s[car] + offset_s[compound]
    + slope_s_per_lap[car][compound] * tyre_age + fuel_s_per_kg * fuel_kg(lap)
    + warmup_s[compound][k] on the k-th green lap of a stint (k = 0 is the out-lap)
    + StudentT(nu, 0, noise_sd_s), where fuel_kg(lap) = race_fuel_kg * (1 - (lap - 0.5) / laps)
    and tyre_age counts the lap being driven."""

    race_median_s: float
    race_fuel_kg: float
    fuel_s_per_kg: list[float]  # per draw
    nu: list[float]  # per draw
    noise_sd_s: list[float]  # per draw
    offset_s: list[list[float]]  # per compound, per draw
    warmup_s: list[list[list[float]]]  # per compound, per stint lap, per draw
    # Per compound: the race's own evidence. Few laps mean pace and wear come from other races.
    race_clean_laps: list[int]


class PitLoss(_Contract):
    """Time a stop costs over the in-lap and out-lap: (transit_s + a stationary time) x the
    factor of the condition it is made under (1 when green)."""

    transit_s: float
    stationary_s: list[float]  # empirical sample from other races, slow stops included
    sc_factor: float
    vsc_factor: float


class NeutralisationParams(_Contract):
    kind: NeutralisationKind
    rate_per_lap: list[float]  # per draw: starts per green lap
    duration_laps: list[int]  # empirical sample from other races
    lap_factor: float  # neutralised lap time over a free-air lap


class DirtyAirBin(_Contract):
    gap_upto_s: float
    loss_s: float


class Traffic(_Contract):
    """P(pass the car ahead on a green lap) = logistic(intercept + beta_gap_s * gap
    + beta_pace_delta_s * pace delta + beta_within_drs * [gap <= drs_gap_s]) for gap <= max_gap_s.
    The intercept includes the track's effect."""

    max_gap_s: float
    drs_gap_s: float
    dirty_air: list[DirtyAirBin]
    intercept: list[float]  # per draw
    beta_gap_s: list[float]  # per draw
    beta_pace_delta_s: list[float]  # per draw
    beta_within_drs: list[float]  # per draw


class PlannedStop(_Contract):
    lap: int  # in-lap: the car pits at the end of it
    compound_c: int
    tyre_age: int  # laps already run on the set fitted


class Car(_Contract):
    driver: str
    team_id: str
    # "field": the driver has no clean laps, so pace is the field median of each draw.
    pace_from: Literal["driver", "field"]
    pace_s: list[float]  # per draw
    slope_s_per_lap: list[list[float]]  # per compound, per draw
    dnf_rate_per_lap: list[float]  # per draw
    stops: list[PlannedStop]  # the strategy actually run
    finish_position: int | None  # official classification; None for DNF and DSQ
    retired_after_lap: int | None  # last lap completed by a car that did not finish


class Snapshot(_Contract):
    """Race state after `lap` was completed. Lists are per car, in SimRace.cars order; None for a
    car that has retired. A stop made at the end of `lap` has already happened."""

    lap: int
    race_time_s: list[float | None]
    compound_c: list[int | None]
    tyre_age: list[int | None]
    stint_laps: list[int | None]  # laps raced on the current set in this race
    stops: list[int]
    dry_compounds: list[list[int]]  # C-numbers used so far


class Neutralisation(_Contract):
    kind: NeutralisationKind
    start_lap: int
    end_lap: int


class SimRace(_Contract):
    schema_version: SchemaVersion
    season: int
    round: int
    name: str
    era: str
    total_laps: int
    dataset_version: str
    draws: int
    rules: Rules
    mechanics: Mechanics
    compounds: list[int]  # C-numbers the degradation model covers for this race
    degradation: Degradation
    pit_loss: PitLoss
    neutralisations: list[NeutralisationParams]
    traffic: Traffic
    cars: list[Car]
    snapshots: list[Snapshot]  # after laps 1 .. total_laps - 1
    realised: list[Neutralisation]  # what happened: for replays and ex-post views only


# Simulator calibration (Phase 7): ex-ante simulations of every simulable race with the actual
# strategies, scored against the official classification.


class SegmentScore(_Contract):
    """Scores of one group of car-starts. coverage_*: share of randomised PIT values inside the
    central interval (nominal 0.5 / 0.8 when calibrated). interval_coverage_*: share of finishes
    inside the simulated central interval of places (at least nominal, the places being discrete).
    log_score*: mean log probability of the actual result, nats; higher is better."""

    segment: str
    races: int
    entries: int
    coverage_50: float
    coverage_80: float
    interval_coverage_50: float
    interval_coverage_80: float
    log_score: float
    log_score_start_order: float  # baseline: finish follows the order at the start lap
    log_score_lap1_order: float  # baseline: finish follows the order after lap 1 (for the grid)


class GateResult(_Contract):
    passed: bool
    reasons: list[str]  # why it failed; empty when it passed


class Calibration(_Contract):
    schema_version: SchemaVersion
    git_sha: str
    generated_at: datetime
    dataset_version: str  # hash of every scored race's dataset version
    runs: int  # simulations per race and start lap
    segments: list[SegmentScore]  # "all" first
    pit_histogram: list[float]  # share of car-starts per equal-width PIT bin; flat when calibrated
    gate: GateResult


TOP_LEVEL: dict[str, type[_Contract]] = {
    "manifest": Manifest,
    "race": Race,
    "sim": SimRace,
    "calibration": Calibration,
}


class _UntitledFields(GenerateJsonSchema):
    """Field titles would become one TypeScript alias per field (`Season = number`, ...)."""

    def field_title_should_be_set(self, schema: object) -> bool:
        return False


def write_schemas(out_dir: Path) -> list[Path]:
    """Serialization-mode schemas: they describe the JSON the browser receives."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in TOP_LEVEL.items():
        path = out_dir / f"{name}.schema.json"
        schema = model.model_json_schema(mode="serialization", schema_generator=_UntitledFields)
        path.write_text(json.dumps(schema, indent=2) + "\n")
        written.append(path)
    return written
