"""LLM client wrappers with caching, retry, and an offline default.

The default pipeline extraction is rule-based (see extraction/observations.py)
and needs no network. These clients back the optional LLM extraction path and
the test suite, which uses ``OfflineClient`` — a deterministic, network-free
client. Real provider clients are constructed only when explicitly configured
and require credentials.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Protocol

from laubmann_kg.llm.cache import LLMCache, cache_key
from laubmann_kg.llm.retry import retry_call

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    model: str

    def complete(self, prompt: str) -> str: ...


class TruncatedOutput(RuntimeError):
    """The provider stopped at ``max_output_tokens``. ``text`` carries the
    partial answer (usually clipped JSON) so callers can still attempt a
    repair; a retry cannot help, and the answer must never be cached."""

    def __init__(self, text: str, message: str = "output truncated at max_output_tokens") -> None:
        super().__init__(message)
        self.text = text or ""


class OfflineClient:
    """Deterministic, network-free client. Returns a canned response per prompt
    (looked up by content hash); unknown prompts return an empty JSON array,
    i.e. 'no structured output'."""

    def __init__(self, responses: Optional[dict[str, str]] = None, model: str = "offline") -> None:
        self.model = model
        self._responses = responses or {}

    def complete(self, prompt: str) -> str:
        return self._responses.get(cache_key(self.model, prompt), "[]")


class CachedClient:
    """Wraps any client with disk caching and deterministic retry.

    Cache KEY = sha256(model, prompt) -- deliberately independent of the
    generation parameters (temperature, token cap, thinking level), which are
    recorded in the cache RECORD for audit only. Truncated answers are returned
    to the caller (the JSON repair pass may still salvage them) but never
    cached, so a re-run with a higher cap regenerates them.
    """

    def __init__(self, client: LLMClient, cache: Optional[LLMCache] = None,
                 attempts: int = 3, backoff: float = 0.0) -> None:
        self.client = client
        self.model = client.model
        self.cache = cache or LLMCache()
        self.attempts = attempts
        self.backoff = backoff

    def _request(self, prompt: str) -> dict:
        return {
            "model": self.model,
            "prompt": prompt,
            "params": {
                "temperature": getattr(self.client, "temperature", None),
                "max_output_tokens": getattr(self.client, "max_output_tokens", None),
                "thinking_level": getattr(self.client, "thinking_level", None),
            },
        }

    def complete(self, prompt: str) -> str:
        key = cache_key(self.model, prompt)
        hit = self.cache.get(key)
        if hit is not None:
            logger.debug("llm cache hit %s", key)
            return hit
        try:
            response = retry_call(lambda: self.client.complete(prompt),
                                  attempts=self.attempts, backoff=self.backoff,
                                  no_retry=(TruncatedOutput,))
        except TruncatedOutput as exc:
            logger.warning("truncated output for prompt %s (%d chars): returned "
                           "to caller, NOT cached", key[:12], len(exc.text))
            return exc.text
        self.cache.set(key, self._request(prompt), response)
        return response


def build_client(config: Optional[dict] = None, cache: Optional[LLMCache] = None) -> LLMClient:
    """Build a cached client from config. Defaults to offline/rule-based.

    ``config`` keys: ``backend`` (offline|google|openai|anthropic), ``model``.
    Provider backends lazy-import their SDK and require credentials.
    """
    config = config or {}
    backend = (config.get("backend") or "offline").lower()
    if backend == "offline":
        return OfflineClient(model=config.get("model", "offline"))
    inner = _build_provider(backend, config)
    return CachedClient(inner, cache=cache,
                        attempts=int(config.get("retry_attempts", 3)),
                        backoff=float(config.get("retry_backoff", 2.0)))


def _build_provider(backend: str, config: dict) -> LLMClient:  # pragma: no cover - needs creds/network
    if backend in ("google", "gemini"):
        return GeminiClient(
            model=config.get("model", "gemini-1.5-flash"),
            api_key_env=config.get("api_key_env", "GOOGLE_API_KEY"),
            temperature=float(config.get("temperature", 0.0)),
            max_output_tokens=int(config.get("max_output_tokens", 4096)),
            timeout_s=float(config.get("timeout", 120)),
            thinking_level=config.get("thinking_level"),
        )
    raise NotImplementedError(
        f"LLM backend '{backend}' is not configured. Supported: offline, google/gemini. "
        "Add an adapter or use backend=offline."
    )


class GeminiClient:  # pragma: no cover - needs credentials + network
    """Google Gemini adapter. Lazy-imports the SDK (new ``google-genai`` first,
    then legacy ``google-generativeai``) and forces JSON output at temperature 0
    for deterministic, cacheable extraction.

    ``max_output_tokens`` caps each response so a runaway generation cannot spiral
    to the model's hard token ceiling (which is slow, costly, and yields the
    truncated JSON the repair pass then has to salvage). ``timeout_s`` bounds each
    request so a stalled call fails instead of hanging the whole run.
    """

    def __init__(self, model: str, api_key_env: str = "GOOGLE_API_KEY",
                 temperature: float = 0.0, max_output_tokens: int = 4096,
                 timeout_s: float = 120,
                 thinking_level: Optional[str] = None) -> None:
        self.model = model
        self._api_key_env = api_key_env
        # public generation params: CachedClient records them in the cache entry
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.thinking_level = thinking_level
        self._timeout_ms = int(timeout_s * 1000)
        self._impl: Optional[tuple[str, object]] = None
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        if self._impl is not None:
            return
        with self._lock:
            if self._impl is not None:
                return
            self._ensure_locked()

    def _ensure_locked(self) -> None:
        import os

        key = os.environ.get(self._api_key_env) or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                f"No API key found. Set {self._api_key_env} (or GEMINI_API_KEY) "
                "in the environment or in a .env file in the project directory "
                "to use the Gemini extraction backend."
            )
        try:
            from google import genai  # new unified SDK
            from google.genai import types

            self._impl = ("genai", genai.Client(
                api_key=key,
                http_options=types.HttpOptions(timeout=self._timeout_ms)))
        except ImportError:
            import google.generativeai as gga  # legacy SDK

            gga.configure(api_key=key)
            self._impl = ("legacy", gga.GenerativeModel(self.model))
            if self.thinking_level:
                logger.warning("thinking_level is ignored on the legacy "
                               "google-generativeai SDK")
        logger.info(
            "Gemini backend ready: model=%s temperature=%s max_output_tokens=%s "
            "timeout=%.0fs thinking_level=%s",
            self.model, self.temperature, self.max_output_tokens,
            self._timeout_ms / 1000, self.thinking_level or "default")

    def complete(self, prompt: str) -> str:
        self._ensure()
        kind, obj = self._impl  # type: ignore[misc]
        logger.debug("Gemini call: model=%s prompt_chars=%d", self.model, len(prompt))
        if kind == "genai":
            from google.genai import types

            cfg_kwargs: dict = dict(
                temperature=self.temperature,
                response_mime_type="application/json",
                max_output_tokens=self.max_output_tokens,
            )
            if self.thinking_level:
                cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                    thinking_level=self.thinking_level)
            resp = obj.models.generate_content(  # type: ignore[attr-defined]
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(**cfg_kwargs),
            )
        else:
            resp = obj.generate_content(  # type: ignore[attr-defined]
                prompt,
                generation_config={"temperature": self.temperature,
                                   "response_mime_type": "application/json",
                                   "max_output_tokens": self.max_output_tokens},
                request_options={"timeout": self._timeout_ms / 1000.0},
            )
        return check_response(resp, self.model)


def _finish_reason(resp) -> str:
    """Upper-cased finish reason of the first candidate ('' when absent). The
    SDK returns an enum or a bare string depending on version; both stringify
    to something ending in the reason name (e.g. 'FinishReason.MAX_TOKENS')."""
    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        return ""
    reason = getattr(candidates[0], "finish_reason", None)
    return "" if reason is None else str(reason).upper()


def _response_text(resp) -> Optional[str]:
    try:
        return resp.text
    except Exception as exc:  # noqa: BLE001 - some SDK versions raise on empty parts
        logger.debug("response.text unavailable: %s", exc)
        return None


def check_response(resp, model: str = "") -> str:
    """Return the response text, or raise: ``TruncatedOutput`` (carrying the
    partial text) when the model hit max_output_tokens, ``RuntimeError`` when
    there is no text at all (safety block, empty candidate) so the retry loop
    tries again."""
    reason = _finish_reason(resp)
    text = _response_text(resp)
    if reason.endswith("MAX_TOKENS"):
        raise TruncatedOutput(text or "",
                              f"{model or 'LLM'} output truncated at max_output_tokens "
                              f"(finish_reason={reason})")
    if text is None:
        feedback = getattr(resp, "prompt_feedback", None)
        raise RuntimeError(
            f"{model or 'LLM'} returned no text (finish_reason={reason or 'n/a'}, "
            f"prompt_feedback={feedback!r})")
    return text
