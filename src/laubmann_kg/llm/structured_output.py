"""Parse structured LLM outputs into Pydantic models."""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def parse_structured(payload: str | dict[str, Any], model: type[T]) -> T:
    """Validate a JSON object or string against a Pydantic model."""
    if isinstance(payload, str):
        try:
            data: Any = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.error("LLM response is not valid JSON: %s", exc)
            raise
    else:
        data = payload
    try:
        return model.model_validate(data)
    except ValidationError:
        logger.error("LLM JSON did not match %s", model.__name__)
        raise
