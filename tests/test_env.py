import os
from pathlib import Path

from laubmann_kg.env import find_dotenv, load_dotenv


def test_load_dotenv_sets_missing_keys_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LAUBMANN_TEST_KEY", raising=False)
    monkeypatch.setenv("LAUBMANN_TEST_KEEP", "from-env")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LAUBMANN_TEST_KEY=from-file\nLAUBMANN_TEST_KEEP=from-file\n",
        encoding="utf-8",
    )
    assert load_dotenv(env_file) == env_file
    assert os.environ["LAUBMANN_TEST_KEY"] == "from-file"
    assert os.environ["LAUBMANN_TEST_KEEP"] == "from-env"


def test_find_dotenv_stops_at_repo_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    assert find_dotenv(nested) is None
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    assert find_dotenv(nested) == tmp_path / ".env"
