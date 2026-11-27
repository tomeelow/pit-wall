import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pitwall.config import SimulatorGate, load_regulations
from pitwall.export.bundle import export_bundle
from pitwall.export.contract import SCHEMA_VERSION, Calibration, GateResult
from pitwall.export.sim import build_sim
from pitwall.ingest.storage import RaceTables, write_race
from pitwall.validate import simulator
from tests.conftest import BUDGETS, CONFIG
from tests.test_sim_export import write_models

GATE = SimulatorGate(
    must_beat_baseline_from=0.5, max_log_score_regression=0.02, max_coverage_error_growth=0.03
)


def coverage(forecast: np.ndarray, truth: np.ndarray, n: int = 4000, seed: int = 0) -> float:
    """Share of randomised PIT values in [0.25, 0.75] when outcomes come from `truth`."""
    rng = np.random.default_rng(seed)
    p = forecast / forecast.sum()
    outcomes = rng.choice(len(truth), size=n, p=truth / truth.sum())
    pit = np.array([simulator.randomised_pit(p, int(y), rng.uniform()) for y in outcomes])
    return float(((pit >= 0.25) & (pit <= 0.75)).mean())


def test_pit_coverage_is_nominal_only_when_calibrated() -> None:
    truth = np.array([1, 4, 10, 4, 1], dtype=float)
    assert coverage(truth, truth) == pytest.approx(0.5, abs=0.03)
    overconfident = np.array([0.1, 1, 30, 1, 0.1])
    assert coverage(overconfident, truth) < 0.4


def test_central_interval_holds_at_least_its_level() -> None:
    assert simulator.central_interval(np.array([0, 10, 80, 10, 0]), 0.8) == (2, 2)
    assert simulator.central_interval(np.array([25, 25, 25, 25]), 0.5) == (1, 2)
    assert simulator.central_interval(np.array([0, 0, 0, 5]), 0.8) == (3, 3)


def test_baselines_learn_from_other_races_only() -> None:
    # Two-car races: in A the car starting first wins, in B it finishes second.
    rows = pd.DataFrame(
        {
            "race": ["A", "B"],
            "fraction": 0.5,
            "cars": 2,
            "start_place": 1,
            "outcome": [0, 1],
        }
    )
    scores = simulator.baseline_log_scores(rows, "start_place", smoothing=0.5)
    # A's car is scored on B alone: one second place, smoothed over {1st, 2nd, not classified}.
    assert scores[0] == pytest.approx(np.log(0.5 / (1 + 3 * 0.5)))
    assert scores[1] == pytest.approx(scores[0])


@pytest.fixture
def race_with_models(race_tables: RaceTables, tmp_path: Path):
    folder = write_race(tmp_path, race_tables)
    write_models(folder, race_tables, ("VER", "LEC"))
    return build_sim(folder, race_tables, load_regulations(), CONFIG.sim)


def test_entries_cover_cars_running_at_the_start(race_with_models) -> None:
    race = race_with_models
    n = len(race.cars)
    counts = [[10, 0, 0, 0]] * n
    backtest = {
        "races": [
            {
                "season": race.season,
                "round": race.round,
                "starts": [
                    {"fraction": 0, "lap": 1, "counts": counts},
                    {"fraction": 0.75, "lap": 40, "counts": counts},
                ],
            }
        ]
    }
    rows = simulator.entries(backtest, {(race.season, race.round): race})
    drivers = {f: sorted(group) for f, group in rows.groupby("fraction")["driver"]}
    assert drivers == {0: ["LEC", "SAR", "VER"], 0.75: ["LEC", "VER"]}  # SAR retired on lap 31
    outcome = rows.set_index(["fraction", "driver"])["outcome"]
    assert (outcome[(0, "VER")], outcome[(0, "LEC")], outcome[(0, "SAR")]) == (0, 1, n)
    assert rows["neutralised_after"].tolist() == [True] * 3 + [False] * 2  # SC on laps 31-33


def scored_rows(model: float, baseline: float, fraction: float = 0.5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "race": ["A", "B"],
            "fraction": fraction,
            "log_score": model,
            "log_score_start_order": baseline,
        }
    )


def accepted(log_score: float, coverage_50: float) -> Calibration:
    segment = simulator.SegmentScore(
        segment="all",
        races=2,
        entries=2,
        coverage_50=coverage_50,
        coverage_80=0.8,
        interval_coverage_50=0.6,
        interval_coverage_80=0.85,
        log_score=log_score,
        log_score_start_order=-2.5,
        log_score_lap1_order=-2.6,
    )
    return Calibration(
        schema_version=SCHEMA_VERSION,
        git_sha="abc",
        generated_at=datetime.now(UTC),
        dataset_version="x",
        runs=10,
        segments=[segment],
        pit_histogram=[0.5, 0.5],
        gate=GateResult(passed=True, reasons=[]),
    )


def test_gate_requires_beating_the_running_order_from_mid_race() -> None:
    overall = accepted(-2.0, 0.5).segments[0]
    assert simulator.gate(scored_rows(-2.0, -2.5), overall, None, GATE).passed
    failed = simulator.gate(scored_rows(-2.6, -2.5), overall, None, GATE)
    assert not failed.passed and "does not beat" in failed.reasons[0]
    early = simulator.gate(scored_rows(-2.6, -2.5, fraction=0.25), overall, None, GATE)
    assert early.passed  # before mid-race the running order may win


def test_gate_rejects_regressions_against_the_accepted_calibration() -> None:
    rows = scored_rows(-2.0, -2.5)
    before = accepted(-1.90, 0.50).segments[0]
    worse_score = accepted(-1.95, 0.50).segments[0]
    assert not simulator.gate(rows, worse_score, before, GATE).passed
    worse_coverage = accepted(-1.90, 0.42).segments[0]
    result = simulator.gate(rows, worse_coverage, before, GATE)
    assert not result.passed and "50% coverage" in result.reasons[0]
    small_change = accepted(-1.91, 0.48).segments[0]
    assert simulator.gate(rows, small_change, before, GATE).passed


def test_a_rebaseline_drops_only_the_log_score_comparison() -> None:
    rows = scored_rows(-2.0, -2.5)
    before = accepted(-1.90, 0.50).segments[0]
    assert simulator.gate(
        rows, accepted(-1.95, 0.50).segments[0], before, GATE, rebaseline=True
    ).passed
    worse_coverage = accepted(-1.95, 0.42).segments[0]
    assert not simulator.gate(rows, worse_coverage, before, GATE, rebaseline=True).passed
    late_loss = simulator.gate(scored_rows(-2.6, -2.5), before, before, GATE, rebaseline=True)
    assert not late_loss.passed


def test_the_gate_reads_the_accepted_score_across_contract_versions(tmp_path: Path) -> None:
    assert simulator.accepted_overall(tmp_path / "none.json") is None
    old = json.loads(accepted(-1.9, 0.5).model_dump_json()) | {"schema_version": "0.1.0"}
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(old))
    assert simulator.accepted_overall(path) == accepted(-1.9, 0.5).segments[0]


def test_bundle_publishes_only_a_calibration_that_matches_the_contract(
    race_tables: RaceTables, tmp_path: Path
) -> None:
    data_dir, bundle_dir = tmp_path / "data", tmp_path / "bundle"
    write_race(data_dir, race_tables)
    source = data_dir / "models" / "sim" / "calibration.json"
    source.parent.mkdir(parents=True)

    source.write_text('{"schema_version": "0.0.1"}')
    manifest = export_bundle(data_dir, bundle_dir, "abc", CONFIG.sim, load_regulations(), BUDGETS)
    assert manifest.calibration_path is None

    source.write_text(accepted(-1.9, 0.5).model_dump_json())
    manifest = export_bundle(data_dir, bundle_dir, "abc", CONFIG.sim, load_regulations(), BUDGETS)
    assert manifest.calibration_path == "calibration.json"
    published = Calibration.model_validate_json((bundle_dir / "calibration.json").read_text())
    assert published.segments[0].log_score == -1.9
