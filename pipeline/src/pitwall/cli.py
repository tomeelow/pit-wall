import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from pitwall import store, weekend
from pitwall.config import (
    REPO_ROOT,
    PipelineConfig,
    load_allocations,
    load_budgets,
    load_config,
    load_regulations,
    load_team_ids,
    load_thresholds,
)
from pitwall.export.bundle import export_bundle
from pitwall.export.contract import Manifest, SegmentScore, SimRace, write_schemas
from pitwall.ingest.openf1 import OpenF1, fetch_race, finished_rounds
from pitwall.ingest.storage import (
    RaceTables,
    list_races,
    race_dir,
    read_race,
    season_dir,
    write_race,
)
from pitwall.ingest.traces import fetch_traces, read_traces, write_traces
from pitwall.ingest.validate import RaceReport, check_prepared, validate_race, write_summary
from pitwall.models import backtest, degradation, events, traffic, warmup
from pitwall.models.hazards import RateModel
from pitwall.prepare import prepare_race
from pitwall.validate import simulator


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


def _openf1(config: PipelineConfig, refresh: bool = False) -> OpenF1:
    return OpenF1(
        config.openf1_url,
        config.data_dir / "openf1-cache.sqlite",
        config.calendar_cache_hours,
        config.openf1_min_interval_s,
        refresh,
    )


def ingest_rounds(
    config: PipelineConfig, client: OpenF1, season: int, rounds: list[int]
) -> list[RaceReport]:
    """Pull, validate and store these rounds; a race that fails validation is not written."""
    team_ids, allocations = load_team_ids(), load_allocations()
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
        write_traces(config.data_dir, tables, *fetch_traces(client, tables))
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
    if reports:
        write_summary(season_dir(config.data_dir, season), reports)
    return reports


def ingest(config: PipelineConfig, season: int, round_: int | None) -> bool:
    """Ingest one race, or every finished race of the season. True if every race validated."""
    client = _openf1(config)
    rounds = (
        [round_]
        if round_ is not None
        else finished_rounds(client, season, datetime.now(UTC), config.min_hours_after_race)
    )
    reports = ingest_rounds(config, client, season, rounds)
    failed = [r for r in reports if r.errors]
    logger.info(
        "{}: {} races ingested, {} rejected, {} warnings",
        season,
        len(reports) - len(failed),
        len(failed),
        sum(len(r.warnings) for r in reports),
    )
    return not failed


def ingest_traces(config: PipelineConfig, season: int | None) -> None:
    """Fetch fastest-lap traces for stored races that have none; `ingest` fetches them itself."""
    client = _openf1(config)
    for path in list_races(config.data_dir):
        tables = read_race(path)
        if (season is not None and tables.event.season != season) or read_traces(path):
            continue
        traces, track = fetch_traces(client, tables)
        write_traces(config.data_dir, tables, traces, track)
        logger.info(
            "{} R{}: {} fastest laps, track outline of {} points",
            tables.event.season,
            tables.event.round,
            traces.groupby("driver").ngroups,
            len(track),
        )


def _model_dir(config: PipelineConfig, model: str = "degradation") -> Path:
    return config.data_dir / "models" / model


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


def _history(config: PipelineConfig) -> events.History:
    tables = list(map(read_race, list_races(config.data_dir)))
    return events.History.of(tables, config.events, load_regulations())


def fit_events(config: PipelineConfig) -> bool:
    """Fit event rates on every race (the gate), then per race with that race masked out, and
    export each race's pit-loss parameters and rate draws. A race whose masked fit fails the gate
    gets nothing new: its previous files stay live."""
    settings = config.events.hazards
    history = _history(config)
    model = RateModel(history.rows, settings)
    full = model.fit()
    out = _model_dir(config, "events")
    out.mkdir(parents=True, exist_ok=True)
    card = events.model_card(history, full, _git_sha())
    if not full.passed:
        (out / "card.rejected.json").write_text(card.model_dump_json(indent=2))
        logger.error("event rates failed the gate, nothing exported: {}", full.diagnostics)
        return False

    regulations = load_regulations()
    rng = np.random.default_rng(settings.sampler.seed)
    failed = []
    for race, tables in history.races.items():
        fit = model.fit((history.rows["race"] == race).to_numpy())
        if not fit.passed:
            failed.append(race)
            logger.error("{} masked: failed the gate, not exported: {}", race, fit.diagnostics)
            continue
        era = regulations.era_of(tables.event.season).name
        folder = race_dir(config.data_dir, tables.event.season, tables.event.round)
        draws = events.race_hazards(fit, tables, era, settings.export_draws, rng)
        draws.to_parquet(folder / "hazard_draws.parquet", index=False)
        (folder / "events.json").write_text(history.parameters(race, era).model_dump_json(indent=2))
    (out / "card.json").write_text(card.model_dump_json(indent=2))
    logger.info(
        "event rates: {}; {} races exported, {} failed",
        full.diagnostics,
        len(history.races) - len(failed),
        failed,
    )
    return not failed


def validate_events(config: PipelineConfig) -> Path:
    """Leave-one-season-out: predicted vs observed neutralisations per race and track."""
    settings = config.events.hazards
    history = _history(config)
    model = RateModel(history.rows, settings)
    rng = np.random.default_rng(settings.sampler.seed)
    predictions, diagnostics = [], []
    for season in settings.validation_seasons:
        found, fit = events.validate_season(model, history, season, rng)
        predictions.append(found.assign(season=season))
        diagnostics.append({"season": season, **fit.diagnostics.model_dump(), "passed": fit.passed})
        logger.info("{} held out: {}", season, fit.diagnostics)
    results = pd.concat(predictions, ignore_index=True)
    per_track = results.pivot_table(
        index="track", columns="kind", values=["observed", "model", "baseline"], aggfunc="sum"
    ).round(2)
    per_track.columns = [f"{kind}_{value}" for value, kind in per_track.columns]
    per_track = per_track[sorted(per_track.columns)]
    per_track["races"] = results.groupby("track")["race"].nunique()
    sections = {
        "Overall": events.scores(results),
        "By held-out season": results.groupby("season")[
            ["kind", "observed", "model", "baseline"]
        ].apply(events.scores),
        "Per track: races with at least one event, observed vs expected": per_track,
        "Sampler diagnostics per held-out fit": pd.DataFrame(diagnostics)
        .set_index("season")
        .round(3),
    }
    out = _model_dir(config, "events")
    out.mkdir(parents=True, exist_ok=True)
    results.to_parquet(out / "validation.parquet", index=False)
    report = out / "validation.md"
    report.write_text(
        f"# Neutralisation rates: leave-one-season-out (git {_git_sha()})\n\n"
        "Probability of at least one SC / VSC / red flag per race, ex ante (every lap after the "
        "first at risk). Baseline: share of the same era's training races with at least one. "
        "Brier score and log loss: lower is better.\n\n"
        + "\n\n".join(f"## {title}\n\n{_markdown(table)}" for title, table in sections.items())
        + "\n"
    )
    logger.info("event validation:\n{}", sections["Overall"].to_string())
    return report


def _traffic_pairs(config: PipelineConfig) -> tuple[pd.DataFrame, dict[str, RaceTables]]:
    """Lap pairs of every race with degradation draws (they give each car's free-air pace)."""
    regulations = load_regulations()
    frames, races = [], {}
    for path in list_races(config.data_dir):
        tables = read_race(path)
        race = degradation.race_id(tables.event.season, tables.event.round)
        races[race] = tables
        draws_path = path / "degradation_draws.parquet"
        if not draws_path.exists():
            logger.warning("{}: no degradation draws, no traffic pairs", race)
            continue
        predicted = traffic.predicted_laps(tables, pd.read_parquet(draws_path))
        frames.append(
            traffic.lap_pairs(tables, predicted).assign(
                race=race,
                season=tables.event.season,
                era=regulations.era_of(tables.event.season).name,
                circuit=tables.event.circuit,
            )
        )
    return pd.concat(frames, ignore_index=True), races


def fit_traffic(config: PipelineConfig) -> bool:
    """Fit the pass model on every race and, if it passes the gate, export each race's track
    terms and its era's dirty-air table."""
    settings = config.traffic
    pairs, races = _traffic_pairs(config)
    rows = traffic.training_pairs(pairs, settings)
    fit = traffic.PassModel(rows, settings).fit()
    card = traffic.model_card(fit, rows, pairs, settings, _git_sha())
    out = _model_dir(config, "traffic")
    out.mkdir(parents=True, exist_ok=True)
    if not fit.passed:
        (out / "card.rejected.json").write_text(card.model_dump_json(indent=2))
        logger.error("pass model failed the gate, nothing exported: {}", fit.diagnostics)
        return False

    regulations = load_regulations()
    rng = np.random.default_rng(settings.sampler.seed)
    picks = np.linspace(0, fit.samples - 1, settings.export_draws).round().astype(int)
    for tables in races.values():
        era = regulations.era_of(tables.event.season).name
        folder = race_dir(config.data_dir, tables.event.season, tables.event.round)
        terms = fit.terms(era, tables.event.circuit_key, rng).iloc[picks].reset_index(drop=True)
        terms.rename_axis("draw").reset_index().to_parquet(
            folder / "traffic_draws.parquet", index=False
        )
        (folder / "traffic.json").write_text(
            traffic.RaceTraffic(
                max_gap_s=settings.max_gap_s,
                drs_gap_s=settings.drs_gap_s,
                dirty_air=card.dirty_air[era],
            ).model_dump_json(indent=2)
        )
    (out / "card.json").write_text(card.model_dump_json(indent=2))
    logger.info("pass model: {}; {} races exported", fit.diagnostics, len(races))
    return True


def validate_traffic(config: PipelineConfig) -> Path:
    """Leave-one-season-out: pass probability against observed passes, with a reliability table."""
    settings = config.traffic
    pairs, _ = _traffic_pairs(config)
    model = traffic.PassModel(traffic.training_pairs(pairs, settings), settings)
    rng = np.random.default_rng(settings.sampler.seed)
    predictions, diagnostics = [], []
    for season in settings.validation_seasons:
        held = (model.rows["season"] == season).to_numpy()
        found, fit = traffic.validate_season(model, held, rng, settings.export_draws)
        predictions.append(found)
        diagnostics.append({"season": season, **fit.diagnostics.model_dump(), "passed": fit.passed})
        logger.info("{} held out: {}", season, fit.diagnostics)
    results = pd.concat(predictions, ignore_index=True)
    results["gap"] = pd.cut(results["gap_s"], settings.dirty_air_bins, include_lowest=True).astype(
        str
    )
    bins = settings.reliability_bins
    sections = {
        "Overall": traffic.scores(results),
        "By held-out season": traffic.scores(results, ["season"]),
        "By gap at the start of the lap (s)": traffic.scores(results, ["gap"]),
        "Reliability: model": traffic.reliability(
            results["model"].to_numpy(), results["passed"].to_numpy(), bins
        ),
        "Reliability: baseline": traffic.reliability(
            results["baseline"].to_numpy(), results["passed"].to_numpy(), bins
        ),
        "Per track: passes observed vs expected": traffic.scores(results, ["circuit"]),
        "Sampler diagnostics per held-out fit": pd.DataFrame(diagnostics)
        .set_index("season")
        .round(3),
    }
    out = _model_dir(config, "traffic")
    out.mkdir(parents=True, exist_ok=True)
    results.to_parquet(out / "validation.parquet", index=False)
    report = out / "validation.md"
    report.write_text(
        f"# Pass model: leave-one-season-out (git {_git_sha()})\n\n"
        "Probability that a car passes the car directly ahead on a lap, for pairs within "
        f"{settings.max_gap_s} s at the start of a lap that can only be decided on track. "
        "Baseline: the training pass rate in the same era and gap bin. Lower log loss and Brier "
        "are better; reliability compares mean predicted probability with observed frequency.\n\n"
        + "\n\n".join(f"## {title}\n\n{_markdown(table)}" for title, table in sections.items())
        + "\n"
    )
    logger.info("traffic validation:\n{}", sections["Overall"].to_string())
    return report


def fit_warmup(config: PipelineConfig) -> None:
    """Fit tyre warm-up per era and export each race's C-numbers to the race."""
    regulations = load_regulations()
    settings = config.warmup
    frames, compounds = [], {}
    for path in list_races(config.data_dir):
        draws_path = path / "degradation_draws.parquet"
        if not draws_path.exists():
            continue
        tables = read_race(path)
        draws = pd.read_parquet(draws_path)
        compounds[path] = sorted(int(c) for c in draws["compound_c"].unique())
        frames.append(
            warmup.warmup_laps(tables, draws, settings.stint_laps).assign(
                race=degradation.race_id(tables.event.season, tables.event.round),
                era=regulations.era_of(tables.event.season).name,
                path=str(path),
            )
        )
    laps = pd.concat(frames, ignore_index=True)
    out = _model_dir(config, "warmup")
    out.mkdir(parents=True, exist_ok=True)
    for era, era_laps in laps.groupby("era"):
        draws = warmup.fit(era_laps, settings)
        card = warmup.model_card(str(era), era_laps, draws, _git_sha())
        (out / f"{era}.json").write_text(card.model_dump_json(indent=2))
        for path in era_laps["path"].unique():
            race_draws = draws[draws["compound_c"].isin(compounds[Path(path)])]
            race_draws.to_parquet(Path(path) / "warmup_draws.parquet", index=False)
        logger.info(
            "{}: warm-up from {} laps in {} races:\n{}",
            era,
            len(era_laps),
            era_laps["race"].nunique(),
            draws.groupby(["compound_c", "stint_lap"])["warmup_s"].median().unstack().round(2),
        )


def validate_sim(config: PipelineConfig, rebaseline: bool = False) -> bool:
    """Run the engine ex ante over every simulable race in the exported bundle, score it and apply
    the publish gate. Needs `make export` first. A run that fails the gate is kept as
    calibration.rejected.json; the accepted calibration stays. `rebaseline` (by hand only, never
    in the weekend workflow) accepts a lower log score than the accepted one: see `gate`."""
    settings = config.sim_validation
    manifest = Manifest.model_validate_json((config.bundle_dir / "manifest.json").read_text())
    races = {
        (e.season, e.round): SimRace.model_validate_json(
            (config.bundle_dir / e.sim_path).read_text()
        )
        for e in manifest.races
        if e.sim_path
    }
    logger.info("simulating {} races, {} runs per start", len(races), settings.runs)
    found = simulator.run_backtest(REPO_ROOT / "web", config.bundle_dir, settings)
    scored = simulator.score(simulator.entries(found, races), settings)

    out = _model_dir(config, "sim")
    out.mkdir(parents=True, exist_ok=True)
    accepted_path = out / "calibration.json"
    accepted = simulator.accepted_overall(accepted_path)
    thresholds = load_thresholds().simulator
    report = simulator.calibration(
        scored, races, settings, accepted, thresholds, _git_sha(), rebaseline
    )
    if rebaseline and accepted is not None:
        logger.warning(
            "rebaseline: log score {} replaces the accepted {} without the regression check",
            report.segments[0].log_score,
            accepted.log_score,
        )
    scored.drop(columns="counts").to_parquet(out / "validation.parquet", index=False)
    table = pd.DataFrame([s.model_dump() for s in report.segments]).set_index("segment")
    histogram = pd.DataFrame(
        {"pit_bin": range(1, settings.pit_bins + 1), "share": report.pit_histogram}
    ).set_index("pit_bin")
    gate = "passed" if report.gate.passed else "FAILED: " + "; ".join(report.gate.reasons)
    (out / "validation.md").write_text(
        f"# Simulator calibration\n\nGate: {gate}\n\n"
        f"{settings.runs} ex-ante runs per race and start lap, actual strategies. "
        "coverage_*: randomised PIT (nominal 0.5 / 0.8); interval_coverage_*: place inside the "
        "simulated central interval (at least nominal); log scores in nats per car.\n\n"
        f"{_markdown(table)}\n\n## PIT histogram (flat when calibrated)\n\n"
        f"{_markdown(histogram)}\n"
    )
    target = accepted_path if report.gate.passed else out / "calibration.rejected.json"
    target.write_text(report.model_dump_json(indent=2))
    logger.info("simulator calibration:\n{}", table.to_string())
    if not report.gate.passed:
        logger.error("calibration gate failed: {}", report.gate.reasons)
    return report.gate.passed


def export(config: PipelineConfig) -> Manifest:
    return export_bundle(
        config.data_dir,
        config.bundle_dir,
        _git_sha(),
        config.sim,
        load_regulations(),
        load_budgets().bundle,
    )


def _overall(config: PipelineConfig) -> SegmentScore | None:
    return simulator.accepted_overall(_model_dir(config, "sim") / "calibration.json")


def _outcome(report: RaceReport, status: str) -> weekend.RaceOutcome:
    return weekend.RaceOutcome(
        season=report.season,
        round=report.round,
        name=report.name,
        status="rejected" if report.errors else status,
        laps=report.lap_rows,
        clean=report.lap_classes.get("clean", 0),
        warnings=len(report.warnings),
    )


def run_weekend(
    config: PipelineConfig, season: int, round_: int | None, publish: bool
) -> tuple[bool, bool]:
    """Ingest the season's new races and pull the last stored one again; if anything changed,
    refit every model, validate, export and (with publish) upload to the store. Any failed gate
    puts the previous parameters back: the new races' descriptive data still publishes. Returns
    (published, problems): problems is a failed gate or a race that did not validate."""
    client = _openf1(config)
    stored = [int(p.name) for p in list_races(config.data_dir) if p.parent.name == str(season)]
    finished = (
        []
        if round_ is not None
        else finished_rounds(client, season, datetime.now(UTC), config.min_hours_after_race)
    )
    new, again = weekend.plan_rounds(finished, stored, round_)
    logger.info("{}: new rounds {}, pulled again {}", season, new, again)

    def fingerprint(round_: int) -> str:
        return read_race(race_dir(config.data_dir, season, round_)).fingerprint()

    before = {r: fingerprint(r) for r in again}
    outcomes = [_outcome(rep, "new") for rep in ingest_rounds(config, client, season, new)]
    for rep in ingest_rounds(config, _openf1(config, refresh=True), season, again):
        same = fingerprint(rep.round) == before[rep.round]
        outcomes.append(_outcome(rep, "unchanged" if same else "amended"))
    changed = [(o.season, o.round) for o in outcomes if o.status in ("new", "amended")]
    problems = any(o.status == "rejected" for o in outcomes)
    gates: dict[str, bool] = {}
    previous = _overall(config)
    published = "Nothing changed: nothing published."
    if changed:
        regulations = load_regulations()
        with tempfile.TemporaryDirectory() as tmp:
            weekend.snapshot(config.data_dir, Path(tmp))
            eras = sorted({regulations.era_of(s).name for s, _ in changed})
            fits: list[tuple[str, Callable[[], bool]]] = [
                *((f"degradation {era}", partial(fit_degradation, config, era)) for era in eras),
                ("events", partial(fit_events, config)),
                ("traffic", partial(fit_traffic, config)),
            ]
            # Later fits build on earlier ones: once a gate fails, the rest would be wasted.
            for name, fit in fits:
                gates[name] = fit()
                if not gates[name]:
                    break
            else:
                fit_warmup(config)
                export(config)
                gates["simulator calibration"] = validate_sim(config)
            refreshed = all(gates.values())
            if not refreshed:
                weekend.restore(config.data_dir, Path(tmp))
                logger.error("a gate failed: the previous model parameters stay live")
        export(config)
        problems = problems or not refreshed
        everything = [(int(p.parent.name), int(p.name)) for p in list_races(config.data_dir)]
        if publish:
            store.push(config.data_dir, everything if refreshed else changed, models=refreshed)
        published = f"{'Published' if publish else 'Not published (dry run)'}: " + (
            "models refreshed, every race."
            if refreshed
            else f"models NOT refreshed (previous parameters live); races {changed}."
        )

    summary = weekend.report(
        outcomes,
        gates,
        previous,
        _overall(config) if changed else None,
        weekend.largest_files(config.bundle_dir) if changed else {},
        published,
    )
    (config.data_dir / "weekend.md").write_text(summary)
    logger.info("\n{}", summary)
    return bool(changed) and publish, problems


def _github_outputs(published: bool, problems: bool) -> None:
    """Step outputs and the job summary, when running on GitHub Actions."""
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a") as f:
            f.write(f"published={str(published).lower()}\nproblems={str(problems).lower()}\n")


def main() -> None:
    parser = argparse.ArgumentParser(prog="pitwall")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = commands.add_parser(
        "ingest", help="pull, validate and store one race, or every finished race of a season"
    )
    ingest_cmd.add_argument("--season", type=int, required=True)
    ingest_cmd.add_argument("--round", type=int, help="omit to ingest the whole season")

    traces_cmd = commands.add_parser(
        "ingest-traces", help="fetch fastest-lap car data and location for stored races"
    )
    traces_cmd.add_argument("--season", type=int, help="omit for every stored race")

    fit_cmd = commands.add_parser(
        "fit-degradation", help="fit the degradation model and export posterior draws per race"
    )
    fit_cmd.add_argument("--era", help="omit to fit every era in config/regulations.yaml")

    commands.add_parser(
        "backtest-degradation", help="leave-one-race-out backtest against the baselines"
    )

    commands.add_parser(
        "fit-events", help="fit pit loss and SC/VSC/red-flag/DNF rates; export them per race"
    )
    commands.add_parser(
        "validate-events", help="leave-one-season-out validation of the neutralisation rates"
    )

    commands.add_parser(
        "fit-traffic", help="fit dirty air and the pass model; export them per race"
    )
    commands.add_parser(
        "validate-traffic", help="leave-one-season-out validation of the pass model"
    )

    commands.add_parser(
        "fit-warmup", help="fit tyre warm-up per C-number and stint lap; export it per race"
    )
    validate_sim_cmd = commands.add_parser(
        "validate-sim", help="calibrate the simulator on the exported bundle; apply the gate"
    )
    validate_sim_cmd.add_argument(
        "--rebaseline",
        action="store_true",
        help="accept a lower log score than the accepted calibration (after a scoring or engine "
        "fix that made the accepted score wrong); every other gate check still applies",
    )
    commands.add_parser("export", help="write the static bundle from all ingested races")

    weekend_cmd = commands.add_parser(
        "weekend", help="ingest new races, pull the last one again, refit, validate and export"
    )
    weekend_cmd.add_argument("--season", type=int, help="default: the current year")
    weekend_cmd.add_argument("--round", type=int, help="pull this round (again), not the calendar")
    weekend_cmd.add_argument(
        "--publish", action="store_true", help="upload what changed to the GitHub Releases store"
    )
    commands.add_parser("data-pull", help="download the published races and models (ADR-008)")
    commands.add_parser(
        "data-push", help="upload every stored race and the models to the store (seeding)"
    )

    contract = commands.add_parser("contract", help="write JSON Schema for the export contract")
    contract.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    config = load_config()

    match args.command:
        case "ingest":
            if not ingest(config, args.season, args.round):
                sys.exit(1)
        case "ingest-traces":
            ingest_traces(config, args.season)
        case "fit-degradation":
            eras = [args.era] if args.era else [e.name for e in load_regulations().eras]
            if not all([fit_degradation(config, era) for era in eras]):
                sys.exit(1)
        case "backtest-degradation":
            backtest_degradation(config)
        case "fit-events":
            if not fit_events(config):
                sys.exit(1)
        case "validate-events":
            validate_events(config)
        case "fit-traffic":
            if not fit_traffic(config):
                sys.exit(1)
        case "validate-traffic":
            validate_traffic(config)
        case "fit-warmup":
            fit_warmup(config)
        case "validate-sim":
            if not validate_sim(config, args.rebaseline):
                sys.exit(1)
        case "export":
            export(config)
        case "weekend":
            published, problems = run_weekend(
                config, args.season or datetime.now(UTC).year, args.round, args.publish
            )
            _github_outputs(published, problems)
        case "data-pull":
            store.pull(config.data_dir)
        case "data-push":
            races = [(int(p.parent.name), int(p.name)) for p in list_races(config.data_dir)]
            store.push(config.data_dir, races, models=True)
        case "contract":
            for path in write_schemas(args.out):
                logger.info("wrote {}", path)
