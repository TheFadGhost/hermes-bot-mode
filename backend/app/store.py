"""Ownership-aware data access for the bot-mode API."""

from __future__ import annotations

import time
import uuid
import hashlib
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from .db import Database, json_dumps, json_loads
from .errors import APIError


def now() -> int:
    return int(time.time())


def new_id() -> str:
    return str(uuid.uuid4())


def _dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _agent(row: Any) -> dict[str, Any]:
    result = _dict(row)
    if result:
        result["desktop_state"] = result.get("desktop_state") or "unavailable"
    return result


def _conversation(row: Any) -> dict[str, Any]:
    return _dict(row)


def _message(row: Any) -> dict[str, Any]:
    result = _dict(row)
    if result:
        result.pop("_rowid", None)
        result["metadata"] = json_loads(result.pop("metadata_json", "{}"), {})
    return result


def _task(row: Any) -> dict[str, Any]:
    result = _dict(row)
    if result:
        if "error_code" in result or "error_message" in result:
            error_code = result.pop("error_code", None)
            error_message = result.pop("error_message", None)
            result["error"] = (
                {"code": error_code, "message": error_message}
                if error_code or error_message
                else None
            )
    return result


def _memory(row: Any) -> dict[str, Any]:
    return _dict(row)


def _file(row: Any) -> dict[str, Any]:
    result = _dict(row)
    if result:
        result["size"] = result.pop("size_bytes")
    return result


MESSAGE_COLUMNS = (
    "id, conversation_id, user_id, role, content, status, metadata_json, created_at, "
    "author_agent_id, source_task_id, request_id, origin_conversation_id, reply_to_id"
)
TASK_COLUMNS = (
    "id, user_id, conversation_id, agent_id, message_id, status, error_code, error_message, "
    "runtime_task_id, created_at, updated_at, started_at, completed_at, kind, request_id, "
    "parent_task_id, origin_conversation_id"
)


class Store:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Activity
    # ------------------------------------------------------------------
    def activity(self, user_id: str, event_type: str, payload: Mapping[str, Any] | None = None) -> int:
        with self.db.transaction() as connection:
            result = connection.execute(
                "INSERT INTO activity_events(user_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (user_id, event_type, json_dumps(dict(payload or {})), now()),
            )
            return int(result.lastrowid)

    def list_activity(self, user_id: str, *, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT id, event_type, payload_json, created_at FROM activity_events "
                "WHERE user_id = ? AND id > ? ORDER BY id LIMIT ?",
                (user_id, after_id, limit),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "event_type": row["event_type"],
                "payload": json_loads(row["payload_json"], {}),
                "created_at": int(row["created_at"]),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------
    def get_agent(self, user_id: str, agent_id: str) -> dict[str, Any]:
        with self.db.read() as connection:
            row = connection.execute(
                "SELECT id, user_id, name, instructions, model, status, avatar, color, desktop_state, desktop_id, created_at, updated_at "
                "FROM agents WHERE id = ? AND user_id = ?",
                (agent_id, user_id),
            ).fetchone()
        if row is None:
            raise APIError(404, "agent_not_found", "Agent was not found")
        return _agent(row)

    def list_agents(self, user_id: str) -> list[dict[str, Any]]:
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT id, user_id, name, instructions, model, status, avatar, color, desktop_state, desktop_id, created_at, updated_at "
                "FROM agents WHERE user_id = ? ORDER BY updated_at DESC, name COLLATE NOCASE",
                (user_id,),
            ).fetchall()
        return [_agent(row) for row in rows]

    def create_agent(
        self,
        user_id: str,
        *,
        name: str,
        instructions: str,
        model: str,
        status: str = "active",
        avatar: str | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        agent_id = new_id()
        timestamp = now()
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO agents(id, user_id, name, instructions, model, status, avatar, color, desktop_state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unavailable', ?, ?)",
                (agent_id, user_id, name, instructions, model, status, avatar, color, timestamp, timestamp),
            )
            row = connection.execute(
                "SELECT id, user_id, name, instructions, model, status, avatar, color, desktop_state, desktop_id, created_at, updated_at "
                "FROM agents WHERE id = ?",
                (agent_id,),
            ).fetchone()
        return _agent(row)

    def update_agent(self, user_id: str, agent_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        self.get_agent(user_id, agent_id)
        allowed = {key: values[key] for key in ("name", "instructions", "model", "status", "avatar", "color") if key in values}
        if not allowed:
            return self.get_agent(user_id, agent_id)
        allowed["updated_at"] = now()
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        with self.db.transaction() as connection:
            connection.execute(
                f"UPDATE agents SET {assignments} WHERE id = ? AND user_id = ?",
                (*allowed.values(), agent_id, user_id),
            )
        return self.get_agent(user_id, agent_id)

    def delete_agent(self, user_id: str, agent_id: str) -> None:
        self.get_agent(user_id, agent_id)
        with self.db.transaction() as connection:
            membership = connection.execute(
                "SELECT 1 FROM conversation_members WHERE user_id = ? AND agent_id = ? LIMIT 1",
                (user_id, agent_id),
            ).fetchone()
            if membership is not None:
                raise APIError(409, "agent_in_group", "Remove the agent from its groups before deleting it")
            connection.execute("DELETE FROM agents WHERE id = ? AND user_id = ?", (agent_id, user_id))

    # ------------------------------------------------------------------
    # Conversations and messages
    # ------------------------------------------------------------------
    def get_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        with self.db.read() as connection:
            row = connection.execute(
                "SELECT id, user_id, agent_id, title, status, created_at, updated_at, kind FROM conversations "
                "WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
        if row is None:
            raise APIError(404, "conversation_not_found", "Conversation was not found")
        return _conversation(row)

    def list_conversations(self, user_id: str, *, agent_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT id, user_id, agent_id, title, status, created_at, updated_at, kind FROM conversations "
            "WHERE user_id = ?"
        )
        params: list[Any] = [user_id]
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY updated_at DESC"
        with self.db.read() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_conversation(row) for row in rows]

    def create_conversation(self, user_id: str, agent_id: str, title: str = "") -> dict[str, Any]:
        agent = self.get_agent(user_id, agent_id)
        if agent["status"] == "archived":
            raise APIError(409, "agent_archived", "Archived agents cannot receive conversations")
        conversation_id = new_id()
        timestamp = now()
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO conversations(id, user_id, agent_id, title, kind, created_at, updated_at) VALUES (?, ?, ?, ?, 'direct', ?, ?)",
                (conversation_id, user_id, agent_id, title, timestamp, timestamp),
            )
            row = connection.execute(
                "SELECT id, user_id, agent_id, title, status, created_at, updated_at, kind FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return _conversation(row)

    def list_messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        limit: int = 200,
        before_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.get_conversation(user_id, conversation_id)
        limit = max(1, min(limit, 1000))
        with self.db.read() as connection:
            if before_id is None:
                rows = connection.execute(
                    f"SELECT {MESSAGE_COLUMNS} "
                    "FROM messages WHERE conversation_id = ? AND user_id = ? "
                    "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (conversation_id, user_id, limit),
                ).fetchall()
            else:
                cursor = connection.execute(
                    "SELECT created_at, rowid AS _rowid FROM messages "
                    "WHERE id = ? AND conversation_id = ? AND user_id = ?",
                    (before_id, conversation_id, user_id),
                ).fetchone()
                if cursor is None:
                    raise APIError(404, "message_not_found", "The message cursor was not found")
                rows = connection.execute(
                    f"SELECT {MESSAGE_COLUMNS} "
                    "FROM messages WHERE conversation_id = ? AND user_id = ? "
                    "AND (created_at < ? OR (created_at = ? AND rowid < ?)) "
                    "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (
                        conversation_id,
                        user_id,
                        cursor["created_at"],
                        cursor["created_at"],
                        cursor["_rowid"],
                        limit,
                    ),
                ).fetchall()
        # Fetch newest rows efficiently, but expose them in the same
        # chronological order as an unbounded history.
        rows.reverse()
        return [_message(row) for row in rows]

    def create_message_and_task(
        self,
        user_id: str,
        conversation_id: str,
        content: str,
        *,
        file_ids: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        timestamp = now()
        message_id = new_id()
        task_id = new_id()
        if file_ids is None:
            requested_file_ids: list[str] = []
        elif isinstance(file_ids, (list, tuple)):
            requested_file_ids = []
            seen_file_ids: set[str] = set()
            for value in file_ids:
                file_id = str(value).strip()
                if not file_id or len(file_id) > 128:
                    raise APIError(422, "file_ids_invalid", "Attached file IDs are invalid")
                if file_id not in seen_file_ids:
                    requested_file_ids.append(file_id)
                    seen_file_ids.add(file_id)
            if len(requested_file_ids) > 20:
                raise APIError(422, "too_many_files", "A message can include at most 20 files")
        else:
            raise APIError(422, "file_ids_invalid", "Attached file IDs must be a list")
        with self.db.transaction(immediate=True) as connection:
            conversation = connection.execute(
                "SELECT id, agent_id, title, status FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
            if conversation is None:
                raise APIError(404, "conversation_not_found", "Conversation was not found")
            if conversation["status"] == "archived":
                raise APIError(409, "conversation_archived", "Archived conversations cannot receive messages")
            agent = connection.execute(
                "SELECT id, status FROM agents WHERE id = ? AND user_id = ?",
                (conversation["agent_id"], user_id),
            ).fetchone()
            if agent is None:
                raise APIError(404, "agent_not_found", "Agent was not found")
            if agent["status"] == "archived":
                raise APIError(409, "agent_archived", "Archived agents cannot receive messages")
            attachments: list[dict[str, str]] = []
            for file_id in requested_file_ids:
                file = connection.execute(
                    "SELECT id, agent_id, relative_path, content_type FROM files "
                    "WHERE id = ? AND user_id = ? AND agent_id = ?",
                    (file_id, user_id, conversation["agent_id"]),
                ).fetchone()
                if file is None:
                    # Keep cross-agent and missing IDs indistinguishable at
                    # the API boundary while validating inside this atomic
                    # message/task transaction.
                    raise APIError(404, "file_not_found", "An attached file was not found")
                relative_path = str(file["relative_path"])
                attachments.append(
                    {
                        "file_id": str(file["id"]),
                        "path": relative_path,
                        "name": PurePosixPath(relative_path).name,
                        "content_type": str(file["content_type"]),
                    }
                )
            message_metadata = {"attachments": attachments} if attachments else {}
            connection.execute(
                "INSERT INTO messages(id, conversation_id, user_id, role, content, status, metadata_json, created_at) "
                "VALUES (?, ?, ?, 'user', ?, 'completed', ?, ?)",
                (message_id, conversation_id, user_id, content, json_dumps(message_metadata), timestamp),
            )
            connection.execute(
                "INSERT INTO tasks(id, user_id, conversation_id, agent_id, message_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)",
                (task_id, user_id, conversation_id, conversation["agent_id"], message_id, timestamp, timestamp),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ?, title = CASE WHEN title = '' THEN ? ELSE title END "
                "WHERE id = ?",
                (timestamp, content[:80], conversation_id),
            )
            message = connection.execute(
                f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            task = connection.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return _message(message), _task(task), self.get_agent(user_id, str(conversation["agent_id"]))

    def conversation_turn_context(
        self,
        user_id: str,
        conversation_id: str,
        limit: int = 1000,
        *,
        message_id: str | None = None,
        responding_agent_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        conversation = self.get_conversation(user_id, conversation_id)
        agent = self.get_agent(user_id, responding_agent_id or conversation["agent_id"])
        limit = max(1, min(limit, 1000))
        if message_id is None:
            messages = self.list_messages(user_id, conversation_id, limit=limit)
            return conversation, agent, messages

        # A task must see the prompt that created it and history that existed
        # at that point.  In particular, do not let a later concurrently
        # submitted user message become this turn's prompt.  Selecting the
        # target separately also guarantees it remains in the bounded window
        # when a delayed worker starts after a long conversation has grown.
        with self.db.read() as connection:
            target = connection.execute(
                f"SELECT {MESSAGE_COLUMNS}, rowid AS _rowid "
                "FROM messages WHERE id = ? AND conversation_id = ? AND user_id = ?",
                (message_id, conversation_id, user_id),
            ).fetchone()
            if target is None:
                raise APIError(404, "message_not_found", "The task's source message was not found")
            if target["role"] != "user":
                raise APIError(409, "task_message_invalid", "A task must be bound to a user message")
            preceding = connection.execute(
                f"SELECT {MESSAGE_COLUMNS} "
                "FROM messages WHERE conversation_id = ? AND user_id = ? "
                "AND (created_at < ? OR (created_at = ? AND rowid < ?)) "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (
                    conversation_id,
                    user_id,
                    target["created_at"],
                    target["created_at"],
                    target["_rowid"],
                    max(0, limit - 1),
                ),
            ).fetchall()
        preceding.reverse()
        messages = [_message(row) for row in preceding]
        messages.append(_message(target))
        return conversation, agent, messages

    # ------------------------------------------------------------------
    # Messenger aliases, exact reads, and collaboration lineage
    # ------------------------------------------------------------------
    def canonical_conversation_id(self, user_id: str, conversation_id: str) -> str:
        """Resolve a legacy direct conversation to its canonical home."""

        with self.db.read() as connection:
            row = connection.execute(
                "SELECT canonical_conversation_id FROM conversation_aliases "
                "WHERE user_id = ? AND alias_conversation_id = ?",
                (user_id, conversation_id),
            ).fetchone()
            if row is not None:
                return str(row["canonical_conversation_id"])
            exists = connection.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
        if exists is None:
            raise APIError(404, "conversation_not_found", "Conversation was not found")
        return str(conversation_id)

    def conversation_alias_ids(self, user_id: str, conversation_id: str) -> list[str]:
        canonical_id = self.canonical_conversation_id(user_id, conversation_id)
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT alias_conversation_id FROM conversation_aliases "
                "WHERE user_id = ? AND canonical_conversation_id = ? "
                "ORDER BY alias_conversation_id",
                (user_id, canonical_id),
            ).fetchall()
        ids = [str(row["alias_conversation_id"]) for row in rows]
        if canonical_id not in ids:
            ids.insert(0, canonical_id)
        return ids

    def list_messages_in_scope(
        self,
        user_id: str,
        conversation_ids: list[str] | tuple[str, ...],
        *,
        limit: int = 200,
        before_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read one stable chronological page across physical aliases."""

        ids = list(dict.fromkeys(str(item) for item in conversation_ids if str(item)))
        if not ids:
            return []
        limit = max(1, min(int(limit), 1000))
        placeholders = ",".join("?" for _ in ids)
        params: list[Any] = [user_id, *ids]
        cursor_clause = ""
        if before_id is not None:
            with self.db.read() as connection:
                cursor = connection.execute(
                    f"SELECT created_at, rowid AS _rowid FROM messages WHERE id = ? AND user_id = ? "
                    f"AND conversation_id IN ({placeholders})",
                    (before_id, user_id, *ids),
                ).fetchone()
                if cursor is None:
                    raise APIError(404, "message_not_found", "The message cursor was not found")
            cursor_clause = " AND (created_at < ? OR (created_at = ? AND rowid < ?))"
            params.extend([cursor["created_at"], cursor["created_at"], cursor["_rowid"]])
        params.extend([limit])
        with self.db.read() as connection:
            rows = connection.execute(
                f"SELECT {MESSAGE_COLUMNS}, rowid AS _rowid FROM messages "
                f"WHERE user_id = ? AND conversation_id IN ({placeholders}){cursor_clause} "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                params,
            ).fetchall()
        rows.reverse()
        return [_message(row) for row in rows]

    def get_message(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        *,
        conversation_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        ids = list(dict.fromkeys(str(item) for item in (conversation_ids or self.conversation_alias_ids(user_id, conversation_id))))
        placeholders = ",".join("?" for _ in ids)
        with self.db.read() as connection:
            row = connection.execute(
                f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE id = ? AND user_id = ? "
                f"AND conversation_id IN ({placeholders})",
                (message_id, user_id, *ids),
            ).fetchone()
        if row is None:
            raise APIError(404, "message_not_found", "Message was not found")
        return _message(row)

    # A descriptive alias used by history readers during the transition.
    exact_message = get_message

    def search_messages(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
        *,
        limit: int = 50,
        conversation_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(str(item) for item in (conversation_ids or self.conversation_alias_ids(user_id, conversation_id))))
        needle = str(query or "").strip()[:500]
        if not needle:
            return []
        placeholders = ",".join("?" for _ in ids)
        like = f"%{needle}%"
        with self.db.read() as connection:
            rows = connection.execute(
                f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE user_id = ? "
                f"AND conversation_id IN ({placeholders}) "
                "AND content LIKE ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (user_id, *ids, like, max(1, min(int(limit), 200))),
            ).fetchall()
        return [_message(row) for row in rows]

    def task_turn_context(
        self,
        user_id: str,
        task_id: str,
        limit: int = 1000,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """Resolve runtime policy from the task's responding agent."""

        task = self.get_task(user_id, task_id)
        return self.conversation_turn_context(
            user_id,
            str(task["conversation_id"]),
            limit,
            message_id=str(task["message_id"]) if task.get("message_id") else None,
            responding_agent_id=str(task["agent_id"]),
        )

    def _ensure_lineage_table(self, connection: Any) -> None:
        # scoped_tools creates this table when delegation is enabled.  Store
        # helpers also work in persistence-only deployments and tests.
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tool_task_lineage ("
            "child_task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, "
            "parent_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, "
            "user_id TEXT NOT NULL, parent_agent_id TEXT NOT NULL, child_agent_id TEXT NOT NULL, "
            "created_at INTEGER NOT NULL, UNIQUE(parent_task_id, child_task_id))"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_task_lineage_parent "
            "ON tool_task_lineage(parent_task_id, created_at)"
        )

    def attach_child(
        self,
        child_task_id: str,
        parent_task_id: str,
        origin_conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach a delegated task and inherit request/origin metadata."""

        with self.db.transaction(immediate=True) as connection:
            self._ensure_lineage_table(connection)
            child = connection.execute(
                "SELECT " + TASK_COLUMNS + " FROM tasks WHERE id = ?",
                (child_task_id,),
            ).fetchone()
            parent = connection.execute(
                "SELECT " + TASK_COLUMNS + " FROM tasks WHERE id = ?",
                (parent_task_id,),
            ).fetchone()
            if child is None or parent is None or str(child["user_id"]) != str(parent["user_id"]):
                raise APIError(404, "task_not_found", "The parent or child task was not found")
            if str(child_task_id) == str(parent_task_id):
                raise APIError(409, "lineage_cycle", "A task cannot be its own child")
            cycle = connection.execute(
                "WITH RECURSIVE ancestors(task_id) AS ("
                "SELECT parent_task_id FROM tool_task_lineage WHERE child_task_id = ? "
                "UNION ALL SELECT l.parent_task_id FROM tool_task_lineage l "
                "JOIN ancestors a ON l.child_task_id = a.task_id) "
                "SELECT 1 FROM ancestors WHERE task_id = ? LIMIT 1",
                (parent_task_id, child_task_id),
            ).fetchone()
            if cycle is not None:
                raise APIError(409, "lineage_cycle", "Delegation would create a cycle")
            existing = connection.execute(
                "SELECT parent_task_id, user_id FROM tool_task_lineage WHERE child_task_id = ?",
                (child_task_id,),
            ).fetchone()
            if existing is not None and str(existing["parent_task_id"]) != str(parent_task_id):
                raise APIError(409, "lineage_conflict", "The child task already has a different parent")
            connection.execute(
                "INSERT OR IGNORE INTO tool_task_lineage(child_task_id, parent_task_id, user_id, parent_agent_id, child_agent_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    child_task_id,
                    parent_task_id,
                    parent["user_id"],
                    parent["agent_id"],
                    child["agent_id"],
                    now(),
                ),
            )
            origin = origin_conversation_id or parent["origin_conversation_id"] or parent["conversation_id"]
            alias = connection.execute(
                "SELECT canonical_conversation_id FROM conversation_aliases WHERE user_id = ? AND alias_conversation_id = ?",
                (parent["user_id"], origin),
            ).fetchone()
            if alias is not None:
                origin = alias["canonical_conversation_id"]
            connection.execute(
                "UPDATE tasks SET parent_task_id = ?, request_id = COALESCE(request_id, ?), "
                "origin_conversation_id = COALESCE(origin_conversation_id, ?) WHERE id = ?",
                (parent_task_id, parent["request_id"], origin, child_task_id),
            )
            row = connection.execute(
                "SELECT " + TASK_COLUMNS + " FROM tasks WHERE id = ?",
                (child_task_id,),
            ).fetchone()
        return _task(row)

    def append_collaboration_message(
        self,
        user_id: str,
        origin_conversation_id: str,
        author_agent_id: str,
        text: str,
        source_task_id: str,
        request_id: str | None = None,
    ) -> str:
        """Relay a helper result into its originating chat exactly once."""

        timestamp = now()
        with self.db.transaction(immediate=True) as connection:
            origin_alias = connection.execute(
                "SELECT canonical_conversation_id FROM conversation_aliases "
                "WHERE user_id = ? AND alias_conversation_id = ?",
                (user_id, origin_conversation_id),
            ).fetchone()
            canonical_origin = str(origin_alias["canonical_conversation_id"]) if origin_alias else origin_conversation_id
            origin = connection.execute(
                "SELECT id, status FROM conversations WHERE id = ? AND user_id = ?",
                (canonical_origin, user_id),
            ).fetchone()
            if origin is None:
                raise APIError(404, "conversation_not_found", "The originating conversation was not found")
            source = connection.execute(
                "SELECT " + TASK_COLUMNS + " FROM tasks WHERE id = ? AND user_id = ?",
                (source_task_id, user_id),
            ).fetchone()
            if source is None:
                raise APIError(404, "task_not_found", "The source task was not found")
            if str(source["agent_id"]) != str(author_agent_id):
                raise APIError(403, "task_author_forbidden", "The source task does not belong to this author")
            resolved_request = str(request_id or source["request_id"] or f"task:{source_task_id}")
            existing = connection.execute(
                "SELECT message_id FROM message_collaboration_links WHERE user_id = ? "
                "AND origin_conversation_id = ? AND source_task_id = ? AND request_id = ?",
                (user_id, canonical_origin, source_task_id, resolved_request),
            ).fetchone()
            if existing is not None:
                return str(existing["message_id"])
            message_id = new_id()
            metadata = {
                "collaboration": True,
                "author_agent_id": author_agent_id,
                "source_task_id": source_task_id,
                "request_id": resolved_request,
                "origin_conversation_id": canonical_origin,
            }
            connection.execute(
                "INSERT INTO messages(id, conversation_id, user_id, role, content, status, metadata_json, created_at, "
                "author_agent_id, source_task_id, request_id, origin_conversation_id) "
                "VALUES (?, ?, ?, 'assistant', ?, 'completed', ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    canonical_origin,
                    user_id,
                    str(text),
                    json_dumps(metadata),
                    timestamp,
                    author_agent_id,
                    source_task_id,
                    resolved_request,
                    canonical_origin,
                ),
            )
            connection.execute(
                "INSERT INTO message_collaboration_links(user_id, origin_conversation_id, source_task_id, request_id, message_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, canonical_origin, source_task_id, resolved_request, message_id, timestamp),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (timestamp, canonical_origin),
            )
        return message_id

    # ------------------------------------------------------------------
    # Tasks and durable events
    # ------------------------------------------------------------------
    def get_task(self, user_id: str, task_id: str) -> dict[str, Any]:
        with self.db.read() as connection:
            row = connection.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks "
                "WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            ).fetchone()
        if row is None:
            raise APIError(404, "task_not_found", "Task was not found")
        return _task(row)

    def list_tasks(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self.db.read() as connection:
            rows = connection.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks "
                "WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [_task(row) for row in rows]

    def mark_restarted_tasks_failed(self) -> int:
        timestamp = now()
        with self.db.transaction(immediate=True) as connection:
            result = connection.execute(
                "UPDATE tasks SET status = 'failed', error_code = 'runtime_restarted', "
                "error_message = 'Task stopped when the bot-mode service restarted', updated_at = ?, completed_at = ? "
                "WHERE status IN ('queued', 'running')",
                (timestamp, timestamp),
            )
            return result.rowcount

    def mark_task_running(self, task_id: str) -> bool:
        timestamp = now()
        with self.db.transaction() as connection:
            result = connection.execute(
                "UPDATE tasks SET status = 'running', started_at = ?, updated_at = ? WHERE id = ? AND status = 'queued'",
                (timestamp, timestamp, task_id),
            )
        return result.rowcount == 1

    def cancel_task(
        self,
        task_id: str,
        *,
        error_code: str = "cancelled",
        error_message: str = "Task cancelled",
    ) -> bool:
        """Atomically cancel a task that has not reached a terminal state."""

        timestamp = now()
        with self.db.transaction() as connection:
            result = connection.execute(
                "UPDATE tasks SET status = 'cancelled', error_code = ?, error_message = ?, "
                "updated_at = ?, completed_at = ? WHERE id = ? AND status IN ('queued', 'running')",
                (error_code, error_message, timestamp, timestamp, task_id),
            )
        return result.rowcount == 1

    def finish_task(
        self,
        task_id: str,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        timestamp = now()
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, error_code = ?, error_message = ?, updated_at = ?, completed_at = ? "
                "WHERE id = ?",
                (status, error_code, error_message, timestamp, timestamp, task_id),
            )

    def append_task_event(self, task_id: str, event_type: str, data: Mapping[str, Any] | None = None) -> int:
        with self.db.transaction() as connection:
            result = connection.execute(
                "INSERT INTO task_events(task_id, event_type, data_json, created_at) VALUES (?, ?, ?, ?)",
                (task_id, event_type, json_dumps(dict(data or {})), now()),
            )
            return int(result.lastrowid)

    def list_task_events(self, user_id: str, task_id: str, *, after_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        self.get_task(user_id, task_id)
        limit = max(1, min(limit, 1000))
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT e.id, e.task_id, e.event_type, e.data_json, e.created_at FROM task_events e "
                "JOIN tasks t ON t.id = e.task_id WHERE e.task_id = ? AND t.user_id = ? AND e.id > ? "
                "ORDER BY e.id LIMIT ?",
                (task_id, user_id, after_id, limit),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "task_id": row["task_id"],
                "event_type": row["event_type"],
                "data": json_loads(row["data_json"], {}),
                "created_at": int(row["created_at"]),
            }
            for row in rows
        ]

    def append_assistant_message(
        self,
        user_id: str,
        task_id: str,
        content: str,
        *,
        status: str = "completed",
        metadata: Mapping[str, Any] | None = None,
        author_agent_id: str | None = None,
        source_task_id: str | None = None,
        request_id: str | None = None,
        origin_conversation_id: str | None = None,
        reply_to_id: str | None = None,
    ) -> str:
        message_id = new_id()
        timestamp = now()
        with self.db.transaction(immediate=True) as connection:
            task = connection.execute(
                "SELECT conversation_id, agent_id, request_id, origin_conversation_id FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            ).fetchone()
            if task is None:
                raise APIError(404, "task_not_found", "Task was not found")
            resolved_author = author_agent_id or str(task["agent_id"])
            resolved_source_task = source_task_id or task_id
            resolved_request = request_id or task["request_id"]
            resolved_origin = origin_conversation_id or task["origin_conversation_id"] or str(task["conversation_id"])
            enriched_metadata = dict(metadata or {})
            # Keep these keys in the JSON object for callers that only know the
            # old Store shape, while the columns below make them queryable.
            enriched_metadata.update(
                {
                    key: value
                    for key, value in {
                        "author_agent_id": resolved_author,
                        "source_task_id": resolved_source_task,
                        "request_id": resolved_request,
                        "origin_conversation_id": resolved_origin,
                        "reply_to_id": reply_to_id,
                    }.items()
                    if value is not None
                }
            )
            connection.execute(
                "INSERT INTO messages(id, conversation_id, user_id, role, content, status, metadata_json, created_at, "
                "author_agent_id, source_task_id, request_id, origin_conversation_id, reply_to_id) "
                "VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    task["conversation_id"],
                    user_id,
                    content,
                    status,
                    json_dumps(enriched_metadata),
                    timestamp,
                    resolved_author,
                    resolved_source_task,
                    resolved_request,
                    resolved_origin,
                    reply_to_id,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (timestamp, task["conversation_id"]),
            )
        return message_id

    def get_task_approvals(self, user_id: str, task_id: str) -> list[dict[str, Any]]:
        self.get_task(user_id, task_id)
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT id, task_id, kind, description, status, data_json, created_at, updated_at FROM approvals "
                "WHERE task_id = ? AND user_id = ? ORDER BY created_at",
                (task_id, user_id),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "kind": row["kind"],
                "description": row["description"],
                "status": row["status"],
                "data": json_loads(row["data_json"], {}),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def upsert_approval(self, user_id: str, task_id: str, approval: Mapping[str, Any]) -> dict[str, Any]:
        self.get_task(user_id, task_id)
        approval_id = str(approval.get("approval_id") or approval.get("id") or new_id())
        timestamp = now()
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO approvals(id, task_id, user_id, kind, description, status, data_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, description=excluded.description, "
                "status=excluded.status, data_json=excluded.data_json, updated_at=excluded.updated_at",
                (
                    approval_id,
                    task_id,
                    user_id,
                    str(approval.get("kind", "approval")),
                    str(approval.get("description", "")),
                    str(approval.get("status", "pending")),
                    json_dumps(dict(approval.get("data") or {})),
                    timestamp,
                    timestamp,
                ),
            )
        return next(item for item in self.get_task_approvals(user_id, task_id) if item["id"] == approval_id)

    def update_approval(self, user_id: str, task_id: str, approval_id: str, decision: str) -> dict[str, Any]:
        self.get_task(user_id, task_id)
        with self.db.transaction() as connection:
            result = connection.execute(
                "UPDATE approvals SET status = ?, updated_at = ? WHERE id = ? AND task_id = ? AND user_id = ?",
                (decision, now(), approval_id, task_id, user_id),
            )
            if result.rowcount != 1:
                raise APIError(404, "approval_not_found", "Approval was not found")
        return next(item for item in self.get_task_approvals(user_id, task_id) if item["id"] == approval_id)

    # ------------------------------------------------------------------
    # Memory with shared/private ACL and FTS
    # ------------------------------------------------------------------
    def _memory_acl(self, user_id: str, scope: str | None, agent_id: str | None) -> tuple[str, list[Any]]:
        clauses = ["m.user_id = ?", "m.deleted_at IS NULL"]
        params: list[Any] = [user_id]
        if scope:
            clauses.append("m.scope = ?")
            params.append(scope)
        if agent_id:
            clauses.append("(m.scope = 'shared' OR m.agent_id = ?)")
            params.append(agent_id)
        else:
            # A caller without an agent context may see shared memory only.
            clauses.append("m.scope = 'shared'")
        return " AND ".join(clauses), params

    def get_memory(self, user_id: str, memory_id: int, *, agent_id: str | None = None) -> dict[str, Any]:
        clauses, params = self._memory_acl(user_id, None, agent_id)
        params.append(memory_id)
        with self.db.read() as connection:
            row = connection.execute(
                "SELECT m.id, m.user_id, m.agent_id, m.scope, m.memory_key, m.content, m.source, m.confidence, "
                "m.supersedes_id, m.created_at, m.updated_at FROM memory_entries m "
                f"WHERE {clauses} AND m.id = ?",
                params,
            ).fetchone()
        if row is None:
            raise APIError(404, "memory_not_found", "Memory entry was not found")
        return _memory(row)

    def list_memory(
        self, user_id: str, *, scope: str | None = None, agent_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        clauses, params = self._memory_acl(user_id, scope, agent_id)
        clauses += self._active_memory_clause()
        limit = max(1, min(limit, 500))
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT m.id, m.user_id, m.agent_id, m.scope, m.memory_key, m.content, m.source, m.confidence, "
                "m.supersedes_id, m.created_at, m.updated_at FROM memory_entries m "
                f"WHERE {clauses} ORDER BY m.updated_at DESC, m.id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [_memory(row) for row in rows]

    @staticmethod
    def _active_memory_clause() -> str:
        # Corrections retire facts only within exactly the same visibility scope.
        return (" AND NOT EXISTS (SELECT 1 FROM memory_entries replacement "
                "WHERE replacement.supersedes_id=m.id AND replacement.deleted_at IS NULL "
                "AND replacement.user_id=m.user_id AND replacement.scope=m.scope "
                "AND replacement.agent_id IS m.agent_id)")

    @staticmethod
    def _validate_memory_replacement(connection: Any, user_id: str, scope: str,
                                     agent_id: str | None, supersedes_id: int | None,
                                     memory_id: int | None = None) -> None:
        if supersedes_id is None:
            return
        seen = {memory_id} if memory_id is not None else set()
        candidate = supersedes_id
        while candidate is not None:
            if candidate in seen:
                raise APIError(422, "memory_cycle", "A correction cannot supersede itself or create a cycle")
            seen.add(candidate)
            row = connection.execute(
                "SELECT user_id,scope,agent_id,supersedes_id,deleted_at FROM memory_entries WHERE id=?",
                (candidate,),
            ).fetchone()
            if (not row or row['user_id'] != user_id or row['scope'] != scope
                    or row['agent_id'] != agent_id or (candidate == supersedes_id and row['deleted_at'] is not None)):
                raise APIError(422, "memory_scope", "A correction must reference a fact in the same memory scope")
            candidate = row['supersedes_id']

    def create_memory(
        self,
        user_id: str,
        *,
        scope: str,
        content: str,
        agent_id: str | None,
        memory_key: str,
        source: str,
        confidence: float,
        supersedes_id: int | None,
    ) -> dict[str, Any]:
        if scope == "private" and not agent_id:
            raise APIError(422, "private_memory_requires_agent", "Private memory requires an agent")
        if agent_id:
            self.get_agent(user_id, agent_id)
        timestamp = now()
        with self.db.transaction(immediate=True) as connection:
            self._validate_memory_replacement(connection, user_id, scope,
                                              agent_id if scope == "private" else None, supersedes_id)
            result = connection.execute(
                "INSERT INTO memory_entries(user_id, agent_id, scope, memory_key, content, source, confidence, supersedes_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    agent_id if scope == "private" else None,
                    scope,
                    memory_key,
                    content,
                    source,
                    confidence,
                    supersedes_id,
                    timestamp,
                    timestamp,
                ),
            )
            memory_id = int(result.lastrowid)
        return self.get_memory(user_id, memory_id, agent_id=agent_id if scope == "private" else None)

    def update_memory(self, user_id: str, memory_id: int, values: Mapping[str, Any], *, agent_id: str | None = None) -> dict[str, Any]:
        current = self.get_memory(user_id, memory_id, agent_id=agent_id)
        allowed = {
            key: values[key]
            for key in ("memory_key", "content", "source", "confidence", "supersedes_id")
            if key in values
        }
        if not allowed:
            return current
        allowed["updated_at"] = now()
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        with self.db.transaction(immediate=True) as connection:
            if "supersedes_id" in allowed:
                self._validate_memory_replacement(connection, user_id, current['scope'],
                                                  current.get('agent_id'), allowed['supersedes_id'], memory_id)
            connection.execute(
                f"UPDATE memory_entries SET {assignments} WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                (*allowed.values(), memory_id, user_id),
            )
        return self.get_memory(user_id, memory_id, agent_id=current.get("agent_id"))

    def delete_memory(self, user_id: str, memory_id: int, *, agent_id: str | None = None) -> None:
        self.get_memory(user_id, memory_id, agent_id=agent_id)
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE memory_entries SET deleted_at = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (now(), now(), memory_id, user_id),
            )

    def search_memory(
        self,
        user_id: str,
        query: str,
        *,
        scope: str | None = None,
        agent_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses, params = self._memory_acl(user_id, scope, agent_id)
        clauses += self._active_memory_clause()
        limit = max(1, min(limit, 100))
        # Natural chat requests contain question words absent from the fact itself.
        # Keep useful terms bounded and let FTS rank their overlap.
        from .history import search_terms
        terms = search_terms(query[:1000])
        if not terms:
            return []
        with self.db.read() as connection:
            if self.db.fts_available and terms:
                # Quoting each token prevents MATCH operators supplied by a
                # user from changing the FTS expression.
                match_query = " OR ".join('"' + term.replace('"', "") + '"' for term in terms)
                rows = connection.execute(
                    "SELECT m.id, m.user_id, m.agent_id, m.scope, m.memory_key, m.content, m.source, m.confidence, "
                    "m.supersedes_id, m.created_at, m.updated_at, bm25(memory_fts) AS rank FROM memory_fts "
                    "JOIN memory_entries m ON m.id = memory_fts.rowid "
                    f"WHERE memory_fts MATCH ? AND {clauses} ORDER BY rank, m.updated_at DESC, m.id DESC LIMIT ?",
                    (match_query, *params, limit),
                ).fetchall()
            else:
                matches = ["(lower(m.content) LIKE ? ESCAPE '\\' OR lower(m.memory_key) LIKE ? ESCAPE '\\')" for _ in terms]
                patterns = ["%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for term in terms]
                match_params = [pattern for pattern in patterns for _ in range(2)]
                relevance = " + ".join(f"CASE WHEN {match} THEN 1 ELSE 0 END" for match in matches)
                rows = connection.execute(
                    "SELECT m.id, m.user_id, m.agent_id, m.scope, m.memory_key, m.content, m.source, m.confidence, "
                    "m.supersedes_id, m.created_at, m.updated_at FROM memory_entries m "
                    f"WHERE ({' OR '.join(matches)}) AND {clauses} "
                    f"ORDER BY ({relevance}) DESC, m.updated_at DESC, m.id DESC LIMIT ?",
                    (*match_params, *params, *match_params, limit),
                ).fetchall()
        return [_memory(row) for row in rows]

    # ------------------------------------------------------------------
    # Files and settings
    # ------------------------------------------------------------------
    def list_files(self, user_id: str, *, agent_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, user_id, agent_id, relative_path, size_bytes, sha256, content_type, created_at, updated_at FROM files WHERE user_id = ?"
        params: list[Any] = [user_id]
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY updated_at DESC, relative_path"
        with self.db.read() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_file(row) for row in rows]

    def get_file(self, user_id: str, file_id: str) -> dict[str, Any]:
        with self.db.read() as connection:
            row = connection.execute(
                "SELECT id, user_id, agent_id, relative_path, size_bytes, sha256, content_type, created_at, updated_at "
                "FROM files WHERE id = ? AND user_id = ?",
                (file_id, user_id),
            ).fetchone()
        if row is None:
            raise APIError(404, "file_not_found", "File was not found")
        return _file(row)

    def create_file(self, user_id: str, *, agent_id: str, relative_path: str, size: int, sha256: str, content_type: str) -> dict[str, Any]:
        self.get_agent(user_id, agent_id)
        file_id = new_id()
        timestamp = now()
        try:
            with self.db.transaction() as connection:
                connection.execute(
                    "INSERT INTO files(id, user_id, agent_id, relative_path, size_bytes, sha256, content_type, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (file_id, user_id, agent_id, relative_path, size, sha256, content_type[:255], timestamp, timestamp),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise APIError(409, "file_exists", "A file already exists at that path") from exc
            raise
        return self.get_file(user_id, file_id)

    def delete_file(self, user_id: str, file_id: str) -> dict[str, Any]:
        item = self.get_file(user_id, file_id)
        with self.db.transaction() as connection:
            connection.execute("DELETE FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
        return item

    def get_setting(self, user_id: str, key: str) -> Any:
        with self.db.read() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE user_id = ? AND setting_key = ?", (user_id, key)
            ).fetchone()
        return json_loads(row["value_json"], None) if row else None

    def settings(self, user_id: str) -> dict[str, Any]:
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT setting_key, value_json FROM settings WHERE user_id = ? ORDER BY setting_key", (user_id,)
            ).fetchall()
        return {row["setting_key"]: json_loads(row["value_json"], None) for row in rows}

    def update_settings(self, user_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        timestamp = now()
        with self.db.transaction() as connection:
            for key, value in values.items():
                connection.execute(
                    "INSERT INTO settings(user_id, setting_key, value_json, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(user_id, setting_key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                    (user_id, key, json_dumps(value), timestamp),
                )
        return self.settings(user_id)

