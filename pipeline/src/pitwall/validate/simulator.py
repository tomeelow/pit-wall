"""Simulator calibration (plan Phase 7): is the simulated distribution of finishing places right
as often as it claims?

The TypeScript engine (web/scripts/backtest.ts) runs every simulable race ex ante from several
start laps, with the strategies actually run. Safety cars, VSCs, red flags, retirements and slow
stops are sampled, never replayed; their rates for a race come from refits without it. Pace and
the pass model are fitted on every race, the race itself included: the documented softening.

Every car running at a start lap is one entry. Its outcome is its official place, or "not
classified" (one more category, the worst). It is scored by:
- randomised PIT: F(y - 1) + U * P(y). Uniform when the distribution is calibrated, so the share
  inside [0.25, 0.75] is 50 % and inside [0.1, 0.9] is 80 %;
- the simulated central interval of places (discrete, so it should hold at least that often);
- log score against two baselines: P(outcome | place at the start lap) and P(outcome | place
  after lap 1), each learnt from every other race at the same share of race distance.
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pitwall.config import SimulatorGate, SimValidationConfig
from pitwall.export.contract import (
    SCHEMA_VERSION,
    Calibration,
    GateResult,
    SegmentScore,
    SimRace,
)

NODE = ("node", "--disable-warning=ExperimentalWarning")


def run_backtest(web_dir: Path, bundle_dir: Path, settings: SimValidationConfig) -> dict:
    """The engine's finish counts for every simulable race in the bundle."""
    fractions = ",".join(str(f) for f in settings.start_fractions)
    args = [str(bundle_dir), str(settings.runs), str(settings.seed), fractions]
    done = subprocess.run(
        [*NODE, "scripts/backtest.ts", *args],
        cwd=web_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def _order(times: list[float | None]) -> dict[int, int]:
    """Car index → place among the cars with a time."""
    running = sorted((t, i) for i, t in enumerate(times) if t is not None)
    return {i: place for place, (_, i) in enumerate(running, start=1)}


def entries(backtest: dict, races: dict[tuple[int, int], SimRace]) -> pd.DataFrame:
    """One row per car running at a start lap: its counts, outcome and the places the baselines
    condition on. outcome and count index: place - 1, or `cars` for not classified."""
    passability = {key: float(np.mean(r.traffic.intercept)) for key, r in races.items()}
    rows = []
    for result in backtest["races"]:
        key = (result["season"], result["round"])
        race = races[key]
        cars = len(race.cars)
        after_lap1 = _order(race.snapshots[0].race_time_s)
        for start in result["starts"]:
            lap = start["lap"]
            at_start = _order(race.snapshots[lap - 1].race_time_s)
            neutralised = any(n.end_lap > lap for n in race.realised)
            for i, car in enumerate(race.cars):
                if i not in at_start:
                    continue
                place = car.finish_position
                rows.append(
                    {
                        "race": f"{race.season}-{race.round:02d}",
                        "era": race.era,
                        "fraction": start["fraction"],
                        "lap": lap,
                        "driver": car.driver,
                        "cars": cars,
                        "start_place": at_start[i],
                        "lap1_place": after_lap1.get(i, at_start[i]),
                        "outcome": cars if place is None else place - 1,
                        "counts": np.asarray(start["counts"][i], dtype=float),
                        "neutralised_after": neutralised,
                        "passability": passability[key],
                    }
                )
    return pd.DataFrame(rows)


def probabilities(counts: np.ndarray, smoothing: float) -> np.ndarray:
    return (counts + smoothing) / (counts.sum() + smoothing * len(counts))


def randomised_pit(p: np.ndarray, outcome: int, u: float) -> float:
    return float(p[:outcome].sum() + u * p[outcome])


def central_interval(counts: np.ndarray, level: float) -> tuple[int, int]:
    """Indexes of the lowest and highest outcome in the central `level` interval of the runs."""
    cdf = np.cumsum(counts) / counts.sum()
    # The tolerance keeps a tail that holds exactly (1 - level) / 2 out of the interval despite
    # rounding in the level arithmetic.
    lo = int(np.searchsorted(cdf, (1 - level) / 2 + 1e-12, side="right"))
    hi = int(np.searchsorted(cdf, (1 + level) / 2 - 1e-12, side="left"))
    return lo, min(hi, len(counts) - 1)


def baseline_log_scores(rows: pd.DataFrame, condition: str, smoothing: float) -> np.ndarray:
    """log P(outcome | `condition` place), learnt per start fraction from every other race.

    Outcomes are pooled on a shared scale: places 1 .. max cars, then not classified. For a race
    with fewer cars, places it cannot have are dropped before normalising."""
    width = int(rows["cars"].max()) + 1
    category = np.where(rows["outcome"] == rows["cars"], width - 1, rows["outcome"])
    frame = rows.reset_index(drop=True).assign(category=category)
    scores = np.empty(len(frame))
    for _, group in frame.groupby("fraction"):
        totals = np.zeros((width, width))
        np.add.at(totals, (group[condition] - 1, group["category"]), 1)
        for _, race in group.groupby("race"):
            own = np.zeros((width, width))
            np.add.at(own, (race[condition] - 1, race["category"]), 1)
            others = totals - own
            for idx, row in zip(race.index, race.to_dict("records"), strict=True):
                allowed = np.r_[np.arange(row["cars"]), width - 1]
                counts = others[row[condition] - 1, allowed]
                p = probabilities(counts, smoothing)
                k = row["outcome"] if row["outcome"] < row["cars"] else len(allowed) - 1
                scores[idx] = np.log(p[k])
    return scores


def score(rows: pd.DataFrame, settings: SimValidationConfig) -> pd.DataFrame:
    """Per-entry PIT, interval hits and log scores of the simulator and both baselines."""
    rng = np.random.default_rng(settings.seed)
    pit, log_score, hits = [], [], {50: [], 80: []}
    for row in rows.to_dict("records"):
        counts, y = row["counts"], row["outcome"]
        p = probabilities(counts, settings.smoothing)
        pit.append(randomised_pit(p, y, float(rng.uniform())))
        log_score.append(float(np.log(p[y])))
        for level in hits:
            lo, hi = central_interval(counts, level / 100)
            hits[level].append(lo <= y <= hi)
    return rows.assign(
        pit=pit,
        log_score=log_score,
        interval_50=hits[50],
        interval_80=hits[80],
        log_score_start_order=baseline_log_scores(rows, "start_place", settings.smoothing),
        log_score_lap1_order=baseline_log_scores(rows, "lap1_place", settings.smoothing),
    )


def _segment(name: str, rows: pd.DataFrame) -> SegmentScore:
    pit = rows["pit"]
    return SegmentScore(
        segment=name,
        races=rows["race"].nunique(),
        entries=len(rows),
        coverage_50=round(float(pit.between(0.25, 0.75).mean()), 3),
        coverage_80=round(float(pit.between(0.1, 0.9).mean()), 3),
        interval_coverage_50=round(float(rows["interval_50"].mean()), 3),
        interval_coverage_80=round(float(rows["interval_80"].mean()), 3),
        log_score=round(float(rows["log_score"].mean()), 4),
        log_score_start_order=round(float(rows["log_score_start_order"].mean()), 4),
        log_score_lap1_order=round(float(rows["log_score_lap1_order"].mean()), 4),
    )


def segments(scored: pd.DataFrame) -> list[SegmentScore]:
    """Overall, then by start, era, neutralisation after the start and how hard passing is."""
    passing = pd.qcut(
        scored.groupby("race")["passability"].first(), 3, labels=["hard", "medium", "easy"]
    )
    frame = scored.assign(passing=scored["race"].map(passing))
    out = [_segment("all", frame)]
    for fraction, rows in frame.groupby("fraction"):
        label = "after lap 1" if fraction == 0 else f"{fraction:.0%} distance"
        out.append(_segment(f"start: {label}", rows))
    for era, rows in frame.groupby("era"):
        out.append(_segment(f"era: {era}", rows))
    for neutralised, rows in frame.groupby("neutralised_after"):
        out.append(_segment(f"neutralised after start: {'yes' if neutralised else 'no'}", rows))
    for passing_label, rows in frame.groupby("passing", observed=True):
        out.append(_segment(f"passing: {passing_label}", rows))
    return out


def pit_histogram(scored: pd.DataFrame, bins: int) -> list[float]:
    counts, _ = np.histogram(scored["pit"], bins=bins, range=(0, 1))
    return [round(float(c), 4) for c in counts / counts.sum()]


def accepted_overall(path: Path) -> SegmentScore | None:
    """The overall score of the accepted calibration, read on its own: a contract bump elsewhere
    must not lose the comparison. A change to the score's own shape raises."""
    if not path.exists():
        return None
    return SegmentScore.model_validate(json.loads(path.read_text())["segments"][0])


def gate(
    scored: pd.DataFrame,
    overall: SegmentScore,
    accepted: SegmentScore | None,
    thresholds: SimulatorGate,
) -> GateResult:
    reasons = []
    late = scored[scored["fraction"] >= thresholds.must_beat_baseline_from]
    for fraction, rows in late.groupby("fraction"):
        model, baseline = rows["log_score"].mean(), rows["log_score_start_order"].mean()
        if model <= baseline:
            reasons.append(
                f"from {fraction:.0%} distance the simulator ({model:.3f}) does not beat the "
                f"order at the start lap ({baseline:.3f})"
            )
    if accepted is not None:
        before = accepted
        if overall.log_score < before.log_score - thresholds.max_log_score_regression:
            reasons.append(f"log score fell from {before.log_score} to {overall.log_score}")
        for level, now, then in (
            (0.5, overall.coverage_50, before.coverage_50),
            (0.8, overall.coverage_80, before.coverage_80),
        ):
            if abs(now - level) > abs(then - level) + thresholds.max_coverage_error_growth:
                reasons.append(f"{level:.0%} coverage moved from {then} to {now}")
    return GateResult(passed=not reasons, reasons=reasons)


def calibration(
    scored: pd.DataFrame,
    races: dict[tuple[int, int], SimRace],
    settings: SimValidationConfig,
    accepted: SegmentScore | None,
    thresholds: SimulatorGate,
    git_sha: str,
) -> Calibration:
    parts = segments(scored)
    versions = sorted(r.dataset_version for r in races.values())
    return Calibration(
        schema_version=SCHEMA_VERSION,
        git_sha=git_sha,
        generated_at=datetime.now(UTC),
        dataset_version=hashlib.sha256("".join(versions).encode()).hexdigest()[:16],
        runs=settings.runs,
        segments=parts,
        pit_histogram=pit_histogram(scored, settings.pit_bins),
        gate=gate(scored, parts[0], accepted, thresholds),
    )
