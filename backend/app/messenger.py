"""Canonical conversations, groups, inbox state, and message fanout.

The legacy Store keeps the physical conversation/message/task tables used by
the runtime.  This service adds the public messenger model around those rows:
direct aliases aggregate into one canonical home, groups retain membership
and grants, and one request transaction owns its message and responder tasks.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from .errors import APIError
from .store import MESSAGE_COLUMNS, TASK_COLUMNS, Store, _agent, _file, _message, _task, now, new_id


MAX_GROUP_MEMBERS = 6
MIN_GROUP_MEMBERS = 2
MAX_MESSAGE_FILES = 20
MAX_MESSAGE_FANOUT = 6


def _clean_id(value: Any, *, field: str = "id") -> str:
    result = str(value or "").strip()
    if not result or len(result) > 128:
        raise APIError(422, f"{field}_invalid", f"{field} is invalid")
    return result


def _ids(values: Sequence[Any] | None, *, field: str, maximum: int) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        raise APIError(422, f"{field}_invalid", f"{field} must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_id(value, field=field)
        if item in seen:
            raise APIError(422, f"{field}_duplicate", f"{field} contains a duplicate value")
        seen.add(item)
        result.append(item)
    if len(result) > maximum:
        raise APIError(422, f"too_many_{field}", f"Too many {field}")
    return result


def _dedupe_file_ids(values: Sequence[Any] | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        raise APIError(422, "file_ids_invalid", "Attached file IDs must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_id(value, field="file_ids")
        if item not in seen:
            seen.add(item)
            result.append(item)
    if len(result) > MAX_MESSAGE_FILES:
        raise APIError(422, "too_many_files", "A message can include at most 20 files")
    return result


def _public_agent(row: Mapping[str, Any]) -> dict[str, Any]:
    # Instructions are intentionally omitted from messenger identity objects.
    return {
        key: row.get(key)
        for key in ("id", "name", "status", "model", "avatar", "color", "desktop_state", "desktop_id")
        if key in row
    }


class Messenger:
    """Public messenger operations backed by a legacy-compatible Store."""

    def __init__(self, store: Store):
        self.store = store
        # The delegation bridge creates this table lazily.  Creating it here
        # makes lineage-aware alias filtering and request lookup deterministic
        # for persistence-only callers as well.
        with self.store.db.transaction() as connection:
            self.store._ensure_lineage_table(connection)

    # ------------------------------------------------------------------
    # Internal row and scope helpers
    # ------------------------------------------------------------------
    def _direct_candidates(self, connection: Any, user_id: str, agent_id: str) -> list[Any]:
        return connection.execute(
            "SELECT c.id, c.agent_id, c.title, c.status, c.created_at, c.updated_at, c.kind "
            "FROM conversations c WHERE c.user_id = ? AND c.agent_id = ? "
            "AND COALESCE(c.kind, 'direct') = 'direct' "
            "AND NOT EXISTS (SELECT 1 FROM conversation_groups g WHERE g.conversation_id = c.id) "
            "AND NOT EXISTS (SELECT 1 FROM tasks t JOIN tool_task_lineage l ON l.child_task_id = t.id "
            "WHERE t.conversation_id = c.id AND t.user_id = c.user_id) "
            "ORDER BY c.created_at ASC, c.rowid ASC",
            (user_id, agent_id),
        ).fetchall()

    def _ensure_state(self, connection: Any, user_id: str, conversation_id: str, *, archived: bool = False) -> None:
        timestamp = now()
        connection.execute(
            "INSERT OR IGNORE INTO conversation_inbox(user_id, conversation_id, archived, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, conversation_id, 1 if archived else 0, timestamp),
        )

    def _ensure_alias(self, connection: Any, user_id: str, alias_id: str, canonical_id: str, kind: str = "direct") -> None:
        connection.execute(
            "INSERT OR IGNORE INTO conversation_aliases(user_id, alias_conversation_id, canonical_conversation_id, alias_kind, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, alias_id, canonical_id, kind, now()),
        )

    def _home_id_tx(self, connection: Any, user_id: str, agent_id: str, *, create: bool = True) -> str:
        row = connection.execute(
            "SELECT conversation_id FROM conversation_homes WHERE user_id = ? AND agent_id = ?",
            (user_id, agent_id),
        ).fetchone()
        if row is not None:
            canonical_id = str(row["conversation_id"])
            # A legacy conversation may have been created after the home was
            # first materialized.  Reconcile aliases on each home lookup so
            # pagination/search never silently drops that physical history.
            for candidate in self._direct_candidates(connection, user_id, agent_id):
                self._ensure_alias(connection, user_id, str(candidate["id"]), canonical_id)
            self._ensure_alias(connection, user_id, canonical_id, canonical_id)
            self._ensure_state(connection, user_id, canonical_id)
            return canonical_id
        agent = connection.execute(
            "SELECT id, status FROM agents WHERE id = ? AND user_id = ?",
            (agent_id, user_id),
        ).fetchone()
        if agent is None:
            raise APIError(404, "agent_not_found", "Agent was not found")
        candidates = self._direct_candidates(connection, user_id, agent_id)
        if candidates:
            canonical_id = str(candidates[0]["id"])
        elif create:
            canonical_id = new_id()
            timestamp = now()
            connection.execute(
                "INSERT INTO conversations(id, user_id, agent_id, title, kind, created_at, updated_at) "
                "VALUES (?, ?, ?, '', 'direct', ?, ?)",
                (canonical_id, user_id, agent_id, timestamp, timestamp),
            )
        else:
            raise APIError(404, "conversation_not_found", "Conversation was not found")
        timestamp = now()
        connection.execute(
            "INSERT OR IGNORE INTO conversation_homes(user_id, agent_id, conversation_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, agent_id, canonical_id, timestamp, timestamp),
        )
        # A second process cannot win while this transaction is IMMEDIATE, but
        # read the row back so this remains correct if the schema is imported
        # into a database with a pre-existing mapping.
        mapped = connection.execute(
            "SELECT conversation_id FROM conversation_homes WHERE user_id = ? AND agent_id = ?",
            (user_id, agent_id),
        ).fetchone()
        canonical_id = str(mapped["conversation_id"] if mapped else canonical_id)
        for candidate in candidates:
            self._ensure_alias(connection, user_id, str(candidate["id"]), canonical_id)
        self._ensure_alias(connection, user_id, canonical_id, canonical_id)
        self._ensure_state(connection, user_id, canonical_id)
        return canonical_id

    def _resolve(self, user_id: str, conversation_id: str, *, create_direct_home: bool = True) -> str:
        requested = _clean_id(conversation_id, field="conversation_id")
        physical = self.store.get_conversation(user_id, requested)
        if str(physical.get("kind") or "direct") == "direct" and create_direct_home:
            with self.store.db.transaction(immediate=True) as connection:
                return self._home_id_tx(user_id=user_id, agent_id=str(physical["agent_id"]), connection=connection)
        return self.store.canonical_conversation_id(user_id, requested)

    def _eligible_scope(self, user_id: str, canonical_id: str) -> list[str]:
        with self.store.db.read() as connection:
            rows = connection.execute(
                "SELECT a.alias_conversation_id FROM conversation_aliases a "
                "WHERE a.user_id = ? AND a.canonical_conversation_id = ? "
                "AND NOT EXISTS (SELECT 1 FROM tasks t JOIN tool_task_lineage l ON l.child_task_id = t.id "
                "WHERE t.conversation_id = a.alias_conversation_id AND t.user_id = a.user_id) "
                "ORDER BY a.alias_conversation_id",
                (user_id, canonical_id),
            ).fetchall()
        result = [str(row["alias_conversation_id"]) for row in rows]
        if canonical_id not in result:
            result.insert(0, canonical_id)
        return result

    def _member_rows(self, connection: Any, user_id: str, conversation_id: str, *, include_removed: bool = True) -> list[dict[str, Any]]:
        status_clause = "" if include_removed else " AND m.status = 'active'"
        rows = connection.execute(
            "SELECT m.conversation_id, m.agent_id, m.role, m.status, m.joined_at, m.removed_at, "
            "a.name, a.avatar, a.color, a.model FROM conversation_members m "
            "JOIN agents a ON a.id = m.agent_id AND a.user_id = m.user_id "
            "WHERE m.user_id = ? AND m.conversation_id = ?" + status_clause + " ORDER BY m.joined_at, m.agent_id",
            (user_id, conversation_id),
        ).fetchall()
        return [
            {
                "agent_id": row["agent_id"],
                "name": row["name"],
                "role": row["role"],
                "status": row["status"],
                "avatar": row["avatar"],
                "color": row["color"],
                "model": row["model"],
                "joined_at": row["joined_at"],
                "removed_at": row["removed_at"],
            }
            for row in rows
        ]

    def _state(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        with self.store.db.read() as connection:
            row = connection.execute(
                "SELECT pinned, archived, read_through_message_id, read_through_created_at, read_through_rowid, updated_at "
                "FROM conversation_inbox WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            ).fetchone()
        if row is None:
            return {
                "pinned": False,
                "archived": False,
                "read_through_message_id": None,
                "read_through_created_at": None,
                "read_through_rowid": None,
                "updated_at": None,
            }
        return {
            "pinned": bool(row["pinned"]),
            "archived": bool(row["archived"]),
            "read_through_message_id": row["read_through_message_id"],
            "read_through_created_at": row["read_through_created_at"],
            "read_through_rowid": row["read_through_rowid"],
            "updated_at": row["updated_at"],
        }

    def _message_preview(self, user_id: str, scope_ids: Sequence[str]) -> tuple[str, int | None, int]:
        ids = list(dict.fromkeys(str(item) for item in scope_ids))
        placeholders = ",".join("?" for _ in ids)
        with self.store.db.read() as connection:
            row = connection.execute(
                f"SELECT content, created_at FROM messages WHERE user_id = ? AND conversation_id IN ({placeholders}) "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (user_id, *ids),
            ).fetchone()
        return (str(row["content"] or "")[:240] if row else "", int(row["created_at"]) if row else None, 0)

    def _unread_count(self, user_id: str, scope_ids: Sequence[str], state: Mapping[str, Any]) -> int:
        ids = list(dict.fromkeys(str(item) for item in scope_ids))
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        clauses = ["user_id = ?", f"conversation_id IN ({placeholders})", "role = 'assistant'"]
        params: list[Any] = [user_id, *ids]
        watermark_time = state.get("read_through_created_at")
        watermark_rowid = state.get("read_through_rowid")
        if watermark_time is not None and watermark_rowid is not None:
            clauses.append("(created_at > ? OR (created_at = ? AND rowid > ?))")
            params.extend([watermark_time, watermark_time, watermark_rowid])
        with self.store.db.read() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE " + " AND ".join(clauses),
                params,
            ).fetchone()
        return int(row["count"] if row else 0)

    def _active_tasks(self, user_id: str, scope_ids: Sequence[str]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(str(item) for item in scope_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.store.db.read() as connection:
            rows = connection.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks t WHERE t.user_id = ? AND (t.conversation_id IN ({placeholders}) "
                f"OR t.origin_conversation_id IN ({placeholders})) AND t.status IN ('queued', 'running') "
                "ORDER BY t.updated_at DESC, t.rowid DESC LIMIT 50",
                (user_id, *ids, *ids),
            ).fetchall()
        return [_task(row) for row in rows]

    def _augmented(self, user_id: str, canonical_id: str, *, requested_id: str | None = None) -> dict[str, Any]:
        with self.store.db.read() as connection:
            row = connection.execute(
                "SELECT id, user_id, agent_id, title, status, created_at, updated_at, kind FROM conversations "
                "WHERE id = ? AND user_id = ?",
                (canonical_id, user_id),
            ).fetchone()
            if row is None:
                raise APIError(404, "conversation_not_found", "Conversation was not found")
            group = connection.execute(
                "SELECT name, coordinator_id, created_at, updated_at FROM conversation_groups "
                "WHERE conversation_id = ? AND user_id = ?",
                (canonical_id, user_id),
            ).fetchone()
            self._ensure_state(connection, user_id, canonical_id, archived=row["status"] == "archived")
        raw_kind = str(row["kind"] or "direct")
        kind = "group" if group is not None or raw_kind == "group" else ("delegated" if raw_kind == "delegated" else "direct")
        state = self._state(user_id, canonical_id)
        scope_ids = [canonical_id] if kind == "group" else self._eligible_scope(user_id, canonical_id)
        preview, preview_at, _ = self._message_preview(user_id, scope_ids)
        active_tasks = self._active_tasks(user_id, scope_ids)
        agent = self.store.get_agent(user_id, str(row["agent_id"]))
        if kind == "group":
            with self.store.db.read() as connection:
                all_members = self._member_rows(connection, user_id, canonical_id, include_removed=True)
                members = [item for item in all_members if item.get("status") == "active"]
            name = str(group["name"] if group is not None else row["title"])
            coordinator_id = str(group["coordinator_id"] if group is not None else row["agent_id"])
        else:
            members = []
            name = str(agent.get("name") or row["title"] or "")
            coordinator_id = str(row["agent_id"])
        result: dict[str, Any] = {
            "id": str(row["id"]),
            "conversation_id": str(row["id"]),
            "canonical_conversation_id": str(row["id"]),
            "requested_conversation_id": requested_id or str(row["id"]),
            "user_id": str(row["user_id"]),
            "agent_id": str(row["agent_id"]),
            "title": str(row["title"] or ""),
            "name": name,
            "kind": kind,
            "status": "archived" if state["archived"] or row["status"] == "archived" else str(row["status"]),
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
            "preview": preview,
            "preview_created_at": preview_at,
            "unread_count": self._unread_count(user_id, scope_ids, state),
            "pinned": bool(state["pinned"]),
            "archived": bool(state["archived"] or row["status"] == "archived"),
            "read_through_message_id": state["read_through_message_id"],
            "active_tasks": active_tasks,
            "agent": _public_agent(agent),
            "coordinator_id": coordinator_id,
            "members": members,
        }
        if kind == "group":
            result["group"] = {
                "name": name,
                "coordinator_id": coordinator_id,
                "members": members,
            }
            result["all_members"] = all_members
            result["removed_members"] = [item for item in all_members if item.get("status") == "removed"]
        else:
            result["aliases"] = scope_ids
        return result

    def _validate_group(self, user_id: str, conversation_id: str, *, include_archived: bool = True) -> dict[str, Any]:
        canonical_id = self._resolve(user_id, conversation_id)
        with self.store.db.read() as connection:
            row = connection.execute(
                "SELECT c.id, c.agent_id, c.status, c.kind, g.name, g.coordinator_id FROM conversations c "
                "JOIN conversation_groups g ON g.conversation_id = c.id AND g.user_id = c.user_id "
                "WHERE c.id = ? AND c.user_id = ?",
                (canonical_id, user_id),
            ).fetchone()
        if row is None:
            raise APIError(409, "group_required", "This operation requires a group conversation")
        if not include_archived and row["status"] == "archived":
            raise APIError(409, "conversation_archived", "Archived conversations cannot receive messages")
        return dict(row)

    def _validate_active_member(self, connection: Any, user_id: str, conversation_id: str, agent_id: str) -> Any:
        row = connection.execute(
            "SELECT m.agent_id, m.role, m.status, a.status AS agent_status FROM conversation_members m "
            "JOIN agents a ON a.id = m.agent_id AND a.user_id = m.user_id "
            "WHERE m.user_id = ? AND m.conversation_id = ? AND m.agent_id = ?",
            (user_id, conversation_id, agent_id),
        ).fetchone()
        if row is None or row["status"] != "active":
            raise APIError(403, "group_member_forbidden", "The agent is not a current group member")
        if row["agent_status"] == "archived":
            raise APIError(409, "agent_archived", "Archived agents cannot receive tasks")
        return row

    def _attachments_tx(
        self,
        connection: Any,
        user_id: str,
        conversation_id: str,
        agent_ids: Sequence[str],
        file_ids: Sequence[str],
        *,
        group: bool,
        coordinator_id: str | None = None,
    ) -> list[dict[str, str]]:
        attachments: list[dict[str, str]] = []
        for file_id in file_ids:
            file = connection.execute(
                "SELECT id, agent_id, relative_path, content_type FROM files WHERE id = ? AND user_id = ?",
                (file_id, user_id),
            ).fetchone()
            if file is None:
                raise APIError(404, "file_not_found", "An attached file was not found")
            source_agent = str(file["agent_id"])
            if not group:
                if source_agent not in agent_ids:
                    raise APIError(404, "file_not_found", "An attached file was not found")
            else:
                grant = connection.execute(
                    "SELECT 1 FROM conversation_file_grants WHERE user_id = ? AND conversation_id = ? "
                    "AND file_id = ? AND revoked_at IS NULL",
                    (user_id, conversation_id, file_id),
                ).fetchone()
                if grant is None:
                    # Coordinator uploads may be attached by the owner; make
                    # that access explicit in the grant table for subsequent
                    # tool/model reads.  Other members require a prior grant.
                    if coordinator_id is None or source_agent != coordinator_id:
                        raise APIError(403, "file_grant_required", "The file has not been shared with this group")
                    connection.execute(
                        "INSERT OR IGNORE INTO conversation_file_grants(user_id, conversation_id, file_id, granted_by_agent_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user_id, conversation_id, file_id, coordinator_id, now()),
                    )
            path = str(file["relative_path"])
            attachments.append(
                {
                    "file_id": str(file["id"]),
                    "path": path,
                    "name": PurePosixPath(path).name,
                    "content_type": str(file["content_type"]),
                }
            )
        return attachments

    def _request_result_tx(self, connection: Any, user_id: str, canonical_id: str, request_row: Any) -> dict[str, Any]:
        message = connection.execute(
            f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE id = ? AND user_id = ?",
            (request_row["message_id"], user_id),
        ).fetchone()
        tasks = connection.execute(
            f"SELECT {TASK_COLUMNS} FROM tasks WHERE user_id = ? AND conversation_id = ? "
            "AND request_id = ? AND parent_task_id IS NULL ORDER BY created_at ASC, rowid ASC",
            (user_id, canonical_id, request_row["request_id"]),
        ).fetchall()
        task_values = [_task(row) for row in tasks]
        return {
            "message": _message(message),
            "task": task_values[0] if task_values else None,
            "tasks": task_values,
            "request_id": str(request_row["request_id"]),
            "replayed": True,
        }

    def _fingerprint(
        self,
        content: str,
        file_ids: Sequence[str],
        mention_agent_ids: Sequence[str],
        reply_to_id: str | None,
    ) -> str:
        payload = {
            "content": content,
            "file_ids": sorted(file_ids),
            "mention_agent_ids": sorted(mention_agent_ids),
            "reply_to_id": reply_to_id,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Public direct/group reads
    # ------------------------------------------------------------------
    def home(self, user_id: str, agent_id: str) -> dict[str, Any]:
        agent_id = _clean_id(agent_id, field="agent_id")
        with self.store.db.transaction(immediate=True) as connection:
            canonical_id = self._home_id_tx(connection, str(user_id), agent_id)
        return self._augmented(str(user_id), canonical_id)

    def conversation(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        requested = _clean_id(conversation_id, field="conversation_id")
        physical = self.store.get_conversation(str(user_id), requested)
        canonical_id = self._resolve(str(user_id), requested)
        return self._augmented(str(user_id), canonical_id, requested_id=requested)

    def scope_ids(self, user_id: str, conversation_id: str) -> list[str]:
        requested = _clean_id(conversation_id, field="conversation_id")
        physical = self.store.get_conversation(str(user_id), requested)
        canonical_id = self._resolve(str(user_id), requested)
        if str(physical.get("kind") or "direct") == "group":
            return [canonical_id]
        return self._eligible_scope(str(user_id), canonical_id)

    def list_messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        limit: int = 200,
        before_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.store.list_messages_in_scope(str(user_id), self.scope_ids(str(user_id), conversation_id), limit=limit, before_id=before_id)

    def exact_message(self, user_id: str, conversation_id: str, message_id: str) -> dict[str, Any]:
        return self.store.get_message(
            str(user_id),
            conversation_id,
            _clean_id(message_id, field="message_id"),
            conversation_ids=self.scope_ids(str(user_id), conversation_id),
        )

    # Compatibility spelling used by a few history callers.
    get_message = exact_message

    def search(self, user_id: str, conversation_id: str, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.search_messages(str(user_id), conversation_id, query, limit=limit, conversation_ids=self.scope_ids(str(user_id), conversation_id))

    def search_messages(self, user_id: str, conversation_id: str, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.search(user_id, conversation_id, query, limit=limit)

    def tasks(self, user_id: str, conversation_id: str, *, limit: int = 50) -> dict[str, Any]:
        """Return the latest task and all currently active responders."""

        user_id = str(user_id)
        scope = self.scope_ids(user_id, conversation_id)
        placeholders = ",".join("?" for _ in scope)
        with self.store.db.read() as connection:
            rows = connection.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks t WHERE t.user_id = ? AND (t.conversation_id IN ({placeholders}) "
                f"OR t.origin_conversation_id IN ({placeholders})) "
                "ORDER BY t.updated_at DESC, t.rowid DESC LIMIT ?",
                (user_id, *scope, *scope, max(1, min(int(limit), 200))),
            ).fetchall()
        values = [_task(row) for row in rows]
        active = [item for item in values if item.get("status") in {"queued", "running"}]
        return {"latest": values[0] if values else None, "active": active, "tasks": values}

    def append_collaboration_message(
        self,
        user_id: str,
        origin_conversation_id: str,
        author_agent_id: str,
        text: str,
        *,
        source_task_id: str,
        request_id: str | None = None,
    ) -> str:
        source = self.store.get_task(str(user_id), str(source_task_id))
        resolved_request = str(request_id or source.get("request_id") or f"task:{source_task_id}")
        return self.store.append_collaboration_message(
            str(user_id),
            origin_conversation_id,
            str(author_agent_id),
            text,
            str(source_task_id),
            resolved_request,
        )

    def inbox(self, user_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
        user_id = str(user_id)
        # Existing accounts can have agents and legacy conversations without a
        # home row.  Materialize each active agent's home before listing so the
        # inbox is stable across devices and restarts.
        for agent in self.store.list_agents(user_id):
            if agent.get("status") != "archived":
                self.home(user_id, str(agent["id"]))
        with self.store.db.read() as connection:
            rows = connection.execute(
                "SELECT c.id FROM conversations c WHERE c.user_id = ? AND c.kind = 'group' "
                "UNION SELECT h.conversation_id FROM conversation_homes h WHERE h.user_id = ?",
                (user_id, user_id),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                item = self._augmented(user_id, str(row["id"] if "id" in row.keys() else row[0]))
            except APIError:
                continue
            if item["archived"] and not include_archived:
                continue
            # Inbox contract uses ``items`` entries that retain the same rich
            # conversation identity fields for simple clients.
            items.append(item)
        items.sort(key=lambda item: (not bool(item.get("pinned")), -int(item.get("updated_at") or 0), str(item.get("conversation_id"))))
        return items

    # ------------------------------------------------------------------
    # Group lifecycle and inbox state
    # ------------------------------------------------------------------
    def create_group(
        self,
        user_id: str,
        name: str,
        agent_ids: Sequence[str],
        coordinator_id: str | None = None,
    ) -> dict[str, Any]:
        user_id = str(user_id)
        name = str(name or "").strip()
        if not name or len(name) > 120:
            raise APIError(422, "group_name_invalid", "Group name is invalid")
        members = _ids(agent_ids, field="agent_ids", maximum=MAX_GROUP_MEMBERS)
        if len(members) < MIN_GROUP_MEMBERS:
            raise APIError(422, "group_members_invalid", "A group needs 2 to 6 agents")
        coordinator = _clean_id(coordinator_id, field="coordinator_id") if coordinator_id else members[0]
        if coordinator not in members:
            raise APIError(422, "coordinator_invalid", "The coordinator must be a group member")
        with self.store.db.transaction(immediate=True) as connection:
            placeholders = ",".join("?" for _ in members)
            rows = connection.execute(
                f"SELECT id, status FROM agents WHERE user_id = ? AND id IN ({placeholders})",
                (user_id, *members),
            ).fetchall()
            found = {str(row["id"]): str(row["status"]) for row in rows}
            if len(found) != len(members):
                raise APIError(404, "agent_not_found", "One or more group agents were not found")
            if any(status == "archived" for status in found.values()):
                raise APIError(409, "agent_archived", "Archived agents cannot join a group")
            conversation_id = new_id()
            timestamp = now()
            connection.execute(
                "INSERT INTO conversations(id, user_id, agent_id, title, kind, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'group', ?, ?)",
                (conversation_id, user_id, coordinator, name, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO conversation_groups(conversation_id, user_id, name, coordinator_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, user_id, name, coordinator, timestamp, timestamp),
            )
            for agent_id in members:
                connection.execute(
                    "INSERT INTO conversation_members(conversation_id, user_id, agent_id, role, status, joined_at) "
                    "VALUES (?, ?, ?, ?, 'active', ?)",
                    (conversation_id, user_id, agent_id, "coordinator" if agent_id == coordinator else "member", timestamp),
                )
            self._ensure_state(connection, user_id, conversation_id)
        return self._augmented(user_id, conversation_id)

    def update_group(
        self,
        user_id: str,
        conversation_id: str,
        *,
        name: str | None = None,
        agent_ids: Sequence[str] | None = None,
        coordinator_id: str | None = None,
        archived: bool | None = None,
        pinned: bool | None = None,
    ) -> dict[str, Any]:
        user_id = str(user_id)
        group = self._validate_group(user_id, conversation_id)
        canonical_id = str(group["id"])
        members = _ids(agent_ids, field="agent_ids", maximum=MAX_GROUP_MEMBERS) if agent_ids is not None else None
        with self.store.db.transaction(immediate=True) as connection:
            current_rows = connection.execute(
                "SELECT agent_id, role, status FROM conversation_members WHERE user_id = ? AND conversation_id = ?",
                (user_id, canonical_id),
            ).fetchall()
            current_active = [str(row["agent_id"]) for row in current_rows if row["status"] == "active"]
            target = members if members is not None else current_active
            if len(target) < MIN_GROUP_MEMBERS or len(target) > MAX_GROUP_MEMBERS:
                raise APIError(422, "group_members_invalid", "A group needs 2 to 6 agents")
            target_set = set(target)
            if len(target_set) != len(target):
                raise APIError(422, "agent_ids_duplicate", "agent_ids contains a duplicate value")
            placeholders = ",".join("?" for _ in target)
            rows = connection.execute(
                f"SELECT id, status FROM agents WHERE user_id = ? AND id IN ({placeholders})",
                (user_id, *target),
            ).fetchall()
            found = {str(row["id"]): str(row["status"]) for row in rows}
            if len(found) != len(target):
                raise APIError(404, "agent_not_found", "One or more group agents were not found")
            if any(status == "archived" for status in found.values()):
                raise APIError(409, "agent_archived", "Archived agents cannot join a group")
            chosen_coordinator = _clean_id(coordinator_id, field="coordinator_id") if coordinator_id else str(group["coordinator_id"])
            if chosen_coordinator not in target_set:
                if coordinator_id:
                    raise APIError(422, "coordinator_invalid", "The coordinator must be a group member")
                chosen_coordinator = target[0]
            timestamp = now()
            for row in current_rows:
                agent_id = str(row["agent_id"])
                if agent_id not in target_set and row["status"] == "active":
                    connection.execute(
                        "UPDATE conversation_members SET status = 'removed', role = 'member', removed_at = ? "
                        "WHERE user_id = ? AND conversation_id = ? AND agent_id = ?",
                        (timestamp, user_id, canonical_id, agent_id),
                    )
            for agent_id in target:
                connection.execute(
                    "INSERT INTO conversation_members(conversation_id, user_id, agent_id, role, status, joined_at, removed_at) "
                    "VALUES (?, ?, ?, ?, 'active', ?, NULL) "
                    "ON CONFLICT(conversation_id, agent_id) DO UPDATE SET role=excluded.role, status='active', removed_at=NULL",
                    (canonical_id, user_id, agent_id, "coordinator" if agent_id == chosen_coordinator else "member", timestamp),
                )
            updates: list[str] = ["agent_id = ?", "updated_at = ?"]
            params: list[Any] = [chosen_coordinator, timestamp]
            if name is not None:
                clean_name = str(name).strip()
                if not clean_name or len(clean_name) > 120:
                    raise APIError(422, "group_name_invalid", "Group name is invalid")
                updates.extend(["title = ?"])
                params.append(clean_name)
                connection.execute(
                    "UPDATE conversation_groups SET name = ?, coordinator_id = ?, updated_at = ? WHERE conversation_id = ? AND user_id = ?",
                    (clean_name, chosen_coordinator, timestamp, canonical_id, user_id),
                )
            else:
                connection.execute(
                    "UPDATE conversation_groups SET coordinator_id = ?, updated_at = ? WHERE conversation_id = ? AND user_id = ?",
                    (chosen_coordinator, timestamp, canonical_id, user_id),
                )
            if archived is not None:
                updates.append("status = ?")
                params.append("archived" if archived else "active")
                connection.execute(
                    "UPDATE conversation_inbox SET archived = ?, updated_at = ? WHERE user_id = ? AND conversation_id = ?",
                    (1 if archived else 0, timestamp, user_id, canonical_id),
                )
            if updates:
                params.extend([canonical_id, user_id])
                connection.execute(
                    "UPDATE conversations SET " + ", ".join(updates) + " WHERE id = ? AND user_id = ?",
                    params,
                )
            if pinned is not None:
                connection.execute(
                    "UPDATE conversation_inbox SET pinned = ?, updated_at = ? WHERE user_id = ? AND conversation_id = ?",
                    (1 if pinned else 0, timestamp, user_id, canonical_id),
                )
        return self._augmented(user_id, canonical_id)

    edit_group = update_group

    def archive(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        return self.update_group(user_id, conversation_id, archived=True)

    def restore(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        return self.update_group(user_id, conversation_id, archived=False)

    archive_group = archive
    restore_group = restore

    def archive_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        canonical_id = self._resolve(str(user_id), conversation_id)
        with self.store.db.transaction() as connection:
            self._ensure_state(connection, str(user_id), canonical_id)
            connection.execute("UPDATE conversations SET status = 'archived', updated_at = ? WHERE id = ? AND user_id = ?", (now(), canonical_id, str(user_id)))
            connection.execute("UPDATE conversation_inbox SET archived = 1, updated_at = ? WHERE user_id = ? AND conversation_id = ?", (now(), str(user_id), canonical_id))
        return self._augmented(str(user_id), canonical_id)

    def restore_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        canonical_id = self._resolve(str(user_id), conversation_id)
        with self.store.db.transaction() as connection:
            self._ensure_state(connection, str(user_id), canonical_id)
            connection.execute("UPDATE conversations SET status = 'active', updated_at = ? WHERE id = ? AND user_id = ?", (now(), canonical_id, str(user_id)))
            connection.execute("UPDATE conversation_inbox SET archived = 0, updated_at = ? WHERE user_id = ? AND conversation_id = ?", (now(), str(user_id), canonical_id))
        return self._augmented(str(user_id), canonical_id)

    def set_pinned(self, user_id: str, conversation_id: str, pinned: bool = True) -> dict[str, Any]:
        canonical_id = self._resolve(str(user_id), conversation_id)
        with self.store.db.transaction() as connection:
            self._ensure_state(connection, str(user_id), canonical_id)
            connection.execute("UPDATE conversation_inbox SET pinned = ?, updated_at = ? WHERE user_id = ? AND conversation_id = ?", (1 if pinned else 0, now(), str(user_id), canonical_id))
        return self._augmented(str(user_id), canonical_id)

    def pin(self, user_id: str, conversation_id: str, pinned: bool = True) -> dict[str, Any]:
        return self.set_pinned(user_id, conversation_id, pinned)

    pin_group = pin

    def mark_read(self, user_id: str, conversation_id: str, through_message_id: str) -> dict[str, Any]:
        user_id = str(user_id)
        canonical_id = self._resolve(user_id, conversation_id)
        scope = self.scope_ids(user_id, canonical_id)
        placeholders = ",".join("?" for _ in scope)
        with self.store.db.transaction(immediate=True) as connection:
            row = connection.execute(
                f"SELECT id, created_at, rowid AS _rowid FROM messages WHERE id = ? AND user_id = ? AND conversation_id IN ({placeholders})",
                (through_message_id, user_id, *scope),
            ).fetchone()
            if row is None:
                raise APIError(404, "message_not_found", "The read watermark message was not found")
            self._ensure_state(connection, user_id, canonical_id)
            current = connection.execute(
                "SELECT read_through_created_at, read_through_rowid FROM conversation_inbox "
                "WHERE user_id = ? AND conversation_id = ?",
                (user_id, canonical_id),
            ).fetchone()
            current_position = (
                (int(current["read_through_created_at"]), int(current["read_through_rowid"]))
                if current is not None and current["read_through_created_at"] is not None and current["read_through_rowid"] is not None
                else None
            )
            target_position = (int(row["created_at"]), int(row["_rowid"]))
            if current_position is None or target_position >= current_position:
                connection.execute(
                    "UPDATE conversation_inbox SET read_through_message_id = ?, read_through_created_at = ?, read_through_rowid = ?, updated_at = ? "
                    "WHERE user_id = ? AND conversation_id = ?",
                    (row["id"], row["created_at"], row["_rowid"], now(), user_id, canonical_id),
                )
        return self._augmented(user_id, canonical_id)

    mark_read_through = mark_read

    # Short names keep the service convenient for non-HTTP callers while the
    # descriptive names remain the preferred public API.
    read = mark_read

    # ------------------------------------------------------------------
    # Group attachment grants and authorization
    # ------------------------------------------------------------------
    def grant_files(
        self,
        user_id: str,
        conversation_id: str,
        file_ids: Sequence[str],
        *,
        granted_by_agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        user_id = str(user_id)
        group = self._validate_group(user_id, conversation_id, include_archived=False)
        ids = _dedupe_file_ids(file_ids)
        grantor = str(granted_by_agent_id or group["coordinator_id"])
        with self.store.db.transaction(immediate=True) as connection:
            self._validate_active_member(connection, user_id, str(group["id"]), grantor)
            for file_id in ids:
                file = connection.execute(
                    "SELECT id, agent_id FROM files WHERE id = ? AND user_id = ?",
                    (file_id, user_id),
                ).fetchone()
                if file is None:
                    raise APIError(404, "file_not_found", "File was not found")
                source_agent = str(file["agent_id"])
                self._validate_active_member(connection, user_id, str(group["id"]), source_agent)
                connection.execute(
                    "INSERT INTO conversation_file_grants(user_id, conversation_id, file_id, granted_by_agent_id, created_at, revoked_at) "
                    "VALUES (?, ?, ?, ?, ?, NULL) ON CONFLICT(user_id, conversation_id, file_id) DO UPDATE SET "
                    "granted_by_agent_id = excluded.granted_by_agent_id, revoked_at = NULL",
                    (user_id, str(group["id"]), file_id, grantor, now()),
                )
        return self.list_granted_files(user_id, str(group["id"]))

    grant_file_ids = grant_files

    def revoke_files(self, user_id: str, conversation_id: str, file_ids: Sequence[str]) -> list[dict[str, Any]]:
        user_id = str(user_id)
        group = self._validate_group(user_id, conversation_id)
        ids = _dedupe_file_ids(file_ids)
        with self.store.db.transaction() as connection:
            placeholders = ",".join("?" for _ in ids) or "NULL"
            connection.execute(
                f"UPDATE conversation_file_grants SET revoked_at = ? WHERE user_id = ? AND conversation_id = ? AND file_id IN ({placeholders})",
                (now(), user_id, str(group["id"]), *ids),
            )
        return self.list_granted_files(user_id, str(group["id"]))

    def list_granted_files(self, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
        user_id = str(user_id)
        group = self._validate_group(user_id, conversation_id)
        with self.store.db.read() as connection:
            rows = connection.execute(
                "SELECT f.id, f.user_id, f.agent_id, f.relative_path, f.size_bytes, f.sha256, f.content_type, f.created_at, f.updated_at, "
                "g.granted_by_agent_id, g.created_at AS granted_at FROM conversation_file_grants g "
                "JOIN files f ON f.id = g.file_id AND f.user_id = g.user_id "
                "WHERE g.user_id = ? AND g.conversation_id = ? AND g.revoked_at IS NULL ORDER BY g.created_at DESC, f.id",
                (user_id, str(group["id"])),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = _file(row)
            item["granted_by_agent_id"] = row["granted_by_agent_id"]
            item["granted_at"] = row["granted_at"]
            result.append(item)
        return result

    granted_files = list_granted_files
    list_group_files = list_granted_files

    def can_respond(self, user_id: str, conversation_id: str, agent_id: str) -> bool:
        try:
            canonical_id = self._resolve(str(user_id), conversation_id)
        except APIError:
            return False
        agent_id = str(agent_id)
        with self.store.db.read() as connection:
            conversation = connection.execute(
                "SELECT c.agent_id, c.status, c.kind, m.status AS member_status, a.status AS agent_status "
                "FROM conversations c LEFT JOIN conversation_members m ON m.conversation_id = c.id AND m.user_id = c.user_id AND m.agent_id = ? "
                "JOIN agents a ON a.id = ? AND a.user_id = c.user_id WHERE c.id = ? AND c.user_id = ?",
                (agent_id, agent_id, canonical_id, str(user_id)),
            ).fetchone()
        if conversation is None or conversation["status"] == "archived" or conversation["agent_status"] == "archived":
            return False
        if str(conversation["kind"] or "direct") == "group":
            return conversation["member_status"] == "active"
        return str(conversation["agent_id"]) == agent_id

    def file_allowed(self, user_id: str, agent_id: str, conversation_id: str, file_id: str) -> bool:
        try:
            canonical_id = self._resolve(str(user_id), conversation_id)
            file_id = _clean_id(file_id, field="file_id")
        except APIError:
            return False
        with self.store.db.read() as connection:
            row = connection.execute(
                "SELECT f.agent_id, c.agent_id AS conversation_agent_id, c.kind, c.status, a.status AS agent_status, "
                "m.status AS member_status, g.file_id AS grant_file_id, g.revoked_at FROM files f "
                "JOIN conversations c ON c.id = ? AND c.user_id = f.user_id "
                "JOIN agents a ON a.id = ? AND a.user_id = f.user_id "
                "LEFT JOIN conversation_members m ON m.conversation_id = c.id AND m.user_id = c.user_id AND m.agent_id = ? "
                "LEFT JOIN conversation_file_grants g ON g.user_id = f.user_id AND g.conversation_id = c.id AND g.file_id = f.id "
                "WHERE f.id = ? AND f.user_id = ?",
                (canonical_id, str(agent_id), str(agent_id), file_id, str(user_id)),
            ).fetchone()
            if row is None or row["status"] == "archived" or row["agent_status"] == "archived":
                return False
            if str(row["kind"] or "direct") == "group":
                return row["member_status"] == "active" and row["grant_file_id"] is not None and row["revoked_at"] is None
            if str(row["kind"] or "direct") == "delegated":
                return row["grant_file_id"] is not None and row["revoked_at"] is None and str(row["conversation_agent_id"]) == str(agent_id)
            return str(row["conversation_agent_id"]) == str(agent_id) and str(row["agent_id"]) == str(agent_id)

    # ------------------------------------------------------------------
    # Atomic user sends and bounded delegation
    # ------------------------------------------------------------------
    def send(
        self,
        user_id: str,
        conversation_id: str,
        content: str,
        *,
        file_ids: Sequence[str] | None = None,
        mention_agent_ids: Sequence[str] | None = None,
        reply_to_id: str | None = None,
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        user_id = str(user_id)
        content = str(content)
        if not content.strip() or len(content) > 100_000:
            raise APIError(422, "content_invalid", "Message content is invalid")
        requested = _clean_id(conversation_id, field="conversation_id")
        physical = self.store.get_conversation(user_id, requested)
        canonical_id = self._resolve(user_id, requested)
        file_list = _dedupe_file_ids(file_ids)
        raw_mentions = _ids(mention_agent_ids, field="mention_agent_ids", maximum=MAX_MESSAGE_FANOUT)
        reply_id = _clean_id(reply_to_id, field="reply_to_id") if reply_to_id else None
        client_id = _clean_id(client_request_id, field="client_request_id") if client_request_id else str(uuid4())
        kind = str(physical.get("kind") or "direct")
        if canonical_id != requested:
            # A legacy direct URL can only write through its canonical home.
            kind = "direct"
        fingerprint = self._fingerprint(content, file_list, raw_mentions, reply_id)
        with self.store.db.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT user_id, canonical_conversation_id, client_request_id, request_id, body_fingerprint, message_id "
                "FROM message_requests WHERE user_id = ? AND canonical_conversation_id = ? AND client_request_id = ?",
                (user_id, canonical_id, client_id),
            ).fetchone()
            if existing is not None:
                if str(existing["body_fingerprint"]) != fingerprint:
                    raise APIError(409, "idempotency_conflict", "The request ID was already used for different message content")
                return self._request_result_tx(connection, user_id, canonical_id, existing)
            conversation = connection.execute(
                "SELECT id, agent_id, title, status, kind FROM conversations WHERE id = ? AND user_id = ?",
                (canonical_id, user_id),
            ).fetchone()
            if conversation is None:
                raise APIError(404, "conversation_not_found", "Conversation was not found")
            if conversation["status"] == "archived":
                raise APIError(409, "conversation_archived", "Archived conversations cannot receive messages")
            group_row = connection.execute(
                "SELECT coordinator_id, name FROM conversation_groups WHERE conversation_id = ? AND user_id = ?",
                (canonical_id, user_id),
            ).fetchone()
            is_group = group_row is not None or str(conversation["kind"] or kind) == "group"
            if is_group:
                active_rows = connection.execute(
                    "SELECT m.agent_id, m.role FROM conversation_members m JOIN agents a ON a.id = m.agent_id AND a.user_id = m.user_id "
                    "WHERE m.user_id = ? AND m.conversation_id = ? AND m.status = 'active' AND a.status != 'archived'",
                    (user_id, canonical_id),
                ).fetchall()
                active_ids = [str(row["agent_id"]) for row in active_rows]
                coordinator = str(group_row["coordinator_id"] if group_row else conversation["agent_id"])
                if raw_mentions and any(value.casefold() in {"@everyone", "everyone"} for value in raw_mentions):
                    if len(raw_mentions) != 1:
                        raise APIError(422, "mention_agent_ids_invalid", "@everyone cannot be combined with another mention")
                    responders = active_ids
                elif raw_mentions:
                    responders = raw_mentions
                    if any(agent_id not in active_ids for agent_id in responders):
                        raise APIError(403, "group_member_forbidden", "A mentioned agent is not a current group member")
                else:
                    responders = [coordinator]
                if len(responders) > MAX_MESSAGE_FANOUT:
                    raise APIError(422, "too_many_responders", "A message can address at most six agents")
                for agent_id in responders:
                    self._validate_active_member(connection, user_id, canonical_id, agent_id)
                attachments = self._attachments_tx(
                    connection,
                    user_id,
                    canonical_id,
                    responders,
                    file_list,
                    group=True,
                    coordinator_id=coordinator,
                )
            else:
                responder = str(conversation["agent_id"])
                if raw_mentions and raw_mentions != [responder]:
                    raise APIError(403, "mention_agent_forbidden", "A direct conversation has one responder")
                agent = connection.execute(
                    "SELECT id, status FROM agents WHERE id = ? AND user_id = ?",
                    (responder, user_id),
                ).fetchone()
                if agent is None:
                    raise APIError(404, "agent_not_found", "Agent was not found")
                if agent["status"] == "archived":
                    raise APIError(409, "agent_archived", "Archived agents cannot receive messages")
                responders = [responder]
                attachments = self._attachments_tx(connection, user_id, canonical_id, responders, file_list, group=False)
            if reply_id:
                placeholders = ",".join("?" for _ in ([canonical_id] if is_group else self._eligible_scope(user_id, canonical_id)))
                scope = [canonical_id] if is_group else self._eligible_scope(user_id, canonical_id)
                found_reply = connection.execute(
                    f"SELECT 1 FROM messages WHERE id = ? AND user_id = ? AND conversation_id IN ({placeholders})",
                    (reply_id, user_id, *scope),
                ).fetchone()
                if found_reply is None:
                    raise APIError(404, "message_not_found", "The reply target was not found")
            request_id = str(uuid4())
            message_id = new_id()
            timestamp = now()
            metadata: dict[str, Any] = {"request_id": request_id}
            if attachments:
                metadata["attachments"] = attachments
            if raw_mentions:
                metadata["mention_agent_ids"] = list(responders)
            if reply_id:
                metadata["reply_to_id"] = reply_id
            connection.execute(
                "INSERT INTO messages(id, conversation_id, user_id, role, content, status, metadata_json, created_at, "
                "request_id, origin_conversation_id, reply_to_id) VALUES (?, ?, ?, 'user', ?, 'completed', ?, ?, ?, ?, ?)",
                (message_id, canonical_id, user_id, content, json.dumps(metadata, separators=(",", ":"), ensure_ascii=False), timestamp, request_id, canonical_id, reply_id),
            )
            tasks: list[dict[str, Any]] = []
            for responder in responders:
                task_id = new_id()
                connection.execute(
                    "INSERT INTO tasks(id, user_id, conversation_id, agent_id, message_id, status, created_at, updated_at, kind, request_id, origin_conversation_id) "
                    "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
                    (task_id, user_id, canonical_id, responder, message_id, timestamp, timestamp, "group" if is_group else "direct", request_id, canonical_id),
                )
                task_row = connection.execute(f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = ?", (task_id,)).fetchone()
                tasks.append(_task(task_row))
            connection.execute(
                "INSERT INTO message_requests(user_id, canonical_conversation_id, client_request_id, request_id, body_fingerprint, message_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, canonical_id, client_id, request_id, fingerprint, message_id, timestamp),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ?, title = CASE WHEN title = '' AND kind = 'direct' THEN ? ELSE title END WHERE id = ?",
                (timestamp, content[:80], canonical_id),
            )
            connection.execute(
                "UPDATE conversation_inbox SET archived = 0, updated_at = ? WHERE user_id = ? AND conversation_id = ?",
                (timestamp, user_id, canonical_id),
            )
            message_row = connection.execute(f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE id = ?", (message_id,)).fetchone()
        result = {
            "message": _message(message_row),
            "task": tasks[0],
            "tasks": tasks,
            "request_id": request_id,
            "replayed": False,
        }
        return result

    def delegate(
        self,
        user_id: str,
        parent_task_id: str,
        child_agent_id: str,
        prompt: str,
        max_children: int = 3,
    ) -> dict[str, Any]:
        """Atomically create a one-level delegated task and its lineage."""

        user_id = str(user_id)
        child_agent_id = _clean_id(child_agent_id, field="child_agent_id")
        prompt = str(prompt)
        if not prompt.strip() or len(prompt) > 100_000:
            raise APIError(422, "prompt_invalid", "Delegated prompt is invalid")
        max_children = max(1, min(int(max_children), 6))
        with self.store.db.transaction(immediate=True) as connection:
            self.store._ensure_lineage_table(connection)
            parent = connection.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = ? AND user_id = ?",
                (parent_task_id, user_id),
            ).fetchone()
            if parent is None:
                raise APIError(404, "task_not_found", "The parent task was not found")
            if parent["status"] in {"completed", "failed", "cancelled"}:
                raise APIError(409, "task_terminal", "A terminal task cannot delegate")
            parent_conversation_state = connection.execute(
                "SELECT status FROM conversations WHERE id = ? AND user_id = ?",
                (parent["conversation_id"], user_id),
            ).fetchone()
            if parent_conversation_state is None:
                raise APIError(404, "conversation_not_found", "The parent conversation was not found")
            if parent_conversation_state["status"] == "archived":
                raise APIError(409, "conversation_archived", "Archived conversations cannot create delegated work")
            parent_agent_state = connection.execute(
                "SELECT status FROM agents WHERE id = ? AND user_id = ?",
                (parent["agent_id"], user_id),
            ).fetchone()
            if parent_agent_state is None:
                raise APIError(404, "agent_not_found", "The parent agent was not found")
            if parent_agent_state["status"] == "archived":
                raise APIError(409, "agent_archived", "Archived agents cannot create delegated work")
            nested = connection.execute(
                "SELECT 1 FROM tool_task_lineage WHERE child_task_id = ? LIMIT 1",
                (parent_task_id,),
            ).fetchone()
            if nested is not None or parent["parent_task_id"] is not None:
                raise APIError(409, "nested_delegation_forbidden", "Child tasks cannot delegate further")
            child_count = connection.execute(
                "SELECT COUNT(*) AS count FROM tool_task_lineage WHERE parent_task_id = ?",
                (parent_task_id,),
            ).fetchone()
            if int(child_count["count"] if child_count else 0) >= max_children:
                raise APIError(429, "delegation_limit", f"A task may spawn at most {max_children} children")
            child_agent = connection.execute(
                "SELECT id, name, status FROM agents WHERE id = ? AND user_id = ?",
                (child_agent_id, user_id),
            ).fetchone()
            if child_agent is None:
                raise APIError(404, "agent_not_found", "The delegated agent was not found")
            if child_agent["status"] == "archived":
                raise APIError(409, "agent_archived", "Archived agents cannot receive delegated tasks")
            origin_id = str(parent["origin_conversation_id"] or parent["conversation_id"])
            alias = connection.execute(
                "SELECT canonical_conversation_id FROM conversation_aliases WHERE user_id = ? AND alias_conversation_id = ?",
                (user_id, origin_id),
            ).fetchone()
            if alias is not None:
                origin_id = str(alias["canonical_conversation_id"])
            child_conversation_id = new_id()
            timestamp = now()
            connection.execute(
                "INSERT INTO conversations(id, user_id, agent_id, title, kind, created_at, updated_at) VALUES (?, ?, ?, ?, 'delegated', ?, ?)",
                (child_conversation_id, user_id, child_agent_id, f"Delegated: {prompt[:70]}", timestamp, timestamp),
            )
            source_message = None
            if parent["message_id"]:
                source_message = connection.execute(
                    "SELECT metadata_json FROM messages WHERE id = ? AND user_id = ?",
                    (parent["message_id"], user_id),
                ).fetchone()
            parent_conversation = connection.execute(
                "SELECT kind, status FROM conversations WHERE id = ? AND user_id = ?",
                (parent["conversation_id"], user_id),
            ).fetchone()
            inherited_attachments = []
            if source_message is not None:
                decoded = json.loads(source_message["metadata_json"] or "{}")
                inherited_attachments = [str(item.get("file_id")) for item in decoded.get("attachments", []) if isinstance(item, Mapping) and item.get("file_id")]
            child_message_id = new_id()
            child_request = str(parent["request_id"] or uuid4())
            metadata = {"request_id": child_request, "delegated_from_task_id": parent_task_id, "origin_conversation_id": origin_id}
            if inherited_attachments:
                metadata["attachments"] = []
                for file_id in inherited_attachments:
                    file = connection.execute(
                        "SELECT id, agent_id, relative_path, content_type FROM files WHERE id = ? AND user_id = ?",
                        (file_id, user_id),
                    ).fetchone()
                    if file is None:
                        continue
                    allowed_parent_file = str(file["agent_id"]) == str(parent["agent_id"])
                    if parent_conversation is not None and str(parent_conversation["kind"] or "direct") == "group":
                        grant = connection.execute(
                            "SELECT 1 FROM conversation_file_grants WHERE user_id = ? AND conversation_id = ? "
                            "AND file_id = ? AND revoked_at IS NULL",
                            (user_id, parent["conversation_id"], file_id),
                        ).fetchone()
                        member = connection.execute(
                            "SELECT 1 FROM conversation_members WHERE user_id = ? AND conversation_id = ? "
                            "AND agent_id = ? AND status = 'active'",
                            (user_id, parent["conversation_id"], parent["agent_id"]),
                        ).fetchone()
                        allowed_parent_file = grant is not None and member is not None
                    if not allowed_parent_file:
                        continue
                    path = str(file["relative_path"])
                    metadata["attachments"].append({"file_id": str(file["id"]), "path": path, "name": PurePosixPath(path).name, "content_type": str(file["content_type"])})
                    connection.execute(
                        "INSERT OR IGNORE INTO conversation_file_grants(user_id, conversation_id, file_id, granted_by_agent_id, created_at) VALUES (?, ?, ?, ?, ?)",
                        (user_id, child_conversation_id, file_id, str(parent["agent_id"]), timestamp),
                    )
            connection.execute(
                "INSERT INTO messages(id, conversation_id, user_id, role, content, status, metadata_json, created_at, request_id, origin_conversation_id) "
                "VALUES (?, ?, ?, 'user', ?, 'completed', ?, ?, ?, ?)",
                (child_message_id, child_conversation_id, user_id, prompt, json.dumps(metadata, separators=(",", ":"), ensure_ascii=False), timestamp, child_request, origin_id),
            )
            child_task_id = new_id()
            connection.execute(
                "INSERT INTO tasks(id, user_id, conversation_id, agent_id, message_id, status, created_at, updated_at, kind, request_id, parent_task_id, origin_conversation_id) "
                "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, 'delegated', ?, ?, ?)",
                (child_task_id, user_id, child_conversation_id, child_agent_id, child_message_id, timestamp, timestamp, child_request, parent_task_id, origin_id),
            )
            connection.execute(
                "INSERT INTO tool_task_lineage(child_task_id, parent_task_id, user_id, parent_agent_id, child_agent_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (child_task_id, parent_task_id, user_id, parent["agent_id"], child_agent_id, timestamp),
            )
            parent_agent = connection.execute(
                "SELECT name FROM agents WHERE id = ? AND user_id = ?",
                (parent["agent_id"], user_id),
            ).fetchone()
            parent_name = str(parent_agent["name"] if parent_agent else "The parent bot")
            child_name = str(child_agent["name"])
            handoff_text = f"{parent_name} asked {child_name} to help."
            handoff_metadata = {
                "collaboration_handoff": True,
                "parent_task_id": parent_task_id,
                "child_task_id": child_task_id,
                "author_agent_id": str(parent["agent_id"]),
                "parent_agent_id": str(parent["agent_id"]),
                "helper_agent_id": child_agent_id,
                "request_id": child_request,
                "origin_conversation_id": origin_id,
            }
            connection.execute(
                "INSERT INTO messages(id, conversation_id, user_id, role, content, status, metadata_json, created_at, "
                "author_agent_id, request_id, origin_conversation_id) VALUES (?, ?, ?, 'system', ?, 'completed', ?, ?, ?, ?, ?)",
                (
                    new_id(),
                    origin_id,
                    user_id,
                    handoff_text,
                    json.dumps(handoff_metadata, separators=(",", ":"), ensure_ascii=False),
                    timestamp,
                    parent["agent_id"],
                    child_request,
                    origin_id,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id IN (?, ?)",
                (timestamp, child_conversation_id, origin_id),
            )
            self._ensure_state(connection, user_id, child_conversation_id)
            task_row = connection.execute(f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = ?", (child_task_id,)).fetchone()
            message_row = connection.execute(f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE id = ?", (child_message_id,)).fetchone()
            child_conversation = connection.execute(
                "SELECT id, user_id, agent_id, title, status, created_at, updated_at, kind FROM conversations WHERE id = ?",
                (child_conversation_id,),
            ).fetchone()
        return {
            "message": _message(message_row),
            "task": _task(task_row),
            "conversation": dict(child_conversation),
        }

    def request_task_ids(self, user_id: str, conversation_id: str, request_id: str) -> list[str]:
        user_id = str(user_id)
        canonical_id = self._resolve(user_id, conversation_id)
        request_id = _clean_id(request_id, field="request_id")
        # Explicit request cancellation may need a legacy root that already
        # has a lineage child.  Such a physical alias is excluded from human
        # history aggregation, but the owner can still address its durable
        # request by ID.
        scope = self.store.conversation_alias_ids(user_id, canonical_id)
        placeholders = ",".join("?" for _ in scope)
        with self.store.db.read() as connection:
            roots = connection.execute(
                f"SELECT id FROM tasks WHERE user_id = ? AND conversation_id IN ({placeholders}) AND request_id = ? AND parent_task_id IS NULL ORDER BY created_at, rowid",
                (user_id, *scope, request_id),
            ).fetchall()
            result = [str(row["id"]) for row in roots]
            frontier = list(result)
            while frontier:
                child_rows = connection.execute(
                    "SELECT child_task_id FROM tool_task_lineage WHERE user_id = ? AND parent_task_id IN (" + ",".join("?" for _ in frontier) + ") ORDER BY created_at, child_task_id",
                    (user_id, *frontier),
                ).fetchall()
                next_frontier = []
                for row in child_rows:
                    child = str(row["child_task_id"])
                    if child not in result:
                        result.append(child)
                        next_frontier.append(child)
                frontier = next_frontier
        return result

