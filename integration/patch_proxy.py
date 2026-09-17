"""Patch the existing aiohttp login proxy with explicit ``/bot`` routes.

The proxy remains the owner of dashboard authentication and forwarding.  The
bot-mode service owns its own session cookie and authentication, so the two
``/bot`` routes are registered before the existing dashboard catch-all.  HTTP
responses stream through unchanged (including SSE), and a small WebSocket
bridge is included for future bot-mode realtime endpoints.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


class PatchError(RuntimeError):
    """Raised when the proxy source is not the expected revision."""


MARKER = "# DAD_BOT_MODE_PROXY"
BLOCK_MARKER = "# DAD_BOT_MODE_PROXY_BEGIN"
ROUTE_MARKER = "# DAD_BOT_MODE_PROXY_ROUTES"

HOP_ANCHOR = (
    'HOP = {"connection","keep-alive","proxy-authenticate","proxy-authorization",\n'
    '       "te","trailers","transfer-encoding","upgrade","content-length"}\n'
)

BOT_BLOCK = r'''# DAD_BOT_MODE_PROXY_BEGIN
BOT_HOST, BOT_PORT = "127.0.0.1", 9120
BOT_HTTP = f"http://{BOT_HOST}:{BOT_PORT}"
BOT_WS = f"ws://{BOT_HOST}:{BOT_PORT}"
BOT_HOSTHDR = f"{BOT_HOST}:{BOT_PORT}"

def _bot_forward_headers(request):
    """Forward bot-mode cookies/headers while stripping hop-by-hop fields."""
    # aiohttp creates a fresh WebSocket handshake. Forwarding the browser's
    # Sec-WebSocket-* fields would duplicate its key and version headers and
    # can make the upstream handshake fail. The selected protocol is supplied
    # explicitly to ws_connect below.
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP and not k.lower().startswith("sec-websocket-")
    }
    headers["Host"] = BOT_HOSTHDR
    return headers

async def _bot_ws_proxy(request):
    requested_protocols = [
        protocol.strip()
        for protocol in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
        if protocol.strip()
    ]
    protocols = ["binary"] if "binary" in requested_protocols else []
    server = web.WebSocketResponse(protocols=protocols)
    await server.prepare(request)
    session = request.app["session"]
    try:
        async with session.ws_connect(
            BOT_WS + request.path_qs,
            headers=_bot_forward_headers(request),
            protocols=protocols,
        ) as client:
            async def client_to_server():
                async for message in client:
                    if message.type == WSMsgType.TEXT:
                        await server.send_str(message.data)
                    elif message.type == WSMsgType.BINARY:
                        await server.send_bytes(message.data)
                    elif message.type == WSMsgType.PING:
                        await server.ping()
                    elif message.type == WSMsgType.PONG:
                        await server.pong()
                    else:
                        break

            async def server_to_client():
                async for message in server:
                    if message.type == WSMsgType.TEXT:
                        await client.send_str(message.data)
                    elif message.type == WSMsgType.BINARY:
                        await client.send_bytes(message.data)
                    elif message.type == WSMsgType.PING:
                        await client.ping()
                    elif message.type == WSMsgType.PONG:
                        await client.pong()
                    else:
                        break

            relays = {
                asyncio.create_task(client_to_server()),
                asyncio.create_task(server_to_client()),
            }
            done, pending = await asyncio.wait(
                relays, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*relays, return_exceptions=True)
    except Exception:
        # The browser receives a closed socket; proxy logs remain free of
        # cookies and nonce values.
        pass
    finally:
        await server.close()
    return server

async def bot_proxy(request):
    """Forward /bot requests without applying the dashboard login cookie."""
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await _bot_ws_proxy(request)
    session = request.app["session"]
    body = await request.read()
    async with session.request(
        request.method,
        BOT_HTTP + request.path_qs,
        headers=_bot_forward_headers(request),
        data=body,
        allow_redirects=False,
        # SSE and other long lived bot responses are allowed to remain open;
        # only the TCP connection attempt has a finite deadline.
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
    ) as upstream:
        response = web.StreamResponse(status=upstream.status)
        for key, value in _resp_headers(upstream):
            response.headers.add(key, value)
        await response.prepare(request)
        async for chunk in upstream.content.iter_chunked(65536):
            await response.write(chunk)
        await response.write_eof()
        return response

# DAD_BOT_MODE_PROXY_END
'''

ROUTE_ANCHOR = '    app.router.add_route("*","/{tail:.*}",handler); return app\n'
ROUTE_REPLACEMENT = (
    f"    {ROUTE_MARKER}\n"
    '    app.router.add_route("*", "/bot", bot_proxy)\n'
    '    app.router.add_route("*", "/bot/{tail:.*}", bot_proxy)\n'
    '    app.router.add_route("*", "/{tail:.*}", handler); return app\n'
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def _backup(path: Path) -> Path:
    backup = path.with_name(path.name + ".dad-bot-mode.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def _replace_once(text: str, anchor: str, replacement: str, label: str) -> str:
    count = text.count(anchor)
    if count != 1:
        raise PatchError(f"expected exactly one {label} anchor; found {count}")
    return text.replace(anchor, replacement, 1)


def patch_proxy(app_path: str | Path, *, dry_run: bool = False) -> bool:
    """Patch one proxy app source file; return whether it changed."""

    path = Path(app_path).expanduser().resolve()
    if not path.is_file():
        raise PatchError(f"proxy app does not exist: {path}")
    text = _read(path)
    if MARKER in text:
        if BLOCK_MARKER not in text or ROUTE_MARKER not in text:
            raise PatchError(f"partial bot-mode proxy marker found in {path}")
        return False

    text = _replace_once(text, HOP_ANCHOR, HOP_ANCHOR + "\n" + BOT_BLOCK, "hop-header")
    text = _replace_once(text, ROUTE_ANCHOR, ROUTE_REPLACEMENT, "dashboard catch-all route")
    if not dry_run:
        _backup(path)
        _write(path, text)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, help="existing login proxy app.py")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify anchors and report the patch without writing files",
    )
    args = parser.parse_args()
    try:
        changed = patch_proxy(args.app, dry_run=args.dry_run)
    except PatchError as exc:
        parser.error(str(exc))
    action = "would patch" if args.dry_run else "patched"
    print(f"proxy {action}: {args.app if changed else 'already applied'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

