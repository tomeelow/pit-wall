"""On-disk layout of canonical race tables and their content fingerprint."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict


class EventInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    season: int
    round: int
    name: str
    total_laps: int


@dataclass(frozen=True)
class RaceTables:
    event: EventInfo
    laps: pd.DataFrame
    results: pd.DataFrame


def race_dir(data_dir: Path, season: int, round_: int) -> Path:
    return data_dir / "races" / str(season) / f"{round_:02d}"


def write_race(data_dir: Path, tables: RaceTables) -> Path:
    out = race_dir(data_dir, tables.event.season, tables.event.round)
    out.mkdir(parents=True, exist_ok=True)
    (out / "event.json").write_text(tables.event.model_dump_json(indent=2))
    tables.laps.to_parquet(out / "laps.parquet", index=False)
    tables.results.to_parquet(out / "results.parquet", index=False)
    return out


def read_race(path: Path) -> RaceTables:
    return RaceTables(
        event=EventInfo.model_validate_json((path / "event.json").read_text()),
        laps=pd.read_parquet(path / "laps.parquet"),
        results=pd.read_parquet(path / "results.parquet"),
    )


def list_races(data_dir: Path) -> list[Path]:
    return sorted(p.parent for p in (data_dir / "races").glob("*/*/event.json"))


def dataset_fingerprint(*frames: pd.DataFrame) -> str:
    """Content hash of one or more tables. Same contents → same hash, regardless of run."""
    digest = hashlib.sha256()
    for frame in frames:
        digest.update("\x1f".join(map(str, frame.columns)).encode())
        digest.update(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes())
    return digest.hexdigest()[:16]
