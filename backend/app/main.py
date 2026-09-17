"""FastAPI application for the standalone Hermes bot-mode service."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.routing import APIRouter
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import AuthManager, Session
from .config import Settings
from .db import Database
from .errors import APIError
from .runtime import RuntimeUnavailable, UnavailableRuntime, runtime_status
from .schemas import (
    AgentCreate,
    AgentPatch,
    ApprovalDecision,
    CompactRequest,
    ConversationCreate,
    ExchangeRequest,
    MemoryCreate,
    MemoryPatch,
    MessageCreate,
    NonceRequest,
    model_values,
)
from .store import Store
from .learned_skills import LearnedSkills
from .tasks import TaskManager
from .workspace import Workspace
from .messenger import Messenger
from .history import History
from .orchestration import Orchestration
from .routines import Routines


API_PREFIX = "/bot/api"


def _header_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    return origin.rstrip("/") if origin else None


def _same_origin(request: Request, settings: Settings) -> bool:
    origin = _header_origin(request)
    if origin is None:
        return not settings.production
    if origin in settings.allowed_origins:
        return True
    # A local development client can use its TestClient origin without a
    # configured public URL. Production always requires an explicit allowlist.
    if not settings.production:
        expected = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
        return origin == expected
    return False


def _set_session_cookie(response: Any, settings: Settings, token: str, expires_at: int) -> None:
    """Set the persistent session cookie with the session's absolute expiry."""

    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        expires=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        path=settings.cookie_path,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _delete_session_cookie(response: Any, settings: Settings) -> None:
    response.delete_cookie(
        settings.cookie_name,
        path=settings.cookie_path,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


class OriginMiddleware(BaseHTTPMiddleware):
    """Protect every cookie-authenticated state mutation against CSRF."""

    def __init__(self, app: Any, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path
        mutating = request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        internal = path == f"{API_PREFIX}/internal/auth/nonce"
        if mutating and path.startswith(API_PREFIX) and not internal:
            if request.cookies.get(self.settings.cookie_name) and not _same_origin(request, self.settings):
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "origin_forbidden", "message": "Request origin is not allowed"}},
                )
        response = await call_next(request)
        session = getattr(request.state, "session", None)
        token = request.cookies.get(self.settings.cookie_name)
        if (
            isinstance(session, Session)
            and session.cookie_refresh
            and token
            and not getattr(request.state, "skip_session_cookie_refresh", False)
        ):
            _set_session_cookie(response, self.settings, token, session.expires_at)
        if path.startswith(API_PREFIX):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response


def _http_error(exc: HTTPException) -> APIError:
    code = {
        400: "bad_request",
        401: "unauthenticated",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
        422: "validation_error",
        429: "rate_limited",
        500: "server_error",
        503: "service_unavailable",
    }.get(exc.status_code, "request_failed")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return APIError(exc.status_code, code, message, details=exc.detail if not isinstance(exc.detail, str) else None)


def create_app(settings: Settings | None = None, runtime: Any | None = None, desktop: Any | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    db = Database(settings.database_path)
    store = Store(db)
    auth = AuthManager(db, settings)
    workspace = Workspace(settings)
    if runtime is None:
        runtime_name = os.getenv("BOT_RUNTIME", "unavailable").strip().lower()
        if runtime_name in {"codex", "codex-app-server", "app-server"}:
            # Import only when explicitly selected so the standalone backend
            # stays testable on hosts without a codex executable.
            from .codex_runtime import CodexRuntime

            runtime = CodexRuntime(settings.database_path.parent / "runtime", settings.workspace_root)
        else:
            runtime = UnavailableRuntime()
    if desktop is None:
        try:
            from .desktops import DesktopManager

            desktop = DesktopManager()
        except ImportError:
            # Desktop support is optional; the API remains truthful about its
            # unavailable state when the supervisor dependencies are absent.
            desktop = None
    messenger = Messenger(store)
    history = History(store, messenger)
    orchestration = Orchestration(store, messenger, settings.default_model)
    task_manager = TaskManager(store, workspace, runtime, messenger=messenger, history=history, desktop=desktop)
    task_manager.orchestration = orchestration
    routines = Routines(store, messenger, task_manager)
    task_manager.routines = routines
    from .extension_service import Extensions
    extensions = Extensions(store, messenger, task_manager, settings)
    task_manager.teachings = extensions.teachings
    from .telegram_bridge import TelegramBridge
    telegram_bridge = TelegramBridge(store, messenger, task_manager,
        owner_id=os.getenv('BOT_TELEGRAM_BRIDGE_OWNER_ID', ''),
        secret=os.getenv('BOT_TELEGRAM_BRIDGE_SECRET', ''), default_model=settings.default_model)
    if callable(getattr(runtime, "register_tools", None)):
        from .scoped_tools import build_scoped_tool_bridge
        from .extension_tools import DEFINITIONS, NAMES, handle as handle_extension

        bridge = build_scoped_tool_bridge(store, workspace, task_manager, desktop)
        async def scoped_handle(request, name, args):
            if name in NAMES:
                return await handle_extension(extensions, request, name, args)
            return await bridge.handle(request, name, args)
        runtime.register_tools(bridge.definitions() + DEFINITIONS, scoped_handle)
    if callable(getattr(runtime, "register_image_handler", None)):
        from .codex_images import persist_codex_image
        runtime.register_image_handler(lambda request, item: persist_codex_image(
            store, workspace, request.user_id, request.agent_id, item))
    app = FastAPI(
        title="Hermes Bot Mode API",
        version="0.1.0",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.state.settings = settings
    app.state.db = db
    app.state.store = store
    app.state.auth = auth
    app.state.workspace = workspace
    app.state.runtime = runtime
    app.state.desktop = desktop
    app.state.task_manager = task_manager
    app.state.messenger = messenger
    app.state.history = history
    app.state.routines = routines
    app.state.extensions = extensions
    app.state.telegram_bridge = telegram_bridge
    app.add_middleware(OriginMiddleware, settings=settings)

    @app.on_event("startup")
    async def startup() -> None:
        await task_manager.start()
        await routines.start()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await routines.close()
        await task_manager.close()
        # Database uses short-lived connections; no open connection needs to
        # be kept here. Runtime adapters own their separate process/database.

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.as_dict())

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        error = _http_error(exc)
        return JSONResponse(status_code=error.status_code, content=error.as_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "Request validation failed", "details": exc.errors()}},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Keep stack traces out of the remote API. Detailed diagnostics belong
        # in the service log, while clients receive one stable error shape.
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "server_error", "message": "The server could not complete the request"}},
        )

    api = APIRouter(prefix=API_PREFIX)

    def current_session(request: Request) -> Session:
        token = request.cookies.get(settings.cookie_name)
        session = auth.get_session(token)
        if session is None:
            raise APIError(401, "unauthenticated", "A valid bot-mode session is required")
        request.state.session = session
        return session

    def internal_authorized(request: Request) -> None:
        if settings.production:
            client_host = request.client.host if request.client else ""
            normalized = client_host.removeprefix("::ffff:")
            if normalized not in {"127.0.0.1", "::1", "localhost"}:
                raise APIError(403, "internal_only", "Internal endpoint is loopback-only")
        supplied = request.headers.get("x-bot-internal-secret", "")
        authorization = request.headers.get("authorization", "")
        if not supplied and authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
        if not supplied or not settings.internal_secret:
            raise APIError(403, "internal_forbidden", "Internal authentication failed")
        import hmac

        if not hmac.compare_digest(supplied.encode(), settings.internal_secret.encode()):
            raise APIError(403, "internal_forbidden", "Internal authentication failed")

    def normalize_identity(value: str | int | None, field: str) -> str | None:
        if value is None:
            return None
        normalized = str(value)
        if not normalized or len(normalized) > 128 or any(ord(char) < 32 for char in normalized):
            raise APIError(422, "identity_invalid", f"{field} is invalid")
        return normalized

    def require_origin(request: Request) -> None:
        if not _same_origin(request, settings):
            raise APIError(403, "origin_forbidden", "Request origin is not allowed")

    @api.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "service": "hermes-bot-mode"}

    # -------------------------------------------------------------- auth
    @api.post("/internal/auth/nonce", status_code=201)
    async def issue_nonce(request: Request, body: NonceRequest) -> dict[str, Any]:
        internal_authorized(request)
        user_id = normalize_identity(body.user_id, "user_id")
        chat_id = normalize_identity(body.chat_id, "chat_id")
        assert user_id is not None
        result = auth.create_nonce(user_id, source_chat_id=chat_id)
        store.activity(user_id, "auth.nonce_issued", {"source_chat_id": chat_id} if chat_id else {})
        return result

    @api.post("/auth/exchange")
    async def exchange(request: Request, body: ExchangeRequest) -> JSONResponse:
        require_origin(request)
        try:
            token, session = auth.exchange(
                body.nonce,
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host if request.client else None,
            )
        except ValueError as exc:
            raise APIError(401, "nonce_invalid", "The login link is invalid, expired, or already used") from exc
        store.activity(session.user_id, "auth.login", {"session_id": session.id})
        response = JSONResponse(
            {
                "authenticated": True,
                "user": {"id": session.user_id},
                "session": session.as_dict(),
            }
        )
        _set_session_cookie(response, settings, token, session.expires_at)
        return response

    @api.get("/auth/me")
    async def me(session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"authenticated": True, "user": {"id": session.user_id}, "session": session.as_dict()}

    @api.post("/auth/logout")
    async def logout(request: Request, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> JSONResponse:
        auth.revoke(session.id)
        store.activity(session.user_id, "auth.logout", {"session_id": session.id})
        request.state.skip_session_cookie_refresh = True
        response = JSONResponse({"logged_out": True})
        _delete_session_cookie(response, settings)
        return response

    @api.post("/auth/revoke-all")
    async def revoke_all(request: Request, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> JSONResponse:
        count = auth.revoke_all(session.user_id)
        store.activity(session.user_id, "auth.sessions_revoked", {"count": count})
        request.state.skip_session_cookie_refresh = True
        response = JSONResponse({"revoked": count})
        _delete_session_cookie(response, settings)
        return response

    @api.get("/auth/sessions")
    async def sessions(session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"sessions": [item.as_dict() for item in auth.list_sessions(session.user_id)]}

    @api.post("/auth/sessions/{session_id}/revoke")
    async def revoke_session(
        session_id: str,
        request: Request,
        session: Session = Depends(current_session),
        _: None = Depends(require_origin),
    ) -> JSONResponse:
        if not auth.revoke_owned(session.user_id, session_id):
            raise APIError(404, "session_not_found", "Session was not found")
        store.activity(session.user_id, "auth.session_revoked", {"session_id": session_id})
        response = JSONResponse({"revoked": True})
        if session.id == session_id:
            request.state.skip_session_cookie_refresh = True
            _delete_session_cookie(response, settings)
        return response

    # ------------------------------------------------------------ runtime
    @api.get("/runtime/status")
    async def runtime_status_route(session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"runtime": runtime_status(runtime).as_dict()}

    async def optional_runtime_call(name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(runtime, name, None)
        if not callable(method):
            raise APIError(503, "runtime_unavailable", "This runtime capability is unavailable")
        try:
            value = method(*args, **kwargs)
            if hasattr(value, "__await__"):
                value = await value
            return value
        except RuntimeUnavailable as exc:
            raise APIError(503, "runtime_unavailable", str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise APIError(400, "runtime_request_invalid", str(exc)) from exc
        except Exception as exc:
            raise APIError(503, "runtime_error", "The runtime capability failed") from exc

    @api.get("/runtime/account")
    async def runtime_account(session: Session = Depends(current_session)) -> Any:
        return await optional_runtime_call("account_status")

    @api.post("/runtime/login")
    async def runtime_login(session: Session = Depends(current_session), _: None = Depends(require_origin)) -> Any:
        result = await optional_runtime_call("login")
        store.activity(session.user_id, "runtime.login_started", {})
        return result

    @api.get("/runtime/usage")
    async def runtime_usage(session: Session = Depends(current_session)) -> Any:
        return await optional_runtime_call("usage")

    # --------------------------------------------------------------- agents
    @api.get("/agents")
    async def list_agents(session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"agents": store.list_agents(session.user_id)}

    @api.post("/agents", status_code=201)
    async def create_agent(body: AgentCreate, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        values = model_values(body)
        values["model"] = values.get("model") or settings.default_model
        agent = store.create_agent(session.user_id, **values)
        store.activity(session.user_id, "agent.created", {"agent_id": agent["id"]})
        return {"agent": agent}

    @api.get("/agents/{agent_id}")
    async def get_agent(agent_id: str, session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"agent": store.get_agent(session.user_id, agent_id)}

    @api.patch("/agents/{agent_id}")
    async def update_agent(agent_id: str, body: AgentPatch, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        agent = store.update_agent(session.user_id, agent_id, model_values(body, exclude_unset=True))
        store.activity(session.user_id, "agent.updated", {"agent_id": agent_id})
        return {"agent": agent}

    @api.delete("/agents/{agent_id}")
    async def delete_agent(agent_id: str, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> JSONResponse:
        store.get_agent(session.user_id, agent_id)
        if desktop is not None:
            state = await desktop.status(agent_id)
            if state.get("created"):
                await desktop.stop(agent_id)
        store.delete_agent(session.user_id, agent_id)
        store.activity(session.user_id, "agent.deleted", {"agent_id": agent_id})
        return JSONResponse({"deleted": True})

    # Desktop creation/viewing is intentionally unavailable until a separate
    # supervisor adapter is connected. The stable response lets the UI render
    # a truthful state instead of pretending an interactive desktop exists.
    @api.get("/agents/{agent_id}/desktop")
    async def desktop_status(agent_id: str, session: Session = Depends(current_session)) -> dict[str, Any]:
        agent = store.get_agent(session.user_id, agent_id)
        if desktop is not None:
            result = await desktop.status(agent_id)
            return {"agent_id": agent_id, **result}
        return {
            "agent_id": agent_id,
            "available": False,
            "created": False,
            "running": False,
            "status": "unavailable",
            "reason": "Desktop supervisor is not configured",
            "view_url": None,
            "desktop_id": agent.get("desktop_id"),
        }

    @api.post("/agents/{agent_id}/desktop")
    async def create_desktop(agent_id: str, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        store.get_agent(session.user_id, agent_id)
        if desktop is None:
            raise APIError(503, "desktop_unavailable", "Desktop supervisor is not configured")
        result = await desktop.create(agent_id, viewer_id=session.id)
        store.activity(session.user_id, "desktop.created", {"agent_id": agent_id})
        return {"desktop": result}

    @api.delete("/agents/{agent_id}/desktop")
    async def delete_desktop(agent_id: str, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        store.get_agent(session.user_id, agent_id)
        if desktop is None:
            raise APIError(503, "desktop_unavailable", "Desktop supervisor is not configured")
        result = await desktop.stop(agent_id)
        store.activity(session.user_id, "desktop.stopped", {"agent_id": agent_id})
        return {"desktop": result}

    @api.post("/agents/{agent_id}/desktop/action")
    async def desktop_action(
        agent_id: str,
        request: Request,
        session: Session = Depends(current_session),
        _: None = Depends(require_origin),
    ) -> dict[str, Any]:
        store.get_agent(session.user_id, agent_id)
        if desktop is None:
            raise APIError(503, "desktop_unavailable", "Desktop supervisor is not configured")
        payload = await request.json()
        if not isinstance(payload, dict):
            raise APIError(422, "desktop_action_invalid", "Desktop action must be a JSON object")
        return {"result": await desktop.action(agent_id, payload)}

    @api.get("/agents/{agent_id}/desktop/view/{view_path:path}")
    async def desktop_view(
        agent_id: str,
        view_path: str,
        request: Request,
        session: Session = Depends(current_session),
    ) -> Any:
        store.get_agent(session.user_id, agent_id)
        if desktop is None:
            raise APIError(503, "desktop_unavailable", "Desktop supervisor is not configured")
        return await desktop.proxy_http(agent_id, view_path, request)

    @api.websocket("/agents/{agent_id}/desktop/view/websockify")
    async def desktop_websocket(websocket: WebSocket, agent_id: str) -> None:
        """Proxy noVNC only after checking the same scoped session cookie."""
        token = websocket.cookies.get(settings.cookie_name)
        session = auth.get_session(token)
        origin = websocket.headers.get("origin", "").rstrip("/")
        origin_allowed = origin in settings.allowed_origins
        if not settings.production and not origin:
            origin_allowed = True
        if not origin_allowed or session is None:
            await websocket.close(code=1008)
            return
        try:
            store.get_agent(session.user_id, agent_id)
            if desktop is None:
                await websocket.close(code=1013)
                return
            await desktop.proxy_websocket(agent_id, websocket)
        except Exception:
            try:
                await websocket.close(code=1011)
            except Exception:
                pass

    # ------------------------------------------------------- conversations
    @api.get("/conversations")
    async def list_conversations(agent_id: str | None = None, session: Session = Depends(current_session)) -> dict[str, Any]:
        if agent_id:
            return {"conversations": [messenger.home(session.user_id, agent_id)]}
        return {"conversations": [messenger.conversation(session.user_id,item["conversation_id"]) for item in messenger.inbox(session.user_id)]}

    @api.post("/conversations", status_code=201)
    async def create_conversation(body: ConversationCreate, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        conversation = messenger.home(session.user_id, body.agent_id)
        store.activity(session.user_id, "conversation.created", {"conversation_id": conversation["id"], "agent_id": body.agent_id})
        return {"conversation": conversation}

    @api.get("/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str, session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"conversation": messenger.conversation(session.user_id, conversation_id)}

    @api.get("/conversations/{conversation_id}/messages")
    async def list_messages(conversation_id: str, limit: int = Query(200, ge=1, le=1000), before_id: str | None = Query(None, max_length=128), session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"messages": messenger.list_messages(session.user_id, conversation_id, limit=limit, before_id=before_id)}

    @api.post("/conversations/{conversation_id}/messages", status_code=202)
    async def send_message(
        conversation_id: str,
        body: MessageCreate,
        session: Session = Depends(current_session),
        _: None = Depends(require_origin),
    ) -> dict[str, Any]:
        result = messenger.send(session.user_id, conversation_id, body.content, file_ids=body.file_ids,
            mention_agent_ids=getattr(body,"mention_agent_ids",[]),reply_to_id=getattr(body,"reply_to_id",None),client_request_id=getattr(body,"client_request_id",None))
        for task in result["tasks"]:
            task_manager.submit(session.user_id,task["id"])
        return result

    @api.post("/conversations/{conversation_id}/compact", status_code=202)
    async def compact_conversation(
        conversation_id: str,
        body: CompactRequest | None = None,
        session: Session = Depends(current_session),
        _: None = Depends(require_origin),
    ) -> dict[str, Any]:
        conversation = messenger.conversation(session.user_id, conversation_id)
        if callable(getattr(runtime,"compact",None)):
            await runtime.compact(conversation["id"],session.user_id,conversation["agent_id"])
        store.activity(session.user_id, "conversation.compaction_requested", {"conversation_id": conversation_id, "reason": (body.reason if body else None)})
        return {"accepted": True, "conversation_id": conversation["id"]}

    # ---------------------------------------------------------------- tasks
    @api.get("/tasks")
    async def list_tasks(limit: int = Query(100, ge=1, le=500), session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"tasks": store.list_tasks(session.user_id, limit=limit)}

    @api.get("/conversations/{conversation_id}/tasks")
    async def conversation_tasks(conversation_id: str, session: Session = Depends(current_session)) -> dict[str, Any]:
        return messenger.tasks(session.user_id,conversation_id)

    @api.get("/tasks/{task_id}")
    async def get_task(task_id: str, session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"task": store.get_task(session.user_id, task_id)}

    @api.post("/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        return {"task": await task_manager.cancel(session.user_id, task_id)}

    async def task_events_stream(request: Request, user_id: str, task_id: str, after_id: int) -> AsyncIterator[str]:
        cursor = max(0, after_id)
        while True:
            if await request.is_disconnected():
                return
            events = store.list_task_events(user_id, task_id, after_id=cursor, limit=200)
            for event in events:
                cursor = max(cursor, int(event["id"]))
                yield (
                    f"id: {event['id']}\n"
                    f"event: {event['event_type']}\n"
                    f"data: {json.dumps(event['data'], separators=(',', ':'), ensure_ascii=False)}\n\n"
                )
            task = store.get_task(user_id, task_id)
            if task["status"] in {"completed", "failed", "cancelled"}:
                # Event rows are committed before terminal status; one final
                # poll catches a terminal event that raced this read.
                final_events = store.list_task_events(user_id, task_id, after_id=cursor, limit=200)
                if not final_events:
                    return
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    @api.get("/tasks/{task_id}/events")
    async def task_events(
        request: Request,
        task_id: str,
        after_id: int = Query(0, ge=0),
        session: Session = Depends(current_session),
    ) -> StreamingResponse:
        # Ownership is checked before creating the generator so errors use the
        # normal JSON error envelope rather than appearing mid-stream.
        store.get_task(session.user_id, task_id)
        header_cursor = request.headers.get("last-event-id")
        if header_cursor and header_cursor.isdigit():
            after_id = max(after_id, int(header_cursor))
        return StreamingResponse(
            task_events_stream(request, session.user_id, task_id, after_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------- approvals
    @api.get("/tasks/{task_id}/approvals")
    async def list_approvals(task_id: str, session: Session = Depends(current_session)) -> dict[str, Any]:
        approvals = store.get_task_approvals(session.user_id, task_id)
        try:
            runtime_approvals = await optional_runtime_call("list_approvals", task_id)
            for item in runtime_approvals or []:
                data = item.data if hasattr(item, "data") else item
                approval_id = getattr(item, "approval_id", None) if hasattr(item, "approval_id") else data.get("approval_id")
                data = {
                    "approval_id": approval_id,
                    "kind": getattr(item, "kind", "approval"),
                    "description": getattr(item, "description", ""),
                    "status": getattr(item, "status", "pending"),
                    "data": data,
                }
                stored = store.upsert_approval(session.user_id, task_id, data)
                if not any(existing["id"] == stored["id"] for existing in approvals):
                    approvals.append(stored)
        except APIError as exc:
            if exc.code != "runtime_unavailable":
                raise
        return {"approvals": approvals}

    @api.post("/tasks/{task_id}/approvals/{approval_id}")
    async def decide_approval(
        task_id: str,
        approval_id: str,
        body: ApprovalDecision,
        session: Session = Depends(current_session),
        _: None = Depends(require_origin),
    ) -> dict[str, Any]:
        store.get_task(session.user_id, task_id)
        await optional_runtime_call("respond_approval", task_id, approval_id, body.decision)
        approval = store.update_approval(session.user_id, task_id, approval_id, body.decision)
        store.append_task_event(task_id, "approval.decided", {"approval_id": approval_id, "decision": body.decision})
        return {"approval": approval}

    # --------------------------------------------------------------- memory
    @api.get("/memory")
    async def list_memory(
        scope: str | None = Query(None, pattern="^(shared|private)$"),
        agent_id: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        session: Session = Depends(current_session),
    ) -> dict[str, Any]:
        if agent_id:
            store.get_agent(session.user_id, agent_id)
        return {"memory": store.list_memory(session.user_id, scope=scope, agent_id=agent_id, limit=limit)}

    @api.post("/memory", status_code=201)
    async def create_memory(body: MemoryCreate, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        values = model_values(body)
        memory = store.create_memory(session.user_id, **values)
        store.activity(session.user_id, "memory.created", {"memory_id": memory["id"], "scope": memory["scope"], "agent_id": memory.get("agent_id")})
        return {"memory": memory}

    @api.get("/memory/search")
    async def search_memory(
        q: str = Query(..., min_length=1, max_length=500),
        scope: str | None = Query(None, pattern="^(shared|private)$"),
        agent_id: str | None = None,
        limit: int = Query(20, ge=1, le=100),
        session: Session = Depends(current_session),
    ) -> dict[str, Any]:
        if agent_id:
            store.get_agent(session.user_id, agent_id)
        return {"memory": store.search_memory(session.user_id, q, scope=scope, agent_id=agent_id, limit=limit)}

    @api.get("/memory/{memory_id}")
    async def get_memory(memory_id: int, agent_id: str | None = None, session: Session = Depends(current_session)) -> dict[str, Any]:
        if agent_id:
            store.get_agent(session.user_id, agent_id)
        return {"memory": store.get_memory(session.user_id, memory_id, agent_id=agent_id)}

    @api.patch("/memory/{memory_id}")
    async def update_memory(
        memory_id: int,
        body: MemoryPatch,
        agent_id: str | None = Query(None),
        session: Session = Depends(current_session),
        _: None = Depends(require_origin),
    ) -> dict[str, Any]:
        if agent_id:
            store.get_agent(session.user_id, agent_id)
        memory = store.update_memory(session.user_id, memory_id, model_values(body, exclude_unset=True), agent_id=agent_id)
        store.activity(session.user_id, "memory.updated", {"memory_id": memory_id})
        return {"memory": memory}

    @api.delete("/memory/{memory_id}")
    async def delete_memory(
        memory_id: int,
        agent_id: str | None = Query(None),
        session: Session = Depends(current_session),
        _: None = Depends(require_origin),
    ) -> JSONResponse:
        if agent_id:
            store.get_agent(session.user_id, agent_id)
        store.delete_memory(session.user_id, memory_id, agent_id=agent_id)
        store.activity(session.user_id, "memory.deleted", {"memory_id": memory_id})
        return JSONResponse({"deleted": True})

    # ---------------------------------------------------------------- files
    @api.get("/files")
    async def list_files(agent_id: str | None = None, session: Session = Depends(current_session)) -> dict[str, Any]:
        if agent_id:
            store.get_agent(session.user_id, agent_id)
        return {"files": store.list_files(session.user_id, agent_id=agent_id)}

    @api.post("/files", status_code=201)
    async def upload_file(
        file: UploadFile = File(...),
        agent_id: str = Form(..., min_length=1, max_length=128),
        path: str | None = Form(None, max_length=1024),
        session: Session = Depends(current_session),
        _: None = Depends(require_origin),
    ) -> dict[str, Any]:
        store.get_agent(session.user_id, agent_id)
        relative_path = path or file.filename or ""
        # clean_relative_path runs before touching the filesystem.
        relative_path = workspace.clean_relative_path(relative_path)
        content_length = int(file.headers.get("content-length", "0") or 0)
        if content_length > settings.max_file_bytes + 1_048_576:
            raise APIError(413, "file_too_large", f"Files are limited to {settings.max_file_bytes} bytes")
        saved_path, size, sha256 = workspace.save_stream(
            session.user_id,
            agent_id,
            relative_path,
            file.file,
            max_bytes=settings.max_file_bytes,
        )
        try:
            item = store.create_file(
                session.user_id,
                agent_id=agent_id,
                relative_path=relative_path,
                size=size,
                sha256=sha256,
                content_type=workspace.content_type(relative_path, file.content_type),
            )
        except Exception:
            try:
                saved_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        store.activity(session.user_id, "file.created", {"file_id": item["id"], "agent_id": agent_id, "size": size})
        return {"file": item}

    @api.get("/files/{file_id}")
    async def get_file(file_id: str, session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"file": store.get_file(session.user_id, file_id)}

    @api.get("/files/{file_id}/download")
    async def download_file(file_id: str, session: Session = Depends(current_session)) -> FileResponse:
        item = store.get_file(session.user_id, file_id)
        path = workspace.path_for(session.user_id, item["agent_id"], item["relative_path"], must_exist=True)
        return FileResponse(path, media_type=item["content_type"], filename=Path(item["relative_path"]).name)

    @api.delete("/files/{file_id}")
    async def delete_file(file_id: str, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> JSONResponse:
        item = store.get_file(session.user_id, file_id)
        path = workspace.path_for(session.user_id, item["agent_id"], item["relative_path"])
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except OSError as exc:
            raise APIError(400, "file_delete_failed", "The file could not be removed") from exc
        store.delete_file(session.user_id, file_id)
        store.activity(session.user_id, "file.deleted", {"file_id": file_id})
        return JSONResponse({"deleted": True})

    @api.get("/agents/{agent_id}/skills")
    async def list_skills(agent_id: str, session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"skills": LearnedSkills(store).list(session.user_id, agent_id)}

    @api.patch("/agents/{agent_id}/skills/{skill_id}")
    async def change_skill(agent_id: str, skill_id: str, body: dict[str, Any], session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        if set(body) != {"enabled"} or not isinstance(body["enabled"], bool):
            raise APIError(422, "skill_invalid", "Provide enabled as a boolean")
        LearnedSkills(store).change(session.user_id, agent_id, skill_id, enabled=body["enabled"])
        return {"updated": True}

    @api.delete("/agents/{agent_id}/skills/{skill_id}")
    async def delete_skill(agent_id: str, skill_id: str, session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        LearnedSkills(store).change(session.user_id, agent_id, skill_id, delete=True)
        return {"deleted": True}

    # ---------------------------------------------------------- onboarding
    @api.get("/onboarding")
    async def onboarding(session: Session = Depends(current_session)) -> dict[str, Any]:
        settings_data = store.settings(session.user_id)
        return {
            "complete": bool(settings_data.get("onboarding_complete", False)),
            "steps": [
                {"id": "start-chat", "title": "Start your first chat", "description": "Choose an agent and send a message."},
                {"id": "connect-codex", "title": "Connect Codex", "description": "Connect the ChatGPT account used by the Codex app server."},
                {"id": "install-mobile", "title": "Install on iPhone", "description": "In Safari, use Share then Add to Home Screen."},
                {"id": "desktop", "title": "Optional desktop", "description": "Create an agent desktop only when you need one."},
            ],
            "runtime": runtime_status(runtime).as_dict(),
        }

    @api.post("/onboarding/complete")
    async def complete_onboarding(session: Session = Depends(current_session), _: None = Depends(require_origin)) -> dict[str, Any]:
        values = store.update_settings(session.user_id, {"onboarding_complete": True})
        store.activity(session.user_id, "onboarding.completed", {})
        return {"complete": True, "settings": values}

    @api.get("/settings")
    async def get_settings(session: Session = Depends(current_session)) -> dict[str, Any]:
        return {"settings": store.settings(session.user_id)}

    @api.patch("/settings")
    async def patch_settings(
        request: Request,
        session: Session = Depends(current_session),
        _: None = Depends(require_origin),
    ) -> dict[str, Any]:
        try:
            values = await request.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise APIError(422, "settings_invalid", "Settings must be valid JSON") from exc
        if not isinstance(values, dict) or len(values) > 50:
            raise APIError(422, "settings_invalid", "Settings must be a JSON object")
        clean: dict[str, Any] = {}
        for key, value in values.items():
            if not isinstance(key, str) or not key or len(key) > 80 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in key):
                raise APIError(422, "settings_invalid", "Setting keys contain unsupported characters")
            if len(json.dumps(value, ensure_ascii=False)) > 20_000:
                raise APIError(422, "settings_invalid", "A setting value is too large")
            clean[key] = value
        result = store.update_settings(session.user_id, clean)
        store.activity(session.user_id, "settings.updated", {"keys": list(clean)})
        return {"settings": result}

    # ------------------------------------------------------------- activity
    @api.get("/activity")
    async def activity(
        after_id: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
        session: Session = Depends(current_session),
    ) -> dict[str, Any]:
        return {"events": store.list_activity(session.user_id, after_id=after_id, limit=limit)}

    async def activity_stream(request: Request, user_id: str, after_id: int) -> AsyncIterator[str]:
        cursor = max(0, after_id)
        while True:
            if await request.is_disconnected():
                return
            events = store.list_activity(user_id, after_id=cursor, limit=200)
            for event in events:
                cursor = max(cursor, int(event["id"]))
                yield (
                    f"id: {event['id']}\n"
                    f"event: {event['event_type']}\n"
                    f"data: {json.dumps(event['payload'], separators=(',', ':'), ensure_ascii=False)}\n\n"
                )
            if not events:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    @api.get("/activity/events")
    async def activity_events(
        request: Request,
        after_id: int = Query(0, ge=0),
        session: Session = Depends(current_session),
    ) -> StreamingResponse:
        header_cursor = request.headers.get("last-event-id")
        if header_cursor and header_cursor.isdigit():
            after_id = max(after_id, int(header_cursor))
        return StreamingResponse(
            activity_stream(request, session.user_id, after_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @api.post("/bootstrap")
    async def bootstrap(session: Session = Depends(current_session), _: None = Depends(require_origin)):
        return orchestration.bootstrap(session.user_id)

    @api.get("/conversations/{conversation_id}/search")
    async def search_history(conversation_id: str,q: str = Query(...,min_length=1,max_length=500),session: Session = Depends(current_session)):
        return {"matches":history.search(session.user_id,conversation_id,q),"next_cursor":None}

    @api.get("/conversations/{conversation_id}/messages/{message_id}")
    async def exact_message(conversation_id: str,message_id: str,session: Session = Depends(current_session)):
        return {"message":history.read(session.user_id,conversation_id,[message_id])[0]}

    from .messenger_api import register_messenger_routes
    from .routines_api import register_routine_routes
    from .desktop_api import register_desktop_routes
    register_messenger_routes(api, messenger=messenger, task_manager=task_manager, current_session=current_session, require_origin=require_origin)
    register_routine_routes(api, routines=routines, current_session=current_session, require_origin=require_origin)
    register_desktop_routes(api, store=store, desktop=desktop, current_session=current_session, require_origin=require_origin)
    from .extension_api import register_extension_routes
    register_extension_routes(api, extensions=extensions, current_session=current_session, require_origin=require_origin)
    telegram_bridge.install_routes(api)
    app.include_router(api)

    # Public app shell; every private resource still requires the session API.
    static_dir = Path(os.getenv("BOT_MODE_STATIC_DIR", str(Path(__file__).resolve().parents[2] / "frontend" / "dist"))).resolve()

    @app.get("/bot", include_in_schema=False)
    async def app_redirect():
        return RedirectResponse("/bot/", status_code=307)

    @app.get("/bot/{asset_path:path}", include_in_schema=False)
    async def app_shell(asset_path: str):
        if asset_path == "api" or asset_path.startswith("api/"):
            raise HTTPException(404, "Endpoint not found")
        target = (static_dir / (asset_path or "index.html")).resolve()
        if not target.is_relative_to(static_dir):
            raise HTTPException(404, "File not found")
        if not target.is_file():
            if "." in Path(asset_path).name:
                raise HTTPException(404, "File not found")
            target = static_dir / "index.html"
        if not target.is_file():
            raise HTTPException(503, "Build the web interface before opening Bot mode")
        headers = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}
        if target.name == "sw.js":
            headers["Service-Worker-Allowed"] = "/bot/"
        if target.suffix == ".html":
            headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; frame-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'"
        return FileResponse(target, headers=headers)
    return app


app = create_app()

