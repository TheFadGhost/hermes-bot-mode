from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthManager
from app.config import ConfigurationError, Settings
from app.db import Database
from app.main import create_app


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


def login(client: TestClient, settings: Settings, user_id: str = "owner") -> None:
    issued = client.post(
        "/bot/api/internal/auth/nonce",
        headers={"Authorization": "Bearer " + settings.internal_secret},
        json={"user_id": user_id},
    )
    assert issued.status_code == 201
    exchanged = client.post(
        "/bot/api/auth/exchange",
        headers={"Origin": "http://testserver"},
        json={"nonce": issued.json()["nonce"]},
    )
    assert exchanged.status_code == 200, exchanged.text


def create_agent_and_conversation(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/bot/api/agents",
        headers={"Origin": "http://testserver"},
        json={"name": "Dad", "instructions": "Be useful"},
    )
    assert created.status_code == 201
    agent_id = created.json()["agent"]["id"]
    conversation = client.post(
        "/bot/api/conversations",
        headers={"Origin": "http://testserver"},
        json={"agent_id": agent_id, "title": "First chat"},
    )
    assert conversation.status_code == 201
    return agent_id, conversation.json()["conversation"]["id"]


def test_agent_avatar_identity_round_trips_and_survives_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    payload = {
        "name": "Night Shift",
        "instructions": "Prepare a morning digest and ask before external actions.",
        "avatar": "lozenge",
        "color": "#ff9d0a",
    }
    with TestClient(create_app(settings)) as client:
        login(client, settings)
        created = client.post(
            "/bot/api/agents",
            headers={"Origin": "http://testserver"},
            json=payload,
        )
        assert created.status_code == 201, created.text
        agent = created.json()["agent"]
        assert agent["avatar"] == payload["avatar"]
        assert agent["color"] == payload["color"]

        updated = client.patch(
            f"/bot/api/agents/{agent['id']}",
            headers={"Origin": "http://testserver"},
            json={"avatar": "cloud", "color": "#ff36a0"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["agent"]["avatar"] == "cloud"
        assert updated.json()["agent"]["color"] == "#ff36a0"

    with TestClient(create_app(settings)) as restarted:
        login(restarted, settings)
        agents = restarted.get("/bot/api/agents")
        assert agents.status_code == 200
        persisted = next(item for item in agents.json()["agents"] if item["id"] == agent["id"])
        assert persisted["avatar"] == "cloud"
        assert persisted["color"] == "#ff36a0"


def test_agent_identity_migration_adds_nullable_columns(tmp_path: Path) -> None:
    database = Database(tmp_path / "identity-migration.sqlite3")
    with database.read() as connection:
        columns = {str(row["name"]): row for row in connection.execute("PRAGMA table_info(agents)").fetchall()}
        version = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()["version"]
    assert {"avatar", "color"}.issubset(columns)
    assert version == 2


def test_nonce_is_one_time_and_session_can_be_revoked(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        issued = client.post(
            "/bot/api/internal/auth/nonce",
            headers={"X-Bot-Internal-Secret": settings.internal_secret},
            json={"user_id": "123"},
        )
        assert issued.status_code == 201
        nonce = issued.json()["nonce"]
        first = client.post("/bot/api/auth/exchange", headers={"Origin": "http://testserver"}, json={"nonce": nonce})
        assert first.status_code == 200
        assert "HttpOnly" in first.headers["set-cookie"]
        assert "Path=/bot" in first.headers["set-cookie"]
        replay = client.post("/bot/api/auth/exchange", headers={"Origin": "http://testserver"}, json={"nonce": nonce})
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "nonce_invalid"
        assert client.get("/bot/api/auth/me").status_code == 200
        logged_out = client.post("/bot/api/auth/logout", headers={"Origin": "http://testserver"})
        assert logged_out.status_code == 200
        assert client.get("/bot/api/auth/me").status_code == 401


def test_expired_nonce_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, nonce_ttl_seconds=1)
    with TestClient(create_app(settings)) as client:
        issued = client.post(
            "/bot/api/internal/auth/nonce",
            headers={"Authorization": "Bearer " + settings.internal_secret},
            json={"user_id": "123"},
        )
        assert issued.status_code == 201
        time.sleep(1.05)
        response = client.post(
            "/bot/api/auth/exchange",
            headers={"Origin": "http://testserver"},
            json={"nonce": issued.json()["nonce"]},
        )
        assert response.status_code == 401


def test_cookie_mutation_checks_origin(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, settings)
        response = client.post("/bot/api/auth/logout", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "origin_forbidden"
        assert client.get("/bot/api/auth/me").status_code == 200


def test_private_memory_is_scoped_to_agent(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        login(client, settings)
        first = client.post("/bot/api/agents", headers={"Origin": "http://testserver"}, json={"name": "One"}).json()["agent"]["id"]
        second = client.post("/bot/api/agents", headers={"Origin": "http://testserver"}, json={"name": "Two"}).json()["agent"]["id"]
        created = client.post(
            "/bot/api/memory",
            headers={"Origin": "http://testserver"},
            json={"scope": "private", "agent_id": first, "memory_key": "secret", "content": "first agent secret"},
        )
        assert created.status_code == 201
        memory_id = created.json()["memory"]["id"]
        assert client.get(f"/bot/api/memory/{memory_id}?agent_id={first}").status_code == 200
        assert client.get(f"/bot/api/memory/{memory_id}?agent_id={second}").status_code == 404
        assert client.get(f"/bot/api/memory/search?q=secret&agent_id={second}").json()["memory"] == []
        assert client.get(f"/bot/api/memory/search?q=secret&agent_id={first}").json()["memory"]


def test_file_traversal_and_scoped_download(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, max_file_bytes=16)
    with TestClient(create_app(settings)) as client:
        login(client, settings)
        agent_id, _ = create_agent_and_conversation(client)
        bad = client.post(
            "/bot/api/files",
            headers={"Origin": "http://testserver"},
            data={"agent_id": agent_id, "path": "../escape.txt"},
            files={"file": ("escape.txt", b"bad")},
        )
        assert bad.status_code == 400
        assert not (tmp_path / "escape.txt").exists()
        good = client.post(
            "/bot/api/files",
            headers={"Origin": "http://testserver"},
            data={"agent_id": agent_id, "path": "notes/hello.txt"},
            files={"file": ("hello.txt", b"hello")},
        )
        assert good.status_code == 201, good.text
        file_id = good.json()["file"]["id"]
        downloaded = client.get(f"/bot/api/files/{file_id}/download")
        assert downloaded.status_code == 200
        assert downloaded.content == b"hello"
        oversized = client.post(
            "/bot/api/files",
            headers={"Origin": "http://testserver"},
            data={"agent_id": agent_id, "path": "large.bin"},
            files={"file": ("large.bin", b"x" * 17)},
        )
        assert oversized.status_code == 413


def test_chat_failure_is_durable_and_streamed(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, settings)
        _, conversation_id = create_agent_and_conversation(client)
        response = client.post(
            f"/bot/api/conversations/{conversation_id}/messages",
            headers={"Origin": "http://testserver"},
            json={"content": "hello"},
        )
        assert response.status_code == 202
        task_id = response.json()["task"]["id"]
        for _ in range(20):
            task = client.get(f"/bot/api/tasks/{task_id}").json()["task"]
            if task["status"] in {"failed", "completed"}:
                break
            time.sleep(0.02)
        assert task["status"] == "failed"
        assert task["error"]["code"] == "runtime_unavailable"
        with client.stream("GET", f"/bot/api/tasks/{task_id}/events") as stream:
            body = stream.read().decode()
        assert "task.error" in body
        assert "runtime_unavailable" in body
    # A fresh app instance reads the same SQLite task state.
    with TestClient(create_app(settings)) as second:
        login(second, settings)
        durable = second.get(f"/bot/api/tasks/{task_id}")
        assert durable.status_code == 200
        assert durable.json()["task"]["status"] == "failed"


def test_production_requires_explicit_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_ENV", "production")
    monkeypatch.delenv("BOT_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("BOT_SESSION_SECRET", raising=False)
    monkeypatch.delenv("BOT_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(ConfigurationError):
        Settings.from_env()

