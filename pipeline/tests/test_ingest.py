from typing import Any

import pandas as pd
import pytest

from pitwall.ingest.openf1 import canonical_laps, canonical_results, find_race_session
from pitwall.ingest.storage import RaceTables, dataset_fingerprint, read_race, write_race
from tests.conftest import openf1_race


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


def test_unrecognised_compound_maps_to_unknown() -> None:
    laps, stints, drivers = openf1_race({1: [("TEST_UNKNOWN", 2, 0)]})
    stints["compound"] = [None]
    canonical = canonical_laps(laps, stints, drivers, season=2024, round_=1)
    assert set(canonical["compound"]) == {"UNKNOWN"}


def test_overlapping_stints_do_not_duplicate_laps() -> None:
    laps, stints, drivers = openf1_race({1: [("MEDIUM", 10, 0), ("HARD", 10, 0)]})
    stints.loc[0, "lap_end"] = 12  # source error: stint 1 claims laps 11-12 too
    canonical = canonical_laps(laps, stints, drivers, season=2024, round_=1)
    assert len(canonical) == 20
    assert canonical.set_index("lap").loc[11, "compound"] == "HARD"


def test_results_status_and_order() -> None:
    _, _, drivers = openf1_race({1: [], 16: [], 2: []})
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
    canonical = canonical_results(results, drivers)
    assert canonical["driver"].tolist() == ["VER", "LEC", "SAR"]
    assert canonical["status"].tolist() == ["Finished", "DSQ", "DNF"]


class FakeClient:
    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        self.sessions = sessions

    def get(self, endpoint: str, **params: int | str) -> list[dict[str, Any]]:
        assert endpoint == "sessions"
        return self.sessions


def test_round_is_calendar_position_skipping_cancelled_races() -> None:
    client = FakeClient(
        [
            {"session_key": 3, "date_start": "2023-05-28", "is_cancelled": False},
            {"session_key": 1, "date_start": "2023-03-05", "is_cancelled": False},
            {"session_key": 2, "date_start": "2023-05-21", "is_cancelled": True},
        ]
    )
    assert find_race_session(client, 2023, 1)["session_key"] == 1
    assert find_race_session(client, 2023, 2)["session_key"] == 3
    with pytest.raises(ValueError, match="round 3"):
        find_race_session(client, 2023, 3)


def test_fingerprint_is_deterministic_and_content_sensitive(race_tables: RaceTables) -> None:
    laps = race_tables.laps
    assert dataset_fingerprint(laps) == dataset_fingerprint(laps.copy())

    changed = laps.copy()
    changed.loc[1, "lap_time_s"] = 95.001
    assert dataset_fingerprint(changed) != dataset_fingerprint(laps)

    renamed = laps.rename(columns={"lap_time_s": "lap_time"})
    assert dataset_fingerprint(renamed) != dataset_fingerprint(laps)


def test_fingerprint_survives_parquet_round_trip(race_tables: RaceTables, tmp_path) -> None:
    restored = read_race(write_race(tmp_path, race_tables))
    pd.testing.assert_frame_equal(restored.laps, race_tables.laps)
    assert dataset_fingerprint(restored.laps, restored.results) == dataset_fingerprint(
        race_tables.laps, race_tables.results
    )
