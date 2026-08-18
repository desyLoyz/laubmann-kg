"""Cache LLM requests and responses on disk."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def cache_key(*parts: str) -> str:
    """Build a stable SHA-256 cache key from prompt and model parts."""
    joined = "\n".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def cache_path(cache_dir: Path, key: str) -> Path:
    """Return the JSON file path for a cache key."""
    return cache_dir / f"{key}.json"


def read_cache(cache_dir: Path, key: str) -> dict[str, Any] | None:
    """Return a cached JSON payload, or None on a miss."""
    path = cache_path(cache_dir, key)
    if not path.exists():
        return None
    logger.info("LLM cache hit: %s", path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_cache(cache_dir: Path, key: str, payload: dict[str, Any]) -> None:
    """Store an LLM response JSON payload. Never overwrites raw source data."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(cache_dir, key)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("LLM cache write: %s", path)
