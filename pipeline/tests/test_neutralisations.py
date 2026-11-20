import pandas as pd

from pitwall.ingest.neutralisations import parse_neutralisations
from tests.conftest import message


def periods(*messages: dict) -> tuple[list[tuple], list[str]]:
    table, issues = parse_neutralisations(pd.DataFrame(messages))
    rows = table[["kind", "start_lap", "end_lap", "ended_by"]].itertuples(index=False)
    return [tuple(row) for row in rows], issues


def test_red_flag_race_with_three_stoppages() -> None:
    """Shaped like 2023 Australia: lap-1 SC, SC upgraded to a red, a VSC, and two late reds."""
    found, issues = periods(
        message(1, "SAFETY CAR DEPLOYED", minute=2),
        message(3, "SAFETY CAR IN THIS LAP", minute=5),
        message(7, "SAFETY CAR DEPLOYED", minute=12),
        message(8, minute=15, flag="RED"),
        message(9, minute=30, flag="GREEN"),
        message(18, "VIRTUAL SAFETY CAR DEPLOYED", minute=46),
        message(19, "VIRTUAL SAFETY CAR ENDING", minute=48),
        message(55, minute=99, flag="RED"),
        message(56, minute=109, flag="GREEN"),
        message(57, minute=118, flag="RED"),
        message(58, minute=141, flag="CLEAR"),
        message(58, minute=150, flag="CHEQUERED"),
    )
    assert found == [
        ("SC", 1, 3, "end_message"),
        ("SC", 7, 8, "red_flag"),
        ("RED", 8, 9, "restart"),
        ("VSC", 18, 19, "end_message"),
        ("RED", 55, 56, "restart"),
        ("RED", 57, 58, "restart"),
    ]
    assert issues == []


def test_red_flag_ends_when_the_restart_is_behind_the_safety_car() -> None:
    found, _ = periods(
        message(10, minute=20, flag="RED"),
        message(11, "SAFETY CAR DEPLOYED", minute=50),
        message(13, "SAFETY CAR IN THIS LAP", minute=55),
        message(50, minute=100, flag="CHEQUERED"),
    )
    assert found == [("RED", 10, 11, "restart"), ("SC", 11, 13, "end_message")]


def test_vsc_upgraded_to_safety_car() -> None:
    found, issues = periods(
        message(20, "VIRTUAL SAFETY CAR DEPLOYED", minute=30),
        message(21, "SAFETY CAR DEPLOYED", minute=31),
        message(23, "SAFETY CAR IN THIS LAP", minute=35),
        message(50, minute=90, flag="CHEQUERED"),
    )
    assert found == [("VSC", 20, 21, "safety_car"), ("SC", 21, 23, "end_message")]
    assert issues == []


def test_race_finishing_under_safety_car_ends_at_the_flag() -> None:
    found, issues = periods(
        message(55, "SAFETY CAR DEPLOYED", minute=90),
        message(58, minute=96, flag="CHEQUERED"),
    )
    assert found == [("SC", 55, 58, "chequered")]
    assert issues == []


def test_messages_after_the_chequered_flag_are_ignored() -> None:
    found, issues = periods(
        message(58, minute=96, flag="CHEQUERED"),
        message(58, minute=99, flag="RED"),
    )
    assert found == []
    assert issues == []


def test_messages_are_processed_in_time_order() -> None:
    found, _ = periods(
        message(23, "SAFETY CAR IN THIS LAP", minute=35),
        message(50, minute=90, flag="CHEQUERED"),
        message(21, "SAFETY CAR DEPLOYED", minute=31),
    )
    assert found == [("SC", 21, 23, "end_message")]


def test_inconsistent_messages_are_reported() -> None:
    found, issues = periods(
        message(5, "SAFETY CAR IN THIS LAP", minute=10),
        message(8, "VIRTUAL SAFETY CAR DEPLOYED", minute=14),
        message(8, "VIRTUAL SAFETY CAR DEPLOYED", minute=15),
    )
    assert found == []
    assert issues == [
        "SC end on lap 5 without a start",
        "VSC deployed on lap 8 while already active",
        "race control has no chequered flag; ['VSC'] unclosed",
    ]


def test_sector_flags_are_not_neutralisations() -> None:
    sector_red = {**message(5, minute=10, flag="RED"), "scope": "Sector"}
    found, _ = periods(sector_red, message(50, minute=90, flag="CHEQUERED"))
    assert found == []


def test_empty_race_control_gives_typed_empty_table() -> None:
    table, issues = parse_neutralisations(
        pd.DataFrame(columns=["date", "lap_number", "category", "flag", "scope", "message"])
    )
    assert table.empty
    assert str(table["start_utc"].dtype) == "datetime64[ns, UTC]"
    assert issues == []
