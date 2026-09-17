from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass

from integration import gateway_bot_mode


@dataclass
class Source:
    platform: str = "telegram"
    chat_type: str = "dm"
    user_id: str = "42"
    chat_id: str = "42"


@dataclass
class Event:
    source: Source


def test_private_dm_requires_same_user_and_chat_id():
    event = Event(Source())
    assert gateway_bot_mode.is_private_telegram_event(event)

    event.source.chat_type = "group"
    assert not gateway_bot_mode.is_private_telegram_event(event)
    event.source.chat_type = "dm"
    event.source.chat_id = "-1009"
    assert not gateway_bot_mode.is_private_telegram_event(event)


def test_nonce_request_uses_exact_loopback_contract(monkeypatch):
    calls = {}

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self, **kwargs):
            return {"url": "https://your-hermes-origin.example/bot/#nonce=abc", "expires_at": 4_000_000_000}

    class Session:
        def __init__(self, **kwargs):
            calls["session"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, url, **kwargs):
            calls["post"] = (url, kwargs)
            return Response()

    fake_aiohttp = types.SimpleNamespace(
        ClientTimeout=lambda **kwargs: ("timeout", kwargs),
        ClientSession=Session,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    monkeypatch.setenv("BOT_INTERNAL_SECRET", "s" * 40)

    result = asyncio.run(gateway_bot_mode.handle_bot_mode_command(Event(Source())))

    assert result.startswith("Open Dad Bot Mode:\nhttps://")
    url, kwargs = calls["post"]
    assert url == gateway_bot_mode.DEFAULT_INTERNAL_URL
    assert kwargs["json"] == {"user_id": "42", "chat_id": "42"}
    assert kwargs["headers"] == {"X-Bot-Internal-Secret": "s" * 40}

