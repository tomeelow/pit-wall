import json

from pitwall.config import load_regulations
from pitwall.export.bundle import build_race, export_bundle
from pitwall.export.contract import SCHEMA_VERSION, Manifest, Race, write_schemas
from pitwall.ingest.storage import RaceTables, write_race
from tests.conftest import BUDGETS, CONFIG


def test_stints_follow_the_laps(race_tables: RaceTables) -> None:
    race = build_race(race_tables)
    lec = next(d for d in race.drivers if d.driver == "LEC")
    assert [(s.compound, s.start_lap, s.end_lap) for s in lec.stints] == [
        ("SOFT", 1, 15),
        ("HARD", 16, 40),
        ("SOFT", 41, 57),
    ]


def test_used_sets_keep_their_age(race_tables: RaceTables) -> None:
    race = build_race(race_tables)
    lec = next(d for d in race.drivers if d.driver == "LEC")
    assert [s.tyre_age_at_start for s in lec.stints] == [3, 0, 2]


def test_drivers_ordered_by_finish_with_unclassified_last(race_tables: RaceTables) -> None:
    race = build_race(race_tables)
    assert [d.driver for d in race.drivers] == ["VER", "LEC", "SAR"]
    assert race.drivers[-1].position is None


def test_exported_bundle_validates_against_the_contract(race_tables: RaceTables, tmp_path) -> None:
    data_dir, bundle_dir = tmp_path / "data", tmp_path / "bundle"
    write_race(data_dir, race_tables)

    manifest = export_bundle(
        data_dir, bundle_dir, "abc123", CONFIG.sim, load_regulations(), BUDGETS
    )

    reloaded = Manifest.model_validate_json((bundle_dir / "manifest.json").read_text())
    assert reloaded == manifest
    assert [entry.path for entry in manifest.races] == ["races/2024/01.json"]
    assert manifest.races[0].sim_path is None  # no fitted models in this bundle
    race = Race.model_validate_json((bundle_dir / manifest.races[0].path).read_text())
    assert race.schema_version == SCHEMA_VERSION
    assert race.dataset_version == manifest.races[0].dataset_version


def test_schemas_require_every_field(tmp_path) -> None:
    for path in write_schemas(tmp_path):
        schema = json.loads(path.read_text())
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False
