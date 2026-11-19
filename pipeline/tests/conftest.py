import numpy as np
import pandas as pd
import pytest

from pitwall.ingest.fastf1_race import canonical_laps, canonical_results
from pitwall.ingest.storage import EventInfo, RaceTables


def fastf1_laps(driver: str, team: str, stints: list[tuple[str, int, int]]) -> pd.DataFrame:
    """A FastF1-shaped `Laps` frame. Each stint is (compound, laps, tyre_life_at_start)."""
    rows = []
    lap = 1
    for stint_no, (compound, n_laps, life_at_start) in enumerate(stints, start=1):
        for i in range(n_laps):
            rows.append(
                {
                    "Driver": driver,
                    "Team": team,
                    "LapNumber": float(lap),
                    "LapTime": pd.Timedelta(seconds=95 + 0.05 * i),
                    "Compound": compound,
                    "TyreLife": float(life_at_start + i + 1),
                    "Stint": float(stint_no),
                    "Position": 1.0,
                    "PitInTime": pd.Timedelta(minutes=lap) if i == n_laps - 1 else None,
                    "PitOutTime": pd.Timedelta(minutes=lap) if i == 0 and stint_no > 1 else None,
                    "TrackStatus": "1",
                }
            )
            lap += 1
    frame = pd.DataFrame(rows)
    for column in ("PitInTime", "PitOutTime"):
        frame[column] = pd.to_timedelta(frame[column])
    return frame


@pytest.fixture
def race_tables() -> RaceTables:
    raw_laps = pd.concat(
        [
            fastf1_laps("VER", "Red Bull Racing", [("MEDIUM", 20, 0), ("HARD", 37, 0)]),
            fastf1_laps("LEC", "Ferrari", [("SOFT", 15, 3), ("HARD", 25, 0), ("SOFT", 17, 2)]),
            fastf1_laps("SAR", "Williams", [("HARD", 30, 0)]),
        ],
        ignore_index=True,
    )
    raw_results = pd.DataFrame(
        {
            "Abbreviation": ["SAR", "LEC", "VER"],
            "TeamName": ["Williams", "Ferrari", "Red Bull Racing"],
            "Position": [np.nan, 2.0, 1.0],
            "Status": ["Retired", "Finished", "Finished"],
        }
    )
    return RaceTables(
        event=EventInfo(season=2024, round=1, name="Test Grand Prix", total_laps=57),
        laps=canonical_laps(raw_laps, season=2024, round_=1),
        results=canonical_results(raw_results),
    )
