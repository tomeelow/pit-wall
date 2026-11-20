"""The pipeline's durable store: GitHub Releases (ADR-008).

One release per season holds each race's directory (canonical tables, traces and the model
parameters exported to it) as `race-<season>-<round>.tar.gz`, and the season's validation summary.
A `models` release holds `.data/models`. Uploads replace an asset of the same name, so publishing
twice never duplicates one. The raw OpenF1 cache is not stored: everything here is derived from it.
"""

import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from loguru import logger

from pitwall.ingest.storage import race_dir, season_dir

SEASON_PREFIX = "data-"
MODELS_RELEASE = "models"

# Runs `gh` with these arguments and returns stdout; raises on failure.
Gh = Callable[[Sequence[str]], str]


def run_gh(args: Sequence[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def race_asset(season: int, round_: int) -> str:
    return f"race-{season}-{round_:02d}.tar.gz"


def _pack(source: Path, out: Path) -> Path:
    with tarfile.open(out, "w:gz") as archive:
        archive.add(source, arcname=".")
    return out


def _unpack(archive_path: Path, target: Path) -> None:
    """Replaces target: a file the published copy no longer has must not survive locally."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with tarfile.open(archive_path) as archive:
        archive.extractall(target, filter="data")


def _ensure_release(tag: str, title: str, gh: Gh) -> None:
    try:
        gh(["release", "view", tag])
    except subprocess.CalledProcessError:
        gh(
            [
                "release",
                "create",
                tag,
                "--title",
                title,
                "--notes",
                "Pipeline data for Pit Wall (ADR-008), replaced by the weekend workflow.",
                "--latest=false",
            ]
        )


def push(data_dir: Path, races: Sequence[tuple[int, int]], models: bool, gh: Gh = run_gh) -> None:
    """Upload these races' directories (and the models, if asked), replacing earlier uploads."""
    with tempfile.TemporaryDirectory() as tmp:
        for season in sorted({s for s, _ in races}):
            tag = f"{SEASON_PREFIX}{season}"
            _ensure_release(tag, f"Pipeline data {season}", gh)
            files = [
                _pack(race_dir(data_dir, s, r), Path(tmp) / race_asset(s, r))
                for s, r in races
                if s == season
            ]
            summary = season_dir(data_dir, season) / "summary.json"
            if summary.exists():
                files.append(Path(shutil.copy(summary, Path(tmp) / f"summary-{season}.json")))
            gh(["release", "upload", tag, *map(str, files), "--clobber"])
            logger.info("{}: uploaded {} files", tag, len(files))
        if models:
            _ensure_release(MODELS_RELEASE, "Pipeline models", gh)
            archive = _pack(data_dir / "models", Path(tmp) / "models.tar.gz")
            gh(["release", "upload", MODELS_RELEASE, str(archive), "--clobber"])
            logger.info("{}: uploaded models", MODELS_RELEASE)


def pull(data_dir: Path, gh: Gh = run_gh) -> int:
    """Download every season's races and the models into data_dir, replacing local copies of the
    same races. Returns the races restored."""
    tags = gh(["release", "list", "--limit", "100", "--json", "tagName", "-q", ".[].tagName"])
    restored = 0
    with tempfile.TemporaryDirectory() as tmp:
        for tag in tags.split():
            if not (tag.startswith(SEASON_PREFIX) or tag == MODELS_RELEASE):
                continue
            folder = Path(tmp) / tag
            gh(["release", "download", tag, "--dir", str(folder)])
            if tag == MODELS_RELEASE:
                _unpack(folder / "models.tar.gz", data_dir / "models")
                continue
            season = int(tag.removeprefix(SEASON_PREFIX))
            for archive in sorted(folder.glob("race-*.tar.gz")):
                round_ = int(archive.name.removesuffix(".tar.gz").rsplit("-", 1)[1])
                _unpack(archive, race_dir(data_dir, season, round_))
                restored += 1
            summary = folder / f"summary-{season}.json"
            if summary.exists():
                shutil.copy(summary, season_dir(data_dir, season) / "summary.json")
    logger.info("restored {} races from releases", restored)
    return restored
