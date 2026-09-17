"""OpenRouter MAI-Transcribe 2 adapter.

This module accepts bounded in-memory audio and forwards it as raw base64
JSON. It does not write audio or transcripts to disk and never retries a
timed-out paid request. A timeout is returned to callers as an uncertain
result so the dictation operation can decide how to reconcile it.

The request and response contract is documented by OpenRouter:

* https://openrouter.ai/microsoft/mai-transcribe-2
* https://openrouter.ai/docs/guides/overview/multimodal/stt
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from .connection_provider import ProviderError, _request_id, _status_error, _text


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TRANSCRIPTION_MODEL = "microsoft/mai-transcribe-2"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
SUPPORTED_AUDIO_FORMATS = frozenset({"wav", "mp3", "flac", "m4a", "ogg", "webm", "aac"})
_AUDIO_MIME_FORMATS = {
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/flac": "flac",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
    "audio/aac": "aac",
}


class VoiceProvider:
    """OpenRouter's synchronous transcription adapter with async HTTP I/O."""

    provider_name = "openrouter"
    model = TRANSCRIPTION_MODEL

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: float = 60.0,
        max_audio_bytes: int = MAX_AUDIO_BYTES,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("An OpenRouter API key is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not isinstance(max_audio_bytes, int) or not 1 <= max_audio_bytes <= MAX_AUDIO_BYTES:
            raise ValueError(f"max_audio_bytes must be between 1 and {MAX_AUDIO_BYTES}")
        self.max_audio_bytes = max_audio_bytes
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": f"Bearer {api_key}",
            },
            timeout=httpx.Timeout(timeout),
            transport=transport,
            trust_env=False,
        )

    async def __aenter__(self) -> "VoiceProvider":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    close = aclose

    async def transcribe(self, audio: bytes, format: str) -> dict[str, Any]:
        """Transcribe one audio payload using the verified MAI model.

        ``format`` is the actual container emitted by the recorder. Callers
        must not relabel WebM/Opus bytes as WAV. Duration and MIME/container
        signature checks belong at the upload boundary; this adapter enforces
        the byte and format limits available from its narrow API.
        """

        if not isinstance(audio, (bytes, bytearray, memoryview)):
            raise ProviderError(
                400,
                "audio_invalid",
                "Audio must be a byte payload.",
                provider=self.provider_name,
            )
        audio_bytes = bytes(audio)
        if not audio_bytes:
            raise ProviderError(
                400,
                "audio_empty",
                "Audio is required.",
                provider=self.provider_name,
            )
        if len(audio_bytes) > self.max_audio_bytes:
            raise ProviderError(
                413,
                "audio_too_large",
                f"Audio is limited to {self.max_audio_bytes} bytes.",
                provider=self.provider_name,
            )
        if not isinstance(format, str):
            raise ProviderError(
                400,
                "audio_format_unsupported",
                "The audio format is not supported.",
                provider=self.provider_name,
            )
        raw_format = format.strip().lower().split(";", 1)[0].strip()
        audio_format = _AUDIO_MIME_FORMATS.get(raw_format, raw_format).lstrip(".")
        if audio_format not in SUPPORTED_AUDIO_FORMATS:
            raise ProviderError(
                400,
                "audio_format_unsupported",
                "The audio format is not supported.",
                provider=self.provider_name,
            )

        body = {
            "model": TRANSCRIPTION_MODEL,
            "input_audio": {
                "data": base64.b64encode(audio_bytes).decode("ascii"),
                "format": audio_format,
            },
        }
        try:
            response = await self._client.post("/audio/transcriptions", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                504,
                "provider_timeout",
                "The transcription result is unknown. Do not retry automatically.",
                provider=self.provider_name,
                retryable=False,
                uncertain=True,
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                503,
                "provider_unavailable",
                "The transcription provider could not be reached.",
                provider=self.provider_name,
                retryable=True,
            ) from exc

        if not 200 <= response.status_code < 300:
            raise _status_error(
                self.provider_name,
                response.status_code,
                request_id=_request_id(response),
                uncertain=response.status_code in (408, 504),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                502,
                "provider_invalid_response",
                "The transcription provider returned an invalid response.",
                provider=self.provider_name,
                request_id=_request_id(response),
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderError(
                502,
                "provider_invalid_response",
                "The transcription provider returned an invalid response.",
                provider=self.provider_name,
                request_id=_request_id(response),
            )
        text = payload.get("text")
        if not isinstance(text, str):
            raise ProviderError(
                502,
                "provider_invalid_response",
                "The transcription provider did not return text.",
                provider=self.provider_name,
                request_id=_request_id(response),
            )

        usage = payload.get("usage")
        safe_usage: dict[str, int | float] | None = None
        if isinstance(usage, dict):
            safe_usage = {}
            for key in ("seconds", "total_tokens", "input_tokens", "output_tokens", "cost"):
                value = usage.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    safe_usage[key] = value
            if not safe_usage:
                safe_usage = None
        return {
            "text": text,
            "model": TRANSCRIPTION_MODEL,
            "usage": safe_usage,
            "generation_id": _text(response.headers.get("x-generation-id"), maximum=128),
        }


OpenRouterVoiceProvider = VoiceProvider
OpenRouterTranscriptionProvider = VoiceProvider


__all__ = [
    "MAX_AUDIO_BYTES",
    "OPENROUTER_BASE_URL",
    "OpenRouterTranscriptionProvider",
    "OpenRouterVoiceProvider",
    "SUPPORTED_AUDIO_FORMATS",
    "TRANSCRIPTION_MODEL",
    "VoiceProvider",
]

