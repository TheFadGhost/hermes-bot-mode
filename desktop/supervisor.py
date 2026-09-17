"""Private host-side desktop controller. Never expose this port through Funnel.

Only fixed Docker/xdotool operations are accepted. The web app has neither a
Docker socket mount nor a general host shell endpoint.
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import re
import contextlib
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
try:
    from .lifecycle import DesktopPool
except ImportError:
    from lifecycle import DesktopPool

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
ROOT = Path(os.environ.get("BOT_DESKTOP_DATA", "/var/lib/hermes-bot-mode/desktops")).resolve()
SECRET = os.environ.get("BOT_DESKTOP_SECRET", "")
IMAGE = os.environ.get("BOT_DESKTOP_IMAGE", "dad-bot-desktop:1")
MAX_RUNNING = max(1, min(int(os.environ.get("BOT_DESKTOP_MAX_RUNNING", "1")), 2))
IDLE_TTL = max(15, int(os.environ.get("BOT_DESKTOP_IDLE_TTL", "300")))


async def authorized(request: Request, authorization: str = Header(default="")):
    if request.client and request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "Local access only")
    if len(SECRET) < 32 or not hmac.compare_digest(authorization, "Bearer " + SECRET):
        raise HTTPException(403, "Not authorized")


def name(agent_id: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", agent_id):
        raise HTTPException(400, "Invalid agent id")
    return "dad-desktop-" + agent_id


async def command(*args: str, timeout: int = 45, allow_missing=False) -> bytes:
    process = await asyncio.create_subprocess_exec("docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise HTTPException(504, "Desktop operation timed out")
    if process.returncode and not allow_missing:
        raise HTTPException(503, "Desktop operation failed: " + stderr.decode(errors="replace")[:180])
    return stdout


async def inspect(agent_id: str) -> dict:
    raw = await command("inspect", name(agent_id), allow_missing=True)
    if not raw.strip() or raw.strip() == b"[]":
        return {"created": False, "running": False}
    info = json.loads(raw)[0]
    bindings = info.get("NetworkSettings", {}).get("Ports", {}).get("6080/tcp") or []
    return {"created": True, "running": info["State"]["Running"], "port": int(bindings[0]["HostPort"]) if bindings else None, "networks": list(info.get("NetworkSettings", {}).get("Networks", {})),
            "desktop_version": (info.get("Config", {}).get("Labels") or {}).get("dad-bot.desktop-version")}


@app.get("/health", dependencies=[Depends(authorized)])
async def health():
    return {"available": True, "max_running": MAX_RUNNING}


@app.post("/codex-auth", dependencies=[Depends(authorized)])
async def codex_auth(force_refresh: bool = False):
    """Keep refresh-token ownership in Hermes; return only its short-lived token.

    This route is loopback-only and has the same dedicated service credential.
    Its response is consumed by app-server, never relayed through the web API.
    """
    code = '''import base64,json,sys
from hermes_cli.auth import resolve_codex_runtime_credentials
try:
    credentials=resolve_codex_runtime_credentials(force_refresh=FORCE_REFRESH)
    if credentials.get("source") != "hermes-auth-store": raise ValueError("unexpected credential source")
    token=credentials["api_key"]
    payload=token.split(".")[1]
    claims=json.loads(base64.urlsafe_b64decode(payload+"="*(-len(payload)%4)))
    account=claims.get("https://api.openai.com/auth",{})
    account_id=account.get("chatgpt_account_id")
    if not isinstance(account_id,str) or not account_id: raise ValueError("missing account metadata")
    result={"accessToken":token,"chatgptAccountId":account_id}
    plan=account.get("chatgpt_plan_type")
    if isinstance(plan,str) and plan: result["chatgptPlanType"]=plan
    print(json.dumps(result))
except Exception:
    sys.exit(2)
'''.replace("FORCE_REFRESH", repr(force_refresh))
    result = await command("exec", "-e", "CODEX_HOME=/tmp/dad-bot-no-import", "-w", "/opt/hermes", "hermes", "/opt/hermes/.venv/bin/python", "-c", code, timeout=20)
    try:
        credentials = json.loads(result)
        if not credentials.get("accessToken") or not credentials.get("chatgptAccountId"):
            raise ValueError()
        return credentials
    except (ValueError, TypeError):
        raise HTTPException(503, "Existing ChatGPT sign-in is unavailable")


async def docker_start(agent_id: str):
    current = await inspect(agent_id)
    if current["created"] and current.get("desktop_version") != "2":
        if current["running"]:
            raise HTTPException(409, "Pause this computer, then start it again to finish its update")
        # Only the stopped container is replaced; its bound UUID profile stays.
        await command("rm", name(agent_id))
        current = {"created": False, "running": False}
    network = name(agent_id) + "-net"
    existing_network = await command("network", "inspect", network, allow_missing=True)
    if not existing_network.strip() or existing_network.strip() == b"[]":
        await command("network", "create", "--driver", "bridge", "--opt", "com.docker.network.bridge.enable_icc=false", "--label", "dad-bot.desktop=true", network)
    if current["created"]:
        await command("update", "--restart=no", name(agent_id))
        networks = current.get("networks", [])
        if network not in networks:
            await command("network", "connect", network, name(agent_id))
        for old_network in networks:
            if old_network != network:
                await command("network", "disconnect", old_network, name(agent_id))
        current = await inspect(agent_id)
    if current["running"]:
        return current
    if current["created"]:
        await command("start", name(agent_id))
    else:
        profile = ROOT / agent_id
        if profile.is_symlink() or not profile.resolve().is_relative_to(ROOT):
            raise HTTPException(400, "Invalid profile directory")
        profile.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chown(profile, 1000, 1000)
        await command("run", "-d", "--network", network, "--name", name(agent_id), "--label", "dad-bot.desktop=true", "--label", "dad-bot.desktop-version=2", "--restart", "no",
                      "--cpus", "0.75", "--memory", "1536m", "--memory-swap", "1536m", "--pids-limit", "256", "--shm-size", "256m",
                      "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-p", "127.0.0.1::6080",
                      "--mount", f"type=bind,src={profile},dst=/profile", IMAGE, timeout=90)
    return await inspect(agent_id)


class Action(BaseModel):
    action: str
    x: int = Field(default=0, ge=0, le=1365)
    y: int = Field(default=0, ge=0, le=899)
    text: str = Field(default="", max_length=12000)
    key: str = Field(default="Return", max_length=40)
    direction: str = "down"
    amount: int = Field(default=3, ge=1, le=20)
    generation: int = Field(ge=0)
    task_id: str = Field(min_length=1, max_length=128)


async def docker_action(agent_id: str, body: Action):
    if not (await inspect(agent_id))["running"]:
        raise HTTPException(409, "Start this agent's computer first.")
    # Bound the process inside the container too: killing the Docker client
    # alone would otherwise leave delayed input running after lock release.
    prefix = ("exec", "-e", "DISPLAY=:99", name(agent_id), "timeout", "--kill-after=2", "20")
    if body.action == "click":
        await command(*prefix, "xdotool", "mousemove", str(body.x), str(body.y), "click", "1")
    elif body.action == "type":
        await command(*prefix, "xdotool", "type", "--clearmodifiers", "--delay", "1", "--", body.text)
    elif body.action == "key":
        if body.key not in {"Return", "Tab", "Escape", "BackSpace", "Delete", "Up", "Down", "Left", "Right", "Home", "End", "Page_Up", "Page_Down", "ctrl+l", "ctrl+a", "ctrl+c", "ctrl+v", "ctrl+t", "ctrl+w", "alt+Left", "shift+Tab"}:
            raise HTTPException(400, "Unsupported key")
        await command(*prefix, "xdotool", "key", "--clearmodifiers", body.key)
    elif body.action == "scroll":
        if body.direction not in {"up", "down"}:
            raise HTTPException(400, "Invalid direction")
        await command(*prefix, "xdotool", "click", "--repeat", str(body.amount), "--delay", "60", "4" if body.direction == "up" else "5")
    elif body.action == "navigate":
        if not body.text.startswith(("https://", "http://")) or "\n" in body.text:
            raise HTTPException(400, "Use an HTTP or HTTPS address")
        await command(*prefix, "xdotool", "key", "--clearmodifiers", "ctrl+l")
        await command(*prefix, "xdotool", "type", "--clearmodifiers", "--delay", "1", "--", body.text)
        await command(*prefix, "xdotool", "key", "Return")
    elif body.action != "screenshot":
        raise HTTPException(400, "Unsupported computer action")
    await asyncio.sleep(0.25)
    await command(*prefix, "scrot", "-o", "/tmp/bot-screen.png")
    screenshot = await command(*prefix, "cat", "/tmp/bot-screen.png")
    return {"image_url": "data:image/png;base64," + base64.b64encode(screenshot).decode(), "width": 1366, "height": 900}


class DockerDriver:
    inspect = staticmethod(inspect)

    async def list(self):
        result = await command("ps", "-a", "--filter", "label=dad-bot.desktop=true", "--format", "{{.Names}}")
        return [value.removeprefix("dad-desktop-") for value in result.decode().splitlines() if value.startswith("dad-desktop-")]

    async def running(self):
        result = await command("ps", "--filter", "label=dad-bot.desktop=true", "--format", "{{.Names}}")
        return result.decode().splitlines()

    async def no_restart(self, agent):
        await command("update", "--restart=no", name(agent))

    async def start(self, agent):
        await docker_start(agent)
        # Verify actual display/browser/VNC readiness, not merely an HTTP file.
        probe = """import socket,time
deadline=time.monotonic()+20
while time.monotonic()<deadline:
 try:
  with socket.create_connection(('127.0.0.1',5900),1) as s:
   s.settimeout(1)
   if s.recv(12).startswith(b'RFB '): break
 except OSError: pass
 time.sleep(.25)
else: raise SystemExit(1)
"""
        await command("exec", name(agent), "python3", "-c", probe, timeout=25)
        return await inspect(agent)

    async def quiesce(self, agent, mode):
        # Replace only the VNC child: X/Chromium/profile keep running. Remote
        # x11vnc -R commands can deadlock behind a stalled framebuffer client.
        # Replacement disconnects every old viewer before applying new input
        # ownership, with no dependency on that client's willingness to read.
        await command("exec", name(agent), "timeout", "--kill-after=1", "16",
                      "python3", "/usr/local/bin/desktop-vnc.py", mode, timeout=18)

    async def stop(self, agent):
        if (await inspect(agent)).get("running"):
            await command("stop", "--time", "15", name(agent))

    async def action(self, agent, params):
        return await docker_action(agent, Action(**params))


POOL = DesktopPool(ROOT / "desktop-leases.json", DockerDriver(), capacity=MAX_RUNNING, idle_ttl=IDLE_TTL)
WATCHDOG: asyncio.Task | None = None


@app.on_event("startup")
async def start_watchdog():
    global WATCHDOG
    await POOL.reconcile()
    async def watchdog():
        while True:
            await asyncio.sleep(5)
            try:
                await POOL.reap()
            except Exception:
                # One failed Docker operation must not disable idle cleanup.
                pass
    WATCHDOG = asyncio.create_task(watchdog())


@app.on_event("shutdown")
async def stop_watchdog():
    if WATCHDOG:
        WATCHDOG.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await WATCHDOG


class StartRequest(BaseModel):
    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    viewer_id: str | None = Field(default=None, min_length=1, max_length=128)
    wait_timeout: float = Field(default=60, ge=0, le=120)


class ControlRequest(BaseModel):
    mode: str
    viewer_id: str = Field(default="open", min_length=1, max_length=128)


class HeartbeatRequest(BaseModel):
    generation: int = Field(ge=0)
    visible: bool
    viewer_id: str = Field(default="open", min_length=1, max_length=128)


class TaskHeartbeatRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    generation: int = Field(ge=0)


class ReleaseRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)


@app.get("/desktops/{agent_id}", dependencies=[Depends(authorized)])
async def state(agent_id: str):
    name(agent_id)
    return await POOL.status(agent_id)


@app.post("/desktops/{agent_id}/start", dependencies=[Depends(authorized)])
async def start(agent_id: str, request: Request, body: StartRequest | None = None):
    name(agent_id)
    body = body or StartRequest()
    return await POOL.wake(agent_id, task_id=body.task_id, viewer_id=body.viewer_id,
        wait_timeout=body.wait_timeout, cancelled=request.is_disconnected)


@app.post("/desktops/{agent_id}/stop", dependencies=[Depends(authorized)])
async def stop(agent_id: str):
    name(agent_id)
    return await POOL.stop(agent_id)


@app.post("/desktops/{agent_id}/control", dependencies=[Depends(authorized)])
async def control(agent_id: str, body: ControlRequest):
    name(agent_id)
    return await POOL.control(agent_id, body.mode, body.viewer_id)


@app.post("/desktops/{agent_id}/heartbeat", dependencies=[Depends(authorized)])
async def heartbeat(agent_id: str, body: HeartbeatRequest):
    name(agent_id)
    return await POOL.heartbeat(agent_id, body.generation, body.visible, body.viewer_id)


@app.post("/desktops/{agent_id}/task-heartbeat", dependencies=[Depends(authorized)])
async def task_heartbeat(agent_id: str, body: TaskHeartbeatRequest):
    name(agent_id)
    return await POOL.heartbeat_task(agent_id, body.task_id, body.generation)


@app.post("/desktops/{agent_id}/release", dependencies=[Depends(authorized)])
async def release(agent_id: str, body: ReleaseRequest):
    name(agent_id)
    await POOL.release_task(agent_id, body.task_id)
    return {"released": True}


@app.post("/desktops/{agent_id}/action", dependencies=[Depends(authorized)])
async def action(agent_id: str, body: Action, request: Request):
    name(agent_id)
    return await POOL.action(agent_id, body.model_dump(), generation=body.generation, task_id=body.task_id, cancelled=request.is_disconnected)

