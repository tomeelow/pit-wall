import pytest
from pydantic import ValidationError

from pitwall.config import RaceAllocation, load_allocations, load_team_ids


def test_allocation_must_run_hard_to_soft() -> None:
    with pytest.raises(ValidationError, match="hard < medium < soft"):
        RaceAllocation(round=1, race="Bahrain Grand Prix", hard=3, medium=2, soft=4)


def test_allocation_needs_a_source(tmp_path) -> None:
    path = tmp_path / "allocation.yaml"
    path.write_text("2024:\n  sources: []\n  races: []\n")
    with pytest.raises(ValidationError, match="sources"):
        load_allocations(path)


def test_a_round_cannot_be_allocated_twice(tmp_path) -> None:
    race = "{round: 1, race: Bahrain Grand Prix, hard: 1, medium: 2, soft: 3}"
    path = tmp_path / "allocation.yaml"
    path.write_text(f"2024:\n  sources: [https://example.org]\n  races: [{race}, {race}]\n")
    with pytest.raises(ValueError, match="allocated twice"):
        load_allocations(path)


def test_repository_config_loads() -> None:
    assert load_allocations() is not None
    assert len(set(load_team_ids().values())) >= 10
