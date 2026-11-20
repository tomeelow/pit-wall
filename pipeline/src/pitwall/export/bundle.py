"""Canonical race tables → static bundle described by the export contract."""

import gzip
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger
from pydantic import ValidationError

from pitwall.config import BundleBudgets, Regulations, SimConfig
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
from pitwall.export.replay import build_replay
from pitwall.export.sim import NotSimulable, build_sim
from pitwall.ingest.storage import RaceTables, list_races, read_race
from pitwall.ingest.traces import read_traces


class OverBudget(RuntimeError):
    """Bundle files larger than config/budgets.yaml allows; the export is not usable."""


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


def _write(bundle_dir: Path, relative: str, json: str) -> int:
    """Writes the file and returns its gzipped size, the size the browser downloads."""
    out = bundle_dir / relative
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json)
    gz = len(gzip.compress(json.encode()))
    logger.info("exported {} ({} bytes, {} gzipped)", relative, out.stat().st_size, gz)
    return gz


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


def _write_replay(
    bundle_dir: Path, path: Path, tables: RaceTables, stem: str, budgets: BundleBudgets
) -> tuple[str | None, list[str]]:
    """The race's replay and telemetry files, if its traces have been fetched, and every file over
    budget."""
    traces = read_traces(path)
    built = build_replay(tables, *traces, f"{stem}/telemetry") if traces else None
    if built is None:
        return None, []
    replay, laps = built
    over = []
    replay_path = f"{stem}.replay.json"
    if _write(bundle_dir, replay_path, replay.model_dump_json()) > budgets.replay_gz_bytes:
        over.append(replay_path)
    for lap, entry in zip(laps, replay.fastest_laps, strict=True):
        size = _write(bundle_dir, entry.telemetry_path, lap.model_dump_json())
        if size > budgets.telemetry_lap_gz_bytes:
            over.append(entry.telemetry_path)
    return replay_path, over


def export_bundle(
    data_dir: Path,
    bundle_dir: Path,
    git_sha: str,
    sim: SimConfig,
    regulations: Regulations,
    budgets: BundleBudgets,
) -> Manifest:
    entries = []
    over: list[str] = []
    for path in list_races(data_dir):
        tables = read_race(path)
        race = build_race(tables)
        stem = f"races/{race.season}/{race.round:02d}"
        core = _write(bundle_dir, f"{stem}.json", race.model_dump_json())
        sim_path: str | None = f"{stem}.sim.json"
        try:
            core += _write(
                bundle_dir,
                f"{stem}.sim.json",
                build_sim(path, tables, regulations, sim).model_dump_json(),
            )
        except NotSimulable as reason:
            logger.warning("{}: not simulable: {}", stem, reason)
            sim_path = None
        if core > budgets.race_core_gz_bytes:
            over.append(f"{stem}.json + .sim.json")
        replay_path, replay_over = _write_replay(bundle_dir, path, tables, stem, budgets)
        over += replay_over
        entries.append(
            RaceEntry(
                season=race.season,
                round=race.round,
                name=race.name,
                path=f"{stem}.json",
                sim_path=sim_path,
                replay_path=replay_path,
                dataset_version=race.dataset_version,
            )
        )
    if over:
        raise OverBudget(f"over the size budget in config/budgets.yaml: {', '.join(over)}")

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
