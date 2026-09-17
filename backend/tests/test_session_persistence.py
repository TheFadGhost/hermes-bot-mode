from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.auth import AuthManager
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.security import hash_token


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_path": tmp_path / "bot.sqlite3",
        "workspace_root": tmp_path / "workspaces",
        "internal_secret": "internal-secret-" + "i" * 32,
        "session_secret": "session-secret-" + "s" * 32,
        "allowed_origins": ("http://testserver",),
        "cookie_secure": False,
    }
    values.update(overrides)
    return Settings(**values)


def issue_session(auth: AuthManager, user_id: str = "owner") -> tuple[str, object]:
    nonce = auth.create_nonce(user_id)["nonce"]
    return auth.exchange(nonce)


def test_session_expiry_rolls_at_a_bounded_cadence_and_expires_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1_000_000]
    monkeypatch.setattr(auth_module, "_now", lambda: clock[0])
    settings = make_settings(tmp_path, session_ttl_seconds=180, session_refresh_interval_seconds=60)
    auth = AuthManager(Database(settings.database_path), settings)

    token, issued = issue_session(auth)
    assert issued.expires_at == 1_000_180

    clock[0] += 30
    active = auth.get_session(token)
    assert active is not None
    assert active.expires_at == issued.expires_at
    assert active.cookie_refresh is False

    clock[0] += 31
    renewed = auth.get_session(token)
    assert renewed is not None
    assert renewed.expires_at == clock[0] + settings.session_ttl_seconds
    assert renewed.last_seen_at == clock[0]
    assert renewed.cookie_refresh is True

    clock[0] = renewed.expires_at
    assert auth.get_session(token) is None


def test_active_request_renews_scoped_persistent_cookie(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, session_ttl_seconds=3600, session_refresh_interval_seconds=60)
    with TestClient(create_app(settings)) as client:
        issued = client.post(
            "/bot/api/internal/auth/nonce",
            headers={"Authorization": "Bearer " + settings.internal_secret},
            json={"user_id": "owner"},
        )
        exchanged = client.post(
            "/bot/api/auth/exchange",
            headers={"Origin": "http://testserver"},
            json={"nonce": issued.json()["nonce"]},
        )
        assert exchanged.status_code == 200
        set_cookie = exchanged.headers["set-cookie"]
        assert "Max-Age=3600" in set_cookie
        assert "expires=" in set_cookie.lower()
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert "Path=/bot" in set_cookie

        time.sleep(1.05)
        token = client.cookies.get(settings.cookie_name)
        assert token
        token_hash = hash_token(token, settings.session_secret)
        with client.app.state.db.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                (int(time.time()) - 120, token_hash),
            )

        response = client.get("/bot/api/auth/me")
        assert response.status_code == 200
        refreshed_cookie = response.headers["set-cookie"]
        assert "Max-Age=3600" in refreshed_cookie
        assert "expires=" in refreshed_cookie.lower()
        assert "HttpOnly" in refreshed_cookie
        assert "SameSite=lax" in refreshed_cookie
        assert "Path=/bot" in refreshed_cookie
        assert response.json()["session"]["expires_at"] > exchanged.json()["session"]["expires_at"]


def test_revoking_current_session_deletes_cookie_and_blocks_reuse(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        issued = client.post(
            "/bot/api/internal/auth/nonce",
            headers={"X-Bot-Internal-Secret": settings.internal_secret},
            json={"user_id": "owner"},
        )
        exchanged = client.post(
            "/bot/api/auth/exchange",
            headers={"Origin": "http://testserver"},
            json={"nonce": issued.json()["nonce"]},
        )
        session_id = exchanged.json()["session"]["id"]

        revoked = client.post(
            f"/bot/api/auth/sessions/{session_id}/revoke",
            headers={"Origin": "http://testserver"},
        )
        assert revoked.status_code == 200
        assert "Max-Age=0" in revoked.headers["set-cookie"]
        assert client.get("/bot/api/auth/me").status_code == 401

