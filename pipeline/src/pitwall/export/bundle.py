"""Canonical race tables → static bundle described by the export contract."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger
from pydantic import ValidationError

from pitwall.config import Regulations, SimConfig
from pitwall.export.contract import (
    SCHEMA_VERSION,
    Calibration,
    DriverRace,
    Manifest,
    Race,
    RaceEntry,
    Stint,
    StrategySettings,
)
from pitwall.export.sim import NotSimulable, build_sim
from pitwall.ingest.storage import RaceTables, list_races, read_race


def driver_stints(laps: pd.DataFrame) -> list[Stint]:
    """One driver's laps → their stints, in order. Laps without a stint number are ignored."""
    stints = []
    timed = laps.dropna(subset=["stint"]).sort_values("lap")
    for _, group in timed.groupby("stint", sort=True):
        first = group.iloc[0]
        age = first["tyre_age"]
        stints.append(
            Stint(
                stint=int(first["stint"]),
                compound=first["compound"],
                start_lap=int(first["lap"]),
                end_lap=int(group["lap"].max()),
                # tyre_age counts the lap just completed, so the set had age - 1 laps beforehand.
                tyre_age_at_start=None if pd.isna(age) else int(age) - 1,
            )
        )
    return stints


def build_race(tables: RaceTables) -> Race:
    drivers = []
    for row in tables.results.to_dict("records"):
        position = row["position"]
        drivers.append(
            DriverRace(
                driver=row["driver"],
                team=row["team"],
                position=None if pd.isna(position) else int(position),
                status=row["status"],
                stints=driver_stints(tables.laps[tables.laps["driver"] == row["driver"]]),
            )
        )
    drivers.sort(key=lambda d: (d.position is None, d.position or 0))
    return Race(
        schema_version=SCHEMA_VERSION,
        season=tables.event.season,
        round=tables.event.round,
        name=tables.event.name,
        total_laps=tables.event.total_laps,
        dataset_version=tables.fingerprint(),
        drivers=drivers,
    )


def _write(bundle_dir: Path, relative: str, json: str) -> None:
    out = bundle_dir / relative
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json)
    logger.info("exported {} ({} bytes)", relative, out.stat().st_size)


def _publish_calibration(data_dir: Path, bundle_dir: Path) -> str | None:
    """The accepted simulator calibration (`pitwall validate-sim`), if it matches this contract."""
    source = data_dir / "models" / "sim" / "calibration.json"
    if not source.exists():
        return None
    try:
        calibration = Calibration.model_validate_json(source.read_text())
    except ValidationError as error:
        logger.warning("calibration not published, re-run validate-sim: {}", error)
        return None
    _write(bundle_dir, "calibration.json", calibration.model_dump_json())
    return "calibration.json"


def export_bundle(
    data_dir: Path, bundle_dir: Path, git_sha: str, sim: SimConfig, regulations: Regulations
) -> Manifest:
    entries = []
    for path in list_races(data_dir):
        tables = read_race(path)
        race = build_race(tables)
        stem = f"races/{race.season}/{race.round:02d}"
        _write(bundle_dir, f"{stem}.json", race.model_dump_json())
        sim_path: str | None = f"{stem}.sim.json"
        try:
            _write(
                bundle_dir,
                f"{stem}.sim.json",
                build_sim(path, tables, regulations, sim).model_dump_json(),
            )
        except NotSimulable as reason:
            logger.warning("{}: not simulable: {}", stem, reason)
            sim_path = None
        entries.append(
            RaceEntry(
                season=race.season,
                round=race.round,
                name=race.name,
                path=f"{stem}.json",
                sim_path=sim_path,
                dataset_version=race.dataset_version,
            )
        )

    manifest = Manifest(
        schema_version=SCHEMA_VERSION,
        git_sha=git_sha,
        generated_at=datetime.now(UTC),
        races=entries,
        calibration_path=_publish_calibration(data_dir, bundle_dir),
        strategy=StrategySettings(**sim.strategy.model_dump()),
    )
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    logger.info("manifest: {} races, schema {}", len(entries), SCHEMA_VERSION)
    return manifest
