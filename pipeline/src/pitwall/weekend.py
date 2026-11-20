"""Post-weekend run: which races to pull, and keeping the previous model parameters live when a gate
fails. The steps themselves are the pipeline's own commands (`pitwall weekend`)."""

import gzip
import shutil
from dataclasses import dataclass
from pathlib import Path

from pitwall.export.contract import SegmentScore
from pitwall.ingest.storage import list_races

# Files the fits write into a race's directory. Together with `.data/models` they are the model
# parameters: published together, or not at all.
PARAMETER_FILES = (
    "degradation_draws.parquet",
    "hazard_draws.parquet",
    "events.json",
    "traffic_draws.parquet",
    "traffic.json",
    "warmup_draws.parquet",
)


def plan_rounds(
    finished: list[int], stored: list[int], round_: int | None
) -> tuple[list[int], list[int]]:
    """(new rounds to ingest, stored rounds to pull again). A named round is pulled whether or not
    it is stored. Otherwise every finished round not stored yet is new, and the last stored round
    before them is pulled again: post-race penalties amend its classification."""
    if round_ is not None:
        return ([], [round_]) if round_ in stored else ([round_], [])
    new = sorted(set(finished) - set(stored))
    before = [r for r in stored if not new or r < new[0]]
    return new, before[-1:]


def snapshot(data_dir: Path, folder: Path) -> None:
    """Copy the parameters live before a run: every race's parameter files, and the models."""
    for race in list_races(data_dir):
        target = folder / race.relative_to(data_dir)
        for name in PARAMETER_FILES:
            if (race / name).exists():
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(race / name, target / name)
    if (data_dir / "models").exists():
        shutil.copytree(data_dir / "models", folder / "models")


def restore(data_dir: Path, folder: Path) -> None:
    """Put the snapshot's parameters back. A race that had none (a new race) is left with none:
    its descriptive data publishes, its simulation waits for a run whose gates pass."""
    for race in list_races(data_dir):
        for name in PARAMETER_FILES:
            (race / name).unlink(missing_ok=True)
            saved = folder / race.relative_to(data_dir) / name
            if saved.exists():
                shutil.copy2(saved, race / name)
    if (folder / "models").exists():
        shutil.rmtree(data_dir / "models", ignore_errors=True)
        shutil.copytree(folder / "models", data_dir / "models")


@dataclass(frozen=True)
class RaceOutcome:
    season: int
    round: int
    name: str
    status: str  # new, amended, unchanged or rejected
    laps: int
    clean: int
    warnings: int


def largest_files(bundle_dir: Path) -> dict[str, tuple[str, int]]:
    """The largest file of each kind in the bundle, gzipped: the size the browser downloads."""
    kinds = {
        "race": "races/*/*[0-9].json",
        "sim": "races/*/*.sim.json",
        "replay": "races/*/*.replay.json",
        "telemetry lap": "races/*/*/telemetry/*.json",
    }
    largest = {}
    for kind, pattern in kinds.items():
        sizes = {
            str(p.relative_to(bundle_dir)): len(gzip.compress(p.read_bytes()))
            for p in bundle_dir.glob(pattern)
        }
        if sizes:
            name = max(sizes, key=lambda k: sizes[k])
            largest[kind] = (name, sizes[name])
    return largest


def report(
    races: list[RaceOutcome],
    gates: dict[str, bool],
    before: SegmentScore | None,
    after: SegmentScore | None,
    largest: dict[str, tuple[str, int]],
    published: str,
) -> str:
    """The run's job summary, in Markdown."""
    lines = ["# Weekend run", "", "| Race | Status | Laps | Clean | Warnings |"]
    lines.append("|---|---|---|---|---|")
    lines += [
        f"| {r.season} R{r.round} {r.name} | {r.status} | {r.laps} | {r.clean} | {r.warnings} |"
        for r in races
    ]
    if gates:
        lines += ["", "| Gate | Result |", "|---|---|"]
        lines += [f"| {name} | {'passed' if ok else 'FAILED'} |" for name, ok in gates.items()]
    if before or after:
        lines += ["", "| Calibration, all races | Coverage 50 % | Coverage 80 % | Log score |"]
        lines += ["|---|---|---|---|"]
        for label, score in (("before", before), ("after", after)):
            if score:
                lines.append(
                    f"| {label} | {score.coverage_50:.3f} | {score.coverage_80:.3f} "
                    f"| {score.log_score:.4f} |"
                )
    if largest:
        lines += ["", "| Largest file | Path | Gzipped bytes |", "|---|---|---|"]
        lines += [f"| {kind} | {path} | {size:,} |" for kind, (path, size) in largest.items()]
    lines += ["", published, ""]
    return "\n".join(lines)
