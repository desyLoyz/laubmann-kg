"""LLM API client wrappers with structured Pydantic outputs."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol, TypeVar

import httpx
from openai import OpenAI
from pydantic import BaseModel

from laubmann_kg.llm.retry import with_retry
from laubmann_kg.llm.structured_output import parse_structured

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

GOOGLE_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/"


class StructuredLLMClient(Protocol):
    """Minimal client interface used by extraction stages."""

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        model: str,
    ) -> T:
        """Return a Pydantic instance parsed from a structured LLM response."""
        ...


class OpenAICompatibleClient:
    """OpenAI SDK client for OpenAI (not used for Google AI Studio keys)."""

    def __init__(self, client: OpenAI) -> None:
        self._client = client

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        model: str,
    ) -> T:
        def _call() -> T:
            completion = self._client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=response_model,
            )
            parsed = completion.choices[0].message.parsed
            if parsed is not None:
                return parsed
            content = completion.choices[0].message.content
            if not content:
                raise ValueError("LLM returned empty structured output")
            return parse_structured(content, response_model)

        return with_retry(_call)


def strip_bearer_use_api_key(request: httpx.Request, api_key: str) -> None:
    """Send AI Studio keys as ``x-goog-api-key``, never as OAuth Bearer tokens."""
    for name in list(request.headers.keys()):
        if name.lower() in {"authorization", "proxy-authorization"}:
            del request.headers[name]
    request.headers["x-goog-api-key"] = api_key


def _interaction_output_text(payload: dict[str, object]) -> str:
    """Extract the model text from an Interactions API response."""
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in reversed(steps):
            if not isinstance(step, dict) or step.get("type") != "model_output":
                continue
            content = step.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"]:
                    return str(part["text"])
    raise ValueError("Gemini Interactions response did not contain output text")


class GeminiClient:
    """Gemini Developer API via REST, using an AI Studio API key header (not OAuth)."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._http = httpx.Client(timeout=120.0)

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        model: str,
    ) -> T:
        def _call() -> T:
            # AQ. AI Studio keys authenticate against the Interactions API
            # with x-goog-api-key. generateContent treats them as OAuth tokens.
            url = f"{GOOGLE_GEMINI_BASE_URL}v1beta/interactions"
            payload: dict[str, object] = {
                "model": model,
                "system_instruction": system_prompt,
                "input": user_prompt,
                "response_format": {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_model.model_json_schema(),
                },
            }
            response = self._http.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self._api_key,
                    "Api-Revision": "2026-05-20",
                },
                json=payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Gemini HTTP {response.status_code}: {response.text[:800]}"
                )
            return parse_structured(_interaction_output_text(response.json()), response_model)

        return with_retry(_call, retry_auth_errors=False)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()
    repo_env = Path.cwd() / ".env"
    if repo_env.exists():
        load_dotenv(repo_env, override=True)


def build_client(provider: str) -> StructuredLLMClient:
    """Build a structured-output client for the configured provider."""
    _load_dotenv()
    normalized = provider.lower()
    if normalized in {"google", "gemini"}:
        api_key = (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        ).strip()
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY or GOOGLE_API_KEY is required for provider 'google'"
            )
        logger.info("Using Google Gemini Developer API with API key header")
        return GeminiClient(api_key=api_key)
    if normalized == "openai":
        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for provider 'openai'")
        logger.info("Using OpenAI API")
        return OpenAICompatibleClient(OpenAI(api_key=api_key))
    raise ValueError(f"Unsupported LLM provider: {provider}")
