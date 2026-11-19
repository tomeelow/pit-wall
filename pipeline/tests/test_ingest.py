import pandas as pd

from pitwall.ingest.fastf1_race import canonical_laps
from pitwall.ingest.storage import RaceTables, dataset_fingerprint, read_race, write_race
from tests.conftest import fastf1_laps


def test_canonical_laps_types_and_units(race_tables: RaceTables) -> None:
    laps = race_tables.laps
    assert laps["lap"].dtype == "int64"
    assert laps["tyre_age"].dtype == "Int64"
    assert laps["lap_time_s"].iloc[0] == 95.0


def test_unrecognised_compound_maps_to_unknown() -> None:
    raw = fastf1_laps("VER", "Red Bull Racing", [("TEST_UNKNOWN", 2, 0)])
    raw.loc[1, "Compound"] = None
    laps = canonical_laps(raw, season=2024, round_=1)
    assert set(laps["compound"]) == {"UNKNOWN"}


def test_pit_flags(race_tables: RaceTables) -> None:
    ver = race_tables.laps[race_tables.laps["driver"] == "VER"].set_index("lap")
    assert ver.loc[20, "pit_in"]
    assert ver.loc[21, "pit_out"]
    assert not ver.loc[1, "pit_out"]


def test_fingerprint_is_deterministic_and_content_sensitive(race_tables: RaceTables) -> None:
    laps = race_tables.laps
    assert dataset_fingerprint(laps) == dataset_fingerprint(laps.copy())

    changed = laps.copy()
    changed.loc[0, "lap_time_s"] = 95.001
    assert dataset_fingerprint(changed) != dataset_fingerprint(laps)

    renamed = laps.rename(columns={"lap_time_s": "lap_time"})
    assert dataset_fingerprint(renamed) != dataset_fingerprint(laps)


def test_fingerprint_survives_parquet_round_trip(race_tables: RaceTables, tmp_path) -> None:
    restored = read_race(write_race(tmp_path, race_tables))
    pd.testing.assert_frame_equal(restored.laps, race_tables.laps)
    assert dataset_fingerprint(restored.laps, restored.results) == dataset_fingerprint(
        race_tables.laps, race_tables.results
    )
