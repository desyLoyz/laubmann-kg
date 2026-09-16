import json
from types import SimpleNamespace

import pytest

from laubmann_kg.llm.cache import LLMCache, cache_key
from laubmann_kg.llm.clients import (
    CacheMiss,
    CacheOnlyClient,
    CachedClient,
    OfflineClient,
    TruncatedOutput,
    build_client,
    check_response,
)
from laubmann_kg.llm.retry import retry_call


def test_cache_key_is_stable_and_order_independent() -> None:
    assert cache_key("m", {"a": 1, "b": 2}) == cache_key("m", {"b": 2, "a": 1})
    assert cache_key("m", "x") != cache_key("m", "y")


def test_cache_roundtrip(tmp_path) -> None:
    cache = LLMCache(tmp_path)
    key = cache_key("model", "prompt")
    assert cache.get(key) is None
    cache.set(key, {"prompt": "prompt"}, "response")
    assert cache.get(key) == "response"


def test_cached_client_calls_underlying_once(tmp_path) -> None:
    calls = {"n": 0}

    class Counting:
        model = "count"

        def complete(self, prompt: str) -> str:
            calls["n"] += 1
            return "ok"

    client = CachedClient(Counting(), cache=LLMCache(tmp_path))
    assert client.complete("hi") == "ok"
    assert client.complete("hi") == "ok"
    assert calls["n"] == 1


def test_offline_client_is_default_and_network_free() -> None:
    client = build_client({"backend": "offline"})
    assert isinstance(client, OfflineClient)
    assert client.complete("anything") == "[]"


def test_cache_only_client_serves_hits_and_raises_on_miss(tmp_path, monkeypatch) -> None:
    cache = LLMCache(tmp_path)
    key = cache_key("gemini-3.5-flash", "hello")
    cache.set(key, {"prompt": "hello"}, '[{"vernacular_de": "Buchfink"}]')

    def boom(*_a, **_k):
        raise AssertionError("provider must not be constructed in cache-only mode")

    monkeypatch.setattr("laubmann_kg.llm.clients.GeminiClient", boom)
    client = build_client(
        {"backend": "google", "model": "gemini-3.5-flash", "cache_only": True},
        cache=cache,
    )
    assert isinstance(client, CacheOnlyClient)
    assert client.complete("hello") == '[{"vernacular_de": "Buchfink"}]'
    with pytest.raises(CacheMiss, match="cache-only"):
        client.complete("uncached prompt")


def test_cache_only_requires_a_cache() -> None:
    with pytest.raises(ValueError, match="cache_dir"):
        build_client({"cache_only": True, "model": "gemini-3.5-flash"})


def test_retry_call_succeeds_after_failures() -> None:
    state = {"n": 0}

    def flaky() -> str:
        state["n"] += 1
        if state["n"] < 3:
            raise ValueError("transient")
        return "done"

    assert retry_call(flaky, attempts=3, backoff=0.0) == "done"


def test_retry_call_no_retry_propagates_immediately() -> None:
    state = {"n": 0}

    def truncating() -> str:
        state["n"] += 1
        raise TruncatedOutput('{"partial": ')

    with pytest.raises(TruncatedOutput) as info:
        retry_call(truncating, attempts=3, backoff=0.0, no_retry=(TruncatedOutput,))
    assert state["n"] == 1                       # not retried
    assert info.value.text == '{"partial": '


def test_truncated_output_returned_but_not_cached(tmp_path) -> None:
    calls = {"n": 0}

    class Truncating:
        model = "trunc"
        temperature = 0.0
        max_output_tokens = 64
        thinking_level = "low"

        def complete(self, prompt: str) -> str:
            calls["n"] += 1
            raise TruncatedOutput('[{"taxon": "Buchfink", "count": ')

    cache = LLMCache(tmp_path)
    client = CachedClient(Truncating(), cache=cache, attempts=3, backoff=0.0)
    assert client.complete("p") == '[{"taxon": "Buchfink", "count": '   # partial text
    assert calls["n"] == 1                                             # no retry
    assert cache.get(cache_key("trunc", "p")) is None                  # nothing cached
    assert not list(tmp_path.glob("*.json"))
    assert client.complete("p") == '[{"taxon": "Buchfink", "count": '
    assert calls["n"] == 2                                             # asked again


def test_empty_response_is_retried_then_raises(tmp_path) -> None:
    calls = {"n": 0}

    class Empty:
        model = "empty"

        def complete(self, prompt: str) -> str:
            calls["n"] += 1
            # what GeminiClient does for resp.text is None (safety block)
            return check_response(SimpleNamespace(candidates=[], text=None), "empty")

    cache = LLMCache(tmp_path)
    client = CachedClient(Empty(), cache=cache, attempts=2, backoff=0.0)
    with pytest.raises(RuntimeError, match="returned no text"):
        client.complete("p")
    assert calls["n"] == 2                                             # retried
    assert cache.get(cache_key("empty", "p")) is None

    # a good answer after a transient failure IS cached
    state = {"n": 0}

    class Flaky:
        model = "flaky"

        def complete(self, prompt: str) -> str:
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("503")
            return "ok"

    client = CachedClient(Flaky(), cache=cache, attempts=2, backoff=0.0)
    assert client.complete("p") == "ok" and state["n"] == 2
    assert cache.get(cache_key("flaky", "p")) == "ok"


def test_check_response_finish_reasons() -> None:
    class _Enum:                       # SDK enum-like: str() ends in the reason name
        def __str__(self):
            return "FinishReason.MAX_TOKENS"

    truncated = SimpleNamespace(candidates=[SimpleNamespace(finish_reason=_Enum())],
                                text='{"a": 1, "b')
    with pytest.raises(TruncatedOutput) as info:
        check_response(truncated, "m")
    assert info.value.text == '{"a": 1, "b'

    ok = SimpleNamespace(candidates=[SimpleNamespace(finish_reason="STOP")], text="[]")
    assert check_response(ok) == "[]"
    # bare-string finish reason, still truncation
    with pytest.raises(TruncatedOutput):
        check_response(SimpleNamespace(candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
                                       text=""))
    # candidates present but no text (blocked) -> RuntimeError for the retry loop
    with pytest.raises(RuntimeError):
        check_response(SimpleNamespace(candidates=[SimpleNamespace(finish_reason="SAFETY")],
                                       text=None))


def test_cache_record_carries_generation_params_but_key_ignores_them(tmp_path) -> None:
    class Inner:
        model = "gemini-x"
        temperature = 0.0
        max_output_tokens = 16384
        thinking_level = "low"

        def complete(self, prompt: str) -> str:
            return "[]"

    cache = LLMCache(tmp_path)
    CachedClient(Inner(), cache=cache).complete("hello")
    key = cache_key("gemini-x", "hello")           # sha256(model, prompt) -- unchanged
    record = json.loads((tmp_path / f"{key}.json").read_text(encoding="utf-8"))
    assert record["response"] == "[]"
    assert record["request"] == {
        "model": "gemini-x", "prompt": "hello",
        "params": {"temperature": 0.0, "max_output_tokens": 16384, "thinking_level": "low"}}

    # a client that exposes no params still yields a well-formed record, and a
    # different token cap hits the SAME cache entry (documented decision)
    class Other:
        model = "gemini-x"
        max_output_tokens = 4096

        def complete(self, prompt: str) -> str:
            raise AssertionError("must be served from cache")

    assert CachedClient(Other(), cache=cache).complete("hello") == "[]"
