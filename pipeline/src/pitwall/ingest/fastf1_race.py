"""Race ingestion from FastF1 into the canonical lap and result tables."""

from pathlib import Path

import fastf1
import pandas as pd
from fastf1.exceptions import DataNotLoadedError
from loguru import logger

from pitwall.ingest.storage import EventInfo, RaceTables

COMPOUNDS = ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET")
UNKNOWN_COMPOUND = "UNKNOWN"


def fetch_race(season: int, round_: int, cache_dir: Path) -> RaceTables:
    cache_dir.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache_dir))
    fastf1.set_log_level("WARNING")

    session = fastf1.get_session(season, round_, "R")
    session.load(laps=True, telemetry=False, weather=False, messages=False)
    try:
        raw_laps = session.laps
    except DataNotLoadedError as exc:
        # FastF1 only warns when sign-in fails and then loads an empty session.
        raise RuntimeError(
            f"No timing data for {season} round {round_}. The F1 live-timing archive needs an "
            "F1 account: run `uv run python -m fastf1 auth f1tv --authenticate` once locally, "
            "or set F1_USERNAME and F1_PASSWORD (CI secrets)."
        ) from exc

    laps = canonical_laps(pd.DataFrame(raw_laps), season, round_)
    results = canonical_results(pd.DataFrame(session.results))
    event = EventInfo(
        season=season,
        round=round_,
        name=str(session.event["EventName"]),
        total_laps=int(laps["lap"].max()),
    )
    logger.info(
        "{} {} R{}: {} laps rows, {} drivers",
        event.name,
        season,
        round_,
        len(laps),
        len(results),
    )
    return RaceTables(event=event, laps=laps, results=results)


def canonical_laps(raw: pd.DataFrame, season: int, round_: int) -> pd.DataFrame:
    """FastF1 `Laps` → canonical lap table. Lap classification is Phase 2, not done here."""
    compound = raw["Compound"].where(raw["Compound"].isin(COMPOUNDS), UNKNOWN_COMPOUND)
    return pd.DataFrame(
        {
            "season": season,
            "round": round_,
            "driver": raw["Driver"].astype(str),
            "team": raw["Team"].astype(str),
            "lap": raw["LapNumber"].astype("int64"),
            "lap_time_s": raw["LapTime"].dt.total_seconds(),
            "compound": compound.astype(str),
            # FastF1 TyreLife counts laps on the set at the end of this lap, including laps run
            # in earlier sessions on a used set.
            "tyre_age": raw["TyreLife"].astype("Int64"),
            "stint": raw["Stint"].astype("Int64"),
            "position": raw["Position"].astype("Int64"),
            "pit_in": raw["PitInTime"].notna(),
            "pit_out": raw["PitOutTime"].notna(),
            "track_status": raw["TrackStatus"].fillna("").astype(str),
        }
    ).reset_index(drop=True)


def canonical_results(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "driver": raw["Abbreviation"].astype(str),
            "team": raw["TeamName"].astype(str),
            "position": raw["Position"].astype("Int64"),
            "status": raw["Status"].fillna("").astype(str),
        }
    ).reset_index(drop=True)
