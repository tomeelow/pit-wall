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


class PipelineConfig(_Config):
    data_dir: Path
    bundle_dir: Path
    openf1_url: str
    calendar_cache_hours: float = Field(gt=0)
    min_hours_after_race: float = Field(ge=0)
    validation: ValidationConfig


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
