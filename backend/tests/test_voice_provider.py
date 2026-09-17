"""Contract tests for OpenRouter MAI-Transcribe 2 without paid requests."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.connection_provider import ProviderError
from app.voice_provider import MAX_AUDIO_BYTES, TRANSCRIPTION_MODEL, VoiceProvider


def _response(request: httpx.Request, body: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, request=request, json=body)


@pytest.mark.asyncio
async def test_transcribe_posts_raw_base64_audio_to_verified_model() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "POST"
        assert request.url.path == "/api/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer openrouter-secret"
        body = json.loads(request.content)
        assert body == {
            "model": TRANSCRIPTION_MODEL,
            "input_audio": {
                "data": base64.b64encode(b"wav-bytes").decode("ascii"),
                "format": "wav",
            },
        }
        return _response(request, {"text": "Hello Dad", "usage": {"seconds": 1.2, "cost": 0.0001}})

    provider = VoiceProvider("openrouter-secret", transport=httpx.MockTransport(handler))
    try:
        result = await provider.transcribe(b"wav-bytes", "WAV")
    finally:
        await provider.aclose()

    assert len(seen) == 1
    assert result == {
        "text": "Hello Dad",
        "model": TRANSCRIPTION_MODEL,
        "usage": {"seconds": 1.2, "cost": 0.0001},
        "generation_id": None,
    }


@pytest.mark.asyncio
async def test_transcribe_normalizes_generation_id_and_ignores_unbounded_usage_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response = _response(
            request,
            {
                "text": "A transcript",
                "usage": {"seconds": 4, "total_tokens": 20, "private": "drop"},
            },
        )
        response.headers["X-Generation-Id"] = "gen_123"
        return response

    provider = VoiceProvider("secret", transport=httpx.MockTransport(handler))
    try:
        result = await provider.transcribe(b"audio", ".mp3")
    finally:
        await provider.aclose()

    assert result == {
        "text": "A transcript",
        "model": TRANSCRIPTION_MODEL,
        "usage": {"seconds": 4, "total_tokens": 20},
        "generation_id": "gen_123",
    }


@pytest.mark.asyncio
async def test_transcribe_enforces_empty_size_and_format_bounds() -> None:
    provider = VoiceProvider("secret", transport=httpx.MockTransport(lambda request: _response(request, {})))
    try:
        with pytest.raises(ProviderError) as empty:
            await provider.transcribe(b"", "wav")
        with pytest.raises(ProviderError) as format_error:
            await provider.transcribe(b"audio", "webm/opus")
        with pytest.raises(ProviderError) as too_large:
            await provider.transcribe(b"x" * (MAX_AUDIO_BYTES + 1), "wav")
    finally:
        await provider.aclose()

    assert empty.value.code == "audio_empty"
    assert format_error.value.code == "audio_format_unsupported"
    assert too_large.value.code == "audio_too_large"


@pytest.mark.asyncio
async def test_transcribe_timeout_is_uncertain_and_never_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("paid request accepted, response lost", request=request)

    provider = VoiceProvider("secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as exc_info:
            await provider.transcribe(b"audio", "ogg")
    finally:
        await provider.aclose()

    assert calls == 1
    assert exc_info.value.uncertain is True
    assert exc_info.value.retryable is False
    assert "paid request accepted" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_transcribe_sanitizes_upstream_errors() -> None:
    secret = "openrouter-secret-do-not-leak"

    def handler(request: httpx.Request) -> httpx.Response:
        response = _response(request, {"error": secret, "raw": "provider details"}, 429)
        response.headers["x-request-id"] = "req_123"
        return response

    provider = VoiceProvider(secret, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as exc_info:
            await provider.transcribe(b"audio", "wav")
    finally:
        await provider.aclose()

    assert exc_info.value.code == "provider_rate_limited"
    assert exc_info.value.request_id == "req_123"
    assert secret not in str(exc_info.value)
    assert "provider details" not in str(exc_info.value)

