from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.contracts import TurnRequest
from app.db import Database
from app.errors import APIError
from app.scoped_tools import ScopedToolBridge
from app.store import Store
from app.workspace import Workspace


class RecordingTaskManager:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, str]] = []

    def submit(self, user_id: str, task_id: str) -> None:
        self.submitted.append((user_id, task_id))


def run(coroutine):
    """Keep these tests runnable with the backend's minimal pytest extras."""

    return asyncio.run(coroutine)


@pytest.fixture
def harness(tmp_path: Path) -> dict[str, object]:
    user_id = "user-1"
    settings = Settings(
        database_path=tmp_path / "bot.sqlite3",
        workspace_root=tmp_path / "workspaces",
    )
    store = Store(Database(settings.database_path))
    workspace = Workspace(settings)
    agents = {
        name: store.create_agent(
            user_id,
            name=name,
            instructions=f"private instructions for {name}",
            model="gpt-5.6-luna",
        )
        for name in ("Dad", "Researcher", "Writer", "Reviewer", "Extra")
    }
    parent_conversation = store.create_conversation(user_id, agents["Dad"]["id"], "Parent")
    _message, parent_task, _agent = store.create_message_and_task(
        user_id, parent_conversation["id"], "parent task"
    )
    other_conversation = store.create_conversation(user_id, agents["Dad"]["id"], "Other source")
    _message, other_task, _agent = store.create_message_and_task(
        user_id, other_conversation["id"], "other source task"
    )
    task_manager = RecordingTaskManager()
    bridge = ScopedToolBridge(store, workspace, task_manager, max_file_bytes=1024)

    def request(task: dict[str, object], agent: dict[str, object]) -> TurnRequest:
        return TurnRequest(
            task_id=str(task["id"]),
            user_id=user_id,
            conversation_id=str(task["conversation_id"]),
            agent_id=str(agent["id"]),
            model=str(agent["model"]),
            instructions=str(agent["instructions"]),
        )

    return {
        "user_id": user_id,
        "store": store,
        "workspace": workspace,
        "bridge": bridge,
        "task_manager": task_manager,
        "agents": agents,
        "parent_task": parent_task,
        "other_task": other_task,
        "request": request,
    }


def test_tool_definitions_are_cli_compatible_and_identity_is_bound() -> None:
    definitions = ScopedToolBridge.definitions()
    assert definitions
    assert all(set(item) == {"type", "name", "description", "inputSchema"} for item in definitions)
    names = {item["name"] for item in definitions}
    assert names == {
        "memory_search",
        "memory_save",
        "files_list",
        "files_read",
        "files_write",
        "colleagues",
        "delegate_task",
        "colleague_result",
        "computer_action",
        "computer_start",
        "skills_search",
        "skills_save",
        "image_generate",
        "history_search",
        "history_read",
        "create_bot",
        "routines_list",
        "routine_create",
        "group_create",
    }
    for item in definitions:
        properties = item["inputSchema"].get("properties", {})
        assert "user_id" not in properties
        assert "agent_id" not in properties


def test_memory_and_files_are_scoped_to_bound_agent(harness: dict[str, object]) -> None:
    bridge = harness["bridge"]
    store = harness["store"]
    agents = harness["agents"]
    request = harness["request"]
    parent_task = harness["parent_task"]
    user_id = str(harness["user_id"])
    dad_request = request(parent_task, agents["Dad"])
    researcher_conversation = store.create_conversation(user_id, agents["Researcher"]["id"], "Researcher")
    _message, researcher_task, _agent = store.create_message_and_task(
        user_id, researcher_conversation["id"], "researcher task"
    )
    researcher_request = request(researcher_task, agents["Researcher"])

    run(bridge.handle(dad_request, "memory_save", {"content": "alphaonly private fact"}))
    run(bridge.handle(dad_request, "memory_save", {"content": "teamonly shared fact", "scope": "shared"}))
    run(bridge.handle(researcher_request, "memory_save", {"content": "betaonly private fact"}))

    dad_alpha = run(bridge.handle(dad_request, "memory_search", {"query": "alphaonly"}))
    researcher_alpha = run(bridge.handle(researcher_request, "memory_search", {"query": "alphaonly"}))
    researcher_team = run(bridge.handle(researcher_request, "memory_search", {"query": "teamonly"}))
    dad_beta = run(bridge.handle(dad_request, "memory_search", {"query": "betaonly"}))
    assert [item["content"] for item in dad_alpha["memory"]] == ["alphaonly private fact"]
    assert researcher_alpha["memory"] == []
    assert [item["content"] for item in researcher_team["memory"]] == ["teamonly shared fact"]
    assert dad_beta["memory"] == []

    written = run(bridge.handle(
        dad_request,
        "files_write",
        {"path": "notes/private.txt", "content": "dad-file-only"},
    ))
    assert written["path"] == "notes/private.txt"
    assert run(bridge.handle(dad_request, "files_read", {"path": "notes/private.txt"}))["content"] == "dad-file-only"
    assert run(bridge.handle(researcher_request, "files_list", {}))["files"] == []
    with pytest.raises(APIError) as missing:
        run(bridge.handle(researcher_request, "files_read", {"path": "notes/private.txt"}))
    assert missing.value.code == "file_missing"
    with pytest.raises(APIError) as traversal:
        run(bridge.handle(dad_request, "files_read", {"path": "../private.txt"}))
    assert traversal.value.code == "invalid_file_path"


def test_delegation_is_direct_child_only_and_fanout_is_bounded(harness: dict[str, object]) -> None:
    bridge = harness["bridge"]
    store = harness["store"]
    agents = harness["agents"]
    request = harness["request"]
    parent_task = harness["parent_task"]
    other_task = harness["other_task"]
    user_id = str(harness["user_id"])
    task_manager = harness["task_manager"]
    dad_request = request(parent_task, agents["Dad"])

    children: list[dict[str, object]] = []
    for name in ("Researcher", "Writer", "Reviewer"):
        children.append(
            run(bridge.handle(
                dad_request,
                "delegate_task",
                {"agent_name": name, "prompt": f"work for {name}"},
            ))
        )
    assert len(task_manager.submitted) == 3
    assert all(item["parent_task_id"] == parent_task["id"] for item in children)
    with pytest.raises(APIError) as fanout:
        run(bridge.handle(
            dad_request,
            "delegate_task",
            {"agent_name": "Extra", "prompt": "fourth child"},
        ))
    assert fanout.value.code == "delegation_limit"

    first_child = children[0]
    child_task = store.get_task(user_id, str(first_child["task_id"]))
    child_request = request(child_task, agents["Researcher"])
    with pytest.raises(APIError) as nested:
        run(bridge.handle(
            child_request,
            "delegate_task",
            {"agent_name": "Writer", "prompt": "nested work"},
        ))
    assert nested.value.code == "nested_delegation_forbidden"

    other_source_request = request(other_task, agents["Dad"])
    with pytest.raises(APIError) as wrong_parent:
        run(bridge.handle(
            other_source_request,
            "colleague_result",
            {"task_id": first_child["task_id"]},
        ))
    assert wrong_parent.value.code == "colleague_scope"

    pending = run(bridge.handle(
        dad_request,
        "colleague_result",
        {"task_id": first_child["task_id"], "wait_seconds": 0},
    ))
    assert pending["pending"] is True
    store.append_assistant_message(user_id, str(first_child["task_id"]), "finished child result")
    store.finish_task(str(first_child["task_id"]), status="completed")
    result = run(bridge.handle(
        dad_request,
        "colleague_result",
        {"task_id": first_child["task_id"]},
    ))
    assert result["pending"] is False
    assert result["result"] == "finished child result"


def test_computer_action_is_honest_when_no_desktop_is_running(harness: dict[str, object]) -> None:
    bridge = harness["bridge"]
    request = harness["request"]
    agents = harness["agents"]
    parent_task = harness["parent_task"]
    response = run(bridge.handle(
        request(parent_task, agents["Dad"]),
        "computer_action",
        {"action": "screenshot", "agent_id": "forged-agent-id"},
    ))
    assert response == {
        "available": False,
        "created": False,
        "running": False,
        "reason": "Desktop supervisor is not configured",
    }

