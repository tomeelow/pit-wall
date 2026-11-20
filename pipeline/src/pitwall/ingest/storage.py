"""On-disk layout of canonical race tables and their content fingerprint."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

TABLES = ("laps", "results", "pits", "neutralisations")


class EventInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    season: int
    round: int
    name: str
    circuit: str
    circuit_key: int
    session_key: int
    total_laps: int


@dataclass(frozen=True)
class RaceTables:
    event: EventInfo
    laps: pd.DataFrame
    results: pd.DataFrame
    pits: pd.DataFrame
    neutralisations: pd.DataFrame

    def fingerprint(self) -> str:
        return dataset_fingerprint(*(getattr(self, name) for name in TABLES))


def season_dir(data_dir: Path, season: int) -> Path:
    return data_dir / "races" / str(season)


def race_dir(data_dir: Path, season: int, round_: int) -> Path:
    return season_dir(data_dir, season) / f"{round_:02d}"


def write_race(data_dir: Path, tables: RaceTables) -> Path:
    out = race_dir(data_dir, tables.event.season, tables.event.round)
    out.mkdir(parents=True, exist_ok=True)
    (out / "event.json").write_text(tables.event.model_dump_json(indent=2))
    for name in TABLES:
        getattr(tables, name).to_parquet(out / f"{name}.parquet", index=False)
    return out


def read_race(path: Path) -> RaceTables:
    event = EventInfo.model_validate_json((path / "event.json").read_text())
    frames = {name: pd.read_parquet(path / f"{name}.parquet") for name in TABLES}
    return RaceTables(event=event, **frames)


def list_races(data_dir: Path) -> list[Path]:
    return sorted(p.parent for p in (data_dir / "races").glob("*/*/event.json"))


def dataset_fingerprint(*frames: pd.DataFrame) -> str:
    """Content hash of one or more tables. Same contents → same hash, regardless of run."""
    digest = hashlib.sha256()
    for frame in frames:
        digest.update("\x1f".join(map(str, frame.columns)).encode())
        digest.update(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes())
    return digest.hexdigest()[:16]
