import json
from dataclasses import replace

import pandas as pd

from pitwall.config import load_config
from pitwall.ingest.storage import RaceTables
from pitwall.ingest.validate import validate_race, write_summary
from tests.conftest import ALLOCATION

CONFIG = load_config().validation


def test_clean_race_has_no_errors_or_warnings(race_tables: RaceTables) -> None:
    report = validate_race(race_tables, ALLOCATION, CONFIG, [])
    assert report.errors == []
    assert report.warnings == []
    assert (report.lap_rows, report.drivers, report.pit_stops, report.neutralisations) == (
        144,
        3,
        3,
        1,
    )


def test_allocation_for_another_race_is_an_error(race_tables: RaceTables) -> None:
    wrong = ALLOCATION.model_copy(update={"race": "Saudi Arabian Grand Prix"})
    report = validate_race(race_tables, wrong, CONFIG, [])
    assert len(report.errors) == 1
    assert "'Saudi Arabian Grand Prix'" in report.errors[0]


def test_missing_allocation_is_a_warning(race_tables: RaceTables) -> None:
    report = validate_race(race_tables, None, CONFIG, [])
    assert report.errors == []
    assert any("no Pirelli allocation" in w for w in report.warnings)


def test_unmapped_team_is_an_error(race_tables: RaceTables) -> None:
    laps = race_tables.laps.assign(team_id=pd.Series(pd.NA, index=race_tables.laps.index))
    laps["team_id"] = laps["team_id"].astype("string")
    report = validate_race(replace(race_tables, laps=laps), ALLOCATION, CONFIG, [])
    assert any(e.startswith("laps.team_id") for e in report.errors)


def test_duplicate_laps_are_an_error(race_tables: RaceTables) -> None:
    laps = pd.concat([race_tables.laps, race_tables.laps.head(1)], ignore_index=True)
    report = validate_race(replace(race_tables, laps=laps), ALLOCATION, CONFIG, [])
    assert report.errors


def test_driver_with_laps_but_no_result_is_an_error(race_tables: RaceTables) -> None:
    results = race_tables.results[race_tables.results["driver"] != "SAR"]
    report = validate_race(replace(race_tables, results=results), ALLOCATION, CONFIG, [])
    assert report.errors == ["drivers with laps but no result: ['SAR']"]


def test_data_quirks_are_warnings(race_tables: RaceTables) -> None:
    laps = race_tables.laps
    laps = laps[~((laps["driver"] == "VER") & (laps["lap"] == 30))].copy()
    laps.loc[(laps["driver"] == "LEC") & (laps["lap"] == 10), "lap_time_s"] = 900.0
    laps["pit_in"] = laps["pit_in"] & (laps["driver"] != "VER")
    report = validate_race(replace(race_tables, laps=laps), ALLOCATION, CONFIG, ["race control: x"])
    assert report.errors == []
    assert report.warnings[0] == "race control: x"
    assert "VER: missing laps [30]" in report.warnings
    assert any(w.startswith("1 lap times outside") and "LEC L10" in w for w in report.warnings)
    assert "stint changes without a pit record: ['VER L21']" in report.warnings


def test_tyre_change_under_red_flag_is_not_an_unpitted_stint(race_tables: RaceTables) -> None:
    laps = race_tables.laps.copy()
    laps["pit_in"] = laps["pit_in"] & (laps["driver"] != "VER")
    red = pd.DataFrame(
        {
            "kind": ["RED"],
            "start_lap": [20],
            "end_lap": [20],
            "start_utc": [pd.Timestamp("2024-03-02 15:40", tz="UTC")],
            "end_utc": [pd.Timestamp("2024-03-02 16:00", tz="UTC")],
            "ended_by": ["restart"],
        }
    )
    report = validate_race(
        replace(race_tables, laps=laps, neutralisations=red), ALLOCATION, CONFIG, []
    )
    assert report.warnings == []


def test_race_without_pit_records_gets_one_warning(race_tables: RaceTables) -> None:
    report = validate_race(
        replace(race_tables, pits=race_tables.pits.head(0)), ALLOCATION, CONFIG, []
    )
    assert report.warnings == ["OpenF1 has no pit records for this race; pit_in is all false"]


def test_summary_merges_rounds(race_tables: RaceTables, tmp_path) -> None:
    report = validate_race(race_tables, ALLOCATION, CONFIG, [])
    write_summary(tmp_path, [report.model_copy(update={"round": 3})])
    path = write_summary(tmp_path, [report.model_copy(update={"round": 1})])
    write_summary(tmp_path, [report.model_copy(update={"round": 3, "warnings": ["w"]})])
    summary = json.loads(path.read_text())
    assert list(summary) == ["1", "3"]
    assert summary["3"]["warnings"] == ["w"]
