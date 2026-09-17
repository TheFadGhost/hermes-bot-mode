"""Authenticated-app adapter for the private Linux desktop supervisor."""
from __future__ import annotations

import asyncio
import os
import time
import inspect
from urllib.parse import quote
from typing import Any

import httpx
from fastapi import HTTPException, Request, WebSocket
from starlette.responses import Response
import websockets


class DesktopManager:
    def __init__(self, url: str | None = None, secret: str | None = None):
        self.url = (url or os.getenv("BOT_DESKTOP_URL", "http://127.0.0.1:9121")).rstrip("/")
        self.secret = secret or os.getenv("BOT_DESKTOP_SECRET", "")
        self._ports: dict[str, tuple[int, float]] = {}
        self._task_generations: dict[tuple[str, str], int] = {}
        self._task_keepers: dict[tuple[str, str], asyncio.Task] = {}

    async def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not self.secret:
            raise HTTPException(503, "Computer service is not configured")
        async with httpx.AsyncClient(timeout=180 if path.endswith("/start") else 100, trust_env=False) as client:
            try:
                result = await client.request(method, self.url + path, headers={"Authorization": "Bearer " + self.secret}, json=payload)
            except httpx.RequestError:
                raise HTTPException(503, "Computer service is offline")
            if result.is_error:
                try:
                    reason = result.json().get("detail", "Computer operation failed")
                except ValueError:
                    reason = "Computer operation failed"
                raise HTTPException(result.status_code, reason)
            return result.json()

    async def status(self, agent_id: str) -> dict:
        try:
            result = await self._request("GET", "/desktops/" + agent_id)
        except HTTPException as exc:
            if exc.status_code == 503:
                return {"available": False, "created": False, "running": False, "reason": str(exc.detail)}
            raise
        return self._public(agent_id, result)

    def _public(self, agent_id: str, value: dict) -> dict:
        base = f"/bot/api/agents/{agent_id}/desktop/view/"
        generation = int(value.get("generation", 0))
        mode = value.get("control_mode", "bot")
        socket_path = quote(base.lstrip("/") + f"websockify?generation={generation}", safe="/")
        return {"available": True, "created": value.get("created", False), "running": value.get("running", False),
                "phase": value.get("phase", "running" if value.get("running") else "sleeping"),
                "control_mode": mode, "generation": generation,
                "view_url": base + f"vnc.html?autoconnect=true&resize=scale&generation={generation}&view_only={'true' if mode == 'bot' else 'false'}&path=" + socket_path if value.get("running") else None}

    async def create(self, agent_id: str, *, task_id: str | None = None, viewer_id: str | None = None,
                     cancel_check=None, wait_timeout: float = 60) -> dict:
        self._ports.pop(agent_id, None)
        operation = asyncio.create_task(self._request("POST", "/desktops/" + agent_id + "/start",
            {"task_id": task_id, "viewer_id": viewer_id, "wait_timeout": min(wait_timeout, 60)}))
        try:
            while not operation.done():
                if cancel_check:
                    cancelled = cancel_check()
                    if inspect.isawaitable(cancelled):
                        cancelled = await cancelled
                    if cancelled:
                        raise asyncio.CancelledError
                await asyncio.wait({operation}, timeout=0.25)
            state = await operation
        finally:
            if not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
        if task_id:
            key = (agent_id, task_id)
            self._task_generations[key] = int(state["generation"])
            previous = self._task_keepers.pop(key, None)
            if previous:
                previous.cancel()
                await asyncio.gather(previous, return_exceptions=True)
            if task_id != "legacy-action":
                self._task_keepers[key] = asyncio.create_task(self._keep_task(agent_id, task_id, int(state["generation"])))
        port = await self._port(agent_id)
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            for _ in range(30):
                try:
                    if (await client.get(f"http://127.0.0.1:{port}/vnc.html")).status_code == 200:
                        async with websockets.connect(f"ws://127.0.0.1:{port}/websockify", subprotocols=["binary"], open_timeout=2, close_timeout=1) as socket:
                            greeting = await asyncio.wait_for(socket.recv(), timeout=2)
                            if isinstance(greeting, bytes) and greeting.startswith(b"RFB "):
                                return self._public(agent_id, state)
                except (httpx.RequestError, OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException):
                    pass
                await asyncio.sleep(0.5)
        raise HTTPException(503, "Computer is starting. Try opening it again in a moment.")

    async def stop(self, agent_id: str) -> dict:
        self._ports.pop(agent_id, None)
        result = await self._request("POST", "/desktops/" + agent_id + "/stop")
        self._ports.pop(agent_id, None)
        return self._public(agent_id, result)

    async def action(self, agent_id: str, params: dict, *, task_id: str | None = None,
                     generation: int | None = None, cancel_check=None) -> dict:
        if cancel_check:
            cancelled = cancel_check()
            if inspect.isawaitable(cancelled):
                cancelled = await cancelled
            if cancelled:
                raise asyncio.CancelledError
        # Identity comes from the authenticated caller, never model arguments.
        task_id = task_id or "legacy-action"
        if generation is None:
            generation = self._task_generations.get((agent_id, task_id))
        if generation is None:
            state = await self.create(agent_id, task_id=task_id, cancel_check=cancel_check)
            generation = state["generation"]
        return await self._request("POST", "/desktops/" + agent_id + "/action",
            {**params, "generation": generation, "task_id": task_id})

    async def control(self, agent_id: str, mode: str, *, viewer_id: str | None = None) -> dict:
        result = await self._request("POST", f"/desktops/{agent_id}/control", {"mode": mode, "viewer_id": viewer_id or "open"})
        self._ports.pop(agent_id, None)
        return self._public(agent_id, result)

    async def heartbeat(self, agent_id: str, generation: int, visible: bool, *, viewer_id: str | None = None) -> dict:
        return await self._request("POST", f"/desktops/{agent_id}/heartbeat",
            {"generation": generation, "visible": visible, "viewer_id": viewer_id or "open"})

    async def _keep_task(self, agent_id: str, task_id: str, generation: int) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                await self._request("POST", f"/desktops/{agent_id}/task-heartbeat", {"task_id": task_id, "generation": generation})
        except (HTTPException, asyncio.CancelledError):
            # Ownership changes and backend restarts allow the short lease to
            # expire. The owning task explicitly releases it in its finally.
            return

    async def release_task(self, agent_id: str, task_id: str) -> None:
        self._task_generations.pop((agent_id, task_id), None)
        keeper = self._task_keepers.pop((agent_id, task_id), None)
        if keeper:
            keeper.cancel()
            await asyncio.gather(keeper, return_exceptions=True)
        await self._request("POST", f"/desktops/{agent_id}/release", {"task_id": task_id})

    async def _port(self, agent_id: str) -> int:
        cached = self._ports.get(agent_id)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        state = await self._request("GET", "/desktops/" + agent_id)
        if not state.get("running") or not state.get("port"):
            raise HTTPException(409, "Start this computer first")
        port = int(state["port"])
        if not 1024 <= port <= 65535:
            raise HTTPException(503, "Invalid computer connection")
        self._ports[agent_id] = (port, time.monotonic() + 5)
        return port

    async def proxy_http(self, agent_id: str, path: str, request: Request) -> Response:
        if ".." in path.split("/") or "\\" in path:
            raise HTTPException(400, "Invalid path")
        if path == "lease.js":
            # A self-hosted script (compatible with script-src 'self') renews
            # full-screen noVNC leases too. Hidden/closed viewers expire.
            script = """(() => {
 const generation = Number(new URL(document.currentScript.src).searchParams.get('generation'));
 const endpoint = location.pathname.split('/view/')[0] + '/heartbeat';
 const viewer_token = crypto.randomUUID();
 let intersecting = true;
 const beat = (visible = !document.hidden && intersecting) => fetch(endpoint, {method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({generation,visible,viewer_token}),keepalive:true}).catch(()=>{});
 const observer = new IntersectionObserver(([entry]) => {intersecting=entry.isIntersecting; beat();});
 observer.observe(document.documentElement);
 const timer = setInterval(()=>beat(),15000);
 document.addEventListener('visibilitychange',()=>beat());
 window.addEventListener('pagehide',()=>{clearInterval(timer);observer.disconnect();beat(false);});
 beat();
})();"""
            return Response(script, media_type="text/javascript", headers={"Cache-Control": "no-store"})
        port = await self._port(agent_id)
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            try:
                response = await client.get(f"http://127.0.0.1:{port}/" + path, params=request.query_params)
            except httpx.RequestError:
                raise HTTPException(503, "Computer is starting. Try again in a moment.")
        content = response.content
        if path == "vnc.html" and response.status_code == 200:
            try:
                generation = int(request.query_params.get("generation", "-1"))
            except ValueError:
                raise HTTPException(400, "Invalid computer generation")
            script = f'<script src="lease.js?generation={generation}" defer></script>'
            content = content.replace(b"</head>", script.encode() + b"</head>")
        return Response(content, status_code=response.status_code,
                        headers={"Content-Type": response.headers.get("content-type", "application/octet-stream"), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def proxy_websocket(self, agent_id: str, websocket: WebSocket) -> None:
        try:
            generation = int(websocket.query_params.get("generation", "-1"))
        except ValueError:
            await websocket.close(code=1008)
            return
        state = await self._request("GET", f"/desktops/{agent_id}")
        if generation != state.get("generation") or not state.get("running"):
            await websocket.close(code=1008)
            return
        port = await self._port(agent_id)
        await websocket.accept(subprotocol="binary" if "binary" in websocket.headers.get("sec-websocket-protocol", "") else None)
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/websockify", subprotocols=["binary"], max_size=16 * 1024 * 1024) as upstream:
                # A handoff can occur while the upstream connection opens.
                current = await self._request("GET", f"/desktops/{agent_id}")
                if current.get("generation") != generation or not current.get("running"):
                    return

                async def to_desktop():
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        await upstream.send(message.get("bytes") if message.get("bytes") is not None else message.get("text", ""))

                async def to_browser():
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                async def watch_generation():
                    while True:
                        await asyncio.sleep(2)
                        current = await self._request("GET", f"/desktops/{agent_id}")
                        if not current.get("running") or current.get("generation") != generation:
                            return

                tasks = [asyncio.create_task(to_desktop()), asyncio.create_task(to_browser()), asyncio.create_task(watch_generation())]
                try:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                finally:
                    for task in tasks:
                        task.cancel()
        finally:
            try:
                await websocket.close()
            except RuntimeError:
                pass

