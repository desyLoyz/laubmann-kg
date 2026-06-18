from laubmann_kg.kg import run
from pathlib import Path
import pytest


def test_jsonld_export_not_implemented(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError):
        run(Path('configs/ontology.yaml'), tmp_path, tmp_path)
