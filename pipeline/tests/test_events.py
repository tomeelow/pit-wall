from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from pitwall.config import StintCapConfig, load_regulations
from pitwall.ingest.storage import RaceTables
from pitwall.models import hazards, pit_loss
from pitwall.models.events import History, completed_stints, stint_caps
from tests.conftest import CONFIG

ERA = load_regulations().era("2023-2025")
# The fixture race has three cars; production needs five on a lap to form a reference.
EVENTS = CONFIG.events.model_copy(
    update={"pit_loss": CONFIG.events.pit_loss.model_copy(update={"min_field_cars": 1})}
)


def with_stop_loss(tables: RaceTables, driver: str, in_lap: int, extra: float) -> RaceTables:
    """`extra` seconds added to a stop's in-lap and out-lap together."""
    laps = tables.laps.copy()
    stop = (laps["driver"] == driver) & laps["lap"].isin([in_lap, in_lap + 1])
    laps.loc[stop, "lap_time_s"] += extra / 2
    return replace(tables, laps=laps)


def test_stop_loss_is_measured_against_the_field_on_the_same_laps(
    race_tables: RaceTables,
) -> None:
    tables = with_stop_loss(race_tables, "LEC", 15, 22.0)
    stops = pit_loss.stop_losses(tables, EVENTS.pit_loss).set_index(["driver", "lap"])
    # The out-lap on new tyres beats a field on 15-lap-old ones by 15 x 0.05 s: the loss is net of
    # that, by definition (see the pit_loss module docstring).
    assert stops.loc[("LEC", 15), "loss_s"] == pytest.approx(22.0 - 15 * 0.05, abs=0.01)
    assert stops.loc[("LEC", 15), "condition"] == "GREEN"
    assert set(stops.index) == {("VER", 20), ("LEC", 15), ("LEC", 40)}

    no_tyre_change = replace(tables, pits=tables.pits.assign(lap=tables.pits["lap"] + 3))
    assert pit_loss.stop_losses(no_tyre_change, EVENTS.pit_loss).empty
    queued = replace(tables, pits=tables.pits.assign(lane_s=[21.5, 21.5, 400.0]))
    assert len(pit_loss.stop_losses(queued, EVENTS.pit_loss)) == 2


def test_stop_under_a_safety_car_is_labelled(race_tables: RaceTables) -> None:
    pits = race_tables.pits.copy()
    laps = race_tables.laps.copy()
    # Move LEC's second stop into the safety car (laps 31-33).
    pits.loc[pits["lap"] == 40, "lap"] = 31
    lec = laps["driver"] == "LEC"
    laps.loc[lec & (laps["lap"] >= 32), "stint"] = 3
    laps.loc[lec & (laps["lap"] == 32), "pit_out"] = True
    stops = pit_loss.stop_losses(replace(race_tables, laps=laps, pits=pits), EVENTS.pit_loss)
    assert stops.set_index("lap").loc[31, "condition"] == "SC"


def counts(rows: pd.DataFrame, **match: str) -> tuple[int, float]:
    """(events, exposure) summed over the rows matching every column = value."""
    hit = rows[np.logical_and.reduce([rows[column] == value for column, value in match.items()])]
    assert len(hit) > 0
    return int(hit["events"].sum()), float(hit["exposure"].sum())


def test_neutralisation_exposure_skips_neutralised_laps(race_tables: RaceTables) -> None:
    rows = hazards.neutralisation_rows(race_tables, "2024-01", ERA)
    assert counts(rows, kind="SC", phase="running") == (1, 57 - 1 - 3)
    assert counts(rows, kind="SC", phase="lap1") == (0, 1)
    assert rows["unit"].eq("track:1").all()


def test_retirement_exposure_counts_laps_after_the_first(race_tables: RaceTables) -> None:
    rows = hazards.retirement_rows(race_tables, "2024-01", ERA, bins=10, lag=0)
    assert counts(rows, phase="running", unit="team:2023-2025:williams") == (1, 30)
    assert counts(rows, phase="running", unit="team:2023-2025:red_bull") == (0, 56)
    assert rows.loc[rows["phase"] == "lap1", "events"].sum() == 0


def test_a_retirement_is_placed_where_the_car_ran_before_it(race_tables: RaceTables) -> None:
    rows = hazards.retirement_rows(race_tables, "2024-01", ERA, bins=10, lag=0)
    running = rows[rows["phase"] == "running"]
    assert running["position"].between(-0.5, 0.5).all()
    assert (rows.loc[rows["phase"] == "lap1", "position"] == 0).all()
    williams = race_tables.results.loc[
        race_tables.results["team_id"] == "williams", "driver"
    ].item()
    share = hazards.running_share(race_tables.race_state)
    # It retired on lap 31, after completing 30: it was at risk from where it ran after lap 30.
    before = share[(share["driver"] == williams) & (share["lap"] == 30)]["position"].item()
    assert running.loc[running["events"] > 0, "position"].item() == pytest.approx(before)
    # Three cars: the front, the middle and the back of the field.
    assert sorted(share.loc[share["lap"] == 10, "position"]) == [-0.5, 0.0, 0.5]
    # With a lag, by where it ran five laps earlier; exposure is unchanged.
    lagged = hazards.retirement_rows(race_tables, "2024-01", ERA, bins=10, lag=5)
    earlier = share[(share["driver"] == williams) & (share["lap"] == 25)]["position"].item()
    hit = lagged[lagged["events"] > 0]
    assert hit["position"].item() == pytest.approx(earlier)
    assert lagged["exposure"].sum() == rows["exposure"].sum()


def synthetic_rows(seed: int = 0) -> pd.DataFrame:
    """SC rows for 40 races on 10 tracks at 0.01 per lap, plus one race at a track that saw 30."""
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(40):
        unit = f"track:{r % 10}"
        rows += [
            (f"R{r}", ERA.name, "SC", "lap1", unit, rng.poisson(0.1), 1.0, 0.0),
            (f"R{r}", ERA.name, "SC", "running", unit, rng.poisson(0.5), 50.0, 0.0),
        ]
    rows += [("X", ERA.name, "SC", "running", "track:x", 30, 50.0, 0.0)]
    return pd.DataFrame(rows, columns=hazards.COLUMNS)


@pytest.fixture(scope="module")
def rate_model() -> hazards.RateModel:
    return hazards.RateModel(synthetic_rows(), CONFIG.events.hazards)


def test_rates_are_pooled_and_a_masked_race_is_unseen(rate_model: hazards.RateModel) -> None:
    rng = np.random.default_rng(0)
    full = rate_model.fit()
    masked = rate_model.fit((rate_model.rows["race"] == "X").to_numpy())
    assert full.passed and masked.passed

    base = masked.index.base[(ERA.name, "SC", "running")]
    era_rate = np.exp(masked.posterior["base"].to_numpy()[:, base])
    assert np.median(era_rate) == pytest.approx(0.01, rel=0.35)
    seen = full.rate(ERA.name, "SC", "running", "track:x", rng)
    hidden = masked.rate(ERA.name, "SC", "running", "track:x", rng)
    unseen = masked.rate(ERA.name, "SC", "running", "track:new", rng)
    assert np.median(seen) > 4 * np.median(hidden)  # 30 SCs pull even a shrunk rate up
    assert np.median(hidden) == pytest.approx(np.median(unseen), rel=0.2)
    p = hazards.p_any(masked, ERA.name, "SC", "track:new", 51, rng)
    assert 0 < p.mean() < 1


def test_the_running_position_effect_is_recovered() -> None:
    """Retirements at 0.002 per lap in mid-field, exp(1.5) times more likely at the back than at
    the front, for 10 teams over 40 races."""
    rng = np.random.default_rng(1)
    rows = []
    for r in range(40):
        for team in range(10):
            for x in np.linspace(-0.45, 0.45, 10):
                rate = 0.002 * np.exp(1.5 * x)
                rows.append(
                    (f"R{r}", ERA.name, hazards.DNF, "running", f"team:{team}",
                     rng.poisson(rate * 100), 100.0, x)
                )  # fmt: skip
    fit = hazards.RateModel(
        pd.DataFrame(rows, columns=hazards.COLUMNS), CONFIG.events.hazards
    ).fit()
    assert fit.passed
    assert np.median(fit.position(ERA.name)) == pytest.approx(1.5, abs=0.3)
    mid = fit.rate(ERA.name, hazards.DNF, "running", "team:3", np.random.default_rng(0))
    assert np.median(mid) == pytest.approx(0.002, rel=0.15)


def test_race_parameters_never_learn_from_the_race_itself(race_tables: RaceTables) -> None:
    other = replace(
        race_tables,
        event=race_tables.event.model_copy(update={"round": 2}),
        pits=race_tables.pits.assign(stop_s=3.0),
    )
    history = History.of([race_tables, other], EVENTS, load_regulations())
    first = history.parameters("2024-01", ERA.name)
    assert first.stationary_s == [3.0, 3.0, 3.0]
    assert history.parameters("2024-02", ERA.name).stationary_s == [2.4, 2.4, 2.4]
    assert first.duration_laps == {"SC": [3], "VSC": [], "RED": []}
    assert first.pit_loss_from == "track"


def test_neutralised_pace_is_not_pooled_across_eras(race_tables: RaceTables) -> None:
    laps = race_tables.laps
    slower = laps.assign(
        lap_time_s=laps["lap_time_s"].where(laps["track_status"] != "SC", laps["lap_time_s"] * 2)
    )
    later = replace(
        race_tables,
        event=race_tables.event.model_copy(update={"season": 2026}),
        laps=slower.assign(season=2026),
    )
    history = History.of([race_tables, later], EVENTS, load_regulations())
    alone = pit_loss.neutralised_pace(race_tables)["factor"].median()
    assert history.parameters("2024-01", ERA.name).neutralised_lap_factor["SC"] == round(alone, 3)
    assert history.parameters("2026-01", "2026").neutralised_lap_factor["SC"] > 2 * alone - 0.1


def test_stint_caps_come_from_completed_stints_of_other_races(race_tables: RaceTables) -> None:
    stints = completed_stints(race_tables)
    # SAR's only stint ended in a retirement: it says nothing about how long the tyres could go.
    assert sorted(map(tuple, stints.to_numpy().tolist())) == [
        (1, 25),
        (1, 37),
        (2, 20),
        (3, 15),
        (3, 17),
    ]
    caps, other = stint_caps(stints, StintCapConfig(quantile=1.0 - 1e-9, min_stints=2))
    assert caps == {"1": 37, "3": 17} and other == 37  # C2 has one stint: the era's cap
    assert stint_caps(stints.iloc[:0], StintCapConfig(quantile=0.95, min_stints=2)) == ({}, None)

    other_race = replace(race_tables, event=race_tables.event.model_copy(update={"round": 2}))
    history = History.of([race_tables, other_race], EVENTS, load_regulations())
    # Each race's cap is learnt from the other race only.
    assert history.parameters("2024-01", ERA.name).max_stint_laps_other is not None
    alone = History.of([race_tables], EVENTS, load_regulations()).parameters("2024-01", ERA.name)
    assert alone.max_stint_laps == {} and alone.max_stint_laps_other is None
