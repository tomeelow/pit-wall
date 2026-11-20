import pandas as pd
import pytest

from pitwall.race_state import build_race_state, line_crossings, position_agreement
from tests.conftest import LAP1_S, RACE_START, canonical, openf1_race


def state_of(
    plans: dict[int, list[tuple[str, int, int]]], spacing_s: float = 3.0, dnf: tuple = ()
) -> pd.DataFrame:
    laps = canonical(openf1_race(plans, spacing_s))
    drivers = laps["driver"].unique()
    results = pd.DataFrame(
        {"driver": drivers, "status": ["DNF" if d in dnf else "Finished" for d in drivers]}
    )
    return build_race_state(laps, results)


def test_crossing_is_the_next_lap_start_or_start_plus_lap_time() -> None:
    laps = canonical(openf1_race({1: [("SOFT", 3, 0)]}))
    crossings = line_crossings(laps).tolist()
    assert crossings[0] == RACE_START + pd.Timedelta(seconds=LAP1_S)  # lap 1 has no duration
    assert crossings[2] == laps["lap_start_utc"][2] + pd.Timedelta(seconds=laps["lap_time_s"][2])


def test_order_and_gaps_follow_the_line() -> None:
    state = state_of({1: [("SOFT", 5, 0)], 16: [("SOFT", 5, 0)], 2: [("SOFT", 5, 0)]}, 2.0)
    lap3 = state[state["lap"] == 3].set_index("driver")
    assert lap3["position"].to_dict() == {"VER": 1, "LEC": 2, "SAR": 3}
    assert lap3["gap_to_leader_s"].to_dict() == pytest.approx({"VER": 0, "LEC": 2, "SAR": 4})
    assert lap3["interval_s"].loc[["LEC", "SAR"]].tolist() == pytest.approx([2, 2])
    assert pd.isna(lap3.loc["VER", "interval_s"])
    assert lap3["gap_ahead_s"].loc[["LEC", "SAR"]].tolist() == pytest.approx([2, 2])
    # The leader's car physically ahead is the last car, one lap down at the line.
    assert lap3.loc["VER", "gap_ahead_s"] == pytest.approx(95.1 - 4.0)
    race_time = state.set_index(["driver", "lap"])["race_time_s"]
    assert race_time[("VER", 1)] == pytest.approx(LAP1_S)
    assert race_time[("SAR", 1)] == pytest.approx(LAP1_S + 4.0)


def test_tyre_state_and_stops() -> None:
    state = state_of({16: [("SOFT", 3, 2), ("HARD", 3, 0), ("INTERMEDIATE", 2, 0)]})
    rows = state.set_index("lap")
    assert rows["stops"].tolist() == [0, 0, 0, 1, 1, 1, 2, 2]
    assert rows["in_pit"].tolist() == [False, False, True, False, False, True, False, False]
    assert rows["dry_compounds_used"].tolist() == ["SOFT"] * 3 + ["SOFT,HARD"] * 5
    assert rows.loc[1, "tyre_age"] == 3


def test_retired_driver_is_flagged_on_the_last_lap_and_then_absent() -> None:
    state = state_of({1: [("SOFT", 6, 0)], 2: [("SOFT", 4, 0)]}, dnf=("SAR",))
    sar = state[state["driver"] == "SAR"]
    assert sar["retired"].tolist() == [False, False, False, True]
    assert not state.loc[state["driver"] == "VER", "retired"].any()
    assert state.loc[state["lap"] == 5, "driver"].tolist() == ["VER"]


def test_missing_laps_have_no_row_and_do_not_shift_positions() -> None:
    race = openf1_race({1: [("SOFT", 6, 0)], 16: [("SOFT", 6, 0)]})
    race.laps = race.laps[~race.laps["lap_number"].isin([3, 4])]
    laps = canonical(race)
    state = build_race_state(laps, pd.DataFrame({"driver": ["VER", "LEC"], "status": "Finished"}))
    assert sorted(state["lap"].unique()) == [1, 2, 5, 6]
    for _, positions in state.groupby("lap")["position"]:
        assert sorted(positions.tolist()) == [1, 2]


def test_agreement_with_the_position_feed() -> None:
    state = state_of({1: [("SOFT", 5, 0)], 16: [("SOFT", 5, 0)]})
    feed = state[["driver", "crossing_utc", "position"]].rename(columns={"crossing_utc": "utc"})
    feed = feed.astype({"driver": "string", "position": "int64"})
    assert position_agreement(state, feed, lag_s=1.0) == 1.0

    swapped = feed.assign(position=3 - feed["position"])
    assert position_agreement(state, swapped, lag_s=1.0) == 0.0
    assert position_agreement(state, feed.head(0), lag_s=1.0) is None
