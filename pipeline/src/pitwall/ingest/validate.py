"""Validation of one race's canonical tables.

The pandera schemas below are the definition of the canonical tables. Errors mean downstream
code cannot trust the race, so it is not written; warnings are data quirks that later phases
handle (lap classification, pit-loss filters) and are reported in the season summary.
"""

import json
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
from pydantic import BaseModel

from pitwall.config import ClassificationConfig, RaceAllocation, ValidationConfig
from pitwall.ingest.openf1 import COMPOUNDS, UNKNOWN_COMPOUND
from pitwall.ingest.storage import RaceTables
from pitwall.laps import LAP_CLASSES, TRACK_STATUSES
from pitwall.race_state import position_agreement

UTC = "datetime64[ns, UTC]"

LAPS = pa.DataFrameSchema(
    {
        "season": pa.Column("int64"),
        "round": pa.Column("int64", pa.Check.ge(1)),
        "driver": pa.Column(str),
        "team": pa.Column(str),
        "team_id": pa.Column("string", nullable=False),
        "lap": pa.Column("int64", pa.Check.ge(1)),
        "lap_start_utc": pa.Column(UTC, nullable=True),
        "lap_time_s": pa.Column("float64", pa.Check.gt(0), nullable=True),
        "compound": pa.Column(str, pa.Check.isin([*COMPOUNDS, UNKNOWN_COMPOUND])),
        "compound_c": pa.Column("Int64", pa.Check.in_range(0, 6), nullable=True),
        "tyre_age": pa.Column("Int64", pa.Check.ge(1), nullable=True),
        "stint": pa.Column("Int64", pa.Check.ge(1)),
        "pit_in": pa.Column(bool),
        "pit_out": pa.Column(bool),
    },
    unique=["driver", "lap"],
    strict=True,
    name="laps",
)

RESULTS = pa.DataFrameSchema(
    {
        "driver": pa.Column(str, unique=True),
        "team": pa.Column(str),
        "team_id": pa.Column("string", nullable=False),
        "position": pa.Column("Int64", pa.Check.ge(1), nullable=True),
        "status": pa.Column(str, pa.Check.isin(["Finished", "DNF", "DNS", "DSQ"])),
        "laps_completed": pa.Column("Int64", pa.Check.ge(0), nullable=True),
    },
    strict=True,
    name="results",
)

PITS = pa.DataFrameSchema(
    {
        "driver": pa.Column("string"),
        "lap": pa.Column("int64", pa.Check.ge(1)),
        "lane_s": pa.Column("float64", pa.Check.gt(0), nullable=True),
        "stop_s": pa.Column("float64", pa.Check.gt(0), nullable=True),
    },
    strict=True,
    name="pits",
)

NEUTRALISATIONS = pa.DataFrameSchema(
    {
        "kind": pa.Column(str, pa.Check.isin(["SC", "VSC", "RED"])),
        "start_lap": pa.Column("int64", pa.Check.ge(0)),
        "end_lap": pa.Column("int64", pa.Check.ge(0)),
        "start_utc": pa.Column(UTC),
        "end_utc": pa.Column(UTC),
        "ended_by": pa.Column(str),
    },
    checks=[
        pa.Check(lambda df: df["end_lap"] >= df["start_lap"], error="end_lap before start_lap"),
        pa.Check(lambda df: df["end_utc"] >= df["start_utc"], error="ends before it starts"),
    ],
    strict=True,
    name="neutralisations",
)


YELLOWS = pa.DataFrameSchema(
    {
        "sector": pa.Column("int64", pa.Check.ge(1)),
        "start_utc": pa.Column(UTC),
        "end_utc": pa.Column(UTC),
    },
    checks=[pa.Check(lambda df: df["end_utc"] >= df["start_utc"], error="ends before it starts")],
    strict=True,
    name="yellows",
)

POSITIONS = pa.DataFrameSchema(
    {
        "driver": pa.Column("string"),
        "utc": pa.Column(UTC),
        "position": pa.Column("int64", pa.Check.ge(1)),
    },
    strict=True,
    name="positions",
)

CLASSIFIED_LAPS = LAPS.add_columns(
    {
        "track_status": pa.Column(str, pa.Check.isin(TRACK_STATUSES)),
        "lap_class": pa.Column(str, pa.Check.isin(LAP_CLASSES)),
    }
).set_name("laps")

RACE_STATE = pa.DataFrameSchema(
    {
        "driver": pa.Column(str),
        "lap": pa.Column("int64", pa.Check.ge(1)),
        "crossing_utc": pa.Column(UTC, nullable=True),
        "race_time_s": pa.Column("float64", nullable=True),
        "position": pa.Column("Int64", pa.Check.ge(1), nullable=True),
        "gap_to_leader_s": pa.Column("float64", pa.Check.ge(0), nullable=True),
        "interval_s": pa.Column("float64", pa.Check.ge(0), nullable=True),
        "gap_ahead_s": pa.Column("float64", pa.Check.ge(0), nullable=True),
        "stint": pa.Column("Int64", pa.Check.ge(1)),
        "compound": pa.Column(str),
        "compound_c": pa.Column("Int64", nullable=True),
        "tyre_age": pa.Column("Int64", nullable=True),
        "stops": pa.Column("Int64", pa.Check.ge(0)),
        "in_pit": pa.Column(bool),
        "dry_compounds_used": pa.Column(str),
        "retired": pa.Column(bool),
    },
    unique=["driver", "lap"],
    strict=True,
    name="race_state",
)


class RaceReport(BaseModel):
    season: int
    round: int
    name: str
    dataset_version: str
    lap_rows: int
    drivers: int
    pit_stops: int
    neutralisations: int
    errors: list[str]
    warnings: list[str]
    position_agreement: float | None = None
    lap_classes: dict[str, int] = {}


def _schema_errors(schema: pa.DataFrameSchema, frame: pd.DataFrame) -> list[str]:
    try:
        schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        cases = exc.failure_cases
        grouped = cases.groupby(["column", "check"], dropna=False)["failure_case"]
        return [
            f"{schema.name}.{column}: {check} failed {len(values)}x "
            f"(e.g. {', '.join(map(str, values.head(3)))})"
            for (column, check), values in grouped
        ]
    return []


def _lap_warnings(tables: RaceTables, config: ValidationConfig) -> list[str]:
    laps, warnings = tables.laps, []

    gaps = {
        driver: sorted(set(range(1, group["lap"].max() + 1)) - set(group["lap"]))
        for driver, group in laps.groupby("driver")
    }
    for driver, missing in gaps.items():
        if missing:
            warnings.append(f"{driver}: missing laps {missing}")

    completed = tables.results.set_index("driver")["laps_completed"]
    run = laps.groupby("driver")["lap"].max()
    for driver, laps_run in run.items():
        expected = completed.get(driver)
        if expected is not None and pd.notna(expected) and expected != laps_run:
            warnings.append(f"{driver}: {laps_run} laps timed, classification says {expected}")

    median = laps["lap_time_s"].median()
    low, high = median * config.lap_time_min_factor, median * config.lap_time_max_factor
    outside = laps[(laps["lap_time_s"] < low) | (laps["lap_time_s"] > high)]
    if not outside.empty:
        examples = ", ".join(
            f"{r.driver} L{r.lap} {r.lap_time_s:.1f}s" for r in outside.head(3).itertuples()
        )
        warnings.append(
            f"{len(outside)} lap times outside [{low:.1f}, {high:.1f}]s (e.g. {examples})"
        )

    unknown = (laps["compound"] == UNKNOWN_COMPOUND).sum()
    if unknown:
        warnings.append(f"{unknown} laps with unknown compound")
    return warnings


def _pit_warnings(tables: RaceTables) -> list[str]:
    """A tyre change should follow a pit in-lap, and a pit stop normally changes tyres.

    Tyres may be changed in the pit lane under a red flag without a pit record, so stint changes
    from the red-flag lap to the restart lap are expected.
    """
    if tables.pits.empty:
        return ["OpenF1 has no pit records for this race; pit_in is all false"]
    red_laps = {
        lap
        for period in tables.neutralisations.to_dict("records")
        if period["kind"] == "RED"
        for lap in range(period["start_lap"], period["end_lap"] + 2)
    }
    rows = tables.laps.sort_values(["driver", "lap"]).to_dict("records")
    by_lap = {(r["driver"], r["lap"]): r for r in rows}
    unpitted, no_change = [], []
    for row in rows:
        before = by_lap.get((row["driver"], row["lap"] - 1))
        after = by_lap.get((row["driver"], row["lap"] + 1))
        if (
            before is not None
            and before["stint"] != row["stint"]
            and not before["pit_in"]
            and row["lap"] not in red_laps
        ):
            unpitted.append(f"{row['driver']} L{row['lap']}")
        if row["pit_in"] and after is not None and after["stint"] == row["stint"]:
            no_change.append(f"{row['driver']} L{row['lap']}")
    warnings = []
    if unpitted:
        warnings.append(f"stint changes without a pit record: {unpitted}")
    if no_change:
        warnings.append(f"pit stops without a tyre change (penalty or repair?): {no_change}")
    return warnings


def validate_race(
    tables: RaceTables,
    allocation: RaceAllocation | None,
    config: ValidationConfig,
    source_issues: list[str],
) -> RaceReport:
    event = tables.event
    errors = [
        *_schema_errors(LAPS, tables.laps),
        *_schema_errors(RESULTS, tables.results),
        *_schema_errors(PITS, tables.pits),
        *_schema_errors(NEUTRALISATIONS, tables.neutralisations),
        *_schema_errors(YELLOWS, tables.yellows),
        *_schema_errors(POSITIONS, tables.positions),
    ]
    if allocation is not None and allocation.race != event.name:
        errors.append(
            f"compound allocation for round {event.round} is {allocation.race!r}, "
            f"but OpenF1 round {event.round} is {event.name!r}"
        )
    unclassified = set(tables.laps["driver"]) - set(tables.results["driver"])
    if unclassified:
        errors.append(f"drivers with laps but no result: {sorted(unclassified)}")

    warnings = list(source_issues)
    if allocation is None:
        warnings.append("no Pirelli allocation in compound_allocation.yaml; compound_c empty")
    if not errors:
        warnings += _lap_warnings(tables, config) + _pit_warnings(tables)
    warnings += [
        f"race finished under {row.kind} (since lap {row.start_lap})"
        for row in tables.neutralisations.itertuples()
        if row.ended_by == "chequered" and row.kind != "RED"
    ]

    return RaceReport(
        season=event.season,
        round=event.round,
        name=event.name,
        dataset_version=tables.fingerprint(),
        lap_rows=len(tables.laps),
        drivers=tables.results["driver"].nunique(),
        pit_stops=len(tables.pits),
        neutralisations=len(tables.neutralisations),
        errors=errors,
        warnings=warnings,
    )


def check_prepared(
    tables: RaceTables,
    report: RaceReport,
    config: ValidationConfig,
    classification: ClassificationConfig,
) -> RaceReport:
    """Validate the derived tables and check the race state against OpenF1's position feed."""
    errors = _schema_errors(CLASSIFIED_LAPS, tables.laps) + _schema_errors(
        RACE_STATE, tables.race_state
    )
    agreement = position_agreement(tables.race_state, tables.positions, config.position_lag_s)
    warnings = []
    if agreement is None:
        warnings.append("no OpenF1 position feed; race-state order unchecked")
    elif agreement < config.min_position_agreement:
        warnings.append(
            f"race-state order matches the position feed on only {agreement:.1%} of driver-laps"
        )
    yellow_s = (tables.yellows["end_utc"] - tables.yellows["start_utc"]).dt.total_seconds()
    capped = tables.yellows["sector"][yellow_s > classification.max_yellow_s].tolist()
    if capped:
        warnings.append(
            f"sector yellows longer than {classification.max_yellow_s:.0f}s (not cleared in "
            f"race control?) counted only for that long: sectors {capped}"
        )
    counts = tables.laps["lap_class"].value_counts()
    return report.model_copy(
        update={
            "dataset_version": tables.fingerprint(),
            "errors": report.errors + errors,
            "warnings": report.warnings + warnings,
            "position_agreement": None if agreement is None else round(agreement, 4),
            "lap_classes": {c: int(counts.get(c, 0)) for c in LAP_CLASSES},
        }
    )


def write_summary(season_dir: Path, reports: list[RaceReport]) -> Path:
    """Merge reports into the season summary, keyed by round, so single-race runs update it."""
    path = season_dir / "summary.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    existing.update({str(r.round): r.model_dump() for r in reports})
    season_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(existing.items(), key=lambda kv: int(kv[0]))), indent=2))
    return path
