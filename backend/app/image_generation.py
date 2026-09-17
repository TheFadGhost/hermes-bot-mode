"""Bounded KIE image generation for one authenticated bot agent.

This adapter intentionally keeps provider access on the server.  A caller
supplies the already authenticated ``user_id`` and ``agent_id`` and the
result is saved through the existing :class:`Workspace` and :class:`Store`
seams.  It does not expose provider credentials to a browser or a runtime
model.

Provider contract (verified against the official KIE documentation on
2026-09-16):

* ``POST /api/v1/jobs/createTask`` creates an asynchronous market task.
* ``GET /api/v1/jobs/recordInfo?taskId=...`` returns ``waiting``, ``queuing``,
  ``generating``, ``success`` or ``fail`` and a ``resultJson.resultUrls``
  result on success.

References:

* https://docs.kie.ai/market/gpt/gpt-image-2-text-to-image
* https://docs.kie.ai/market/common/get-task-detail

No provider SDK or provider source code is bundled here.  This module is
original adapter code and remains under the repository's project license.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import io
import ipaddress
import os
import socket
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .errors import APIError
from .store import Store
from .workspace import Workspace


DEFAULT_KIE_BASE_URL = "https://api.kie.ai"
DEFAULT_KIE_IMAGE_MODEL = "gpt-image-2-text-to-image"
DEFAULT_IMAGE_TIMEOUT_SECONDS = 15 * 60
DEFAULT_REQUEST_TIMEOUT_SECONDS = 45.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.5
DEFAULT_MAX_POLL_INTERVAL_SECONDS = 8.0
DEFAULT_MAX_PROMPT_CHARS = 8_000
DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 3
MAX_ALLOWED_IMAGE_TIMEOUT_SECONDS = 15 * 60
MAX_ALLOWED_PROMPT_CHARS = 100_000
MAX_ALLOWED_REDIRECTS = 5

CREATE_TASK_PATH = "/api/v1/jobs/createTask"
RECORD_INFO_PATH = "/api/v1/jobs/recordInfo"

_TERMINAL_STATES = {"success", "fail"}
_ALLOWED_MIME_TYPES = {
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
_MIME_EXTENSIONS = {
    "image/avif": ".avif",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_EXTENSION_MIME = {
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class ImageGenerationError(APIError):
    """Base error returned by the image adapter without provider secrets."""


class ImageGenerationUnavailable(ImageGenerationError):
    """Raised when KIE is not configured for this process."""

    def __init__(self) -> None:
        super().__init__(
            503,
            "image_generation_unavailable",
            "Image generation is not configured",
        )


class ImageGenerationCancelled(ImageGenerationError):
    """Raised when the caller cancels a provider task or its local wait."""

    def __init__(self) -> None:
        super().__init__(
            499,
            "image_generation_cancelled",
            "Image generation was cancelled",
        )


class ImageGenerationTimeout(ImageGenerationError):
    """Raised when a provider task exceeds the configured bounded timeout."""

    def __init__(self) -> None:
        super().__init__(
            504,
            "image_generation_timeout",
            "Image generation timed out",
        )


def _configuration_error(message: str) -> APIError:
    return ImageGenerationError(503, "image_generation_misconfigured", message)


def _validate_positive_float(value: float, field_name: str, maximum: float) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if converted <= 0 or converted > maximum:
        raise ValueError(f"{field_name} must be between 0 and {maximum}")
    return converted


def _validate_public_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("api_base_url must be an HTTPS URL without credentials or query parameters")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("api_base_url has an invalid port") from exc
    if port not in (None, 443):
        raise ValueError("api_base_url must use HTTPS port 443")
    # A path is allowed for test gateways and reverse proxies, but never a
    # query or fragment.  ``urljoin`` below works with a trailing slash.
    return value.rstrip("/")


@dataclass(frozen=True)
class ImageGenerationConfig:
    """Bounded process configuration for the KIE image adapter.

    ``api_key`` is marked ``repr=False`` so accidental config logging cannot
    print a credential.  It is read only on the server and never included in
    result or error values.
    """

    api_key: str | None = field(default=None, repr=False)
    api_base_url: str = DEFAULT_KIE_BASE_URL
    model: str = DEFAULT_KIE_IMAGE_MODEL
    timeout_seconds: float = DEFAULT_IMAGE_TIMEOUT_SECONDS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    max_poll_interval_seconds: float = DEFAULT_MAX_POLL_INTERVAL_SECONDS
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES
    max_redirects: int = DEFAULT_MAX_REDIRECTS

    def __post_init__(self) -> None:
        key = self.api_key.strip() if isinstance(self.api_key, str) else None
        object.__setattr__(self, "api_key", key or None)
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model.strip()) > 200:
            raise ValueError("model must be a non-empty string no longer than 200 characters")
        object.__setattr__(self, "model", self.model.strip())
        if not isinstance(self.api_base_url, str) or not self.api_base_url.strip():
            raise ValueError("api_base_url must be an HTTPS URL")
        object.__setattr__(self, "api_base_url", _validate_public_base_url(self.api_base_url.strip()))
        object.__setattr__(
            self,
            "timeout_seconds",
            _validate_positive_float(
                self.timeout_seconds,
                "timeout_seconds",
                MAX_ALLOWED_IMAGE_TIMEOUT_SECONDS,
            ),
        )
        object.__setattr__(
            self,
            "request_timeout_seconds",
            _validate_positive_float(self.request_timeout_seconds, "request_timeout_seconds", 120.0),
        )
        object.__setattr__(
            self,
            "poll_interval_seconds",
            _validate_positive_float(self.poll_interval_seconds, "poll_interval_seconds", 60.0),
        )
        object.__setattr__(
            self,
            "max_poll_interval_seconds",
            _validate_positive_float(self.max_poll_interval_seconds, "max_poll_interval_seconds", 120.0),
        )
        if self.max_poll_interval_seconds < self.poll_interval_seconds:
            raise ValueError("max_poll_interval_seconds must be at least poll_interval_seconds")
        try:
            max_prompt_chars = int(self.max_prompt_chars)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_prompt_chars must be an integer") from exc
        if max_prompt_chars < 1 or max_prompt_chars > MAX_ALLOWED_PROMPT_CHARS:
            raise ValueError("max_prompt_chars is outside the allowed range")
        object.__setattr__(self, "max_prompt_chars", max_prompt_chars)
        try:
            max_image_bytes = int(self.max_image_bytes)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_image_bytes must be an integer") from exc
        if max_image_bytes < 1:
            raise ValueError("max_image_bytes must be positive")
        object.__setattr__(self, "max_image_bytes", max_image_bytes)
        try:
            max_redirects = int(self.max_redirects)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_redirects must be an integer") from exc
        if max_redirects < 0 or max_redirects > MAX_ALLOWED_REDIRECTS:
            raise ValueError("max_redirects is outside the allowed range")
        object.__setattr__(self, "max_redirects", max_redirects)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> "ImageGenerationConfig":
        """Load KIE settings without ever logging or returning the key."""

        def env_float(name: str, default: float) -> float:
            raw = os.getenv(name)
            if raw is None or not raw.strip():
                return default
            try:
                return float(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be a number") from exc

        def env_int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None or not raw.strip():
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc

        return cls(
            api_key=os.getenv("KIE_API_KEY"),
            api_base_url=os.getenv("KIE_API_BASE_URL", DEFAULT_KIE_BASE_URL),
            model=os.getenv("KIE_IMAGE_MODEL", DEFAULT_KIE_IMAGE_MODEL),
            timeout_seconds=env_float("KIE_IMAGE_TIMEOUT_SECONDS", DEFAULT_IMAGE_TIMEOUT_SECONDS),
            request_timeout_seconds=env_float(
                "KIE_IMAGE_REQUEST_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS
            ),
            poll_interval_seconds=env_float(
                "KIE_IMAGE_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS
            ),
            max_poll_interval_seconds=env_float(
                "KIE_IMAGE_MAX_POLL_INTERVAL_SECONDS", DEFAULT_MAX_POLL_INTERVAL_SECONDS
            ),
            max_prompt_chars=env_int("KIE_IMAGE_MAX_PROMPT_CHARS", DEFAULT_MAX_PROMPT_CHARS),
            max_image_bytes=env_int("KIE_IMAGE_MAX_BYTES", DEFAULT_MAX_IMAGE_BYTES),
            max_redirects=env_int("KIE_IMAGE_MAX_REDIRECTS", DEFAULT_MAX_REDIRECTS),
        )

    def public_dict(self) -> dict[str, Any]:
        """Return safe diagnostics suitable for a status endpoint."""

        return {
            "configured": self.configured,
            "provider": "kie",
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "max_prompt_chars": self.max_prompt_chars,
            "max_image_bytes": self.max_image_bytes,
        }


@dataclass
class ImageGenerationJob:
    """One provider task bound to one owner and agent workspace."""

    task_id: str
    user_id: str = field(repr=False)
    agent_id: str = field(repr=False)
    model: str = field(repr=False)
    prompt: str = field(repr=False)
    created_at: float = field(default_factory=time.time, repr=False)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    external_cancel_event: asyncio.Event | None = field(default=None, repr=False)
    state: str = "waiting"
    progress: int | None = None
    result_url: str | None = field(default=None, repr=False)
    _last_payload: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set() or bool(
            self.external_cancel_event and self.external_cancel_event.is_set()
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "progress": self.progress,
            "model": self.model,
        }


@dataclass(frozen=True)
class ImageProgress:
    """Safe progress data passed to an optional generation callback."""

    task_id: str
    state: str
    progress: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "progress": self.progress,
        }


@dataclass(frozen=True)
class ImageGenerationResult:
    """Persisted image metadata plus the bytes needed for an inline preview."""

    file: Mapping[str, Any]
    file_id: str
    path: str
    mime: str
    download_url: str
    image_bytes: bytes = field(repr=False)
    provider_task_id: str = field(repr=False)

    @property
    def mime_type(self) -> str:
        return self.mime

    @property
    def image_base64(self) -> str:
        return base64.b64encode(self.image_bytes).decode("ascii")

    @property
    def image_data_url(self) -> str:
        return f"data:{self.mime};base64,{self.image_base64}"

    @property
    def image(self) -> bytes:
        """Return the actual downloaded image bytes for non-JSON callers."""

        return self.image_bytes

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe result containing an inline image preview."""

        return {
            "file": dict(self.file),
            "file_id": self.file_id,
            "path": self.path,
            "mime": self.mime,
            "mime_type": self.mime,
            "download_url": self.download_url,
            "image_url": self.image_data_url,
            "image": self.image_data_url,
            "image_base64": self.image_base64,
            "provider_task_id": self.provider_task_id,
        }


ProgressCallback = Callable[[ImageProgress], Awaitable[None] | None]
CancelCheck = Callable[[], Awaitable[bool] | bool]


def _safe_text(value: Any, *, max_length: int = 500) -> str:
    """Normalize provider text without allowing it into secret-bearing errors."""

    if not isinstance(value, str):
        return ""
    # Provider messages are intentionally not exposed by this adapter.  This
    # helper is only used for local validation text and strips control chars.
    return "".join(character for character in value if character.isprintable())[:max_length]


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    # ``is_global`` excludes private, loopback, link-local, multicast,
    # unspecified, documentation and other reserved ranges.  Explicitly
    # inspect IPv4-mapped IPv6 addresses because ``is_global`` alone can be
    # surprising across Python versions.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped.is_global
    return address.is_global


def _resolve_public_addresses(hostname: str, port: int) -> None:
    try:
        infos = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ImageGenerationError(
            422,
            "image_result_url_invalid",
            "The image result host could not be validated",
        ) from exc
    addresses = {str(info[4][0]).split("%", 1)[0] for info in infos if info[4]}
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise ImageGenerationError(
            422,
            "image_result_url_invalid",
            "Image result URLs must use a public HTTPS host",
        )


def validate_public_https_url(value: str) -> str:
    """Validate one result URL against HTTPS and SSRF private-network rules.

    DNS is resolved before each request, including every redirect target.  A
    hostname that resolves to even one non-global address is rejected so a
    multi-address response cannot select an internal endpoint by chance.  The
    HTTP transport must still be kept behind an egress policy in production;
    URL validation cannot pin a DNS answer against every possible rebinding.
    """

    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ImageGenerationError(
            422,
            "image_result_url_invalid",
            "The image result URL is invalid",
        )
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ImageGenerationError(
            422,
            "image_result_url_invalid",
            "Image result URLs must use public HTTPS without credentials",
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ImageGenerationError(
            422,
            "image_result_url_invalid",
            "The image result URL has an invalid port",
        ) from exc
    if port not in (None, 443):
        raise ImageGenerationError(
            422,
            "image_result_url_invalid",
            "Image result URLs must use HTTPS port 443",
        )
    hostname = parsed.hostname.rstrip(".").lower()
    if not hostname:
        raise ImageGenerationError(
            422,
            "image_result_url_invalid",
            "The image result URL has no host",
        )
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        _resolve_public_addresses(hostname, 443)
    else:
        if not _is_public_ip(str(literal)):
            raise ImageGenerationError(
                422,
                "image_result_url_invalid",
                "Image result URLs must use a public HTTPS host",
            )
    return value


def _coerce_progress(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, number))


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            import json

            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return value


def _result_urls(payload: Mapping[str, Any]) -> list[str]:
    raw = payload.get("resultJson", payload.get("result_json"))
    parsed = _parse_json(raw)
    if isinstance(parsed, Mapping):
        raw = parsed.get("resultUrls", parsed.get("result_urls", parsed.get("urls")))
    if raw is None:
        raw = payload.get("resultUrls", payload.get("result_urls", payload.get("urls")))
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    return [item for item in raw if isinstance(item, str) and item][:5]


def _mime_and_extension(content_type: str | None, url: str, data: bytes) -> tuple[str, str]:
    # Trust image signatures rather than the remote server's MIME claim.
    supplied = ""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        supplied = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        supplied = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        supplied = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        supplied = "image/webp"
    elif len(data) >= 16 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
        supplied = "image/avif"
    if supplied not in _ALLOWED_MIME_TYPES:
        raise ImageGenerationError(502, "image_generation_invalid_result", "The image provider returned invalid or unsupported image data")

    return supplied, _MIME_EXTENSIONS[supplied]


class KieImageGenerator:
    """Async KIE text-to-image client with ownership-bound persistence."""

    def __init__(
        self,
        store: Store,
        workspace: Workspace,
        config: ImageGenerationConfig | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        max_image_bytes: int | None = None,
        public_base_url: str | None = None,
    ) -> None:
        self.store = store
        self.workspace = workspace
        try:
            self.config = config or ImageGenerationConfig.from_env()
        except ValueError as exc:
            # Keep malformed env values in the normal API error shape and do
            # not echo any value that could contain a credential.
            raise _configuration_error("Image generation configuration is invalid") from exc
        self.http_client = http_client
        self._owns_client = http_client is None
        configured_workspace_limit = getattr(
            getattr(workspace, "settings", None),
            "max_file_bytes",
            self.config.max_image_bytes,
        )
        try:
            configured_workspace_limit = int(configured_workspace_limit)
        except (TypeError, ValueError):
            configured_workspace_limit = self.config.max_image_bytes
        image_limit = self.config.max_image_bytes if max_image_bytes is None else int(max_image_bytes)
        if image_limit < 1:
            raise ValueError("max_image_bytes must be positive")
        self.max_image_bytes = min(image_limit, configured_workspace_limit)
        if self.max_image_bytes < 1:
            raise ValueError("workspace image limit must be positive")
        configured_public_base = public_base_url
        if configured_public_base is None:
            configured_public_base = getattr(
                getattr(workspace, "settings", None),
                "public_base_url",
                None,
            )
        if configured_public_base:
            try:
                configured_public_base = configured_public_base.rstrip("/")
                parsed = urlsplit(configured_public_base)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    configured_public_base = None
            except (TypeError, ValueError):
                configured_public_base = None
        self.public_base_url = configured_public_base

    def status(self) -> dict[str, Any]:
        """Return safe provider status; credentials never appear here."""

        status = self.config.public_dict()
        if not self.config.configured:
            status["reason"] = "KIE API key is not configured"
        return status

    def _assert_bound_agent(self, user_id: str, agent_id: str) -> tuple[str, str]:
        owner = str(user_id or "").strip()
        agent = str(agent_id or "").strip()
        if not owner or not agent:
            raise ImageGenerationError(
                401,
                "image_generation_identity_missing",
                "Image generation requires a bound owner and agent",
            )
        self.store.get_agent(owner, agent)
        return owner, agent

    def _validate_prompt(self, prompt: str) -> str:
        if not isinstance(prompt, str):
            raise ImageGenerationError(422, "image_prompt_invalid", "Image prompt must be text")
        if not prompt.strip():
            raise ImageGenerationError(422, "image_prompt_invalid", "Image prompt is required")
        if len(prompt) > self.config.max_prompt_chars:
            raise ImageGenerationError(
                422,
                "image_prompt_too_long",
                f"Image prompts are limited to {self.config.max_prompt_chars} characters",
            )
        return prompt.strip()

    def _validate_model(self, model: str | None) -> str:
        chosen = self.config.model if model is None else model
        if not isinstance(chosen, str) or not chosen.strip() or len(chosen.strip()) > 200:
            raise ImageGenerationError(422, "image_model_invalid", "Image model is invalid")
        return chosen.strip()

    def _ensure_configured(self) -> None:
        if not self.config.configured:
            raise ImageGenerationUnavailable()

    def _client_context(self) -> Any:
        if self.http_client is not None:
            return _ExistingClientContext(self.http_client)
        return httpx.AsyncClient(
            base_url=self.config.api_base_url,
            timeout=self.config.request_timeout_seconds,
            follow_redirects=False,
        )

    @staticmethod
    def _provider_url(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}{path}"

    def _headers(self) -> dict[str, str]:
        # This method is the only place where the provider key becomes an
        # HTTP header.  It is never returned by any public result or error.
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    async def start(
        self,
        user_id: str,
        agent_id: str,
        prompt: str,
        *,
        model: str | None = None,
        aspect_ratio: str = "auto",
        cancel_event: asyncio.Event | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ImageGenerationJob:
        """Create one KIE task after checking owner, agent and prompt bounds."""

        owner, agent = self._assert_bound_agent(user_id, agent_id)
        clean_prompt = self._validate_prompt(prompt)
        chosen_model = self._validate_model(model)
        if not isinstance(aspect_ratio, str) or len(aspect_ratio) > 16:
            raise ImageGenerationError(422, "image_options_invalid", "Image aspect ratio is invalid")
        self._ensure_configured()
        job = ImageGenerationJob(
            task_id="pending",
            user_id=owner,
            agent_id=agent,
            model=chosen_model,
            prompt=clean_prompt,
            external_cancel_event=cancel_event,
        )
        self._check_cancelled(job, cancel_check)
        payload = {
            "model": chosen_model,
            "input": {
                "prompt": clean_prompt,
                "aspect_ratio": aspect_ratio.strip() or "auto",
            },
        }
        try:
            async with self._client_context() as client:
                response = await self._await_operation(
                    job,
                    lambda: client.post(
                        self._provider_url(self.config.api_base_url, CREATE_TASK_PATH),
                        json=payload,
                        headers=self._headers(),
                        timeout=self.config.request_timeout_seconds,
                    ),
                    cancel_check=cancel_check,
                )
        except ImageGenerationError:
            raise
        except asyncio.TimeoutError as exc:
            raise ImageGenerationTimeout() from exc
        except (httpx.HTTPError, OSError) as exc:
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider could not be reached",
            ) from exc
        except Exception as exc:
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider request failed",
            ) from exc
        body = self._provider_json(response, create=True)
        data = body.get("data") if isinstance(body.get("data"), Mapping) else body
        task_id = data.get("taskId", data.get("task_id")) if isinstance(data, Mapping) else None
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id.strip()) > 512:
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider returned an invalid task",
            )
        job.task_id = task_id.strip()
        job.state = "waiting"
        return job

    def _provider_json(self, response: httpx.Response, *, create: bool = False) -> dict[str, Any]:
        if response.status_code < 200 or response.status_code >= 300:
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider rejected the request",
            )
        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider returned invalid data",
            ) from exc
        if not isinstance(body, Mapping):
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider returned invalid data",
            )
        code = body.get("code")
        if create and code not in (None, 0, 200, "200", "0"):
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider could not create the task",
            )
        return dict(body)

    def _check_cancelled(self, job: ImageGenerationJob, cancel_check: CancelCheck | None) -> None:
        if job.cancelled:
            raise ImageGenerationCancelled()
        # Async callbacks are checked in ``_check_cancelled_async``.  This
        # synchronous check covers the common event-only path.
        if cancel_check is not None and not inspect.iscoroutinefunction(cancel_check):
            try:
                if bool(cancel_check()):
                    raise ImageGenerationCancelled()
            except ImageGenerationError:
                raise
            except Exception:
                # A broken optional cancellation hook must not turn a valid
                # generation into an unbounded provider error.
                return

    async def _check_cancelled_async(self, job: ImageGenerationJob, cancel_check: CancelCheck | None) -> None:
        self._check_cancelled(job, None)
        if cancel_check is None:
            return
        try:
            value = cancel_check()
            if inspect.isawaitable(value):
                value = await value
            if bool(value):
                raise ImageGenerationCancelled()
        except ImageGenerationError:
            raise
        except Exception:
            return

    async def _await_operation(
        self,
        job: ImageGenerationJob,
        operation: Callable[[], Awaitable[Any]],
        *,
        cancel_check: CancelCheck | None = None,
    ) -> Any:
        """Run one HTTP operation and wake promptly when cancellation fires."""

        await self._check_cancelled_async(job, cancel_check)
        operation_task = asyncio.create_task(operation())
        cancellation_tasks: list[asyncio.Task[Any]] = [
            asyncio.create_task(job.cancel_event.wait()),
        ]
        if job.external_cancel_event is not None:
            cancellation_tasks.append(asyncio.create_task(job.external_cancel_event.wait()))
        try:
            done, _ = await asyncio.wait(
                [operation_task, *cancellation_tasks],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if operation_task in done:
                return await operation_task
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise ImageGenerationCancelled()
        except asyncio.CancelledError:
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise
        finally:
            for cancellation_task in cancellation_tasks:
                cancellation_task.cancel()
            await asyncio.gather(*cancellation_tasks, return_exceptions=True)

    async def _wait_interval(
        self,
        job: ImageGenerationJob,
        seconds: float,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> None:
        await self._check_cancelled_async(job, cancel_check)
        sleeper = asyncio.create_task(asyncio.sleep(seconds))
        cancellation_tasks: list[asyncio.Task[Any]] = [asyncio.create_task(job.cancel_event.wait())]
        if job.external_cancel_event is not None:
            cancellation_tasks.append(asyncio.create_task(job.external_cancel_event.wait()))
        try:
            done, _ = await asyncio.wait(
                [sleeper, *cancellation_tasks],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if sleeper not in done:
                sleeper.cancel()
                await asyncio.gather(sleeper, return_exceptions=True)
                raise ImageGenerationCancelled()
            await sleeper
        except asyncio.CancelledError:
            sleeper.cancel()
            await asyncio.gather(sleeper, return_exceptions=True)
            raise
        finally:
            for cancellation_task in cancellation_tasks:
                cancellation_task.cancel()
            await asyncio.gather(*cancellation_tasks, return_exceptions=True)

    async def poll(
        self,
        job: ImageGenerationJob,
        *,
        timeout_seconds: float | None = None,
        cancel_check: CancelCheck | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> ImageGenerationJob:
        """Poll one started job until success/failure or bounded timeout."""

        if not isinstance(job, ImageGenerationJob) or job.task_id == "pending":
            raise ImageGenerationError(422, "image_task_invalid", "A started image task is required")
        self._ensure_configured()
        wait_limit = self.config.timeout_seconds if timeout_seconds is None else timeout_seconds
        try:
            wait_limit = _validate_positive_float(
                wait_limit,
                "timeout_seconds",
                MAX_ALLOWED_IMAGE_TIMEOUT_SECONDS,
            )
        except ValueError as exc:
            raise ImageGenerationError(422, "image_timeout_invalid", "Image timeout is invalid") from exc
        deadline = time.monotonic() + wait_limit
        delay = self.config.poll_interval_seconds
        try:
            async with self._client_context() as client:
                while True:
                    await self._check_cancelled_async(job, cancel_check)
                    if time.monotonic() >= deadline:
                        raise ImageGenerationTimeout()
                    response = await self._await_operation(
                        job,
                        lambda: client.get(
                            self._provider_url(self.config.api_base_url, RECORD_INFO_PATH),
                            params={"taskId": job.task_id},
                            headers=self._headers(),
                            timeout=self.config.request_timeout_seconds,
                        ),
                        cancel_check=cancel_check,
                    )
                    body = self._provider_json(response)
                    data = body.get("data") if isinstance(body.get("data"), Mapping) else body
                    if not isinstance(data, Mapping):
                        raise ImageGenerationError(
                            502,
                            "image_generation_provider_error",
                            "The image provider returned invalid task data",
                        )
                    job._last_payload = dict(data)
                    state = str(data.get("state", data.get("status", ""))).strip().lower()
                    if not state:
                        raise ImageGenerationError(
                            502,
                            "image_generation_provider_error",
                            "The image provider returned no task state",
                        )
                    job.state = state
                    job.progress = _coerce_progress(data.get("progress"))
                    if on_progress is not None:
                        try:
                            callback_value = on_progress(
                                ImageProgress(job.task_id, job.state, job.progress)
                            )
                            if inspect.isawaitable(callback_value):
                                await callback_value
                        except ImageGenerationError:
                            raise
                        except Exception:
                            # Progress rendering is advisory; provider state
                            # remains authoritative if a UI callback fails.
                            pass
                    if state == "success":
                        urls = _result_urls(data)
                        if not urls:
                            raise ImageGenerationError(
                                502,
                                "image_generation_invalid_result",
                                "The image provider returned no image",
                            )
                        job.result_url = urls[0]
                        return job
                    if state == "fail":
                        raise ImageGenerationError(
                            502,
                            "image_generation_provider_error",
                            "The image provider failed to generate the image",
                        )
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ImageGenerationTimeout()
                    await self._wait_interval(
                        job,
                        min(delay, remaining),
                        cancel_check=cancel_check,
                    )
                    delay = min(self.config.max_poll_interval_seconds, delay * 1.5)
        except ImageGenerationError:
            raise
        except asyncio.TimeoutError as exc:
            raise ImageGenerationTimeout() from exc
        except (httpx.HTTPError, OSError) as exc:
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider could not be reached",
            ) from exc
        except Exception as exc:
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider request failed",
            ) from exc

    async def _download_image(
        self,
        client: httpx.AsyncClient,
        job: ImageGenerationJob,
        url: str,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> tuple[bytes, str, str]:
        current_url = await asyncio.wait_for(asyncio.to_thread(validate_public_https_url, url), timeout=10)
        for redirect_number in range(self.config.max_redirects + 1):
            await self._check_cancelled_async(job, cancel_check)

            async def read_response() -> tuple[int, httpx.Headers, bytes]:
                # ``AsyncClient.stream`` merges the client's default headers.
                # Use ``send`` with a freshly built request so a client that
                # was configured for KIE cannot leak its bearer token to an
                # arbitrary provider-hosted result URL.
                request = httpx.Request(
                    "GET",
                    current_url,
                    headers={"Accept": "image/*"},
                )
                response = await client.send(request, stream=True)
                try:
                    if 300 <= response.status_code < 400:
                        return response.status_code, response.headers, b""
                    if response.status_code < 200 or response.status_code >= 300:
                        return response.status_code, response.headers, b""
                    length_header = response.headers.get("content-length")
                    if length_header:
                        try:
                            if int(length_header) > self.max_image_bytes:
                                raise ImageGenerationError(
                                    413,
                                    "image_too_large",
                                    f"Generated images are limited to {self.max_image_bytes} bytes",
                                )
                        except ValueError:
                            pass
                    pieces: list[bytes] = []
                    total = 0
                    async for piece in response.aiter_bytes(64 * 1024):
                        total += len(piece)
                        if total > self.max_image_bytes:
                            raise ImageGenerationError(
                                413,
                                "image_too_large",
                                f"Generated images are limited to {self.max_image_bytes} bytes",
                            )
                        pieces.append(piece)
                    return response.status_code, response.headers, b"".join(pieces)
                finally:
                    await response.aclose()

            status_code, headers, data = await self._await_operation(
                job,
                read_response,
                cancel_check=cancel_check,
            )
            if 300 <= status_code < 400:
                location = headers.get("location")
                if not location or redirect_number >= self.config.max_redirects:
                    raise ImageGenerationError(
                        502,
                        "image_generation_invalid_result",
                        "The image provider returned too many redirects",
                    )
                current_url = await asyncio.wait_for(asyncio.to_thread(validate_public_https_url, urljoin(current_url, location)), timeout=10)
                continue
            if status_code < 200 or status_code >= 300:
                raise ImageGenerationError(
                    502,
                    "image_generation_invalid_result",
                    "The generated image could not be downloaded",
                )
            mime, extension = _mime_and_extension(headers.get("content-type"), current_url, data)
            return data, mime, extension
        raise ImageGenerationError(
            502,
            "image_generation_invalid_result",
            "The image provider returned too many redirects",
        )

    def _relative_image_path(self, relative_path: str | None, extension: str) -> str:
        if relative_path is None or not str(relative_path).strip():
            return f"generated-images/{uuid.uuid4().hex}{extension}"
        try:
            clean = self.workspace.clean_relative_path(str(relative_path).strip())
        except APIError:
            raise
        if len(clean) > 1024:
            raise ImageGenerationError(422, "image_path_invalid", "The image path is too long")
        return clean

    def _download_url(self, file_id: str) -> str:
        encoded_id = str(file_id).replace("/", "%2F")
        if self.public_base_url:
            return f"{self.public_base_url}/bot/api/files/{encoded_id}/download"
        return f"/bot/api/files/{encoded_id}/download"

    async def generate(
        self,
        user_id: str,
        agent_id: str,
        prompt: str,
        *,
        model: str | None = None,
        aspect_ratio: str = "auto",
        relative_path: str | None = None,
        timeout_seconds: float | None = None,
        cancel_event: asyncio.Event | None = None,
        cancel_check: CancelCheck | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> ImageGenerationResult:
        """Generate, download, and register one image for the bound agent."""

        total_timeout = self.config.timeout_seconds if timeout_seconds is None else timeout_seconds
        try:
            total_timeout = _validate_positive_float(
                total_timeout,
                "timeout_seconds",
                MAX_ALLOWED_IMAGE_TIMEOUT_SECONDS,
            )
        except ValueError as exc:
            raise ImageGenerationError(422, "image_timeout_invalid", "Image timeout is invalid") from exc

        job: ImageGenerationJob | None = None
        try:
            async with asyncio.timeout(total_timeout):
                job = await self.start(
                    user_id,
                    agent_id,
                    prompt,
                    model=model,
                    aspect_ratio=aspect_ratio,
                    cancel_event=cancel_event,
                    cancel_check=cancel_check,
                )
                await self.poll(
                    job,
                    timeout_seconds=total_timeout,
                    cancel_check=cancel_check,
                    on_progress=on_progress,
                )
                await self._check_cancelled_async(job, cancel_check)
                if not job.result_url:
                    raise ImageGenerationError(
                        502,
                        "image_generation_invalid_result",
                        "The image provider returned no image",
                    )
                async with self._client_context() as client:
                    image_bytes, mime, extension = await self._download_image(
                        client,
                        job,
                        job.result_url,
                        cancel_check=cancel_check,
                    )
                path = self._relative_image_path(relative_path, extension)
                saved_path, size, sha256 = self.workspace.save_stream(
                    job.user_id,
                    job.agent_id,
                    path,
                    io.BytesIO(image_bytes),
                    max_bytes=self.max_image_bytes,
                )
                try:
                    item = self.store.create_file(
                        job.user_id,
                        agent_id=job.agent_id,
                        relative_path=path,
                        size=size,
                        sha256=sha256,
                        content_type=mime,
                    )
                except Exception:
                    try:
                        saved_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
                return ImageGenerationResult(
                    file=item,
                    file_id=str(item["id"]),
                    path=path,
                    mime=mime,
                    download_url=self._download_url(str(item["id"])),
                    image_bytes=image_bytes,
                    provider_task_id=job.task_id,
                )
        except ImageGenerationError:
            raise
        except asyncio.TimeoutError as exc:
            if job is not None:
                job.cancel()
            raise ImageGenerationTimeout() from exc
        except asyncio.CancelledError:
            if job is not None:
                job.cancel()
            raise
        except APIError:
            # Preserve ownership, path and workspace errors from the existing
            # Store/Workspace seams instead of flattening them into a provider
            # failure.
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise ImageGenerationError(
                502,
                "image_generation_provider_error",
                "The image provider request failed",
            ) from exc
        except Exception as exc:
            # Never copy arbitrary provider/network exception text into the
            # API response: it may include request metadata or credentials.
            raise ImageGenerationError(
                500,
                "image_generation_failed",
                "Image generation failed",
            ) from exc

    async def cancel(self, job: ImageGenerationJob) -> None:
        """Cancel local polling/download work for a started job.

        KIE's market API exposes task status but no portable cancellation
        endpoint.  Setting the local event prevents further requests and
        leaves the provider task to its own lifecycle.
        """

        if not isinstance(job, ImageGenerationJob):
            raise ImageGenerationError(422, "image_task_invalid", "A started image task is required")
        job.cancel()

    async def generate_dict(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Convenience wrapper for scoped tools and JSON HTTP handlers."""

        result = await self.generate(*args, **kwargs)
        return result.as_dict()


class _ExistingClientContext:
    """Async context wrapper that does not close an injected test/client."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


# Friendly aliases make the integration seam easy to discover without
# coupling the parent scoped tool to a provider-specific class name.
ImageGenerationService = KieImageGenerator
ImageGenerator = KieImageGenerator


async def generate_image(
    store: Store,
    workspace: Workspace,
    user_id: str,
    agent_id: str,
    prompt: str,
    **kwargs: Any,
) -> ImageGenerationResult:
    """One-shot helper for callers that do not need to retain a service."""

    generator = KieImageGenerator(store, workspace)
    return await generator.generate(user_id, agent_id, prompt, **kwargs)


__all__ = [
    "ImageGenerationCancelled",
    "ImageGenerationConfig",
    "ImageGenerationError",
    "ImageGenerationJob",
    "ImageGenerationResult",
    "ImageGenerationService",
    "ImageGenerationTimeout",
    "ImageGenerationUnavailable",
    "ImageGenerator",
    "ImageProgress",
    "KieImageGenerator",
    "generate_image",
    "validate_public_https_url",
]

