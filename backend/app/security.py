"""Hashing and constant-time comparison helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def new_opaque_token(size: int = 32) -> str:
    return secrets.token_urlsafe(size)


def hash_token(token: str, secret: str | None = None) -> str:
    """Return a non-reversible token hash suitable for SQLite storage.

    HMAC is used when a service secret is available, which prevents a database
    reader from testing arbitrary token guesses without also knowing the
    service secret.  SHA-256 remains useful for nonce values in test fixtures.
    """

    raw = token.encode("utf-8")
    if secret:
        return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hashlib.sha256(raw).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def safe_user_key(user_id: str) -> str:
    """Stable filesystem key that cannot contain path separators."""

    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]


