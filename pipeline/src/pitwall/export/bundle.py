"""Canonical race tables → static bundle described by the export contract."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from pitwall.export.contract import (
    SCHEMA_VERSION,
    DriverRace,
    Manifest,
    Race,
    RaceEntry,
    Stint,
)
from pitwall.ingest.storage import RaceTables, dataset_fingerprint, list_races, read_race


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
        dataset_version=dataset_fingerprint(tables.laps, tables.results),
        drivers=drivers,
    )


def export_bundle(data_dir: Path, bundle_dir: Path, git_sha: str) -> Manifest:
    entries = []
    for path in list_races(data_dir):
        race = build_race(read_race(path))
        relative = f"races/{race.season}/{race.round:02d}.json"
        out = bundle_dir / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(race.model_dump_json())
        entries.append(
            RaceEntry(
                season=race.season,
                round=race.round,
                name=race.name,
                path=relative,
                dataset_version=race.dataset_version,
            )
        )
        logger.info("exported {} ({} bytes)", relative, out.stat().st_size)

    manifest = Manifest(
        schema_version=SCHEMA_VERSION,
        git_sha=git_sha,
        generated_at=datetime.now(UTC),
        races=entries,
    )
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    logger.info("manifest: {} races, schema {}", len(entries), SCHEMA_VERSION)
    return manifest
