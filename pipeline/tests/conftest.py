from typing import Any

import pandas as pd
import pytest

from pitwall.ingest.openf1 import canonical_laps, canonical_results
from pitwall.ingest.storage import EventInfo, RaceTables

DRIVERS = {
    1: ("VER", "Red Bull Racing"),
    16: ("LEC", "Ferrari"),
    2: ("SAR", "Williams"),
}


def openf1_race(
    plans: dict[int, list[tuple[str, int, int]]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """OpenF1-shaped laps, stints and drivers. Each stint is (compound, laps, tyre_age_at_start).
    The last stint of each driver has lap_end None, as OpenF1 sometimes reports."""
    laps: list[dict[str, Any]] = []
    stints: list[dict[str, Any]] = []
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
    drivers = pd.DataFrame(
        [
            {"driver_number": n, "name_acronym": code, "team_name": team}
            for n, (code, team) in DRIVERS.items()
            if n in plans
        ]
    )
    return pd.DataFrame(laps), pd.DataFrame(stints), drivers


@pytest.fixture
def race_tables() -> RaceTables:
    laps, stints, drivers = openf1_race(
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
    return RaceTables(
        event=EventInfo(season=2024, round=1, name="Test Grand Prix", total_laps=57),
        laps=canonical_laps(laps, stints, drivers, season=2024, round_=1),
        results=canonical_results(results, drivers),
    )
