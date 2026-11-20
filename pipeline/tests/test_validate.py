import json
from collections.abc import Callable
from dataclasses import replace

import pandas as pd

from pitwall.config import load_config
from pitwall.ingest.storage import RaceTables
from pitwall.ingest.validate import RaceReport, check_prepared, validate_race, write_summary
from pitwall.prepare import prepare_race
from tests.conftest import ALLOCATION, RACE_START

CONFIG = load_config().validation
CLASSIFICATION = load_config().classification


def test_clean_race_has_no_errors_or_warnings(raw_race: RaceTables) -> None:
    report = validate_race(raw_race, ALLOCATION, CONFIG, [])
    assert report.errors == []
    assert report.warnings == []
    assert (report.lap_rows, report.drivers, report.pit_stops, report.neutralisations) == (
        144,
        3,
        3,
        1,
    )


def test_allocation_for_another_race_is_an_error(raw_race: RaceTables) -> None:
    wrong = ALLOCATION.model_copy(update={"race": "Saudi Arabian Grand Prix"})
    report = validate_race(raw_race, wrong, CONFIG, [])
    assert len(report.errors) == 1
    assert "'Saudi Arabian Grand Prix'" in report.errors[0]


def test_missing_allocation_is_a_warning(raw_race: RaceTables) -> None:
    report = validate_race(raw_race, None, CONFIG, [])
    assert report.errors == []
    assert any("no Pirelli allocation" in w for w in report.warnings)


def test_unmapped_team_is_an_error(raw_race: RaceTables) -> None:
    laps = raw_race.laps.assign(team_id=pd.Series(pd.NA, index=raw_race.laps.index))
    laps["team_id"] = laps["team_id"].astype("string")
    report = validate_race(replace(raw_race, laps=laps), ALLOCATION, CONFIG, [])
    assert any(e.startswith("laps.team_id") for e in report.errors)


def test_duplicate_laps_are_an_error(raw_race: RaceTables) -> None:
    laps = pd.concat([raw_race.laps, raw_race.laps.head(1)], ignore_index=True)
    report = validate_race(replace(raw_race, laps=laps), ALLOCATION, CONFIG, [])
    assert report.errors


def test_driver_with_laps_but_no_result_is_an_error(raw_race: RaceTables) -> None:
    results = raw_race.results[raw_race.results["driver"] != "SAR"]
    report = validate_race(replace(raw_race, results=results), ALLOCATION, CONFIG, [])
    assert report.errors == ["drivers with laps but no result: ['SAR']"]


def test_data_quirks_are_warnings(raw_race: RaceTables) -> None:
    laps = raw_race.laps
    laps = laps[~((laps["driver"] == "VER") & (laps["lap"] == 30))].copy()
    laps.loc[(laps["driver"] == "LEC") & (laps["lap"] == 10), "lap_time_s"] = 900.0
    laps["pit_in"] = laps["pit_in"] & (laps["driver"] != "VER")
    report = validate_race(replace(raw_race, laps=laps), ALLOCATION, CONFIG, ["race control: x"])
    assert report.errors == []
    assert report.warnings[0] == "race control: x"
    assert "VER: missing laps [30]" in report.warnings
    assert any(w.startswith("1 lap times outside") and "LEC L10" in w for w in report.warnings)
    assert "stint changes without a pit record: ['VER L21']" in report.warnings


def test_tyre_change_under_red_flag_is_not_an_unpitted_stint(raw_race: RaceTables) -> None:
    laps = raw_race.laps.copy()
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
        replace(raw_race, laps=laps, neutralisations=red), ALLOCATION, CONFIG, []
    )
    assert report.warnings == []


def test_race_without_pit_records_gets_one_warning(raw_race: RaceTables) -> None:
    report = validate_race(replace(raw_race, pits=raw_race.pits.head(0)), ALLOCATION, CONFIG, [])
    assert report.warnings == ["OpenF1 has no pit records for this race; pit_in is all false"]


def test_summary_merges_rounds(raw_race: RaceTables, tmp_path) -> None:
    report = validate_race(raw_race, ALLOCATION, CONFIG, [])
    write_summary(tmp_path, [report.model_copy(update={"round": 3})])
    path = write_summary(tmp_path, [report.model_copy(update={"round": 1})])
    write_summary(tmp_path, [report.model_copy(update={"round": 3, "warnings": ["w"]})])
    summary = json.loads(path.read_text())
    assert list(summary) == ["1", "3"]
    assert summary["3"]["warnings"] == ["w"]


def position_feed(state: pd.DataFrame) -> pd.DataFrame:
    """An OpenF1 position feed that agrees with the race state."""
    return pd.DataFrame(
        {
            "driver": state["driver"].astype("string"),
            "utc": state["crossing_utc"],
            "position": state["position"].astype("int64"),
        }
    )


Feed = Callable[[pd.DataFrame], pd.DataFrame]


def prepared_report(raw: RaceTables, feed: Feed | None = position_feed) -> RaceReport:
    """Validate and prepare as `pitwall ingest` does, with `feed` built from the race state."""
    report = validate_race(raw, ALLOCATION, CONFIG, [])
    tables = prepare_race(raw, CLASSIFICATION)
    if feed is not None:
        tables = replace(tables, positions=feed(tables.race_state))
    return check_prepared(tables, report, CONFIG, CLASSIFICATION)


def test_prepared_race_reports_order_agreement_and_lap_classes(raw_race: RaceTables) -> None:
    report = prepared_report(raw_race)
    assert (report.errors, report.warnings) == ([], [])
    assert report.position_agreement == 1.0
    assert sum(report.lap_classes.values()) == report.lap_rows
    assert report.lap_classes["clean"] > 0


def test_missing_or_disagreeing_position_feed_is_a_warning(raw_race: RaceTables) -> None:
    missing = prepared_report(raw_race, feed=None)
    assert missing.warnings == ["no OpenF1 position feed; race-state order unchecked"]

    def reversed_feed(state: pd.DataFrame) -> pd.DataFrame:
        feed = position_feed(state)
        return feed.assign(position=4 - feed["position"])

    [warning] = prepared_report(raw_race, reversed_feed).warnings
    assert "matches the position feed on only" in warning


def test_uncleared_yellow_is_capped_and_reported(raw_race: RaceTables) -> None:
    yellows = pd.DataFrame(
        {
            "sector": pd.Series([7], dtype="int64"),
            "start_utc": [RACE_START + pd.Timedelta(minutes=5)],
            "end_utc": [RACE_START + pd.Timedelta(minutes=95)],
        }
    )
    report = prepared_report(replace(raw_race, yellows=yellows))
    [warning] = report.warnings
    assert "sectors [7]" in warning
    tables = prepare_race(replace(raw_race, yellows=yellows), CLASSIFICATION)
    yellow_laps = tables.laps.loc[tables.laps["lap_class"] == "yellow", "lap"]
    assert yellow_laps.max() < 15  # 15 minutes of yellow, not the whole race
