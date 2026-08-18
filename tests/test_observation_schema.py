from pathlib import Path

import json

from laubmann_kg.extraction.schemas import ObservationEventModel


def test_observation_schema_is_valid_json() -> None:
    schema_path = Path("schemas/observation.schema.json")
    data = json.loads(schema_path.read_text())
    assert data["title"] == "Observation"


def test_observation_pydantic_schema_matches_export() -> None:
    exported = ObservationEventModel.model_json_schema()
    assert exported["title"] == "Observation"
    assert "observed_taxon" in exported["properties"]
