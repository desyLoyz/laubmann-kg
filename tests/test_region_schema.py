from pathlib import Path
import json


def test_page_layout_schema_is_valid_json() -> None:
    schema_path = Path('schemas/page_layout.schema.json')
    data = json.loads(schema_path.read_text())
    assert data['title'] == 'PageLayout'
