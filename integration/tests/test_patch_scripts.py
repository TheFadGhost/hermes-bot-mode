from __future__ import annotations

from pathlib import Path

import pytest

from integration.patch_gateway import PatchError, patch_gateway
from integration.patch_proxy import patch_proxy


COMMANDS = '''COMMAND_REGISTRY = [
    CommandDef("start", "Acknowledge platform start pings without a reply", "Session",
               gateway_only=True),
    CommandDef("new", "Start a new session", "Session"),
]
'''

RUNNER = '''
        if canonical == "help":
            return await self._handle_help_command(event)

        if canonical == "start":
            return ""

            if _cmd_def_inner and _cmd_def_inner.name == "agents":
                return await self._handle_agents_command(event)

            # /background starts work
'''

PROXY = '''import asyncio
from aiohttp import web, WSMsgType
HOP = {"connection","keep-alive","proxy-authenticate","proxy-authorization",
       "te","trailers","transfer-encoding","upgrade","content-length"}

def _resp_headers(up):
    return []

async def ws_proxy(request):
    return web.Response()

async def handler(request):
    return web.Response()

async def make_app():
    app=web.Application(client_max_size=1024**3)
    app["session"] = None
    app.router.add_route("*","/{tail:.*}",handler); return app
'''


def test_gateway_patch_is_anchored_backed_up_and_idempotent(tmp_path):
    (tmp_path / "hermes_cli").mkdir()
    (tmp_path / "gateway").mkdir()
    (tmp_path / "hermes_cli" / "commands.py").write_text(COMMANDS, encoding="utf-8")
    (tmp_path / "gateway" / "run.py").write_text(RUNNER, encoding="utf-8")

    changed = patch_gateway(tmp_path)
    assert changed == ["hermes_cli/commands.py", "gateway/run.py", "gateway/bot_mode.py"]
    assert 'CommandDef("bot"' in (tmp_path / "hermes_cli" / "commands.py").read_text()
    patched_runner = (tmp_path / "gateway" / "run.py").read_text()
    assert patched_runner.count("return await handle_bot_mode_command(event)") == 2
    assert (tmp_path / "hermes_cli" / "commands.py.dad-bot-mode.bak").exists()
    assert (tmp_path / "gateway" / "run.py.dad-bot-mode.bak").exists()

    first = {
        path: path.read_bytes()
        for path in (tmp_path / "hermes_cli").glob("*")
    }
    second = patch_gateway(tmp_path)
    assert second == []
    assert first == {path: path.read_bytes() for path in (tmp_path / "hermes_cli").glob("*")}


def test_gateway_patch_refuses_missing_anchor(tmp_path):
    (tmp_path / "hermes_cli").mkdir()
    (tmp_path / "gateway").mkdir()
    (tmp_path / "hermes_cli" / "commands.py").write_text("COMMAND_REGISTRY = []\n", encoding="utf-8")
    (tmp_path / "gateway" / "run.py").write_text(RUNNER, encoding="utf-8")
    with pytest.raises(PatchError, match="command registry"):
        patch_gateway(tmp_path)


def test_proxy_patch_preserves_existing_app_and_orders_bot_routes(tmp_path):
    path = tmp_path / "app.py"
    path.write_text(PROXY, encoding="utf-8")

    assert patch_proxy(path)
    patched = path.read_text(encoding="utf-8")
    assert patched.count("DAD_BOT_MODE_PROXY_BEGIN") == 1
    assert patched.index('app.router.add_route("*", "/bot"') < patched.index('app.router.add_route("*", "/{tail:.*}"')
    assert "async def bot_proxy" in patched
    assert "not k.lower().startswith(\"sec-websocket-\")" in patched
    assert 'protocols = ["binary"] if "binary" in requested_protocols else []' in patched
    assert "asyncio.FIRST_COMPLETED" in patched
    assert "ClientTimeout(total=None, sock_connect=10)" in patched
    assert (tmp_path / "app.py.dad-bot-mode.bak").exists()
    before = path.read_bytes()
    assert not patch_proxy(path)
    assert path.read_bytes() == before

