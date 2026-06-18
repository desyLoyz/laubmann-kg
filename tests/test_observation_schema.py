from pathlib import Path
import json


def test_observation_schema_is_valid_json() -> None:
    schema_path = Path('schemas/observation.schema.json')
    data = json.loads(schema_path.read_text())
    assert data['title'] == 'Observation'
