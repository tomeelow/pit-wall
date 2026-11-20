from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pitwall.config import WarmupConfig
from pitwall.ingest.storage import RaceTables, write_race
from pitwall.models import warmup
from tests.test_sim_export import write_models

CONFIG = WarmupConfig(stint_laps=3, min_laps=20, draws=30, seed=1)


def laps(race: str, compound: int, stint_lap: int, residual: float, n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {"race": race, "compound_c": compound, "stint_lap": stint_lap, "residual_s": [residual] * n}
    )


def test_cells_are_medians_and_thin_cells_are_zero() -> None:
    rows = pd.concat(
        [laps(race, 2, 1, 0.5, 30) for race in "ABC"]
        + [laps(race, 2, 2, -0.2, 30) for race in "ABC"]
        + [laps("A", 3, 1, 9.0, 5)]  # 5 laps in a resample of A alone: below min_laps
    )
    draws = warmup.fit(rows, CONFIG)
    assert len(draws) == CONFIG.draws * 2 * CONFIG.stint_laps  # C2, C3 x stint laps 1-3
    cells = draws.groupby(["compound_c", "stint_lap"])["warmup_s"]
    assert cells.min().to_dict() == cells.max().to_dict()  # identical races: no spread
    assert cells.median().to_dict() == {
        (2, 1): 0.5,
        (2, 2): -0.2,
        (2, 3): 0.0,
        (3, 1): 0.0,
        (3, 2): 0.0,
        (3, 3): 0.0,
    }


def test_bootstrap_spread_comes_from_the_races() -> None:
    values = {"A": 0.0, "B": 0.2, "C": 0.4, "D": 1.0}
    rows = pd.concat([laps(race, 2, 1, value, 30) for race, value in values.items()])
    fitted = warmup.fit(rows, CONFIG)["warmup_s"]
    assert fitted.min() < 0.3 < fitted.max()


def test_out_laps_are_centred_and_early_laps_are_clean_residuals(
    race_tables: RaceTables, tmp_path: Path
) -> None:
    folder = write_race(tmp_path, race_tables)
    write_models(folder, race_tables, ("VER", "LEC", "SAR"))
    draws = pd.read_parquet(folder / "degradation_draws.parquet")
    rows = warmup.warmup_laps(race_tables, draws, CONFIG.stint_laps)
    assert set(rows["stint_lap"]) <= {1, 2, 3}
    out = rows[rows["stint_lap"] == 1]
    assert not out.empty and out["residual_s"].median() == pytest.approx(0)
    assert np.isfinite(rows["residual_s"]).all()
