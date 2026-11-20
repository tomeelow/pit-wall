"""Race ingestion from OpenF1 into the canonical race tables."""

import time
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from requests.adapters import HTTPAdapter
from requests_cache import CachedSession
from urllib3.util.retry import Retry

from pitwall.config import RaceAllocation
from pitwall.ingest.neutralisations import parse_neutralisations, parse_yellows
from pitwall.ingest.storage import EventInfo, RaceTables

COMPOUNDS = ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET")
UNKNOWN_COMPOUND = "UNKNOWN"

Records = list[dict[str, Any]]


class Client(Protocol):
    def get(self, endpoint: str, **params: int | str) -> Records: ...


class OpenF1:
    """Cached, retrying client. Finished sessions never change, so their responses are cached
    forever and downloaded once; only the season calendar expires, so new races appear."""

    def __init__(
        self,
        base_url: str,
        cache_path: Path,
        calendar_cache_hours: float,
        min_interval_s: float,
        refresh: bool = False,
    ) -> None:
        """refresh: download again and update the cache, for a race whose results may have been
        amended since it was cached."""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._base_url = base_url.rstrip("/")
        self._min_interval_s = min_interval_s
        self._refresh = refresh
        calendar = f"{self._base_url.split('://', 1)[-1]}/sessions"
        self._session = CachedSession(
            str(cache_path),
            backend="sqlite",
            allowable_codes=(200, 404),
            urls_expire_after={calendar: timedelta(hours=calendar_cache_hours)},
        )
        retry = Retry(
            total=6,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            respect_retry_after_header=True,
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))

    def get(self, endpoint: str, **params: int | str) -> Records:
        response = self._session.get(
            f"{self._base_url}/{endpoint}",
            params=params,
            timeout=60,
            force_refresh=self._refresh,
        )
        if not response.from_cache:
            time.sleep(self._min_interval_s)
        # OpenF1 answers an empty result set with 404 rather than [].
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json()


def race_sessions(client: Client, season: int) -> Records:
    """The season's Grands Prix in calendar order. OpenF1 has no round numbers: the round is the
    race's position among non-cancelled `Race` sessions (sprints are separate sessions)."""
    return sorted(
        (
            s
            for s in client.get("sessions", year=season, session_name="Race")
            if not s["is_cancelled"]
        ),
        key=lambda s: s["date_start"],
    )


def find_race_session(client: Client, season: int, round_: int) -> dict[str, Any]:
    races = race_sessions(client, season)
    if not 1 <= round_ <= len(races):
        raise ValueError(f"{season} has {len(races)} races in OpenF1; round {round_} not found")
    return races[round_ - 1]


def finished_rounds(
    client: Client, season: int, now: datetime, min_hours_after: float
) -> list[int]:
    cutoff = now - timedelta(hours=min_hours_after)
    return [
        round_
        for round_, session in enumerate(race_sessions(client, season), start=1)
        if datetime.fromisoformat(session["date_end"]) <= cutoff
    ]


def fetch_race(
    season: int,
    round_: int,
    client: Client,
    team_ids: dict[str, str],
    allocation: RaceAllocation | None,
) -> tuple[RaceTables, list[str]]:
    """The race's source tables, plus issues found while parsing race control. Laps are not yet
    classified and race_state is empty: `pitwall.prepare.prepare_race` derives both."""
    session = find_race_session(client, season, round_)
    key = session["session_key"]
    meeting = client.get("meetings", meeting_key=session["meeting_key"])[0]

    drivers = pd.DataFrame(client.get("drivers", session_key=key))
    pits = pd.DataFrame(client.get("pit", session_key=key))
    laps = canonical_laps(
        laps=pd.DataFrame(client.get("laps", session_key=key)),
        stints=pd.DataFrame(client.get("stints", session_key=key)),
        pits=pits,
        drivers=drivers,
        team_ids=team_ids,
        allocation=allocation,
        season=season,
        round_=round_,
    )
    results = canonical_results(
        pd.DataFrame(client.get("session_result", session_key=key)), drivers, team_ids
    )
    race_control = pd.DataFrame(client.get("race_control", session_key=key))
    neutralisations, issues = parse_neutralisations(race_control)
    if laps.empty or results.empty:
        raise RuntimeError(f"OpenF1 returned no laps or results for {season} round {round_}")

    tables = RaceTables(
        event=EventInfo(
            season=season,
            round=round_,
            name=meeting["meeting_name"],
            circuit=session["circuit_short_name"],
            circuit_key=session["circuit_key"],
            session_key=key,
            total_laps=int(laps["lap"].max()),
        ),
        laps=laps,
        results=results,
        pits=canonical_pits(pits, drivers),
        neutralisations=neutralisations,
        yellows=parse_yellows(race_control),
        positions=canonical_positions(
            pd.DataFrame(client.get("position", session_key=key)), drivers
        ),
        race_state=pd.DataFrame(),
    )
    return tables, [f"race control: {issue}" for issue in issues]


def _with_driver(frame: pd.DataFrame, drivers: pd.DataFrame) -> pd.DataFrame:
    return frame.merge(drivers[["driver_number", "name_acronym", "team_name"]], on="driver_number")


def _align_stints_to_pits(stints: pd.DataFrame, pit_laps: set[tuple[int, int]]) -> pd.DataFrame:
    """Some sessions start a stint on the pit in-lap. The in-lap is run on the old set (the pit
    record and is_pit_out_lap agree on that), so move the boundary to the out-lap. A stint that
    follows a pit on the previous lap is already aligned, even if it is itself a pit lap (pit
    lane queues under a red flag give pit records on consecutive laps)."""
    rows = stints.sort_values(["driver_number", "stint_number"]).to_dict("records")
    for before, row in pairwise(rows):
        driver, start = row["driver_number"], row["lap_start"]
        if (
            before["driver_number"] == driver
            and (driver, start) in pit_laps
            and (driver, start - 1) not in pit_laps
        ):
            row["lap_start"] += 1
            before["lap_end"] = row["lap_start"] - 1
    return pd.DataFrame(rows, columns=stints.columns)


def canonical_laps(
    laps: pd.DataFrame,
    stints: pd.DataFrame,
    pits: pd.DataFrame,
    drivers: pd.DataFrame,
    team_ids: dict[str, str],
    allocation: RaceAllocation | None,
    season: int,
    round_: int,
) -> pd.DataFrame:
    """OpenF1 laps + stints + pits → canonical lap table, one row per driver per lap.

    Lap classification is added later by `classify_laps`, from these columns.
    """
    # A pit record's lap is the in-lap; the next stint starts on the following lap.
    pit_laps = set(zip(pits.get("driver_number", []), pits.get("lap_number", []), strict=True))
    stints = _align_stints_to_pits(stints, pit_laps)
    joined = _with_driver(laps, drivers).merge(stints, on="driver_number", suffixes=("", "_stint"))
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
    pit_in = [
        (d, lap) in pit_laps
        for d, lap in zip(joined["driver_number"], joined["lap_number"], strict=True)
    ]
    compound = joined["compound"].where(joined["compound"].isin(COMPOUNDS), UNKNOWN_COMPOUND)
    compound_c = compound.map(lambda c: allocation.c_number(c) if allocation else None)
    return pd.DataFrame(
        {
            "season": season,
            "round": round_,
            "driver": joined["name_acronym"].astype(str),
            "team": joined["team_name"].astype(str),
            "team_id": joined["team_name"].map(team_ids).astype("string"),
            "lap": joined["lap_number"].astype("int64"),
            "lap_start_utc": _utc(joined["date_start"]),
            "lap_time_s": joined["lap_duration"].astype("float64"),
            "compound": compound.astype(str),
            "compound_c": compound_c.astype("Int64"),
            # Laps on the set at the end of this lap, including laps run before this stint.
            "tyre_age": (
                joined["tyre_age_at_start"] + joined["lap_number"] - joined["lap_start"] + 1
            ).astype("Int64"),
            "stint": joined["stint_number"].astype("Int64"),
            "pit_in": pit_in,
            "pit_out": joined["is_pit_out_lap"].fillna(False).astype(bool),
        }
    ).reset_index(drop=True)


def canonical_results(
    results: pd.DataFrame, drivers: pd.DataFrame, team_ids: dict[str, str]
) -> pd.DataFrame:
    """Classified drivers by position, then unclassified ones by laps completed."""
    joined = _with_driver(results, drivers)
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
            "team_id": joined["team_name"].map(team_ids).astype("string"),
            "position": joined["position"].astype("Int64"),
            "status": joined["status"].astype(str),
            "laps_completed": joined["number_of_laps"].astype("Int64"),
        }
    ).reset_index(drop=True)


def _utc(timestamps: pd.Series) -> pd.Series:
    return pd.to_datetime(timestamps, utc=True, format="ISO8601").astype("datetime64[ns, UTC]")


def canonical_positions(positions: pd.DataFrame, drivers: pd.DataFrame) -> pd.DataFrame:
    """OpenF1's running-order feed: one row per position change, as timed by F1."""
    columns = {"driver": "string", "utc": "datetime64[ns, UTC]", "position": "int64"}
    if positions.empty:
        return pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in columns.items()})
    joined = _with_driver(positions, drivers)
    return (
        pd.DataFrame(
            {
                "driver": joined["name_acronym"],
                "utc": _utc(joined["date"]),
                "position": joined["position"],
            }
        )
        .astype(columns)
        .sort_values(["utc", "position"])
        .reset_index(drop=True)
    )


def canonical_pits(pits: pd.DataFrame, drivers: pd.DataFrame) -> pd.DataFrame:
    columns = {"driver": "string", "lap": "int64", "lane_s": "float64", "stop_s": "float64"}
    if pits.empty:
        return pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in columns.items()})
    joined = _with_driver(pits, drivers)
    # Older sessions only have pit_duration, which is the pit-lane time.
    lane = joined["lane_duration"] if "lane_duration" in joined else joined["pit_duration"]
    stop = joined["stop_duration"] if "stop_duration" in joined else pd.Series(index=joined.index)
    return (
        pd.DataFrame(
            {
                "driver": joined["name_acronym"],
                "lap": joined["lap_number"],
                "lane_s": pd.to_numeric(lane),
                "stop_s": pd.to_numeric(stop),
            }
        )
        .astype(columns)
        .sort_values(["driver", "lap"])
        .reset_index(drop=True)
    )
