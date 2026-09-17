"""SQLite persistence and migrations for bot mode."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2

MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_nonces (
    id TEXT PRIMARY KEY,
    nonce_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    consumed_at INTEGER,
    source_chat_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_auth_nonces_expiry ON auth_nonces(expires_at, consumed_at);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    revoked_at INTEGER,
    user_agent TEXT,
    ip_address TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, revoked_at, expires_at);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    instructions TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    desktop_state TEXT NOT NULL DEFAULT 'unavailable',
    desktop_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agents_user ON agents(user_id, updated_at);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    error_code TEXT,
    error_message TEXT,
    runtime_task_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, updated_at);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_task ON approvals(task_id, status);

CREATE TABLE IF NOT EXISTS memory_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    agent_id TEXT,
    scope TEXT NOT NULL CHECK (scope IN ('shared', 'private')),
    memory_key TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    confidence REAL NOT NULL DEFAULT 1.0,
    supersedes_id INTEGER REFERENCES memory_entries(id) ON DELETE SET NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    deleted_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_memory_acl ON memory_entries(user_id, scope, agent_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_memory_supersedes ON memory_entries(supersedes_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    memory_key,
    source,
    content='memory_entries',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS memory_entries_ai AFTER INSERT ON memory_entries BEGIN
    INSERT INTO memory_fts(rowid, content, memory_key, source)
    VALUES (new.id, new.content, new.memory_key, new.source);
END;
CREATE TRIGGER IF NOT EXISTS memory_entries_ad AFTER DELETE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, memory_key, source)
    VALUES ('delete', old.id, old.content, old.memory_key, old.source);
END;
CREATE TRIGGER IF NOT EXISTS memory_entries_au AFTER UPDATE OF content, memory_key, source ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, memory_key, source)
    VALUES ('delete', old.id, old.content, old.memory_key, old.source);
    INSERT INTO memory_fts(rowid, content, memory_key, source)
    VALUES (new.id, new.content, new.memory_key, new.source);
END;

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(user_id, agent_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_files_scope ON files(user_id, agent_id, updated_at);

CREATE TABLE IF NOT EXISTS settings (
    user_id TEXT NOT NULL,
    setting_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(user_id, setting_key)
);

CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_events(user_id, id);
"""

# Identity fields were added after the initial schema shipped. They are
# nullable so databases created before the creator existed keep their current
# behavior and the frontend can provide a deterministic visual fallback.
MIGRATION_2 = ("avatar", "color")

# Messenger state is intentionally additive.  The original schema is already
# deployed by the standalone backend and its public migration number is kept
# at 2 for compatibility with older startup checks.  ``_ensure_messenger`` is
# run for both new and already migrated databases below; every statement is
# idempotent so an interrupted/older upgrade can safely resume.
MIGRATION_MESSENGER = """
CREATE TABLE IF NOT EXISTS conversation_homes (
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, agent_id),
    UNIQUE (user_id, conversation_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_homes_conversation
    ON conversation_homes(user_id, conversation_id);

CREATE TABLE IF NOT EXISTS conversation_aliases (
    user_id TEXT NOT NULL,
    alias_conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    canonical_conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    alias_kind TEXT NOT NULL DEFAULT 'direct',
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, alias_conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_conversation_aliases_canonical
    ON conversation_aliases(user_id, canonical_conversation_id, alias_conversation_id);

CREATE TABLE IF NOT EXISTS conversation_groups (
    conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    coordinator_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation_groups_user
    ON conversation_groups(user_id, updated_at);

CREATE TABLE IF NOT EXISTS conversation_members (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'coordinator')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
    joined_at INTEGER NOT NULL,
    removed_at INTEGER,
    PRIMARY KEY (conversation_id, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_conversation_members_active
    ON conversation_members(user_id, conversation_id, status, agent_id);

CREATE TABLE IF NOT EXISTS conversation_inbox (
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    read_through_message_id TEXT,
    read_through_created_at INTEGER,
    read_through_rowid INTEGER,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_conversation_inbox_order
    ON conversation_inbox(user_id, archived, pinned, updated_at);

CREATE TABLE IF NOT EXISTS message_requests (
    user_id TEXT NOT NULL,
    canonical_conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    client_request_id TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    body_fingerprint TEXT NOT NULL,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, canonical_conversation_id, client_request_id)
);
CREATE INDEX IF NOT EXISTS idx_message_requests_message
    ON message_requests(user_id, message_id);

CREATE TABLE IF NOT EXISTS message_collaboration_links (
    user_id TEXT NOT NULL,
    origin_conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    source_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    request_id TEXT NOT NULL,
    message_id TEXT NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, origin_conversation_id, source_task_id, request_id)
);
CREATE INDEX IF NOT EXISTS idx_collaboration_links_message
    ON message_collaboration_links(user_id, message_id);

CREATE TABLE IF NOT EXISTS conversation_file_grants (
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    granted_by_agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    created_at INTEGER NOT NULL,
    revoked_at INTEGER,
    PRIMARY KEY (user_id, conversation_id, file_id)
);
CREATE INDEX IF NOT EXISTS idx_conversation_file_grants_file
    ON conversation_file_grants(user_id, file_id, revoked_at);
"""


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Add one compatible column when upgrading an existing SQLite file."""

    columns = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_messenger_schema(connection: sqlite3.Connection) -> None:
    # These columns make the new public metadata queryable while preserving
    # the existing JSON metadata object and all physical foreign keys.
    _ensure_column(connection, "conversations", "kind", "TEXT NOT NULL DEFAULT 'direct'")
    _ensure_column(connection, "messages", "author_agent_id", "TEXT")
    _ensure_column(connection, "messages", "source_task_id", "TEXT")
    _ensure_column(connection, "messages", "request_id", "TEXT")
    _ensure_column(connection, "messages", "origin_conversation_id", "TEXT")
    _ensure_column(connection, "messages", "reply_to_id", "TEXT")
    _ensure_column(connection, "tasks", "kind", "TEXT NOT NULL DEFAULT 'direct'")
    _ensure_column(connection, "tasks", "request_id", "TEXT")
    _ensure_column(connection, "tasks", "parent_task_id", "TEXT")
    _ensure_column(connection, "tasks", "origin_conversation_id", "TEXT")
    connection.executescript(MIGRATION_MESSENGER)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_request ON messages(user_id, request_id, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_request ON tasks(user_id, conversation_id, request_id, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_kind ON conversations(user_id, kind, updated_at)"
    )


def json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def json_loads(value: str, default: Any = None) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class Database:
    """A small per-operation connection pool backed by SQLite WAL."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.fts_available = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=15,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def migrate(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            current = int(row["version"] if row else 0)
            if current < 1:
                try:
                    connection.executescript(MIGRATION_1)
                    connection.execute(
                        "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES(1, strftime('%s','now'))"
                    )

                except sqlite3.OperationalError as exc:
                    if "fts5" not in str(exc).lower():
                        raise
                    # Keep the rest of the schema usable on a Python build
                    # without FTS5; search.py falls back to parameterized LIKE.
                    self.fts_available = False
                    connection.executescript(MIGRATION_1.replace(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(\n"
                        "    content,\n"
                        "    memory_key,\n"
                        "    source,\n"
                        "    content='memory_entries',\n"
                        "    content_rowid='id'\n"
                        ");",
                        "",
                    ).replace(
                        "CREATE TRIGGER IF NOT EXISTS memory_entries_ai AFTER INSERT ON memory_entries BEGIN\n"
                        "    INSERT INTO memory_fts(rowid, content, memory_key, source)\n"
                        "    VALUES (new.id, new.content, new.memory_key, new.source);\nEND;\n"
                        "CREATE TRIGGER IF NOT EXISTS memory_entries_ad AFTER DELETE ON memory_entries BEGIN\n"
                        "    INSERT INTO memory_fts(memory_fts, rowid, content, memory_key, source)\n"
                        "    VALUES ('delete', old.id, old.content, old.memory_key, old.source);\nEND;\n"
                        "CREATE TRIGGER IF NOT EXISTS memory_entries_au AFTER UPDATE OF content, memory_key, source ON memory_entries BEGIN\n"
                        "    INSERT INTO memory_fts(memory_fts, rowid, content, memory_key, source)\n"
                        "    VALUES ('delete', old.id, old.content, old.memory_key, old.source);\n"
                        "    INSERT INTO memory_fts(rowid, content, memory_key, source)\n"
                        "    VALUES (new.id, new.content, new.memory_key, new.source);\nEND;\n",
                        "",
                    ))
                    connection.execute(
                        "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES(1, strftime('%s','now'))"
                    )

            if current < 2:
                agent_columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(agents)").fetchall()
                }
                for column in MIGRATION_2:
                    if column not in agent_columns:
                        connection.execute(f"ALTER TABLE agents ADD COLUMN {column} TEXT")
                connection.execute(
                    "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES(2, strftime('%s','now'))"
                )

            # Messenger tables/columns are additive and are also required for
            # databases that already recorded version 2 before this feature.
            _ensure_messenger_schema(connection)
            # Existing installations also need the correction lookup index.
            connection.execute("CREATE INDEX IF NOT EXISTS idx_memory_supersedes ON memory_entries(supersedes_id)")

    @contextlib.contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @contextlib.contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

