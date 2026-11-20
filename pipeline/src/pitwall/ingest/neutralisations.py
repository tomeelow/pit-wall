"""Race-control messages → safety car, VSC and red-flag periods, and sector yellows."""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SC, VSC, RED = "SC", "VSC", "RED"

COLUMNS = ["kind", "start_lap", "end_lap", "start_utc", "end_utc", "ended_by"]


@dataclass
class _Open:
    kind: str
    lap: int
    utc: pd.Timestamp


@dataclass
class _Parser:
    periods: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    open: dict[str, _Open] = field(default_factory=dict)

    def start(self, kind: str, lap: int, utc: pd.Timestamp) -> None:
        if kind in self.open:
            self.issues.append(f"{kind} deployed on lap {lap} while already active")
            return
        self.open[kind] = _Open(kind, lap, utc)

    def end(self, kind: str, lap: int, utc: pd.Timestamp, ended_by: str) -> None:
        period = self.open.pop(kind, None)
        if period is None:
            if ended_by == "end_message":
                self.issues.append(f"{kind} end on lap {lap} without a start")
            return
        self.periods.append(
            {
                "kind": kind,
                "start_lap": period.lap,
                "end_lap": max(lap, period.lap),
                "start_utc": period.utc,
                "end_utc": utc,
                "ended_by": ended_by,
            }
        )


def _in_order(race_control: pd.DataFrame) -> pd.DataFrame:
    """Messages by time; same-second messages keep OpenF1's order. OpenF1 returns no rows (not
    even columns) when a session has no race-control messages."""
    return (
        race_control.sort_values("date", kind="stable") if not race_control.empty else race_control
    )


def parse_neutralisations(race_control: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Periods with the lap and time they started and ended, plus parsing issues.

    end_lap is the last lap run under the neutralisation (the lap of the "in this lap" /
    "ending" message). Messages after the chequered flag are ignored; anything still active then
    ends with the race (ended_by "chequered").

    A red flag starts at "SESSION ABORTED", a track RED flag or a "RED FLAG ..." message (2026
    races have only the text message), and ends when the session restarts ("SESSION STARTED") or
    a safety car leads the restart. "TRACK CLEAR" is not a restart: it can come many minutes
    before the session resumes.
    """
    parser = _Parser()
    messages = _in_order(race_control)
    for row in messages.to_dict("records"):
        text = str(row["message"] or "").strip().upper()
        lap = int(row["lap_number"]) if pd.notna(row["lap_number"]) else 0
        utc = pd.Timestamp(row["date"]).tz_convert("UTC")
        track_flag = row["category"] == "Flag" and row.get("scope") == "Track"
        session = row["category"] == "SessionStatus"
        red_flag = (
            (track_flag and row["flag"] == "RED")
            or text.startswith("RED FLAG")
            or (session and text == "SESSION ABORTED")
        )

        if track_flag and row["flag"] == "CHEQUERED":
            for kind in list(parser.open):
                parser.end(kind, lap, utc, "chequered")
            break
        if text == "SAFETY CAR DEPLOYED":
            parser.end(RED, lap, utc, "restart")
            parser.end(VSC, lap, utc, "safety_car")
            parser.start(SC, lap, utc)
        elif text == "SAFETY CAR IN THIS LAP":
            parser.end(SC, lap, utc, "end_message")
        elif text == "VIRTUAL SAFETY CAR DEPLOYED":
            parser.start(VSC, lap, utc)
        elif text == "VIRTUAL SAFETY CAR ENDING":
            parser.end(VSC, lap, utc, "end_message")
        elif red_flag and RED not in parser.open:  # one stoppage is announced several ways
            parser.end(SC, lap, utc, "red_flag")
            parser.end(VSC, lap, utc, "red_flag")
            parser.start(RED, lap, utc)
        elif session and text == "SESSION STARTED":
            parser.end(RED, lap, utc, "restart")

    if parser.open:
        parser.issues.append(f"race control has no chequered flag; {sorted(parser.open)} unclosed")
    table = pd.DataFrame(parser.periods, columns=COLUMNS)
    table["start_lap"] = table["start_lap"].astype("int64")
    table["end_lap"] = table["end_lap"].astype("int64")
    table["start_utc"] = pd.to_datetime(table["start_utc"], utc=True)
    table["end_utc"] = pd.to_datetime(table["end_utc"], utc=True)
    return table, parser.issues


YELLOW_COLUMNS = ["sector", "start_utc", "end_utc"]


def parse_yellows(race_control: pd.DataFrame) -> pd.DataFrame:
    """Local yellow periods per marshal sector.

    A sector's yellow starts with its first YELLOW or DOUBLE YELLOW message and ends with
    "CLEAR IN TRACK SECTOR n"; anything still open at the chequered flag ends there. Upgrades
    from yellow to double yellow do not start a new period.
    """
    open_: dict[int, pd.Timestamp] = {}
    periods: list[dict[str, Any]] = []
    messages = _in_order(race_control)
    for row in messages.to_dict("records"):
        utc = pd.Timestamp(row["date"]).tz_convert("UTC")
        if row["category"] == "Flag" and row.get("scope") == "Track" and row["flag"] == "CHEQUERED":
            periods += [{"sector": s, "start_utc": t, "end_utc": utc} for s, t in open_.items()]
            open_.clear()
            break
        if row.get("scope") != "Sector" or pd.isna(row.get("sector")):
            continue
        sector = int(row["sector"])
        if row["flag"] in ("YELLOW", "DOUBLE YELLOW"):
            open_.setdefault(sector, utc)
        elif row["flag"] == "CLEAR" and sector in open_:
            periods.append({"sector": sector, "start_utc": open_.pop(sector), "end_utc": utc})
    # Without a chequered flag, an open yellow has no known end; it is dropped rather than guessed.
    table = pd.DataFrame(periods, columns=YELLOW_COLUMNS)
    table["sector"] = table["sector"].astype("int64")
    table["start_utc"] = pd.to_datetime(table["start_utc"], utc=True)
    table["end_utc"] = pd.to_datetime(table["end_utc"], utc=True)
    return table.sort_values("start_utc").reset_index(drop=True)
