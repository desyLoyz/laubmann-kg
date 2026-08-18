"""JSON read/write helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def read_json(path: Path) -> Any:
    """Read a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: BaseModel | dict[str, Any] | list[Any]) -> None:
    """Write JSON without overwriting raw source images or transcripts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, BaseModel):
        payload = json.dumps(data.model_dump(mode="json"), ensure_ascii=False, indent=2)
    else:
        payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    path.write_text(payload + "\n", encoding="utf-8")
    logger.info("Wrote JSON: %s", path)
