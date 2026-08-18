from __future__ import annotations

import httpx

from laubmann_kg.llm.clients import _interaction_output_text, strip_bearer_use_api_key


def test_gemini_requests_use_api_key_header_not_bearer() -> None:
    request = httpx.Request(
        "POST",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent",
        headers={"Authorization": "Bearer AQ.example-key"},
    )
    strip_bearer_use_api_key(request, "AQ.example-key")
    assert "Authorization" not in request.headers
    assert request.headers["x-goog-api-key"] == "AQ.example-key"


def test_interaction_output_text_from_steps() -> None:
    text = _interaction_output_text(
        {
            "steps": [
                {"type": "thought", "content": []},
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": '{"ok": true}'}],
                },
            ]
        }
    )
    assert text == '{"ok": true}'
