import numpy as np
import pandas as pd
import pytest

from pitwall.ingest.storage import RaceTables
from pitwall.models import traffic
from tests.conftest import CONFIG

SETTINGS = CONFIG.traffic


def flat_draws(tables: RaceTables) -> pd.DataFrame:
    """Degradation draws that predict every car at 95 s on every lap."""
    cars = tables.laps[["driver", "compound_c"]].dropna().drop_duplicates()
    return cars.assign(
        pace_s=0.0,
        offset_s=0.0,
        slope_s_per_lap=0.0,
        fuel_s_per_kg=0.0,
        race_median_s=95.0,
        race_fuel_kg=110.0,
    )


def test_pairs_keep_only_laps_decided_on_track(race_tables: RaceTables) -> None:
    predicted = traffic.predicted_laps(race_tables, flat_draws(race_tables))
    pairs = traffic.lap_pairs(race_tables, predicted)
    assert (pairs["gap_s"] >= 0).all()
    assert set(map(tuple, pairs[["driver", "ahead"]].to_numpy())) <= {
        (a, b) for a in ("VER", "LEC", "SAR") for b in ("VER", "LEC", "SAR") if a != b
    }
    usable = pairs[pairs["usable"]]
    laps = race_tables.laps
    neutralised = set(laps.loc[laps["track_status"] != "GREEN", "lap"])
    assert neutralised  # the fixture has a safety car
    assert not usable["lap"].isin([1, *neutralised]).any()
    pit_laps = race_tables.laps.loc[race_tables.laps["pit_in"] | race_tables.laps["pit_out"]]
    pitting = set(map(tuple, pit_laps[["driver", "lap"]].to_numpy()))
    for driver, ahead, lap in usable[["driver", "ahead", "lap"]].itertuples(index=False):
        assert (driver, lap) not in pitting and (ahead, lap) not in pitting
    # A usable pass was made on the lap: the car behind made up the whole gap.
    time = laps.set_index(["driver", "lap"])["lap_time_s"]
    passes = usable[usable["passed"]]
    assert len(passes) > 0
    for driver, ahead, lap, gap in passes[["driver", "ahead", "lap", "gap_s"]].itertuples(
        index=False
    ):
        assert time[(driver, lap)] + gap <= time[(ahead, lap)]


def test_dirty_air_uses_laps_where_the_car_ahead_is_not_slower() -> None:
    pairs = pd.DataFrame(
        {
            "gap_s": [0.2, 0.3, 0.4, 0.3, 1.2, 1.4],
            "pace_delta_s": [-0.1, -0.2, 0.0, 0.8, -0.3, -0.1],
            "excess_s": [0.5, 0.4, 0.6, 2.0, 0.1, 0.1],
            "passed": [False, False, False, False, False, True],
            "usable": True,
        }
    )
    table = traffic.dirty_air(pairs, [0.0, 0.5, 1.0, 1.5])
    assert table.to_dict("list") == {"gap_upto_s": [0.5, 1.5], "loss_s": [0.5, 0.1], "laps": [3, 1]}


TRUE = {"intercept": -1.0, "gap_s": -3.0, "pace_delta_s": 1.5, "within_drs": 0.5}
TRACK = {1: -1.5, 2: -0.3, 3: 0.0, 4: 0.6, 5: 1.2}


def synthetic_rows(n: int = 12_000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    gap = rng.uniform(0, SETTINGS.max_gap_s, n)
    rows = pd.DataFrame(
        {
            "era": "2023-2025",
            "track": rng.choice(list(TRACK), n),
            "gap_s": gap,
            "pace_delta_s": rng.normal(0, 0.7, n),
            "within_drs": (gap <= SETTINGS.drs_gap_s).astype(float),
        }
    )
    logit = (
        TRUE["intercept"]
        + rows["track"].map(TRACK)
        + sum(TRUE[name] * rows[name] for name in traffic.FEATURES)
    )
    return rows.assign(passed=rng.random(n) < 1 / (1 + np.exp(-logit)))


@pytest.fixture(scope="module")
def pass_model() -> traffic.PassModel:
    return traffic.PassModel(synthetic_rows(), SETTINGS)


def test_pass_model_recovers_known_coefficients(pass_model: traffic.PassModel) -> None:
    fit = pass_model.fit()
    assert fit.passed
    rng = np.random.default_rng(0)
    for name in traffic.FEATURES:
        assert fit.terms("2023-2025", 3, rng)[f"beta_{name}"].mean() == pytest.approx(
            TRUE[name], abs=0.25
        )
    # Track deviations sum to zero, so they recover the true ones minus their mean.
    shift = np.mean(list(TRACK.values()))
    track = fit.posterior["track"].mean("sample").to_numpy()
    for t, i in fit.tracks.items():
        assert track[i] == pytest.approx(TRACK[t] - shift, abs=0.25)

    rows = pass_model.rows
    p = fit.probability(rows, draws=100, rng=rng)
    assert p.sum() == pytest.approx(rows["passed"].sum(), rel=0.05)


def test_masked_rows_do_not_inform_the_fit(pass_model: traffic.PassModel) -> None:
    rows = pass_model.rows
    monaco_like = (rows["track"] == 1).to_numpy()
    fit = pass_model.fit(monaco_like)
    track = fit.posterior["track"].mean("sample").to_numpy()
    # With its rows masked, track 1 is held only by the zero-sum constraint, not its own data.
    others = [track[i] for t, i in fit.tracks.items() if t != 1]
    assert track[fit.tracks[1]] == pytest.approx(-sum(others), abs=1e-6)
    assert track[fit.tracks[1]] > TRACK[1]


def test_reliability_and_scores() -> None:
    predictions = pd.DataFrame(
        {
            "passed": [True, False, False, False],
            "model": [0.9, 0.1, 0.1, 0.1],
            "baseline": [0.25, 0.25, 0.25, 0.25],
        }
    )
    table = traffic.scores(predictions)
    assert table["log_loss_model"].iloc[0] < table["log_loss_baseline"].iloc[0]
    assert table["passes"].iloc[0] == 1
    reliability = traffic.reliability(
        predictions["model"].to_numpy(), predictions["passed"].to_numpy(), [0, 0.5, 1]
    )
    assert reliability["laps"].tolist() == [3, 1]
    assert reliability["observed"].tolist() == [0.0, 1.0]
