import io
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path

from pitwall import store, weekend
from pitwall.ingest.storage import RaceTables, race_dir, write_race


def test_new_rounds_and_the_one_before_them_are_pulled() -> None:
    # Monday after round 7: 7 is new, 6 may have been amended by the stewards.
    assert weekend.plan_rounds([1, 2, 3, 4, 5, 6, 7], [1, 2, 3, 4, 5, 6], None) == ([7], [6])
    # Wednesday, nothing new: the last race is pulled again.
    assert weekend.plan_rounds([1, 2, 3], [1, 2, 3], None) == ([], [3])
    # A gap (a race that failed validation last week) is retried with the new one.
    assert weekend.plan_rounds([1, 2, 3, 4], [1, 2], None) == ([3, 4], [2])
    assert weekend.plan_rounds([1], [], None) == ([1], [])
    assert weekend.plan_rounds([], [], None) == ([], [])
    # A named round: pulled again if stored, ingested if not.
    assert weekend.plan_rounds([], [1, 2], 2) == ([], [2])
    assert weekend.plan_rounds([], [1, 2], 5) == ([5], [])


def test_a_failed_gate_puts_every_parameter_back(race_tables: RaceTables, tmp_path) -> None:
    data = tmp_path / "data"
    old = write_race(data, race_tables)
    (old / "degradation_draws.parquet").write_text("old draws")
    (old / "traffic.json").write_text("old traffic")
    (data / "models" / "sim").mkdir(parents=True)
    (data / "models" / "sim" / "calibration.json").write_text("old calibration")
    weekend.snapshot(data, tmp_path / "snapshot")

    # The run refits everything and ingests a new race, then a gate fails.
    (old / "degradation_draws.parquet").write_text("new draws")
    (old / "hazard_draws.parquet").write_text("draws the old run never had")
    (data / "models" / "sim" / "calibration.json").write_text("new calibration")
    new_race = race_tables.event.model_copy(update={"round": 2})
    new = write_race(data, RaceTables(**{**race_tables.__dict__, "event": new_race}))
    (new / "degradation_draws.parquet").write_text("new race draws")

    weekend.restore(data, tmp_path / "snapshot")
    assert (old / "degradation_draws.parquet").read_text() == "old draws"
    assert (old / "traffic.json").read_text() == "old traffic"
    assert not (old / "hazard_draws.parquet").exists()
    assert (data / "models" / "sim" / "calibration.json").read_text() == "old calibration"
    # The new race keeps its tables but no parameters: it publishes without a simulation.
    assert (new / "laps.parquet").exists()
    assert not any((new / name).exists() for name in weekend.PARAMETER_FILES)


class FakeReleases:
    """`gh release` against a dict of tag → {asset name: bytes}."""

    def __init__(self) -> None:
        self.releases: dict[str, dict[str, bytes]] = {}

    def __call__(self, args: Sequence[str]) -> str:
        assert args[0] == "release"
        command, rest = args[1], list(args[2:])
        if command == "list":
            return "\n".join(self.releases) + "\n"
        tag, rest = rest[0], rest[1:]
        if command == "view":
            if tag not in self.releases:
                raise subprocess.CalledProcessError(1, "gh")
        elif command == "create":
            self.releases[tag] = {}
        elif command == "upload":
            for path in (Path(a) for a in rest if not a.startswith("--")):
                self.releases[tag][path.name] = path.read_bytes()
        elif command == "download":
            folder = Path(rest[rest.index("--dir") + 1])
            folder.mkdir(parents=True)
            for name, content in self.releases[tag].items():
                (folder / name).write_bytes(content)
        return ""


def test_the_store_round_trips_races_and_models(race_tables: RaceTables, tmp_path) -> None:
    source = tmp_path / "source"
    write_race(source, race_tables)
    (source / "models" / "events").mkdir(parents=True)
    (source / "models" / "events" / "card.json").write_text("{}")
    gh = FakeReleases()

    store.push(source, [(2024, 1)], models=True, gh=gh)
    store.push(source, [(2024, 1)], models=True, gh=gh)  # publishing again replaces, never adds
    assert {tag: sorted(assets) for tag, assets in gh.releases.items()} == {
        "data-2024": ["race-2024-01.tar.gz"],
        "models": ["models.tar.gz"],
    }
    asset = io.BytesIO(gh.releases["data-2024"]["race-2024-01.tar.gz"])
    with tarfile.open(fileobj=asset) as archive:
        assert "./laps.parquet" in archive.getnames()

    target = tmp_path / "target"
    stale = race_dir(target, 2024, 1)
    stale.mkdir(parents=True)
    (stale / "degradation_draws.parquet").write_text("no longer published")
    assert store.pull(target, gh=gh) == 1
    assert sorted(p.name for p in race_dir(target, 2024, 1).iterdir()) == sorted(
        p.name for p in race_dir(source, 2024, 1).iterdir()
    )
    assert (target / "models" / "events" / "card.json").read_text() == "{}"
