import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from pitwall.config import load_regulations
from pitwall.export.contract import SimRace
from pitwall.export.sim import NotSimulable, build_sim
from pitwall.ingest.storage import RaceTables, write_race
from tests.conftest import CONFIG

REGULATIONS = load_regulations()
DRAWS = CONFIG.sim.draws


def write_models(folder: Path, tables: RaceTables, drivers: tuple[str, ...]) -> None:
    """Model outputs shaped like the fit commands write them; values are test inputs."""
    teams = dict(tables.results[["driver", "team_id"]].itertuples(index=False))
    rows = [
        {
            "draw": d,
            "fuel_s_per_kg": 0.03,
            "nu": 3.0,
            "race_median_s": 95.0,
            "race_fuel_kg": 110.0,
            "driver": driver,
            "team_id": teams[driver],
            "compound_c": c,
            "pace_s": 0.1 * k + d / 1000,
            "offset_s": 0.5 * (2 - c),
            "slope_s_per_lap": 0.02 * c,
            "noise_sd_s": 0.3,
        }
        for d in range(DRAWS)
        for k, driver in enumerate(drivers)
        for c in (1, 2, 3)
    ]
    pd.DataFrame(rows).to_parquet(folder / "degradation_draws.parquet", index=False)
    units = [(kind, "track:1") for kind in ("SC", "VSC", "RED")]
    units += [("DNF", f"team:2023-2025:{team}") for team in set(teams.values())]
    hazard = [
        {"draw": d, "kind": kind, "phase": phase, "unit": unit, "rate": 0.01}
        for d in range(DRAWS)
        for kind, unit in units
        for phase in ("lap1", "running")
    ]
    pd.DataFrame(hazard).to_parquet(folder / "hazard_draws.parquet", index=False)
    events = {
        "pit_transit_s": 20.0,
        "pit_condition_factor": {"SC": 0.7, "VSC": 0.85},
        "stationary_s": [2.2, 2.4],
        "neutralised_lap_factor": {"SC": 1.45, "VSC": 1.25},
        "duration_laps": {"SC": [3, 4], "VSC": [1, 2], "RED": [1]},
        "max_stint_laps": {"1": 40, "3": 30},
        "max_stint_laps_other": 35,
    }
    (folder / "events.json").write_text(json.dumps(events))
    traffic = pd.DataFrame(
        {
            "draw": range(DRAWS),
            "intercept": 0.5,
            "beta_gap_s": -4.0,
            "beta_pace_delta_s": 1.8,
            "beta_within_drs": -1.0,
        }
    )
    traffic.to_parquet(folder / "traffic_draws.parquet", index=False)
    warm = [
        {"draw": d, "compound_c": c, "stint_lap": k, "warmup_s": 0.1 * c / k}
        for d in range(DRAWS)
        for c in (1, 2, 3)
        for k in (1, 2)
    ]
    pd.DataFrame(warm).to_parquet(folder / "warmup_draws.parquet", index=False)
    dirty_air = [{"gap_upto_s": 0.5, "loss_s": 0.4}]
    (folder / "traffic.json").write_text(
        json.dumps({"max_gap_s": 3.0, "drs_gap_s": 1.0, "dirty_air": dirty_air})
    )


@pytest.fixture
def race_folder(race_tables: RaceTables, tmp_path: Path) -> Path:
    folder = write_race(tmp_path, race_tables)
    # SAR has no degradation draws, like a driver without clean laps.
    write_models(folder, race_tables, ("VER", "LEC"))
    return folder


def build(folder: Path, tables: RaceTables) -> SimRace:
    return build_sim(folder, tables, REGULATIONS, CONFIG.sim)


def test_strategies_and_state_follow_the_stints(race_folder: Path, race_tables: RaceTables) -> None:
    sim = build(race_folder, race_tables)
    lec = [car.driver for car in sim.cars].index("LEC")
    stops = sim.cars[lec].stops
    # SOFT (C3, 3 laps old) for 15 laps, new HARD (C1) for 25, SOFT again on a 2-lap-old set.
    assert [(s.lap, s.compound_c, s.tyre_age) for s in stops] == [(15, 1, 0), (40, 3, 2)]

    before, after = sim.snapshots[13], sim.snapshots[14]  # after laps 14 and 15
    assert (before.lap, before.compound_c[lec], before.tyre_age[lec]) == (14, 3, 17)
    assert (before.stint_laps[lec], before.stops[lec], before.dry_compounds[lec]) == (14, 0, [3])
    # The stop at the end of lap 15 has been made.
    assert (after.compound_c[lec], after.tyre_age[lec], after.stint_laps[lec]) == (1, 0, 0)
    assert (after.stops[lec], after.dry_compounds[lec]) == (1, [1, 3])
    assert len(sim.snapshots) == sim.total_laps - 1


def test_retirements_and_missing_pace(race_folder: Path, race_tables: RaceTables) -> None:
    sim = build(race_folder, race_tables)
    sar = next(car for car in sim.cars if car.driver == "SAR")
    i = sim.cars.index(sar)
    assert (sar.retired_after_lap, sar.finish_position, sar.pace_from) == (30, None, "field")
    assert sim.snapshots[29].race_time_s[i] is not None  # after lap 30
    assert sim.snapshots[30].race_time_s[i] is None
    # Field pace is the median of the drivers with draws, per draw.
    ver, lec = (next(c for c in sim.cars if c.driver == d) for d in ("VER", "LEC"))
    assert sar.pace_s[0] == pytest.approx((ver.pace_s[0] + lec.pace_s[0]) / 2)
    assert all(len(values) == DRAWS for values in sar.slope_s_per_lap)


def test_race_carries_its_rules_and_realised_events(
    race_folder: Path, race_tables: RaceTables
) -> None:
    sim = build(race_folder, race_tables)
    assert sim.rules.min_dry_compounds == 2 and sim.rules.red_flag_free_tyre_change
    assert [(n.kind, n.start_lap, n.end_lap) for n in sim.realised] == [("SC", 31, 33)]
    assert [p.kind for p in sim.neutralisations] == ["SC", "VSC", "RED"]
    assert sim.neutralisations[2].lap_factor == 1.45  # a red flag runs like a safety car
    assert [w[1][0] for w in sim.degradation.warmup_s] == [0.05, 0.1, 0.15]  # C1-C3, stint lap 2
    clean = race_tables.laps[race_tables.laps["lap_class"] == "clean"]
    assert sim.degradation.race_clean_laps == [
        int((clean["compound_c"] == c).sum()) for c in (1, 2, 3)
    ]
    assert sim.degradation.max_stint_laps == [40, 35, 30]  # C2 has no cap of its own
    assert REGULATIONS.rules(2025, 8).min_stops == 2  # Monaco 2025
    assert REGULATIONS.rules(2024, 8).min_stops == 0


def test_races_the_engine_cannot_run_are_refused(
    race_folder: Path, race_tables: RaceTables, tmp_path: Path
) -> None:
    laps = race_tables.laps.copy()
    laps.loc[laps["lap"] == 10, "compound"] = "INTERMEDIATE"
    with pytest.raises(NotSimulable, match="wet"):
        build(race_folder, replace(race_tables, laps=laps))
    state = race_tables.race_state.copy()
    state.loc[(state["driver"] == "VER") & (state["lap"] == 20), "race_time_s"] = float("nan")
    with pytest.raises(NotSimulable, match="no race time"):
        build(race_folder, replace(race_tables, race_state=state))
    unfitted = write_race(tmp_path / "unfitted", race_tables)
    with pytest.raises(NotSimulable, match="no degradation_draws"):
        build(unfitted, race_tables)
