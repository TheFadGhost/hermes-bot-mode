"""Bounded working context over an intact, searchable conversation archive."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

from .errors import APIError
from .store import Store, _message

RECENT_CHAR_BUDGET = 14_000
RETRIEVAL_CHAR_BUDGET = 6_000
STOP_WORDS = set("a an and are as at be been but by can could did do does for from had has have how i if in into is it its me my of on or our please said say so some that the their them then there these they this to us was we were what when where which who why will with would you your remember earlier before about tell know".split())


def search_terms(query: str) -> list[str]:
    words = re.findall(r"[\w-]{2,}", query.casefold(), flags=re.UNICODE)
    useful = list(dict.fromkeys(word for word in words if word not in STOP_WORDS))
    return sorted(useful, key=lambda word: (-len(word), useful.index(word)))[:10]


def bounded_records(records: list[dict[str, Any]], budget: int, *, newest: bool = False) -> str:
    selected: list[dict[str, Any]] = []
    source = reversed(records) if newest else iter(records)
    for row in source:
        item = {key: row.get(key) for key in ("id", "role", "author_agent_id", "created_at", "content") if row.get(key) is not None}
        item["content"] = str(item.get("content", ""))[:4000]
        trial = [item, *selected] if newest else [*selected, item]
        if len(json.dumps(trial, ensure_ascii=False)) > budget:
            continue
        selected = trial
    return json.dumps(selected, ensure_ascii=False, separators=(",", ":"))


class History:
    def __init__(self, store: Store, messenger: Any):
        self.store = store
        self.messenger = messenger
        self.fts = True
        with store.db.transaction(immediate=True) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='message_archive_fts'").fetchone()
            try:
                db.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS message_archive_fts USING fts5(content, content='messages', content_rowid='rowid');
                CREATE TRIGGER IF NOT EXISTS message_archive_insert AFTER INSERT ON messages BEGIN
                  INSERT INTO message_archive_fts(rowid,content) VALUES(new.rowid,new.content); END;
                CREATE TRIGGER IF NOT EXISTS message_archive_delete AFTER DELETE ON messages BEGIN
                  INSERT INTO message_archive_fts(message_archive_fts,rowid,content) VALUES('delete',old.rowid,old.content); END;
                CREATE TRIGGER IF NOT EXISTS message_archive_update AFTER UPDATE OF content ON messages BEGIN
                  INSERT INTO message_archive_fts(message_archive_fts,rowid,content) VALUES('delete',old.rowid,old.content);
                  INSERT INTO message_archive_fts(rowid,content) VALUES(new.rowid,new.content); END;
                """)
                if not exists:
                    db.execute("INSERT INTO message_archive_fts(message_archive_fts) VALUES('rebuild')")
            except sqlite3.OperationalError as exc:
                if "fts5" not in str(exc).lower():
                    raise
                self.fts = False
            db.execute("""CREATE TABLE IF NOT EXISTS context_records(
                task_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                recent_chars INTEGER NOT NULL, retrieval_chars INTEGER NOT NULL,
                source_ids_json TEXT NOT NULL, compacted_at INTEGER, created_at INTEGER NOT NULL)""")

    def _scope(self, user_id: str, conversation_id: str, agent_id: str | None = None) -> list[str]:
        if agent_id and not self.messenger.can_respond(user_id, conversation_id, agent_id):
            raise APIError(403, "history_scope", "This bot is not a member of this conversation")
        return self.messenger.scope_ids(user_id, conversation_id)

    def search(self, user_id: str, conversation_id: str, query: str, *, agent_id: str | None = None, limit: int = 15, exclude_ids: set[str] | None = None, before_position: int | None = None) -> list[dict[str, Any]]:
        scope = self._scope(user_id, conversation_id, agent_id)
        terms = search_terms(query[:1000])
        if not terms:
            return []
        limit = max(1, min(30, limit))
        placeholders = ",".join("?" for _ in scope)
        with self.store.db.read() as db:
            if self.fts:
                expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
                rows = db.execute(f"""SELECT m.*,m.rowid AS archive_position FROM messages m
                    JOIN message_archive_fts f ON f.rowid=m.rowid
                    WHERE message_archive_fts MATCH ? AND m.user_id=? AND m.conversation_id IN ({placeholders}) AND m.rowid < ?
                    ORDER BY bm25(message_archive_fts),m.created_at DESC,m.rowid DESC LIMIT ?""",
                    (expression, user_id, *scope, before_position or 9223372036854775807, limit + len(exclude_ids or ()))) .fetchall()
            else:
                match = " OR ".join("lower(content) LIKE ? ESCAPE '\\'" for _ in terms)
                patterns = ["%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for term in terms]
                rows = db.execute(f"SELECT *,rowid AS archive_position FROM messages WHERE user_id=? AND conversation_id IN ({placeholders}) AND ({match}) AND rowid < ? ORDER BY created_at DESC,rowid DESC LIMIT ?", (user_id, *scope, *patterns, before_position or 9223372036854775807, limit + len(exclude_ids or ()))).fetchall()
        result = []
        for row in rows:
            item = _message(row)
            if item["id"] in (exclude_ids or set()):
                continue
            item["origin_conversation_id"] = item["conversation_id"]
            item["author_agent_id"] = item.get("metadata", {}).get("author_agent_id")
            item["excerpt"] = item["content"][:700]
            result.append(item)
            if len(result) >= limit:
                break
        return result

    def read(self, user_id: str, conversation_id: str, message_ids: list[str], *, agent_id: str | None = None, surrounding: int = 0) -> list[dict[str, Any]]:
        scope = self._scope(user_id, conversation_id, agent_id)
        if not message_ids or len(message_ids) > 20:
            raise APIError(422, "history_ids", "Choose between one and twenty message IDs")
        markers = ",".join("?" for _ in scope)
        found: dict[str, dict[str, Any]] = {}
        with self.store.db.read() as db:
            for message_id in dict.fromkeys(message_ids):
                row = db.execute(f"SELECT *,rowid AS archive_position FROM messages WHERE id=? AND user_id=? AND conversation_id IN ({markers})", (message_id, user_id, *scope)).fetchone()
                if row is None:
                    raise APIError(404, "message_not_found", "A message was not found in this conversation")
                found[row["id"]] = _message(row)
                for operator, order in (("<", "DESC"), (">", "ASC")):
                    if surrounding:
                        neighbours = db.execute(f"SELECT *,rowid AS archive_position FROM messages WHERE user_id=? AND conversation_id IN ({markers}) AND (created_at {operator} ? OR (created_at=? AND rowid {operator} ?)) ORDER BY created_at {order},rowid {order} LIMIT ?", (user_id, *scope, row["created_at"], row["created_at"], row["archive_position"], min(5, max(0, surrounding)))).fetchall()
                        for item in neighbours:
                            found[item["id"]] = _message(item)
        return sorted(found.values(), key=lambda item: (item["created_at"], item["archive_position"]))

    def recent(self, user_id: str, conversation_id: str, message_id: str, *, agent_id: str) -> list[dict[str, Any]]:
        scope = self._scope(user_id, conversation_id, agent_id)
        target = self.read(user_id, conversation_id, [message_id], agent_id=agent_id)[0]
        markers = ",".join("?" for _ in scope)
        with self.store.db.read() as db:
            rows = db.execute(f"SELECT *,rowid AS archive_position FROM messages WHERE user_id=? AND conversation_id IN ({markers}) AND (created_at < ? OR (created_at=? AND rowid < ?)) ORDER BY created_at DESC,rowid DESC LIMIT 60", (user_id, *scope, target["created_at"], target["created_at"], target["archive_position"])).fetchall()
        selected = []
        used = 0
        for row in rows:
            item = _message(row)
            size = len(item["content"])
            if used + size > RECENT_CHAR_BUDGET:
                continue
            selected.append(item)
            used += size
        selected.reverse()
        return [*selected, target]

    def prepare(self, user_id: str, conversation_id: str, agent_id: str, task_id: str, message_id: str) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        recent = self.recent(user_id, conversation_id, message_id, agent_id=agent_id)
        hits = self.search(user_id, conversation_id, recent[-1]["content"], agent_id=agent_id, limit=8, exclude_ids={item["id"] for item in recent}, before_position=recent[-1]["archive_position"])
        retrieval = bounded_records(hits, RETRIEVAL_CHAR_BUDGET)
        ids = [item["id"] for item in recent[:-1]] + [item["id"] for item in json.loads(retrieval)]
        metrics = {"recent_chars": sum(len(item["content"]) for item in recent[:-1]), "retrieval_chars": len(retrieval), "source_ids": ids, "archive_retained": True}
        with self.store.db.transaction() as db:
            db.execute("INSERT OR REPLACE INTO context_records(task_id,conversation_id,agent_id,recent_chars,retrieval_chars,source_ids_json,created_at) VALUES(?,?,?,?,?,?,?)", (task_id, conversation_id, agent_id, metrics["recent_chars"], metrics["retrieval_chars"], json.dumps(ids), int(time.time())))
        return recent, retrieval, metrics

    def compacted(self, task_id: str) -> None:
        with self.store.db.transaction() as db:
            db.execute("UPDATE context_records SET compacted_at=? WHERE task_id=?", (int(time.time()), task_id))

