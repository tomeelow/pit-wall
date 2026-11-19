"""The export contract: the only interface between the pipeline and the web app.

`make contract` turns these models into JSON Schema (contract/) and TypeScript types
(web/src/contract/). Bump SCHEMA_VERSION on every change; bump the major on breaking ones.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.json_schema import GenerateJsonSchema

SchemaVersion = Literal["0.1.0"]
SCHEMA_VERSION: SchemaVersion = "0.1.0"

Compound = Literal["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Stint(_Contract):
    stint: int
    compound: Compound
    start_lap: int
    end_lap: int
    tyre_age_at_start: int | None


class DriverRace(_Contract):
    driver: str
    team: str
    position: int | None
    status: str
    stints: list[Stint]


class Race(_Contract):
    schema_version: SchemaVersion
    season: int
    round: int
    name: str
    total_laps: int
    dataset_version: str
    drivers: list[DriverRace]


class RaceEntry(_Contract):
    season: int
    round: int
    name: str
    path: str
    dataset_version: str


class Manifest(_Contract):
    schema_version: SchemaVersion
    git_sha: str
    generated_at: datetime
    races: list[RaceEntry]


TOP_LEVEL: dict[str, type[_Contract]] = {"manifest": Manifest, "race": Race}


class _UntitledFields(GenerateJsonSchema):
    """Field titles would become one TypeScript alias per field (`Season = number`, ...)."""

    def field_title_should_be_set(self, schema: object) -> bool:
        return False


def write_schemas(out_dir: Path) -> list[Path]:
    """Serialization-mode schemas: they describe the JSON the browser receives."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in TOP_LEVEL.items():
        path = out_dir / f"{name}.schema.json"
        schema = model.model_json_schema(mode="serialization", schema_generator=_UntitledFields)
        path.write_text(json.dumps(schema, indent=2) + "\n")
        written.append(path)
    return written
