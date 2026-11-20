from datetime import datetime
from typing import Any

import pandas as pd
import pytest

from pitwall.config import load_team_ids
from pitwall.ingest.openf1 import (
    canonical_pits,
    canonical_results,
    find_race_session,
    finished_rounds,
)
from pitwall.ingest.storage import RaceTables, dataset_fingerprint, read_race, write_race
from tests.conftest import canonical, openf1_race


def test_one_row_per_driver_lap(race_tables: RaceTables) -> None:
    laps = race_tables.laps
    assert not laps.duplicated(["driver", "lap"]).any()
    assert laps.groupby("driver")["lap"].max().to_dict() == {"LEC": 57, "SAR": 30, "VER": 57}


def test_tyre_age_counts_laps_before_the_stint(race_tables: RaceTables) -> None:
    lec = race_tables.laps[race_tables.laps["driver"] == "LEC"].set_index("lap")
    assert lec.loc[1, "tyre_age"] == 4  # used set: 3 laps old at the start
    assert lec.loc[16, "tyre_age"] == 1  # new set
    assert lec.loc[57, "tyre_age"] == 19  # open-ended final stint, 2 laps old at the start


def test_missing_lap_time_stays_missing(race_tables: RaceTables) -> None:
    ver = race_tables.laps[race_tables.laps["driver"] == "VER"].set_index("lap")
    assert pd.isna(ver.loc[1, "lap_time_s"])
    assert ver.loc[2, "lap_time_s"] == pytest.approx(95.05)


def test_c_number_follows_the_race_allocation(race_tables: RaceTables) -> None:
    by_compound = race_tables.laps.groupby("compound")["compound_c"].unique()
    assert {c: list(v) for c, v in by_compound.items()} == {
        "HARD": [1],
        "MEDIUM": [2],
        "SOFT": [3],
    }


def test_wet_compounds_and_missing_allocation_have_no_c_number() -> None:
    race = openf1_race({1: [("INTERMEDIATE", 5, 0), ("SOFT", 5, 0)]})
    assert canonical(race)["compound_c"].isna().tolist() == [True] * 5 + [False] * 5
    assert canonical(race, allocation=None)["compound_c"].isna().all()


def test_team_lineages_share_a_team_id() -> None:
    team_ids = load_team_ids()
    assert {team_ids[name] for name in ("AlphaTauri", "RB", "Racing Bulls")} == {"racing_bulls"}
    assert {team_ids[name] for name in ("Alfa Romeo", "Kick Sauber", "Audi")} == {"sauber"}

    laps = canonical(openf1_race({22: [("SOFT", 3, 0)], 1: [("SOFT", 3, 0)]}))
    assert laps.groupby("driver")["team_id"].first().to_dict() == {
        "TSU": "racing_bulls",
        "VER": "red_bull",
    }


def test_unknown_team_has_no_team_id() -> None:
    laps = canonical(openf1_race({1: [("SOFT", 3, 0)]}), team_ids={"Ferrari": "ferrari"})
    assert laps["team_id"].isna().all()


def test_pit_in_marks_the_in_lap(race_tables: RaceTables) -> None:
    lec = race_tables.laps[race_tables.laps["driver"] == "LEC"]
    assert lec.loc[lec["pit_in"], "lap"].tolist() == [15, 40]
    assert lec.loc[lec["pit_out"], "lap"].tolist() == [16, 41]


def test_stint_starting_on_the_in_lap_moves_to_the_out_lap() -> None:
    race = openf1_race({1: [("MEDIUM", 20, 0), ("HARD", 10, 0)]})
    race.stints.loc[0, "lap_end"] = 19  # source error: new stint starts on the in-lap (20)
    race.stints.loc[1, "lap_start"] = 20
    ver = {row["lap"]: row for row in canonical(race).to_dict("records")}
    in_lap, out_lap = ver[20], ver[21]
    assert (in_lap["compound"], in_lap["tyre_age"], in_lap["pit_in"]) == ("MEDIUM", 20, True)
    assert (out_lap["compound"], out_lap["tyre_age"], out_lap["pit_out"]) == ("HARD", 1, True)


def test_stints_after_consecutive_pit_laps_stay_put() -> None:
    race = openf1_race({1: [("SOFT", 10, 0), ("INTERMEDIATE", 1, 0), ("INTERMEDIATE", 5, 0)]})
    extra = {"driver_number": 1, "lap_number": 11, "lane_duration": 900.0, "stop_duration": 2.5}
    race.pits = pd.concat([race.pits, pd.DataFrame([extra])], ignore_index=True)
    laps = canonical(race)
    assert laps.groupby("stint")["lap"].agg(["min", "max"]).values.tolist() == [
        [1, 10],
        [11, 11],
        [12, 16],
    ]


def test_unrecognised_compound_maps_to_unknown() -> None:
    race = openf1_race({1: [("TEST_UNKNOWN", 2, 0)]})
    race.stints["compound"] = [None]
    laps = canonical(race)
    assert set(laps["compound"]) == {"UNKNOWN"}
    assert laps["compound_c"].isna().all()


def test_overlapping_stints_do_not_duplicate_laps() -> None:
    race = openf1_race({1: [("MEDIUM", 10, 0), ("HARD", 10, 0)]})
    race.stints.loc[0, "lap_end"] = 12  # source error: stint 1 claims laps 11-12 too
    laps = canonical(race)
    assert len(laps) == 20
    assert laps.set_index("lap").loc[11, "compound"] == "HARD"


def test_results_status_and_order() -> None:
    drivers = openf1_race({1: [], 16: [], 2: []}).drivers
    results = pd.DataFrame(
        {
            "driver_number": [2, 16, 1],
            "position": [None, None, 1],
            "number_of_laps": [5, 30, 57],
            "dnf": [True, False, False],
            "dns": [False, False, False],
            "dsq": [False, True, False],
        }
    )
    canonical_ = canonical_results(results, drivers, load_team_ids())
    assert canonical_["driver"].tolist() == ["VER", "LEC", "SAR"]
    assert canonical_["status"].tolist() == ["Finished", "DSQ", "DNF"]
    assert canonical_["team_id"].tolist() == ["red_bull", "ferrari", "williams"]


def test_pits_fall_back_to_pit_duration_and_keep_dtypes_when_empty() -> None:
    drivers = openf1_race({1: []}).drivers
    old = pd.DataFrame({"driver_number": [1], "lap_number": [20], "pit_duration": [22.1]})
    pits = canonical_pits(old, drivers)
    assert pits.to_dict("records")[0]["lane_s"] == pytest.approx(22.1)
    assert pits["stop_s"].isna().all()

    empty = canonical_pits(pd.DataFrame(), drivers)
    assert empty.empty
    assert empty.dtypes.to_dict() == pits.dtypes.to_dict()


class FakeClient:
    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        self.sessions = sessions

    def get(self, endpoint: str, **params: int | str) -> list[dict[str, Any]]:
        assert endpoint == "sessions"
        return self.sessions


CALENDAR = FakeClient(
    [
        {
            "session_key": 3,
            "date_start": "2023-05-28T13:00:00+00:00",
            "date_end": "2023-05-28T15:00:00+00:00",
            "is_cancelled": False,
        },
        {
            "session_key": 1,
            "date_start": "2023-03-05T15:00:00+00:00",
            "date_end": "2023-03-05T17:00:00+00:00",
            "is_cancelled": False,
        },
        {
            "session_key": 2,
            "date_start": "2023-05-21T13:00:00+00:00",
            "date_end": "2023-05-21T15:00:00+00:00",
            "is_cancelled": True,
        },
    ]
)


def test_round_is_calendar_position_skipping_cancelled_races() -> None:
    assert find_race_session(CALENDAR, 2023, 1)["session_key"] == 1
    assert find_race_session(CALENDAR, 2023, 2)["session_key"] == 3
    with pytest.raises(ValueError, match="round 3"):
        find_race_session(CALENDAR, 2023, 3)


def test_finished_rounds_wait_after_the_race() -> None:
    def rounds(now: str) -> list[int]:
        return finished_rounds(CALENDAR, 2023, datetime.fromisoformat(now), min_hours_after=12)

    assert rounds("2023-05-29T02:59:00+00:00") == [1]
    assert rounds("2023-05-29T03:00:00+00:00") == [1, 2]
    assert rounds("2023-03-01T00:00:00+00:00") == []


def test_fingerprint_is_deterministic_and_content_sensitive(race_tables: RaceTables) -> None:
    laps = race_tables.laps
    assert dataset_fingerprint(laps) == dataset_fingerprint(laps.copy())

    changed = laps.copy()
    changed.loc[1, "lap_time_s"] = 95.001
    assert dataset_fingerprint(changed) != dataset_fingerprint(laps)

    renamed = laps.rename(columns={"lap_time_s": "lap_time"})
    assert dataset_fingerprint(renamed) != dataset_fingerprint(laps)


def test_race_survives_parquet_round_trip(race_tables: RaceTables, tmp_path) -> None:
    restored = read_race(write_race(tmp_path, race_tables))
    for name in ("laps", "results", "pits", "neutralisations"):
        pd.testing.assert_frame_equal(getattr(restored, name), getattr(race_tables, name))
    assert restored.event == race_tables.event
    assert restored.fingerprint() == race_tables.fingerprint()
