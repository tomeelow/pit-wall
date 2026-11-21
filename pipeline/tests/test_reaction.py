from dataclasses import replace

import numpy as np
import pandas as pd

from pitwall.config import load_regulations
from pitwall.ingest.storage import RaceTables
from pitwall.models import reaction
from pitwall.models.events import History
from tests.conftest import CONFIG

ERA = load_regulations().era("2023-2025")
# The fixture race has three cars; production needs five on a lap to measure a stop's loss.
EVENTS = CONFIG.events.model_copy(
    update={"pit_loss": CONFIG.events.pit_loss.model_copy(update={"min_field_cars": 1})}
)


def test_rows_are_cars_with_a_stop_to_make_when_a_neutralisation_starts(
    race_tables: RaceTables,
) -> None:
    rows = reaction.reaction_rows(race_tables, window_laps=2)
    sc = race_tables.neutralisations.query("kind == 'SC'").iloc[0]
    start = int(sc["start_lap"])
    pits = race_tables.laps[race_tables.laps["pit_in"].astype(bool)]
    # Exactly the cars running at the start that pitted again at or after it.
    expected = pits[pits["lap"] >= start]["driver"].nunique()
    assert len(rows[rows["kind"] == "SC"]) == expected
    stopped = pits.groupby("driver")["lap"].apply(lambda s: s[s >= start].min()).dropna()
    assert rows[rows["kind"] == "SC"]["stopped"].sum() == (stopped <= start + 1).sum()
    assert rows["race_left"].between(0, 1).all()

    wet = replace(
        race_tables, laps=race_tables.laps.assign(compound_c=race_tables.laps["compound_c"])
    )
    wet.laps.loc[0, "compound_c"] = None
    assert reaction.reaction_rows(wet, window_laps=2).empty


def test_the_fit_recovers_known_coefficients() -> None:
    rng = np.random.default_rng(1)
    n = 20_000
    rows = pd.DataFrame(
        {
            "kind": rng.choice(["SC", "VSC"], n),
            "tyre_age": rng.integers(1, 40, n),
            "race_left": rng.uniform(0, 1, n),
        }
    )
    truth = np.array([1.5, -0.8, 1.2, -2.9])
    logit = reaction.design(rows) @ truth
    rows["stopped"] = rng.uniform(size=n) < 1 / (1 + np.exp(-logit))
    beta = reaction.fit_logistic(reaction.design(rows), rows["stopped"].to_numpy(float), 2.0)
    assert np.allclose(beta, truth, atol=0.15)


def test_a_race_learns_its_reaction_from_the_other_races_only(race_tables: RaceTables) -> None:
    other = replace(race_tables, event=race_tables.event.model_copy(update={"round": 2}))
    history = History.of([race_tables, other], EVENTS, load_regulations())
    first = history.parameters("2024-01", ERA.name).reaction
    assert set(first) == set(reaction.COLUMNS)
    assert len(first["intercept_sc"]) == CONFIG.events.hazards.export_draws
    alone = History.of([race_tables], EVENTS, load_regulations())
    assert alone.parameters("2024-01", ERA.name).reaction == {}
