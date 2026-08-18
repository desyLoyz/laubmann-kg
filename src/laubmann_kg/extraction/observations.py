"""Extract biological observations from transcribed diary entries."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from laubmann_kg.extraction.schemas import (
    DiaryEntryModel,
    ExtractedDocument,
    ExtractionProvenance,
)
from laubmann_kg.io.json import write_json
from laubmann_kg.llm.cache import cache_key, read_cache, write_cache
from laubmann_kg.llm.clients import StructuredLLMClient, build_client
from laubmann_kg.llm.prompts import PromptTemplate, load_prompt
from laubmann_kg.llm.structured_output import parse_structured

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = Path("prompts/extraction_prompt.yaml")
_VOLUME_RE = re.compile(r"vol(?:ume)?[_\-]?(\d+)", re.IGNORECASE)
_PAGE_RE = re.compile(r"page[_\-]?(\d+)", re.IGNORECASE)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _repo_root(start: Path) -> Path:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "prompts").is_dir():
            return candidate
    return Path.cwd()


def _extraction_settings(config: Path) -> dict[str, Any]:
    """Read provider/model/prompt/cache paths from pipeline and sibling configs."""
    config = config.resolve()
    pipeline = _load_yaml(config)
    models = _load_yaml(config.parent / "models.yaml")
    prompts = _load_yaml(config.parent / "prompts.yaml")
    extraction = models.get("extraction", {})
    repo = _repo_root(config)
    prompt_rel = prompts.get("extraction") or prompts.get("observation_extraction")
    prompt_path = repo / prompt_rel if prompt_rel else repo / _DEFAULT_PROMPT
    cache_rel = pipeline.get("paths", {}).get("cache", "data/cache/llm")
    return {
        "provider": str(extraction.get("provider", "openai")),
        "model": str(extraction.get("model", "gpt-4o")),
        "prompt_path": prompt_path,
        "cache_dir": repo / cache_rel,
        "volume": pipeline.get("volume"),
    }


def _infer_volume_page(source: Path, configured_volume: str | None) -> tuple[str | None, str | None]:
    text = str(source)
    volume = configured_volume
    if volume is None:
        match = _VOLUME_RE.search(text)
        volume = f"vol{match.group(1).zfill(2)}" if match else None
    page_match = _PAGE_RE.search(source.name)
    page = page_match.group(1) if page_match else None
    return volume, page


def extract_from_text(
    text: str,
    *,
    client: StructuredLLMClient | None = None,
    config: Path | None = None,
    prompt: PromptTemplate | None = None,
    provider: str | None = None,
    model: str | None = None,
    cache_dir: Path | None = None,
) -> DiaryEntryModel:
    """Extract a structured diary entry from transcribed markdown/text via LLM."""
    settings = _extraction_settings(config) if config is not None else {
        "provider": "openai",
        "model": "gpt-4o",
        "prompt_path": Path.cwd() / _DEFAULT_PROMPT,
        "cache_dir": Path.cwd() / "data/cache/llm",
        "volume": None,
    }
    resolved_provider = provider or str(settings["provider"])
    resolved_model = model or str(settings["model"])
    resolved_prompt = prompt or load_prompt(Path(settings["prompt_path"]))
    resolved_cache = cache_dir if cache_dir is not None else Path(settings["cache_dir"])

    system_prompt = resolved_prompt.system
    user_prompt = resolved_prompt.render_user(text)
    key = cache_key(
        resolved_prompt.id,
        resolved_prompt.version,
        resolved_model,
        system_prompt,
        user_prompt,
    )
    cached = read_cache(resolved_cache, key)
    if cached is not None:
        return parse_structured(cached, DiaryEntryModel)

    llm = client or build_client(resolved_provider)
    entry = llm.complete_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=DiaryEntryModel,
        model=resolved_model,
    )
    write_cache(resolved_cache, key, entry.model_dump(mode="json"))
    return entry


def run(config: Path, input_dir: Path, output_dir: Path) -> None:
    """Read transcribed `.md` files, extract observations, and write JSON."""
    logger.info(
        "extract_observations: config=%s input_dir=%s output_dir=%s",
        config,
        input_dir,
        output_dir,
    )
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    settings = _extraction_settings(config)
    prompt = load_prompt(Path(settings["prompt_path"]))
    client = build_client(str(settings["provider"]))
    markdown_files = sorted(input_dir.rglob("*.md"))
    if not markdown_files:
        logger.warning("No markdown files found in %s", input_dir)
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    for source in markdown_files:
        logger.info("Extracting observations from %s", source)
        text = source.read_text(encoding="utf-8")
        entry = extract_from_text(
            text,
            client=client,
            config=config,
            prompt=prompt,
            provider=str(settings["provider"]),
            model=str(settings["model"]),
            cache_dir=Path(settings["cache_dir"]),
        )
        volume, page = _infer_volume_page(
            source,
            settings["volume"] if isinstance(settings.get("volume"), str) else None,
        )
        document = ExtractedDocument(
            provenance=ExtractionProvenance(
                source_path=str(source),
                volume=volume,
                page=page,
                model=str(settings["model"]),
                provider=str(settings["provider"]),
                prompt_id=prompt.id,
                prompt_version=prompt.version,
                extracted_at=datetime.now(timezone.utc),
            ),
            diary_entry=entry,
        )
        relative = source.relative_to(input_dir)
        destination = output_dir / relative.with_suffix(".json")
        write_json(destination, document)
        logger.info("Wrote %s (%s observations)", destination, len(entry.observations))
