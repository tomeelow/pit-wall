import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from pitwall.config import REPO_ROOT, PipelineConfig, load_allocations, load_config, load_team_ids
from pitwall.export.bundle import export_bundle
from pitwall.export.contract import write_schemas
from pitwall.ingest.openf1 import OpenF1, fetch_race, finished_rounds
from pitwall.ingest.storage import season_dir, write_race
from pitwall.ingest.validate import RaceReport, check_prepared, validate_race, write_summary
from pitwall.prepare import prepare_race


def _git_sha() -> str:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha[:12]
    result = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def ingest(config: PipelineConfig, season: int, round_: int | None) -> bool:
    """Ingest one race, or every finished race of the season. True if every race validated."""
    client = OpenF1(
        config.openf1_url, config.data_dir / "openf1-cache.sqlite", config.calendar_cache_hours
    )
    team_ids, allocations = load_team_ids(), load_allocations()
    rounds = (
        [round_]
        if round_ is not None
        else finished_rounds(client, season, datetime.now(UTC), config.min_hours_after_race)
    )

    reports: list[RaceReport] = []
    for r in rounds:
        allocation = allocations.get((season, r))
        tables, issues = fetch_race(season, r, client, team_ids, allocation)
        report = validate_race(tables, allocation, config.validation, issues)
        if not report.errors:
            tables = prepare_race(tables, config.classification)
            report = check_prepared(tables, report, config.validation, config.classification)
        reports.append(report)
        if report.errors:
            logger.error("{} R{} {}: not written", season, r, report.name)
            for error in report.errors:
                logger.error("  {}", error)
            continue
        write_race(config.data_dir, tables)
        logger.info(
            "{} R{} {}: {} laps ({} clean), {} pits, {} neutralisations, order {}, {} warnings",
            season,
            r,
            report.name,
            report.lap_rows,
            report.lap_classes.get("clean", 0),
            report.pit_stops,
            report.neutralisations,
            report.position_agreement,
            len(report.warnings),
        )

    summary = write_summary(season_dir(config.data_dir, season), reports)
    failed = [r for r in reports if r.errors]
    logger.info(
        "{}: {} races ingested, {} rejected, {} warnings; summary at {}",
        season,
        len(reports) - len(failed),
        len(failed),
        sum(len(r.warnings) for r in reports),
        summary,
    )
    return not failed


def main() -> None:
    parser = argparse.ArgumentParser(prog="pitwall")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = commands.add_parser(
        "ingest", help="pull, validate and store one race, or every finished race of a season"
    )
    ingest_cmd.add_argument("--season", type=int, required=True)
    ingest_cmd.add_argument("--round", type=int, help="omit to ingest the whole season")

    commands.add_parser("export", help="write the static bundle from all ingested races")

    contract = commands.add_parser("contract", help="write JSON Schema for the export contract")
    contract.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    config = load_config()

    match args.command:
        case "ingest":
            if not ingest(config, args.season, args.round):
                sys.exit(1)
        case "export":
            export_bundle(config.data_dir, config.bundle_dir, _git_sha())
        case "contract":
            for path in write_schemas(args.out):
                logger.info("wrote {}", path)
