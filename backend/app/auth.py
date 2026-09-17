"""Telegram nonce exchange and persistent session management."""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .db import Database
from .security import hash_token, new_opaque_token


@dataclass(frozen=True)
class Session:
    id: str
    user_id: str
    created_at: int
    last_seen_at: int
    expires_at: int
    # This is an internal signal for the HTTP layer.  It is deliberately not
    # part of the public session representation returned by ``as_dict``.
    cookie_refresh: bool = field(default=False, repr=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "expires_at": self.expires_at,
        }


def _now() -> int:
    return int(time.time())


def _row_session(row: sqlite3.Row) -> Session:
    return Session(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        created_at=int(row["created_at"]),
        last_seen_at=int(row["last_seen_at"]),
        expires_at=int(row["expires_at"]),
    )


class AuthManager:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    def create_nonce(
        self, user_id: str, *, source_chat_id: str | None = None
    ) -> dict[str, Any]:
        now = _now()
        expires_at = now + self.settings.nonce_ttl_seconds
        raw_nonce = new_opaque_token(32)
        nonce_id = str(uuid.uuid4())
        nonce_hash = hash_token(raw_nonce, self.settings.internal_secret)
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM auth_nonces WHERE expires_at < ? OR consumed_at IS NOT NULL",
                (now - 3600,),
            )
            connection.execute(
                "INSERT INTO auth_nonces(id, nonce_hash, user_id, created_at, expires_at, source_chat_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nonce_id, nonce_hash, user_id, now, expires_at, source_chat_id),
            )
        base = self.settings.public_base_url
        login_url = None
        if base:
            login_url = f"{base}/bot/#nonce={raw_nonce}"
        return {
            "nonce": raw_nonce,
            "nonce_id": nonce_id,
            "user_id": user_id,
            "expires_at": expires_at,
            "url": login_url,
        }

    def exchange(
        self,
        raw_nonce: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[str, Session]:
        if not raw_nonce or len(raw_nonce) > 512:
            raise ValueError("invalid nonce")
        now = _now()
        nonce_hash = hash_token(raw_nonce, self.settings.internal_secret)
        session_token = new_opaque_token(48)
        session_hash = hash_token(session_token, self.settings.session_secret)
        session_id = str(uuid.uuid4())
        expires_at = now + self.settings.session_ttl_seconds
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT id, user_id FROM auth_nonces "
                "WHERE nonce_hash = ? AND consumed_at IS NULL AND expires_at > ?",
                (nonce_hash, now),
            ).fetchone()
            if row is None:
                raise ValueError("invalid or expired nonce")
            consumed = connection.execute(
                "UPDATE auth_nonces SET consumed_at = ? "
                "WHERE id = ? AND consumed_at IS NULL AND expires_at > ?",
                (now, row["id"], now),
            )
            if consumed.rowcount != 1:
                raise ValueError("invalid or expired nonce")
            connection.execute(
                "INSERT INTO sessions(id, token_hash, user_id, created_at, last_seen_at, expires_at, user_agent, ip_address) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    session_hash,
                    row["user_id"],
                    now,
                    now,
                    expires_at,
                    user_agent[:512] if user_agent else None,
                    ip_address[:128] if ip_address else None,
                ),
            )
        session = Session(session_id, str(row["user_id"]), now, now, expires_at)
        return session_token, session

    def get_session(self, session_token: str | None) -> Session | None:
        if not session_token:
            return None
        token_hash = hash_token(session_token, self.settings.session_secret)
        now = _now()
        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT id, user_id, created_at, last_seen_at, expires_at FROM sessions "
                "WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > ?",
                (token_hash, now),
            ).fetchone()
            if row is None:
                return None
            # Avoid writing on every static asset/SSE poll while still keeping
            # activity useful for revocation and operational inspection.  The
            # expiry is an inactivity deadline, so renew both values together
            # at the same bounded cadence.
            refresh_due = now - int(row["last_seen_at"]) >= self.settings.session_refresh_interval_seconds
            if refresh_due:
                refreshed_expires_at = now + self.settings.session_ttl_seconds
                updated = connection.execute(
                    "UPDATE sessions SET last_seen_at = ?, expires_at = ? "
                    "WHERE id = ? AND revoked_at IS NULL AND expires_at > ?",
                    (now, refreshed_expires_at, row["id"], now),
                )
                if updated.rowcount != 1:
                    # A concurrent revoke-all/revoke may have invalidated the
                    # session after the initial lookup.
                    return None
                row = dict(row)
                row["last_seen_at"] = now
                row["expires_at"] = refreshed_expires_at
            session = _row_session(row if isinstance(row, sqlite3.Row) else _DictRow(row))
            if refresh_due:
                session = Session(
                    session.id,
                    session.user_id,
                    session.created_at,
                    session.last_seen_at,
                    session.expires_at,
                    cookie_refresh=True,
                )
            return session

    def revoke(self, session_id: str) -> None:
        with self.db.transaction(immediate=True) as connection:
            connection.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (_now(), session_id))

    def list_sessions(self, user_id: str) -> list[Session]:
        now = _now()
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT id, user_id, created_at, last_seen_at, expires_at FROM sessions "
                "WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ? ORDER BY last_seen_at DESC",
                (user_id, now),
            ).fetchall()
        return [_row_session(row) for row in rows]

    def revoke_owned(self, user_id: str, session_id: str) -> bool:
        with self.db.transaction(immediate=True) as connection:
            result = connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
                (_now(), session_id, user_id),
            )
            return result.rowcount == 1

    def revoke_all(self, user_id: str) -> int:
        with self.db.transaction(immediate=True) as connection:
            result = connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (_now(), user_id),
            )
            return result.rowcount


class _DictRow(dict):
    """Minimal Row-compatible mapping for a row updated in Python."""

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)

