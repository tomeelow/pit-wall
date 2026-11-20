"""Race-control messages → safety car, VSC and red-flag periods."""

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


def parse_neutralisations(race_control: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Periods with the lap and time they started and ended, plus parsing issues.

    end_lap is the last lap run under the neutralisation (the lap of the "in this lap" /
    "ending" message). A red flag ends at the first track-wide green or clear signal after the
    stoppage, which is the restart to within about a minute. Messages after the chequered flag are
    ignored; anything still active then ends with the race (ended_by "chequered").
    """
    parser = _Parser()
    messages = race_control.sort_values("date")
    for row in messages.to_dict("records"):
        text = str(row["message"] or "").strip().upper()
        lap = int(row["lap_number"]) if pd.notna(row["lap_number"]) else 0
        utc = pd.Timestamp(row["date"]).tz_convert("UTC")
        track_flag = row["category"] == "Flag" and row.get("scope") == "Track"

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
        elif track_flag and row["flag"] == "RED":
            parser.end(SC, lap, utc, "red_flag")
            parser.end(VSC, lap, utc, "red_flag")
            parser.start(RED, lap, utc)
        elif track_flag and row["flag"] in ("GREEN", "CLEAR"):
            parser.end(RED, lap, utc, "restart")

    if parser.open:
        parser.issues.append(f"race control has no chequered flag; {sorted(parser.open)} unclosed")
    table = pd.DataFrame(parser.periods, columns=COLUMNS)
    table["start_lap"] = table["start_lap"].astype("int64")
    table["end_lap"] = table["end_lap"].astype("int64")
    table["start_utc"] = pd.to_datetime(table["start_utc"], utc=True)
    table["end_utc"] = pd.to_datetime(table["end_utc"], utc=True)
    return table, parser.issues
