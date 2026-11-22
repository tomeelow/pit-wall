from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# pipeline/src/pitwall/config.py → repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ValidationConfig(_Config):
    lap_time_min_factor: float = Field(gt=0)
    lap_time_max_factor: float = Field(gt=1)
    min_position_agreement: float = Field(ge=0, le=1)
    position_lag_s: float = Field(ge=0)


class ClassificationConfig(_Config):
    traffic_gap_s: float = Field(gt=0)
    outlier_factor: float = Field(gt=1)
    max_yellow_s: float = Field(gt=0)


class NormalPrior(_Config):
    mean: float
    sd: float = Field(gt=0)


class SamplerConfig(_Config):
    chains: int = Field(ge=1)
    tune: int = Field(ge=1)
    draws: int = Field(ge=1)
    target_accept: float = Field(gt=0, lt=1)
    seed: int


class DegradationPriors(_Config):
    slope_s_per_lap: NormalPrior
    slope_track_sd: float = Field(gt=0)
    slope_team_sd: float = Field(gt=0)
    compound_offset_sd: float = Field(gt=0)
    compound_track_sd: float = Field(gt=0)
    race_level_sd: float = Field(gt=0)
    pace_sd: float = Field(gt=0)
    noise_sd: float = Field(gt=0)


class GateConfig(_Config):
    max_rhat: float = Field(gt=1)
    min_ess: float = Field(gt=0)
    max_divergences: int = Field(ge=0)


class BacktestConfig(_Config):
    sampler: SamplerConfig
    anchor_laps: int = Field(ge=2)
    min_forecast_laps: int = Field(ge=1)
    races: list[tuple[int, int]] = Field(min_length=1)


class DegradationConfig(_Config):
    sampler: SamplerConfig
    min_compound_races: int = Field(ge=1)
    export_draws: int = Field(ge=1)
    priors: DegradationPriors
    gate: GateConfig
    backtest: BacktestConfig


class PitLossConfig(_Config):
    min_field_cars: int = Field(ge=1)
    max_lane_factor: float = Field(gt=1)


class StintCapConfig(_Config):
    quantile: float = Field(gt=0, lt=1)
    min_stints: int = Field(ge=1)


class HazardPriors(_Config):
    log_rate: NormalPrior
    unit_sd: float = Field(gt=0)


class HazardConfig(_Config):
    sampler: SamplerConfig
    priors: HazardPriors
    gate: GateConfig
    export_draws: int = Field(ge=1)
    validation_seasons: list[int] = Field(min_length=1)


class EventsConfig(_Config):
    pit_loss: PitLossConfig
    stint_cap: StintCapConfig
    hazards: HazardConfig


class TrafficPriors(_Config):
    intercept: NormalPrior
    coefficient_sd: float = Field(gt=0)
    track_sd: float = Field(gt=0)


class TrafficConfig(_Config):
    max_gap_s: float = Field(gt=0)
    drs_gap_s: float = Field(gt=0)
    dirty_air_bins: list[float] = Field(min_length=2)
    sampler: SamplerConfig
    priors: TrafficPriors
    gate: GateConfig
    export_draws: int = Field(ge=1)
    validation_seasons: list[int] = Field(min_length=1)
    reliability_bins: list[float] = Field(min_length=2)


class StrategyConfig(_Config):
    max_stops: int = Field(ge=1)
    min_stint_laps: int = Field(ge=1)
    max_candidates: int = Field(ge=1)
    min_race_clean_laps: int = Field(ge=0)
    first_runs: int = Field(ge=1)
    eta: int = Field(ge=2)
    keep: int = Field(ge=1)
    max_runs: int = Field(ge=1)
    holdout_runs: int = Field(ge=1)


class SimConfig(_Config):
    draws: int = Field(ge=1)
    follow_gap_s: float = Field(gt=0)
    restart_gap_s: float = Field(gt=0)
    grid_change_laps: int = Field(ge=0)
    decimals: int = Field(ge=1)
    strategy: StrategyConfig


class WarmupConfig(_Config):
    stint_laps: int = Field(ge=1)
    min_laps: int = Field(ge=1)
    draws: int = Field(ge=1)
    seed: int


class SimValidationConfig(_Config):
    runs: int = Field(ge=1)
    seed: int
    start_fractions: list[float] = Field(min_length=1)
    smoothing: float = Field(gt=0)
    pit_bins: int = Field(ge=2)
    undercut_runs: int = Field(ge=1)
    undercut_bins: list[float] = Field(min_length=2)


class SimulatorGate(_Config):
    must_beat_baseline_from: float = Field(ge=0, le=1)
    max_log_score_regression: float = Field(ge=0)
    max_coverage_error_growth: float = Field(ge=0)


class Thresholds(_Config):
    simulator: SimulatorGate


class PipelineConfig(_Config):
    data_dir: Path
    bundle_dir: Path
    openf1_url: str
    calendar_cache_hours: float = Field(gt=0)
    openf1_min_interval_s: float = Field(ge=0)
    min_hours_after_race: float = Field(ge=0)
    validation: ValidationConfig
    classification: ClassificationConfig
    degradation: DegradationConfig
    events: EventsConfig
    traffic: TrafficConfig
    warmup: WarmupConfig
    sim: SimConfig
    sim_validation: SimValidationConfig


class Era(_Config):
    name: str
    seasons: list[int] = Field(min_length=1)
    race_fuel_kg: float = Field(gt=0)
    min_dry_compounds: int = Field(ge=1)
    red_flag_free_tyre_change: bool
    classified_fraction: float = Field(gt=0, le=1)
    points_places: int = Field(ge=1)


class RaceRule(_Config):
    """A one-off rule for one race; None leaves the era's rule."""

    season: int
    round: int = Field(ge=1)
    min_stops: int | None = Field(default=None, ge=1)
    max_stint_laps: int | None = Field(default=None, ge=1)


class RaceRules(_Config):
    """Every rule a race's strategies must satisfy."""

    min_dry_compounds: int
    min_stops: int
    max_stint_laps: int | None
    red_flag_free_tyre_change: bool
    classified_fraction: float
    points_places: int


class Regulations(_Config):
    eras: list[Era]
    fuel_effect_s_per_kg: NormalPrior
    race_rules: list[RaceRule]

    @model_validator(mode="after")
    def _disjoint(self) -> "Regulations":
        seasons = [s for era in self.eras for s in era.seasons]
        if len(seasons) != len(set(seasons)):
            raise ValueError("a season belongs to more than one era")
        return self

    def era(self, name: str) -> Era:
        return next(era for era in self.eras if era.name == name)

    def era_of(self, season: int) -> Era:
        return next(era for era in self.eras if season in era.seasons)

    def rules(self, season: int, round_: int) -> RaceRules:
        rule = next(
            (r for r in self.race_rules if (r.season, r.round) == (season, round_)),
            RaceRule(season=season, round=round_),
        )
        era = self.era_of(season)
        return RaceRules(
            min_dry_compounds=era.min_dry_compounds,
            red_flag_free_tyre_change=era.red_flag_free_tyre_change,
            classified_fraction=era.classified_fraction,
            points_places=era.points_places,
            min_stops=rule.min_stops or 0,
            max_stint_laps=rule.max_stint_laps,
        )


class RaceAllocation(_Config):
    """Pirelli's three dry compounds for one race, as C-numbers (C0 hardest ... C6 softest)."""

    round: int = Field(ge=1)
    race: str
    hard: int = Field(ge=0, le=6)
    medium: int = Field(ge=0, le=6)
    soft: int = Field(ge=0, le=6)

    @model_validator(mode="after")
    def _ordered(self) -> "RaceAllocation":
        if not self.hard < self.medium < self.soft:
            raise ValueError(f"{self.race}: expected hard < medium < soft C-numbers")
        return self

    def c_number(self, compound: str) -> int | None:
        return {"HARD": self.hard, "MEDIUM": self.medium, "SOFT": self.soft}.get(compound)


class SeasonAllocation(_Config):
    sources: list[str] = Field(min_length=1)
    races: list[RaceAllocation]


class SimBenchmark(_Config):
    races: int = Field(gt=0)
    laps: int = Field(gt=0)
    cars: int = Field(gt=0)
    max_seconds: float = Field(gt=0)


class BundleBudgets(_Config):
    race_core_gz_bytes: int = Field(gt=0)
    replay_gz_bytes: int = Field(gt=0)
    telemetry_lap_gz_bytes: int = Field(gt=0)


class Budgets(_Config):
    sim_benchmark: SimBenchmark
    bundle: BundleBudgets


def load_budgets(path: Path = CONFIG_DIR / "budgets.yaml") -> Budgets:
    return Budgets.model_validate(yaml.safe_load(path.read_text()))


def load_config(path: Path = CONFIG_DIR / "pipeline.yaml") -> PipelineConfig:
    config = PipelineConfig.model_validate(yaml.safe_load(path.read_text()))
    return config.model_copy(
        update={
            "data_dir": REPO_ROOT / config.data_dir,
            "bundle_dir": REPO_ROOT / config.bundle_dir,
        }
    )


def load_team_ids(path: Path = CONFIG_DIR / "teams.yaml") -> dict[str, str]:
    """OpenF1 team name → stable team_id."""
    raw: dict[str, list[str]] = yaml.safe_load(path.read_text())
    return {name: team_id for team_id, names in raw.items() for name in names}


def load_allocations(
    path: Path = CONFIG_DIR / "compound_allocation.yaml",
) -> dict[tuple[int, int], RaceAllocation]:
    """(season, round) → that race's Pirelli allocation."""
    raw = yaml.safe_load(path.read_text()) or {}
    allocations = {}
    for season, block in raw.items():
        for race in SeasonAllocation.model_validate(block).races:
            if (season, race.round) in allocations:
                raise ValueError(f"{season} round {race.round} allocated twice")
            allocations[(season, race.round)] = race
    return allocations


def load_thresholds(path: Path = CONFIG_DIR / "thresholds.yaml") -> Thresholds:
    return Thresholds.model_validate(yaml.safe_load(path.read_text()))


def load_regulations(path: Path = CONFIG_DIR / "regulations.yaml") -> Regulations:
    raw = yaml.safe_load(path.read_text())
    eras = [{"name": name, **era} for name, era in raw.pop("eras").items()]
    return Regulations.model_validate({"eras": eras, **raw})
