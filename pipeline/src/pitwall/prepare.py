"""Source tables → race state and classified laps, the inputs every model reads."""

from dataclasses import replace

from pitwall.config import ClassificationConfig
from pitwall.ingest.storage import RaceTables
from pitwall.laps import classify_laps
from pitwall.race_state import build_race_state


def prepare_race(tables: RaceTables, config: ClassificationConfig) -> RaceTables:
    race_state = build_race_state(tables.laps, tables.results)
    laps = classify_laps(tables.laps, race_state, tables.neutralisations, tables.yellows, config)
    return replace(tables, laps=laps, race_state=race_state)
