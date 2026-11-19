"""Race ingestion from OpenF1 into the canonical lap and result tables."""

from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from loguru import logger
from requests.adapters import HTTPAdapter
from requests_cache import CachedSession
from urllib3.util.retry import Retry

from pitwall.ingest.storage import EventInfo, RaceTables

COMPOUNDS = ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET")
UNKNOWN_COMPOUND = "UNKNOWN"

Records = list[dict[str, Any]]


class Client(Protocol):
    def get(self, endpoint: str, **params: int | str) -> Records: ...


class OpenF1:
    """Cached, retrying client. Every raw response is kept on disk, so a finished session is
    downloaded once and the free tier's rate limit is only hit on first pulls."""

    def __init__(self, base_url: str, cache_path: Path) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._base_url = base_url.rstrip("/")
        self._session = CachedSession(str(cache_path), backend="sqlite", allowable_codes=(200,))
        retry = Retry(
            total=6,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            respect_retry_after_header=True,
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))

    def get(self, endpoint: str, **params: int | str) -> Records:
        response = self._session.get(f"{self._base_url}/{endpoint}", params=params, timeout=60)
        response.raise_for_status()
        return response.json()


def find_race_session(client: Client, season: int, round_: int) -> dict[str, Any]:
    """OpenF1 has no round numbers: the round is the race's position in the season's calendar
    of non-cancelled Grands Prix (sprints are separate sessions and don't count)."""
    races = sorted(
        (
            s
            for s in client.get("sessions", year=season, session_name="Race")
            if not s["is_cancelled"]
        ),
        key=lambda s: s["date_start"],
    )
    if not 1 <= round_ <= len(races):
        raise ValueError(f"{season} has {len(races)} races in OpenF1; round {round_} not found")
    return races[round_ - 1]


def fetch_race(season: int, round_: int, client: Client) -> RaceTables:
    session = find_race_session(client, season, round_)
    key = session["session_key"]
    meeting = client.get("meetings", meeting_key=session["meeting_key"])[0]

    drivers = pd.DataFrame(client.get("drivers", session_key=key))
    laps = canonical_laps(
        laps=pd.DataFrame(client.get("laps", session_key=key)),
        stints=pd.DataFrame(client.get("stints", session_key=key)),
        drivers=drivers,
        season=season,
        round_=round_,
    )
    results = canonical_results(
        pd.DataFrame(client.get("session_result", session_key=key)), drivers
    )
    if laps.empty or results.empty:
        raise RuntimeError(f"OpenF1 returned no laps or results for {season} round {round_}")

    event = EventInfo(
        season=season,
        round=round_,
        name=meeting["meeting_name"],
        total_laps=int(laps["lap"].max()),
    )
    logger.info(
        "{} {} R{} (session {}): {} lap rows, {} drivers",
        event.name,
        season,
        round_,
        key,
        len(laps),
        len(results),
    )
    return RaceTables(event=event, laps=laps, results=results)


def canonical_laps(
    laps: pd.DataFrame,
    stints: pd.DataFrame,
    drivers: pd.DataFrame,
    season: int,
    round_: int,
) -> pd.DataFrame:
    """OpenF1 laps + stints → canonical lap table, one row per driver per lap.

    Lap classification (in/out laps, neutralisations, traffic) is Phase 2, not done here.
    """
    joined = laps.merge(drivers[["driver_number", "name_acronym", "team_name"]], on="driver_number")
    joined = joined.merge(stints, on="driver_number", suffixes=("", "_stint"))
    # A missing lap_end means the stint ran to the flag. An all-missing column arrives as
    # object dtype from JSON, so coerce before comparing.
    lap_end = pd.to_numeric(joined["lap_end"])
    in_stint = (joined["lap_number"] >= joined["lap_start"]) & (
        lap_end.isna() | (joined["lap_number"] <= lap_end)
    )
    # Overlapping stints in the source would duplicate laps; keep the later stint.
    joined = (
        joined[in_stint]
        .sort_values(["driver_number", "lap_number", "stint_number"])
        .drop_duplicates(["driver_number", "lap_number"], keep="last")
    )
    compound = joined["compound"].where(joined["compound"].isin(COMPOUNDS), UNKNOWN_COMPOUND)
    return pd.DataFrame(
        {
            "season": season,
            "round": round_,
            "driver": joined["name_acronym"].astype(str),
            "team": joined["team_name"].astype(str),
            "lap": joined["lap_number"].astype("int64"),
            "lap_time_s": joined["lap_duration"].astype("float64"),
            "compound": compound.astype(str),
            # Laps on the set at the end of this lap, including laps run before this stint.
            "tyre_age": (
                joined["tyre_age_at_start"] + joined["lap_number"] - joined["lap_start"] + 1
            ).astype("Int64"),
            "stint": joined["stint_number"].astype("Int64"),
            "pit_out": joined["is_pit_out_lap"].fillna(False).astype(bool),
        }
    ).reset_index(drop=True)


def canonical_results(results: pd.DataFrame, drivers: pd.DataFrame) -> pd.DataFrame:
    """Classified drivers by position, then unclassified ones by laps completed."""
    joined = results.merge(
        drivers[["driver_number", "name_acronym", "team_name"]], on="driver_number"
    )
    status = pd.Series("Finished", index=joined.index)
    status[joined["dnf"]] = "DNF"
    status[joined["dns"]] = "DNS"
    status[joined["dsq"]] = "DSQ"
    joined = joined.assign(status=status).sort_values(
        ["position", "number_of_laps"], ascending=[True, False], na_position="last"
    )
    return pd.DataFrame(
        {
            "driver": joined["name_acronym"].astype(str),
            "team": joined["team_name"].astype(str),
            "position": joined["position"].astype("Int64"),
            "status": joined["status"].astype(str),
        }
    ).reset_index(drop=True)
