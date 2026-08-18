"""Retry logic for LLM calls."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _is_non_retryable_auth_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in {400, 401, 403}:
        return True
    text = str(exc)
    return any(
        marker in text
        for marker in (
            "UNAUTHENTICATED",
            "ACCESS_TOKEN_TYPE_UNSUPPORTED",
            "HTTP 401",
            "HTTP 403",
        )
    )


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 1.0,
    retry_auth_errors: bool = True,
) -> T:
    """Call ``fn`` with exponential backoff on transient failures."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — retry wrapper must catch provider errors
            last_error = exc
            if (not retry_auth_errors and _is_non_retryable_auth_error(exc)) or attempt == attempts:
                break
            delay = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "LLM call failed (attempt %s/%s): %s; retrying in %.1fs",
                attempt,
                attempts,
                exc,
                delay,
            )
            time.sleep(delay)
    assert last_error is not None
    raise last_error
