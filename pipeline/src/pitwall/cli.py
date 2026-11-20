import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from pitwall.config import (
    REPO_ROOT,
    PipelineConfig,
    load_allocations,
    load_config,
    load_regulations,
    load_team_ids,
)
from pitwall.export.bundle import export_bundle
from pitwall.export.contract import write_schemas
from pitwall.ingest.openf1 import OpenF1, fetch_race, finished_rounds
from pitwall.ingest.storage import list_races, race_dir, read_race, season_dir, write_race
from pitwall.ingest.validate import RaceReport, check_prepared, validate_race, write_summary
from pitwall.models import backtest, degradation
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


def _model_dir(config: PipelineConfig) -> Path:
    return config.data_dir / "models" / "degradation"


def fit_degradation(config: PipelineConfig, era_name: str) -> bool:
    """Fit one era and, if the sampler diagnostics pass the gate, export draws for its races.
    A failed gate writes nothing but a rejected model card: the previous draws stay live."""
    regulations = load_regulations()
    era = regulations.era(era_name)
    races = [
        t for t in map(read_race, list_races(config.data_dir)) if t.event.season in era.seasons
    ]
    laps, sparse = degradation.drop_sparse_compounds(
        degradation.training_laps(races, era), config.degradation.min_compound_races
    )
    logger.info(
        "{}: fitting {} clean laps from {} races; C-numbers left out: {}",
        era.name,
        len(laps),
        len(races),
        sparse,
    )
    fit = degradation.fit(laps, era, config.degradation, regulations.fuel_effect_s_per_kg)
    card = degradation.model_card(fit, _git_sha(), sparse)
    out = _model_dir(config)
    out.mkdir(parents=True, exist_ok=True)
    if not fit.passed:
        (out / f"{era.name}.rejected.json").write_text(card.model_dump_json(indent=2))
        logger.error(
            "{}: diagnostics failed the gate, nothing exported: {}", era.name, fit.diagnostics
        )
        return False

    allocations = load_allocations()
    rng = np.random.default_rng(config.degradation.sampler.seed)
    for tables in races:
        season, round_ = tables.event.season, tables.event.round
        if degradation.race_id(season, round_) not in set(laps["race"]):
            logger.warning("{} R{}: no clean laps, no draws", season, round_)
            continue
        allocation = allocations.get((season, round_))
        compounds = (
            [allocation.hard, allocation.medium, allocation.soft]
            if allocation
            else sorted(tables.laps["compound_c"].dropna().astype(int).unique())
        )
        draws = degradation.race_draws(fit, tables, compounds, config.degradation.export_draws, rng)
        draws.to_parquet(race_dir(config.data_dir, season, round_) / "degradation_draws.parquet")
    (out / f"{era.name}.json").write_text(card.model_dump_json(indent=2))
    logger.info("{}: {}; draws exported", era.name, fit.diagnostics)
    return True


def _markdown(table: pd.DataFrame) -> str:
    table = table.reset_index()
    lines = ["| " + " | ".join(map(str, table.columns)) + " |", "|" + "---|" * len(table.columns)]
    lines += ["| " + " | ".join(map(str, row)) + " |" for row in table.itertuples(index=False)]
    return "\n".join(lines)


def backtest_degradation(config: PipelineConfig) -> Path:
    """Leave-one-race-out over the configured held-out races; writes a markdown report."""
    regulations = load_regulations()
    settings = config.degradation.backtest
    races = list(map(read_race, list_races(config.data_dir)))
    rng = np.random.default_rng(settings.sampler.seed)
    model_config = config.degradation.model_copy(update={"sampler": settings.sampler})
    forecasts, diagnostics = [], []
    for season, round_ in settings.races:
        era = regulations.era_of(season)
        laps = degradation.training_laps([t for t in races if t.event.season in era.seasons], era)
        held_out = degradation.race_id(season, round_)
        train, _ = degradation.drop_sparse_compounds(
            laps[laps["race"] != held_out], config.degradation.min_compound_races
        )
        fit = degradation.fit(
            train,
            era,
            model_config,
            regulations.fuel_effect_s_per_kg,
        )
        forecasts.append(
            backtest.forecast_stints(laps[laps["race"] == held_out], fit, settings, rng)
        )
        diagnostics.append({"race": held_out, **fit.diagnostics.model_dump(), "passed": fit.passed})
        logger.info("{} held out: {}", held_out, fit.diagnostics)

    results = pd.concat(forecasts, ignore_index=True)
    out = _model_dir(config)
    out.mkdir(parents=True, exist_ok=True)
    results.to_parquet(out / "backtest.parquet", index=False)
    sections = {
        "Overall": backtest.score(results),
        "By race": backtest.score(results, ["race"]),
        "By laps ahead of the anchor": backtest.score(results, ["horizon"]),
        "By C-number": backtest.score(results, ["compound_c"]),
        "Sampler diagnostics per refit": pd.DataFrame(diagnostics).set_index("race").round(3),
    }
    report = out / "backtest.md"
    report.write_text(
        f"# Degradation backtest (git {_git_sha()})\n\n"
        f"Anchor: first {settings.anchor_laps} clean laps of each held-out stint. "
        "MAE / RMSE in seconds. Refits use the lighter backtest sampler and are never "
        "published; `passed` is the publish gate, shown for reference.\n\n"
        + "\n\n".join(f"## {title}\n\n{_markdown(table)}" for title, table in sections.items())
        + "\n"
    )
    logger.info("backtest:\n{}", sections["Overall"].to_string())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="pitwall")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = commands.add_parser(
        "ingest", help="pull, validate and store one race, or every finished race of a season"
    )
    ingest_cmd.add_argument("--season", type=int, required=True)
    ingest_cmd.add_argument("--round", type=int, help="omit to ingest the whole season")

    fit_cmd = commands.add_parser(
        "fit-degradation", help="fit the degradation model and export posterior draws per race"
    )
    fit_cmd.add_argument("--era", help="omit to fit every era in config/regulations.yaml")

    commands.add_parser(
        "backtest-degradation", help="leave-one-race-out backtest against the baselines"
    )

    commands.add_parser("export", help="write the static bundle from all ingested races")

    contract = commands.add_parser("contract", help="write JSON Schema for the export contract")
    contract.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    config = load_config()

    match args.command:
        case "ingest":
            if not ingest(config, args.season, args.round):
                sys.exit(1)
        case "fit-degradation":
            eras = [args.era] if args.era else [e.name for e in load_regulations().eras]
            if not all([fit_degradation(config, era) for era in eras]):
                sys.exit(1)
        case "backtest-degradation":
            backtest_degradation(config)
        case "export":
            export_bundle(config.data_dir, config.bundle_dir, _git_sha())
        case "contract":
            for path in write_schemas(args.out):
                logger.info("wrote {}", path)
