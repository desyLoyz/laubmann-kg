"""Load a project ``.env`` into ``os.environ`` (does not override existing vars).

The Gemini client only reads process environment variables. Colab notebooks set
those explicitly; a local ``laubmann-kg`` CLI run does not, so a ``.env`` next
to ``pyproject.toml`` (or in the working directory) was previously ignored.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def find_dotenv(start: Optional[Path] = None) -> Optional[Path]:
    """``.env`` in ``start`` or a parent, stopping at the repo root."""
    folder = (start or Path.cwd()).resolve()
    for candidate in [folder, *folder.parents]:
        env_path = candidate / ".env"
        if env_path.is_file():
            return env_path
        if (candidate / "pyproject.toml").is_file():
            return None
    return None


def load_dotenv(path: Optional[Path] = None) -> Optional[Path]:
    """Populate ``os.environ`` from a dotenv file. Returns the path loaded, or None."""
    env_path = Path(path) if path is not None else find_dotenv()
    if env_path is None or not env_path.is_file():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value
    logger.debug("loaded environment file %s", env_path)
    return env_path
