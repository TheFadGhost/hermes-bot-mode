"""Hermes gateway handler for the existing Telegram bot's bot-mode link.

This file is copied to ``gateway/bot_mode.py`` by ``patch_gateway.py``.  It is
deliberately independent of Hermes internals: the gateway passes a
``MessageEvent`` and this module reads its normalized ``source`` fields.

The gateway has already completed its normal authorization gate before this
handler runs.  The handler adds a second, command-specific guard so a group
allowlist entry can never issue a private bot-mode login link.
"""

from __future__ import annotations

import logging
import math
import os
import time
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)

DEFAULT_INTERNAL_URL = "http://127.0.0.1:9120/bot/api/internal/auth/nonce"
DEFAULT_TIMEOUT_SECONDS = 5.0


def _source_value(source, name: str) -> str:
    value = getattr(source, name, "") if source is not None else ""
    return str(value or "").strip()


def is_private_telegram_event(event) -> bool:
    """Return true only for an authorized Telegram private-chat shape.

    ``GatewayRunner._handle_message`` performs the configured Telegram
    allowlist check before command dispatch.  Here we require the normalized
    source to identify the same user and private chat, which prevents a
    group-wide allowlist from being reused for this login capability.
    """

    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", None)
    platform = str(platform or getattr(source, "platform", "") or "").lower()
    chat_type = _source_value(source, "chat_type").lower()
    user_id = _source_value(source, "user_id")
    chat_id = _source_value(source, "chat_id")
    return (
        platform == "telegram"
        and chat_type in {"dm", "private"}
        and bool(user_id)
        and bool(chat_id)
        and user_id == chat_id
    )


def _loopback_url(value: str) -> bool:
    """Check the internal URL is plain HTTP on an explicit loopback host."""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "::1"}
        and not parsed.username
        and not parsed.password
        and bool(parsed.netloc)
    )


def _public_link_is_safe(link: str) -> bool:
    """Reject malformed or unexpected URLs returned by the local service."""

    if not link or any(char.isspace() for char in link):
        return False
    try:
        parsed = urlsplit(link)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    # The nonce is intended for the bot-mode origin and path. A compromised or
    # misconfigured loopback response must not turn Telegram into an open URL
    # redirector.
    if not (parsed.path == "/bot" or parsed.path.startswith("/bot/")):
        return False
    expected = (
        os.environ.get("BOT_PUBLIC_BASE_URL", "").strip()
        or os.environ.get("BOT_MODE_PUBLIC_URL", "").strip()
    )
    if expected:
        try:
            expected_parts = urlsplit(expected)
        except ValueError:
            return False
        if (
            parsed.scheme.lower(), parsed.netloc.lower()
        ) != (
            expected_parts.scheme.lower(), expected_parts.netloc.lower()
        ):
            return False
    return True


def _fallback_link(payload: dict) -> str:
    """Build a link only when the backend returned a raw nonce and base URL."""

    nonce = str(payload.get("nonce") or "").strip()
    base = (
        os.environ.get("BOT_PUBLIC_BASE_URL", "").strip()
        or os.environ.get("BOT_MODE_PUBLIC_URL", "").strip()
    ).rstrip("/")
    if not nonce or not base:
        return ""
    return f"{base}/bot/#nonce={quote(nonce, safe='')}"


def _expiry_hint(payload: dict) -> str:
    try:
        expires_at = int(payload.get("expires_at"))
    except (TypeError, ValueError):
        return "This login link expires shortly."
    minutes = max(1, math.ceil(max(0, expires_at - int(time.time())) / 60))
    noun = "minute" if minutes == 1 else "minutes"
    return f"This login link expires in about {minutes} {noun}."


async def handle_bot_mode_command(event) -> str:
    """Create and return a one-time web login link for a Telegram DM."""

    if not is_private_telegram_event(event):
        return "Bot mode links can only be requested from an authorized private Telegram chat."

    source = event.source
    user_id = _source_value(source, "user_id")
    internal_secret = os.environ.get("BOT_INTERNAL_SECRET", "").strip()
    if not internal_secret:
        logger.error("Bot mode command requested but BOT_INTERNAL_SECRET is not configured")
        return "Bot mode is not configured yet."

    internal_url = (
        os.environ.get("BOT_MODE_INTERNAL_URL", DEFAULT_INTERNAL_URL).strip()
        or DEFAULT_INTERNAL_URL
    )
    if not _loopback_url(internal_url):
        logger.error("Refusing non-loopback bot mode internal URL")
        return "Bot mode is unavailable because its internal endpoint is misconfigured."

    try:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.post(
                internal_url,
                json={"user_id": user_id, "chat_id": user_id},
                headers={"X-Bot-Internal-Secret": internal_secret},
            ) as response:
                if response.status < 200 or response.status >= 300:
                    logger.warning(
                        "Bot mode nonce endpoint returned HTTP %s",
                        response.status,
                    )
                    return "Bot mode is temporarily unavailable."
                payload = await response.json(content_type=None)
    except Exception as exc:
        # Keep endpoint details and credentials out of Telegram and logs.
        logger.warning("Bot mode nonce request failed: %s", type(exc).__name__)
        return "Bot mode is temporarily unavailable."

    if not isinstance(payload, dict):
        logger.warning("Bot mode nonce endpoint returned a non-object response")
        return "Bot mode is temporarily unavailable."
    link = str(payload.get("url") or "").strip() or _fallback_link(payload)
    if not _public_link_is_safe(link):
        logger.error("Bot mode nonce response did not contain a valid public URL")
        return "Bot mode is unavailable because its public URL is not configured."
    return f"Open your private Bot Mode:\n{link}\n\nThis link signs in to your Telegram account's own chats. Do not forward it.\n{_expiry_hint(payload)}"

