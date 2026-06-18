from laubmann_kg.dwca import run
from pathlib import Path
import pytest


def test_dwca_export_not_implemented(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError):
        run(Path('configs/dwca.yaml'), tmp_path, tmp_path)
