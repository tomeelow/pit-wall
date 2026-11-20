import numpy as np
import pandas as pd
import pymc as pm
import pytensor.tensor as pt
import pytest

from pitwall.config import GateConfig, SamplerConfig, load_regulations
from pitwall.ingest.storage import RaceTables
from pitwall.models import backtest
from pitwall.models.degradation import (
    Fit,
    drop_sparse_compounds,
    fit,
    race_draws,
    race_id,
    training_laps,
)
from pitwall.models.sampling import Diagnostics, zero_sum_deviation
from tests.conftest import CONFIG

REGULATIONS = load_regulations()
ERA = REGULATIONS.era("2023-2025")
FAST = CONFIG.degradation.model_copy(
    update={"sampler": SamplerConfig(chains=4, tune=600, draws=600, target_accept=0.95, seed=7)}
)
TRUE = {"fuel_s_per_kg": 0.035, "slope": {2: 0.02, 3: 0.09}, "offset": {2: 0.4, 3: -0.4}}
# Tracks and teams wear tyres differently, at about the spread the real fit finds.
TRACK_SLOPE = {0: 0.02, 1: -0.02, 2: 0.03, 3: -0.01}
TEAM_SLOPE = {
    "red_bull": -0.015,
    "ferrari": 0.0,
    "mclaren": 0.015,
    "williams": 0.01,
    "sauber": -0.02,
}
TRACKS = len(TRACK_SLOPE)
RACE_LAPS = 50


def synthetic_laps(seed: int = 0) -> pd.DataFrame:
    """Training laps from known parameters. Fuel burns 110 kg over 50 laps, so it gains
    ~0.08 s/lap: more than C2 wears. Every driver runs C2 then C3, switching at a different lap."""
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(2 * TRACKS):
        race_offset = rng.normal(0, 0.15, size=2)
        for d, team in enumerate(TEAM_SLOPE):
            pace = rng.normal(0, 0.3)
            switch = 18 + 5 * d + r
            for lap in range(2, RACE_LAPS + 1):
                c, age = (2, lap) if lap <= switch else (3, lap - switch)
                slope = TRUE["slope"][c] + TRACK_SLOPE[r % TRACKS] + TEAM_SLOPE[team]
                fuel_kg = ERA.race_fuel_kg * (1 - (lap - 0.5) / RACE_LAPS)
                time = (
                    90
                    + pace
                    + TRUE["offset"][c]
                    + race_offset[c - 2]
                    + slope * age
                    + TRUE["fuel_s_per_kg"] * fuel_kg
                    + rng.normal(0, 0.1)
                )
                rows.append(
                    {
                        "race": race_id(2024, r + 1),
                        "track": r % TRACKS,
                        "driver": f"D{d}",
                        "team": team,
                        "stint": 1 if c == 2 else 2,
                        "compound_c": c,
                        "lap": lap,
                        "tyre_age": age,
                        "lap_time_s": time,
                        "fuel_kg": fuel_kg,
                    }
                )
    laps = pd.DataFrame(rows)
    return laps.assign(race_median_s=laps.groupby("race")["lap_time_s"].transform("median"))


@pytest.fixture(scope="module")
def synthetic_fit() -> Fit:
    # Production sampler settings: the gate this fit must pass is the production gate, and at
    # 600 draws R-hat on slope_c (4 tracks only) lands either side of 1.01 depending on the seed.
    return fit(synthetic_laps(), ERA, CONFIG.degradation, REGULATIONS.fuel_effect_s_per_kg)


def test_fuel_burn_is_not_mistaken_for_negative_degradation(synthetic_fit: Fit) -> None:
    laps = synthetic_fit.laps
    c2 = laps[(laps["compound_c"] == 2) & (laps["race"] == "2024-01") & (laps["driver"] == "D4")]
    naive = np.polyfit(c2["tyre_age"], c2["lap_time_s"], 1)[0]
    assert naive < 0  # tyre age alone: the car gets faster as it wears

    for c in (2, 3):
        draws = synthetic_fit.slope(0, c, "red_bull", np.random.default_rng(0))
        expected = TRUE["slope"][c] + TRACK_SLOPE[0] + TEAM_SLOPE["red_bull"]
        assert draws.mean() == pytest.approx(expected, abs=0.01)
    fuel = synthetic_fit.posterior["fuel_effect"].to_numpy()
    assert fuel.mean() == pytest.approx(TRUE["fuel_s_per_kg"], abs=0.004)
    assert synthetic_fit.passed


def test_unseen_groups_widen_and_unknown_compounds_fail(synthetic_fit: Fit) -> None:
    rng = np.random.default_rng(0)
    seen = synthetic_fit.slope(0, 2, "ferrari", rng)
    new_team = synthetic_fit.slope(0, 2, "haas", rng)
    new_track = synthetic_fit.slope(99, 2, "haas", rng)
    assert seen.std() < new_team.std() < new_track.std()
    assert new_track.mean() == pytest.approx(TRUE["slope"][2], abs=0.04)
    with pytest.raises(KeyError, match="C5"):
        synthetic_fit.slope(0, 5, "ferrari", rng)


def test_gate() -> None:
    gate = GateConfig(max_rhat=1.01, min_ess=400, max_divergences=0)
    good = Diagnostics(max_rhat=1.005, min_ess_bulk=900, min_ess_tail=500, divergences=0)
    assert good.passes(gate)
    assert not good.model_copy(update={"max_rhat": 1.02}).passes(gate)
    assert not good.model_copy(update={"min_ess_tail": 399}).passes(gate)
    assert not good.model_copy(update={"divergences": 1}).passes(gate)


def test_training_laps_are_the_clean_laps_with_fuel(race_tables: RaceTables) -> None:
    laps = training_laps([race_tables], ERA)
    clean = race_tables.laps[race_tables.laps["lap_class"] == "clean"]
    assert len(laps) == len(clean)
    assert laps.sort_values("lap")["fuel_kg"].is_monotonic_decreasing
    assert 0 < laps["fuel_kg"].min() < laps["fuel_kg"].max() < ERA.race_fuel_kg
    with pytest.raises(ValueError, match="not in 2026"):
        training_laps([race_tables], REGULATIONS.era("2026"))


def test_race_draws_cover_every_driver_and_allocated_compound(race_tables: RaceTables) -> None:
    small = fit(training_laps([race_tables], ERA), ERA, FAST, REGULATIONS.fuel_effect_s_per_kg)
    draws = race_draws(small, race_tables, [1, 2, 3, 5], n=50, rng=np.random.default_rng(0))
    assert len(draws) == 50 * draws["driver"].nunique() * 3
    assert set(draws["compound_c"]) == {1, 2, 3}  # the fit has no C5: no parameters, no guess
    assert not draws.isna().any().any()
    assert draws.groupby(["driver", "compound_c"])["draw"].nunique().eq(50).all()


def test_compounds_from_a_single_race_are_left_out() -> None:
    laps = synthetic_laps()
    one_race = laps[laps["race"] == "2024-01"].head(10).assign(compound_c=6)
    kept, sparse = drop_sparse_compounds(pd.concat([laps, one_race]), min_races=2)
    assert sparse == [6]
    assert len(kept) == len(laps)
    assert drop_sparse_compounds(laps, min_races=9)[1] == [2, 3]


def test_backtest_baselines_on_a_straight_stint(synthetic_fit: Fit) -> None:
    held_out = synthetic_laps(seed=1).query("race == '2024-01' and driver == 'D0'")
    held_out = held_out.assign(race="2025-01")
    held_out = held_out.assign(lap_time_s=80 + 0.1 * held_out["lap"])  # exactly linear
    forecasts = backtest.forecast_stints(
        held_out, synthetic_fit, CONFIG.degradation.backtest, np.random.default_rng(0)
    )
    assert (forecasts["ols"] - forecasts["actual"]).abs().max() < 1e-9
    assert set(forecasts["stint"]) == {1, 2}
    on_c6 = held_out.assign(compound_c=6)
    rng = np.random.default_rng(0)
    assert backtest.forecast_stints(on_c6, synthetic_fit, CONFIG.degradation.backtest, rng).empty
    assert forecasts["laps_ahead"].min() == 1
    scores = backtest.score(forecasts, ["horizon"])
    assert scores["mae_ols"].max() < 1e-9 < scores["mae_median"].min()

    with pytest.raises(ValueError, match="has seen"):
        backtest.forecast_stints(
            synthetic_fit.laps, synthetic_fit, CONFIG.degradation.backtest, np.random.default_rng(0)
        )


def test_zero_sum_deviations_match_centred_normals() -> None:
    segment = np.array([0, 1, 0, 2, 0, 1])  # sizes 3, 2 and 1
    with pm.Model():
        deviation = zero_sum_deviation("z", pt.as_tensor(2.0), segment, segments=3)
    draws = np.asarray(pm.draw(deviation, draws=20_000, random_seed=0))
    totals = np.stack([draws[:, segment == s].sum(axis=1) for s in range(3)])
    assert np.abs(totals).max() < 1e-9
    sizes = np.bincount(segment)[segment]
    assert draws.var(axis=0) == pytest.approx(4 * (1 - 1 / sizes), abs=0.15)
