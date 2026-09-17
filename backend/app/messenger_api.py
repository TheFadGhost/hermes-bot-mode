"""FastAPI routes for the additive messenger API.

``register_messenger_routes`` accepts the existing application's router and
dependencies so the legacy handlers can be migrated one route at a time.
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, Depends, Query

from .errors import APIError
from .messenger import Messenger
from .schemas import FileGrantCreate, GroupCreate, GroupPatch, ReadMark, model_values
from .store import Store


def _user_id(session: Any) -> str:
    value = getattr(session, "user_id", None)
    if value is None and isinstance(session, dict):
        value = session.get("user_id")
    return str(value)


def register_messenger_routes(
    api: APIRouter,
    store: Store | None = None,
    workspace: Any | None = None,
    task_manager: Any | None = None,
    current_session: Any | None = None,
    require_origin: Any | None = None,
    *,
    messenger: Messenger | None = None,
) -> Messenger:
    """Register messenger endpoints on ``api`` and return the service.

    The ``workspace`` argument is retained for the parent application seam;
    this persistence layer does not need to access files on disk.
    """

    del workspace
    if messenger is None:
        if store is None:
            raise TypeError("register_messenger_routes requires store or messenger")
        messenger = Messenger(store)
    elif store is None:
        store = messenger.store
    if current_session is None or require_origin is None:
        raise TypeError("register_messenger_routes requires session and origin dependencies")

    def submit(user_id: str, task: dict[str, Any]) -> None:
        if task_manager is None or not callable(getattr(task_manager, "submit", None)):
            return
        task_manager.submit(user_id, str(task["id"]))

    @api.get("/inbox")
    async def inbox(
        include_archived: bool = Query(False),
        session: Any = Depends(current_session),
    ) -> dict[str, Any]:
        return {"items": messenger.inbox(_user_id(session), include_archived=include_archived)}

    @api.get("/search")
    async def search_workspace(
        q: str = Query(..., min_length=1, max_length=500),
        session: Any = Depends(current_session),
    ) -> dict[str, Any]:
        user_id = _user_id(session)
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        # Inbox membership excludes isolated helper transcripts; each scoped
        # search includes authorized legacy aliases of the canonical home.
        for entry in messenger.inbox(user_id):
            conversation_id = str(entry["conversation_id"])
            for item in messenger.search(user_id, conversation_id, q, limit=30):
                message_id = str(item["id"])
                if message_id in seen:
                    continue
                seen.add(message_id)
                matches.append({"id": message_id, "message_id": message_id,
                    "conversation_id": conversation_id, "name": entry.get("name") or entry.get("title") or "Chat",
                    "kind": "message", "snippet": str(item.get("content", ""))[:700],
                    "created_at": item.get("created_at")})
        matches.sort(key=lambda item: (int(item.get("created_at") or 0), item["id"]), reverse=True)
        return {"matches": matches[:30]}

    @api.get("/messages/{message_id}")
    async def exact_workspace_message(message_id: str, session: Any = Depends(current_session)) -> dict[str, Any]:
        user_id = _user_id(session)
        # Resolve physical context only after owner filtering; unknown and
        # another account's IDs have the same not-found response.
        with store.db.read() as connection:
            row = connection.execute("SELECT conversation_id FROM messages WHERE id=? AND user_id=?", (message_id, user_id)).fetchone()
        if row is None:
            raise APIError(404, "message_not_found", "Message was not found")
        physical_id = str(row["conversation_id"])
        message = store.get_message(user_id, physical_id, message_id, conversation_ids=[physical_id])
        canonical = messenger.conversation(user_id, physical_id)
        return {"message": {**message, "conversation_id": canonical["id"]}}

    @api.get("/agents/{agent_id}/home")
    async def agent_home(agent_id: str, session: Any = Depends(current_session)) -> dict[str, Any]:
        return {"conversation": messenger.home(_user_id(session), agent_id)}

    @api.post("/conversations/{conversation_id}/read")
    async def mark_messenger_read(
        conversation_id: str,
        body: ReadMark,
        session: Any = Depends(current_session),
        _: Any = Depends(require_origin),
    ) -> dict[str, Any]:
        return {"conversation": messenger.mark_read(_user_id(session), conversation_id, body.through_message_id)}

    @api.post("/conversations/{conversation_id}/archive")
    async def archive_messenger_conversation(
        conversation_id: str,
        session: Any = Depends(current_session),
        _: Any = Depends(require_origin),
    ) -> dict[str, Any]:
        return {"conversation": messenger.archive_conversation(_user_id(session), conversation_id)}

    @api.post("/conversations/{conversation_id}/restore")
    async def restore_messenger_conversation(
        conversation_id: str,
        session: Any = Depends(current_session),
        _: Any = Depends(require_origin),
    ) -> dict[str, Any]:
        return {"conversation": messenger.restore_conversation(_user_id(session), conversation_id)}

    @api.post("/conversations/{conversation_id}/pin")
    async def pin_messenger_conversation(
        conversation_id: str,
        pinned: bool = Query(True),
        session: Any = Depends(current_session),
        _: Any = Depends(require_origin),
    ) -> dict[str, Any]:
        return {"conversation": messenger.set_pinned(_user_id(session), conversation_id, pinned)}

    @api.post("/conversations/{conversation_id}/requests/{request_id}/cancel")
    async def cancel_messenger_request(
        conversation_id: str,
        request_id: str,
        session: Any = Depends(current_session),
        _: Any = Depends(require_origin),
    ) -> dict[str, Any]:
        user_id = _user_id(session)
        canceller = getattr(task_manager, "cancel_request", None)
        if callable(canceller):
            result = canceller(user_id, conversation_id, request_id)
            if inspect.isawaitable(result):
                result = await result
            return {"tasks": result.get("tasks", result) if isinstance(result, dict) else result}
        # A persistence-only integration can still cancel every known task;
        # the full TaskManager path supplies runtime interruption and tree
        # propagation when available.
        task_ids = messenger.request_task_ids(user_id, conversation_id, request_id)
        tasks: list[dict[str, Any]] = []
        for task_id in task_ids:
            if callable(getattr(task_manager, "cancel", None)):
                result = task_manager.cancel(user_id, task_id)
                if inspect.isawaitable(result):
                    result = await result
                tasks.append(result)
            else:
                task = store.get_task(user_id, task_id)
                if task["status"] in {"queued", "running"}:
                    store.cancel_task(task_id)
                tasks.append(store.get_task(user_id, task_id))
        return {"tasks": tasks}

    @api.post("/groups", status_code=201)
    async def create_messenger_group(
        body: GroupCreate,
        session: Any = Depends(current_session),
        _: Any = Depends(require_origin),
    ) -> dict[str, Any]:
        return {"conversation": messenger.create_group(_user_id(session), body.name, body.agent_ids, body.coordinator_id)}

    @api.get("/groups/{conversation_id}")
    async def get_messenger_group(conversation_id: str, session: Any = Depends(current_session)) -> dict[str, Any]:
        return {"conversation": messenger.conversation(_user_id(session), conversation_id)}

    @api.patch("/groups/{conversation_id}")
    async def update_messenger_group(
        conversation_id: str,
        body: GroupPatch,
        session: Any = Depends(current_session),
        _: Any = Depends(require_origin),
    ) -> dict[str, Any]:
        values = model_values(body, exclude_unset=True)
        return {"conversation": messenger.update_group(_user_id(session), conversation_id, **values)}

    @api.get("/conversations/{conversation_id}/files")
    async def list_messenger_grants(conversation_id: str, session: Any = Depends(current_session)) -> dict[str, Any]:
        return {"files": messenger.list_granted_files(_user_id(session), conversation_id)}

    @api.post("/conversations/{conversation_id}/files")
    async def grant_messenger_files(
        conversation_id: str,
        body: FileGrantCreate,
        session: Any = Depends(current_session),
        _: Any = Depends(require_origin),
    ) -> dict[str, Any]:
        return {"files": messenger.grant_files(_user_id(session), conversation_id, body.file_ids, granted_by_agent_id=body.granted_by_agent_id)}

    return messenger

