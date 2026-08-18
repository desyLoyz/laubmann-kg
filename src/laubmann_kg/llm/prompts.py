"""Load and render versioned prompt templates."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PromptTemplate(BaseModel):
    """A versioned prompt with system text and an optional user template."""

    id: str
    version: str
    description: str | None = None
    system: str
    user_template: str = Field(default="{text}")

    def render_user(self, text: str, **extra: Any) -> str:
        """Fill the user template with the source text and extra fields."""
        return self.user_template.format(text=text, **extra)


def load_prompt(path: Path) -> PromptTemplate:
    """Load a YAML or Markdown prompt template from disk."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Prompt file {path} must contain a YAML mapping")
        return PromptTemplate.model_validate(data)

    return PromptTemplate(
        id=path.stem,
        version="unversioned",
        system=raw.strip(),
        user_template="{text}",
    )
