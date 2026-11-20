from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from pitwall.config import RaceAllocation, load_team_ids
from pitwall.ingest.neutralisations import parse_neutralisations
from pitwall.ingest.openf1 import canonical_laps, canonical_pits, canonical_results
from pitwall.ingest.storage import EventInfo, RaceTables

DRIVERS = {
    1: ("VER", "Red Bull Racing"),
    16: ("LEC", "Ferrari"),
    2: ("SAR", "Williams"),
    22: ("TSU", "RB"),
}

ALLOCATION = RaceAllocation(round=1, race="Test Grand Prix", hard=1, medium=2, soft=3)

RACE_START = pd.Timestamp("2024-03-02 15:00", tz="UTC")


@dataclass
class OpenF1Race:
    laps: pd.DataFrame
    stints: pd.DataFrame
    pits: pd.DataFrame
    drivers: pd.DataFrame


def openf1_race(plans: dict[int, list[tuple[str, int, int]]]) -> OpenF1Race:
    """OpenF1-shaped laps, stints, pits and drivers. Each stint is (compound, laps,
    tyre_age_at_start). Every stint change is a pit stop on the stint's last lap. The last stint
    of each driver has lap_end None, as OpenF1 sometimes reports."""
    laps: list[dict[str, Any]] = []
    stints: list[dict[str, Any]] = []
    pits: list[dict[str, Any]] = []
    for number, plan in plans.items():
        lap = 1
        for stint_no, (compound, n_laps, age_at_start) in enumerate(plan, start=1):
            last = stint_no == len(plan)
            stints.append(
                {
                    "driver_number": number,
                    "stint_number": stint_no,
                    "compound": compound,
                    "lap_start": lap,
                    "lap_end": None if last else lap + n_laps - 1,
                    "tyre_age_at_start": age_at_start,
                }
            )
            for i in range(n_laps):
                laps.append(
                    {
                        "driver_number": number,
                        "lap_number": lap,
                        "lap_duration": None if lap == 1 else 95 + 0.05 * i,
                        "is_pit_out_lap": i == 0 and stint_no > 1,
                    }
                )
                lap += 1
            if not last:
                pits.append(
                    {
                        "driver_number": number,
                        "lap_number": lap - 1,
                        "lane_duration": 21.5,
                        "stop_duration": 2.4,
                    }
                )
    drivers = pd.DataFrame(
        [
            {"driver_number": n, "name_acronym": code, "team_name": team}
            for n, (code, team) in DRIVERS.items()
            if n in plans
        ]
    )
    return OpenF1Race(pd.DataFrame(laps), pd.DataFrame(stints), pd.DataFrame(pits), drivers)


def canonical(
    race: OpenF1Race, allocation: RaceAllocation | None = ALLOCATION, team_ids=None
) -> pd.DataFrame:
    return canonical_laps(
        race.laps,
        race.stints,
        race.pits,
        race.drivers,
        team_ids if team_ids is not None else load_team_ids(),
        allocation,
        season=2024,
        round_=1,
    )


def message(lap: int, text: str = "", *, minute: float, flag: str | None = None) -> dict[str, Any]:
    """One OpenF1 race_control row. A flag makes it a track-wide flag message."""
    return {
        "date": (RACE_START + pd.Timedelta(minutes=minute)).isoformat(),
        "lap_number": lap,
        "category": "Flag" if flag else "SafetyCar",
        "flag": flag,
        "scope": "Track" if flag else None,
        "message": text or f"TRACK {flag}",
    }


@pytest.fixture
def race_tables() -> RaceTables:
    race = openf1_race(
        {
            1: [("MEDIUM", 20, 0), ("HARD", 37, 0)],
            16: [("SOFT", 15, 3), ("HARD", 25, 0), ("SOFT", 17, 2)],
            2: [("HARD", 30, 0)],
        }
    )
    results = pd.DataFrame(
        {
            "driver_number": [2, 16, 1],
            "position": [None, 2, 1],
            "number_of_laps": [30, 57, 57],
            "dnf": [True, False, False],
            "dns": [False, False, False],
            "dsq": [False, False, False],
        }
    )
    neutralisations, _ = parse_neutralisations(
        pd.DataFrame(
            [
                message(31, "SAFETY CAR DEPLOYED", minute=50),
                message(33, "SAFETY CAR IN THIS LAP", minute=54),
                message(57, minute=95, flag="CHEQUERED"),
            ]
        )
    )
    team_ids = load_team_ids()
    return RaceTables(
        event=EventInfo(
            season=2024,
            round=1,
            name="Test Grand Prix",
            circuit="Test",
            circuit_key=1,
            session_key=9999,
            total_laps=57,
        ),
        laps=canonical(race),
        results=canonical_results(results, race.drivers, team_ids),
        pits=canonical_pits(race.pits, race.drivers),
        neutralisations=neutralisations,
    )
