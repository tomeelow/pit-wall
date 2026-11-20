from typing import Any

import pandas as pd

from pitwall.ingest.storage import RaceTables
from pitwall.laps import LAP_CLASSES
from pitwall.prepare import prepare_race
from tests.conftest import (
    CONFIG,
    RACE_START,
    OpenF1Race,
    message,
    openf1_race,
    results_frame,
    source_tables,
)


def lap_start(race: OpenF1Race, number: int, lap: int) -> pd.Timestamp:
    laps = race.laps
    row = laps[(laps["driver_number"] == number) & (laps["lap_number"] == lap)]
    return pd.Timestamp(row["date_start"].iloc[0])


def at(utc: pd.Timestamp, lap: int, text: str = "", **flag: Any) -> dict[str, Any]:
    """A race-control message at `utc`, built on `message` (which counts minutes from start)."""
    row = message(lap, text, minute=(utc - RACE_START).total_seconds() / 60, flag=flag.get("flag"))
    if "sector" in flag:
        row.update(scope="Sector", sector=flag["sector"], message=f"{flag['flag']} IN SECTOR")
    return row


def prepared(race: OpenF1Race, race_control: list[dict[str, Any]], dnf=()) -> RaceTables:
    numbers = race.drivers["driver_number"].tolist()
    last_lap = race.laps.groupby("driver_number")["lap_number"].max()
    laps_run = {int(n): int(last_lap[n]) for n in numbers}
    finish = {n: None if n in dnf else i + 1 for i, n in enumerate(numbers)}
    raw = source_tables(race, results_frame(finish, laps_run, dnf), race_control)
    return prepare_race(raw, CONFIG.classification)


def classes(tables: RaceTables, driver: str) -> dict[int, str]:
    laps = tables.laps[tables.laps["driver"] == driver]
    return dict(zip(laps["lap"], laps["lap_class"], strict=True))


def test_each_class() -> None:
    race = openf1_race({1: [("MEDIUM", 10, 0), ("HARD", 10, 0)], 16: [("INTERMEDIATE", 20, 0)]})
    slow = (race.laps["driver_number"] == 1) & (race.laps["lap_number"] == 15)
    race.laps.loc[slow, "lap_duration"] += 10  # a mistake
    yellow_at = lap_start(race, 1, 5) + pd.Timedelta(seconds=20)
    tables = prepared(
        race,
        [
            at(yellow_at, 5, flag="YELLOW", sector=4),
            at(yellow_at + pd.Timedelta(seconds=15), 5, flag="CLEAR", sector=4),
        ],
    )
    ver, lec = classes(tables, "VER"), classes(tables, "LEC")
    assert [ver[lap] for lap in (1, 2, 5, 10, 11, 15, 16)] == [
        "lap1",
        "clean",
        "yellow",
        "in_lap",
        "out_lap",
        "outlier",
        "clean",
    ]
    assert set(lec.values()) == {"lap1", "wet"}
    assert set(tables.laps["lap_class"]) <= set(LAP_CLASSES)


def test_traffic_is_a_lap_started_close_behind_another_car() -> None:
    close = prepared(openf1_race({1: [("SOFT", 6, 0)], 16: [("SOFT", 6, 0)]}, spacing_s=1.0), [])
    assert classes(close, "LEC") == {1: "lap1", **{lap: "traffic" for lap in range(2, 7)}}
    assert set(classes(close, "VER").values()) == {"lap1", "clean"}

    apart = prepared(openf1_race({1: [("SOFT", 6, 0)], 16: [("SOFT", 6, 0)]}, spacing_s=2.0), [])
    assert set(classes(apart, "LEC").values()) == {"lap1", "clean"}


def test_safety_car_and_vsc() -> None:
    race = openf1_race({1: [("SOFT", 20, 0)], 16: [("SOFT", 20, 0)]})
    second = pd.Timedelta(seconds=30)
    tables = prepared(
        race,
        [
            at(lap_start(race, 1, 5) + second, 5, "SAFETY CAR DEPLOYED"),
            at(lap_start(race, 1, 7) + second, 7, "SAFETY CAR IN THIS LAP"),
            at(lap_start(race, 1, 12) + second, 12, "VIRTUAL SAFETY CAR DEPLOYED"),
            at(lap_start(race, 1, 13) + second, 13, "VIRTUAL SAFETY CAR ENDING"),
            at(lap_start(race, 1, 20) + second, 20, flag="CHEQUERED"),
        ],
    )
    for driver in ("VER", "LEC"):
        lap_class = classes(tables, driver)
        neutralised = [lap for lap, c in lap_class.items() if c == "neutralised"]
        assert neutralised == [5, 6, 7, 8, 12, 13]  # 8 is the restart lap; VSC has none
        assert lap_class[14] == "clean"
    status = tables.laps.set_index(["driver", "lap"])["track_status"]
    assert [status[("VER", lap)] for lap in (4, 5, 8, 12)] == ["GREEN", "SC", "GREEN", "VSC"]


def test_red_flag_and_inferred_in_laps() -> None:
    """Shaped like early 2023 races: no pit records, so in-laps come from the out-lap flag."""
    race = openf1_race({1: [("MEDIUM", 12, 0), ("HARD", 28, 0)], 16: [("HARD", 40, 0)]})
    race.pits = race.pits.head(0)
    red_at = lap_start(race, 1, 20) + pd.Timedelta(seconds=30)
    green_at = red_at + pd.Timedelta(minutes=4)
    tables = prepared(
        race,
        [
            at(red_at, 20, flag="RED"),
            {**at(green_at, 22, "SESSION STARTED"), "category": "SessionStatus"},
            at(lap_start(race, 1, 40) + pd.Timedelta(seconds=30), 40, flag="CHEQUERED"),
        ],
    )
    ver = classes(tables, "VER")
    assert (ver[12], ver[13]) == ("in_lap", "out_lap")

    laps = tables.laps[tables.laps["driver"] == "VER"].set_index("lap")
    red = laps.index[laps["track_status"] == "RED"].tolist()
    restart = int(laps.index[laps["lap_start_utc"] >= green_at].min())
    assert red == list(range(20, restart))
    assert [ver[lap] for lap in [*red, restart]] == ["neutralised"] * (len(red) + 1)
    assert ver[restart + 1] == "clean"


def test_pitting_under_the_safety_car_is_an_in_and_out_lap() -> None:
    race = openf1_race({1: [("SOFT", 6, 0), ("HARD", 6, 0)]})
    tables = prepared(
        race,
        [
            at(lap_start(race, 1, 5) + pd.Timedelta(seconds=30), 5, "SAFETY CAR DEPLOYED"),
            at(lap_start(race, 1, 8) + pd.Timedelta(seconds=30), 8, "SAFETY CAR IN THIS LAP"),
            at(lap_start(race, 1, 12) + pd.Timedelta(seconds=30), 12, flag="CHEQUERED"),
        ],
    )
    ver = classes(tables, "VER")
    assert [ver[lap] for lap in (5, 6, 7, 8, 9)] == [
        "neutralised",
        "in_lap",
        "out_lap",
        "neutralised",
        "neutralised",
    ]


def test_retiring_driver_is_classified_until_retirement() -> None:
    race = openf1_race({1: [("SOFT", 10, 0)], 2: [("SOFT", 4, 0)]})
    tables = prepared(race, [], dnf={2})
    assert list(classes(tables, "SAR")) == [1, 2, 3, 4]
    assert tables.race_state.query("driver == 'SAR'")["retired"].tolist()[-1]


def test_lap_without_a_time_is_an_outlier() -> None:
    race = openf1_race({1: [("SOFT", 6, 0)]})
    race.laps.loc[race.laps["lap_number"] == 4, "lap_duration"] = None
    assert classes(prepared(race, []), "VER")[4] == "outlier"
