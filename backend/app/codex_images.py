"""Persist images returned by the signed-in Codex app-server."""

from __future__ import annotations

import base64
import binascii
import io
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import APIError


_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"RIFF", "image/webp", ".webp"),
)


def _error(code: str, message: str, status: int = 422) -> APIError:
    return APIError(status, code, message)


def _detect_image(data: bytes) -> tuple[str, str]:
    for signature, mime, extension in _SIGNATURES:
        if data.startswith(signature):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime, extension
    raise _error("image_generation_invalid_result", "Codex returned unsupported image data")


def _decode_result(result: Any, max_bytes: int) -> bytes | None:
    if not isinstance(result, str) or not result.strip():
        return None
    value = result.strip()
    if value.startswith("data:"):
        header, separator, payload = value.partition(",")
        if not separator or ";base64" not in header.casefold():
            return None
        value = payload
    if len(value) > ((max_bytes + 2) // 3) * 4:
        raise _error("image_too_large", "The generated image exceeds the file size limit", 413)
    # Native app-server results are generally data URLs. Accept an unwrapped
    # base64 payload as well, while never treating arbitrary text as an image.
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        return None


def _source_bytes(workspace: Any, user_id: str, agent_id: str, item: Mapping[str, Any], max_bytes: int) -> bytes:
    result = _decode_result(item.get("result"), max_bytes)
    if result is not None:
        return result
    raw_path = item.get("savedPath")
    if not isinstance(raw_path, str) or not raw_path:
        raise _error("image_generation_invalid_result", "Codex returned no image data")
    root = workspace.agent_root(user_id, agent_id)
    candidate = Path(raw_path)
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise _error("image_path_invalid", "Codex image path is outside this agent workspace") from exc
    # path_for performs the component-by-component symlink and containment
    # checks, including the leaf, before opening the file.
    safe_path = workspace.path_for(user_id, agent_id, relative, must_exist=True)
    try:
        with safe_path.open("rb") as source:
            return source.read(max_bytes + 1)
    except OSError as exc:
        raise _error("image_generation_invalid_result", "Codex image could not be read") from exc


def persist_codex_image(store: Any, workspace: Any, user_id: str, agent_id: str, item: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and persist one completed native Codex image item.

    This function has no network or provider fallback. It only accepts image
    bytes supplied by app-server or a saved path already inside the bound
    agent workspace.
    """

    if not isinstance(item, Mapping):
        raise _error("image_generation_invalid_result", "Codex returned an invalid image item")
    if str(item.get("status", "")).casefold() != "completed":
        failure = item.get("failure")
        if isinstance(failure, Mapping) and str(failure.get("type", "")).casefold() == "usagelimitexceeded":
            resets_at = failure.get("resetsAt")
            try:
                reset_time = datetime.fromtimestamp(float(resets_at), timezone.utc).strftime("%d %b at %H:%M UTC")
                suffix = f". Available again {reset_time}"
            except (ValueError, TypeError, OverflowError, OSError):
                suffix = ""
            raise _error("image_generation_usage_limit", f"ChatGPT image generation usage limit reached{suffix}", 429)
        raise _error("image_generation_incomplete", "Codex image generation did not complete")

    store.get_agent(user_id, agent_id)
    max_bytes = int(getattr(workspace.settings, "max_file_bytes", 0))
    if max_bytes < 1:
        raise _error("image_generation_unavailable", "Image storage is not configured", 503)
    data = _source_bytes(workspace, user_id, agent_id, item, max_bytes)
    if len(data) > max_bytes:
        raise APIError(413, "file_too_large", f"Images are limited to {max_bytes} bytes")
    mime, extension = _detect_image(data)
    relative_path = f"generated/{uuid.uuid4().hex}{extension}"
    saved_path, size, digest = workspace.save_stream(
        user_id, agent_id, relative_path, io.BytesIO(data), max_bytes=max_bytes
    )
    try:
        file_item = store.create_file(
            user_id,
            agent_id=agent_id,
            relative_path=relative_path,
            size=size,
            sha256=digest,
            content_type=mime,
        )
    except Exception:
        try:
            saved_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    file_id = str(file_item["id"])
    download_url = f"/bot/api/files/{file_id}/download"
    return {
        "file_id": file_id,
        "path": relative_path,
        "mime": mime,
        "download_url": download_url,
        "markdown": f"![Generated image]({download_url})",
        "provider": "codex",
        "model": "provider-selected",
    }


__all__ = ["persist_codex_image"]

