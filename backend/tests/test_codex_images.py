from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.codex_images import persist_codex_image
from app.config import Settings
from app.db import Database
from app.errors import APIError
from app.store import Store
from app.workspace import Workspace


PNG = b"\x89PNG\r\n\x1a\n" + b"native-png"


def harness(tmp_path: Path, max_bytes: int = 1024) -> tuple[Store, Workspace, str]:
    settings = Settings(
        database_path=tmp_path / "bot.sqlite3",
        workspace_root=tmp_path / "workspaces",
        max_file_bytes=max_bytes,
    )
    store = Store(Database(settings.database_path))
    workspace = Workspace(settings)
    agent = store.create_agent("owner", name="Dad", instructions="", model="gpt-5.6-luna")
    return store, workspace, str(agent["id"])


def completed(**extra: object) -> dict[str, object]:
    return {"id": "img-1", "status": "completed", "result": "", **extra}


def test_persists_preferred_base64_png_and_registers_private_file(tmp_path: Path) -> None:
    store, workspace, agent_id = harness(tmp_path)
    data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    result = persist_codex_image(store, workspace, "owner", agent_id, completed(result=data_url))

    assert result["provider"] == "codex"
    assert result["model"] == "provider-selected"
    assert result["mime"] == "image/png"
    assert result["download_url"] == f"/bot/api/files/{result['file_id']}/download"
    assert workspace.path_for("owner", agent_id, str(result["path"]), must_exist=True).read_bytes() == PNG
    assert store.get_file("owner", str(result["file_id"]))["agent_id"] == agent_id


def test_rejects_path_outside_bound_agent_workspace(tmp_path: Path) -> None:
    store, workspace, agent_id = harness(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    with pytest.raises(APIError) as exc:
        persist_codex_image(store, workspace, "owner", agent_id, completed(savedPath=str(outside)))
    assert exc.value.code == "image_path_invalid"


def test_rejects_symlink_saved_path(tmp_path: Path) -> None:
    store, workspace, agent_id = harness(tmp_path)
    root = workspace.agent_root("owner", agent_id)
    target = tmp_path / "target.png"
    target.write_bytes(PNG)
    link = root / "link.png"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(APIError) as exc:
        persist_codex_image(store, workspace, "owner", agent_id, completed(savedPath=str(link)))
    assert exc.value.code in {"symlink_path", "invalid_file_path"}


def test_rejects_oversize_and_invalid_signature(tmp_path: Path) -> None:
    store, workspace, agent_id = harness(tmp_path, max_bytes=len(PNG) - 1)
    with pytest.raises(APIError) as oversize:
        persist_codex_image(store, workspace, "owner", agent_id, completed(result=base64.b64encode(PNG).decode()))
    assert oversize.value.code == "file_too_large"

    store, workspace, agent_id = harness(tmp_path / "invalid")
    with pytest.raises(APIError) as invalid:
        persist_codex_image(store, workspace, "owner", agent_id, completed(result=base64.b64encode(b"text").decode()))
    assert invalid.value.code == "image_generation_invalid_result"


def test_sanitizes_subscription_failure_and_does_not_persist(tmp_path: Path) -> None:
    store, workspace, agent_id = harness(tmp_path)
    with pytest.raises(APIError) as exc:
        persist_codex_image(
            store,
            workspace,
            "owner",
            agent_id,
            {"id": "img-1", "status": "failed", "failure": {"type": "usageLimitExceeded", "limitId": "codex", "resetsAt": 123}},
        )
    assert exc.value.status_code == 429
    assert exc.value.code == "image_generation_usage_limit"
    assert "codex" not in exc.value.message
    assert "01 Jan at 00:02 UTC" in exc.value.message
    assert list(store.list_files("owner", agent_id=agent_id)) == []

