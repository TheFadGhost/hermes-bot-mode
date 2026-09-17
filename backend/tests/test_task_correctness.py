from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.config import Settings
from app.contracts import RuntimeEvent, RuntimeStatus, TurnRequest
from app.db import Database
from app.errors import APIError
from app.learned_skills import LearnedSkills
from app.store import Store
from app.tasks import TaskManager
from app.workspace import Workspace


def make_store(tmp_path: Path) -> tuple[Store, str, dict[str, str], dict[str, str]]:
    settings = Settings(database_path=tmp_path / "bot.sqlite3", workspace_root=tmp_path / "workspaces")
    store = Store(Database(settings.database_path))
    user_id = "owner"
    agent = store.create_agent(user_id, name="Dad", instructions="Initial policy", model="gpt-5.6-luna")
    conversation = store.create_conversation(user_id, agent["id"], "Chat")
    return store, user_id, agent, conversation


def test_message_windows_are_newest_first_then_returned_chronologically(tmp_path: Path) -> None:
    store, user_id, _agent, conversation = make_store(tmp_path)
    messages: list[dict[str, object]] = []
    for index in range(6):
        message, _task, _agent = store.create_message_and_task(user_id, conversation["id"], f"prompt-{index}")
        messages.append(message)

    latest = store.list_messages(user_id, conversation["id"], limit=3)
    assert [message["content"] for message in latest] == ["prompt-3", "prompt-4", "prompt-5"]
    older = store.list_messages(user_id, conversation["id"], limit=2, before_id=str(latest[0]["id"]))
    assert [message["content"] for message in older] == ["prompt-1", "prompt-2"]


def test_turn_context_is_bounded_at_the_task_source_message(tmp_path: Path) -> None:
    store, user_id, _agent, conversation = make_store(tmp_path)
    first, first_task, _agent = store.create_message_and_task(user_id, conversation["id"], "first prompt")
    second, _second_task, _agent = store.create_message_and_task(user_id, conversation["id"], "second prompt")

    _conversation, _agent, context = store.conversation_turn_context(
        user_id,
        conversation["id"],
        message_id=str(first["id"]),
    )
    assert [message["content"] for message in context] == ["first prompt"]
    assert str(first_task["message_id"]) == str(first["id"])
    assert str(second["id"]) not in {str(message["id"]) for message in context}


def test_message_attachments_are_bound_to_the_conversation_agent(tmp_path: Path) -> None:
    store, user_id, agent, conversation = make_store(tmp_path)
    selected = store.create_file(
        user_id,
        agent_id=agent["id"],
        relative_path="notes/selected.txt",
        size=4,
        sha256="a" * 64,
        content_type="text/plain",
    )
    message, _task, _agent = store.create_message_and_task(
        user_id,
        conversation["id"],
        "Review this",
        file_ids=[selected["id"]],
    )
    assert message["metadata"]["attachments"] == [{
        "file_id": selected["id"],
        "path": "notes/selected.txt",
        "name": "selected.txt",
        "content_type": "text/plain",
    }]

    other_agent = store.create_agent(user_id, name="Other", instructions="", model="gpt-5.6-luna")
    other_file = store.create_file(
        user_id,
        agent_id=other_agent["id"],
        relative_path="private.txt",
        size=1,
        sha256="b" * 64,
        content_type="text/plain",
    )
    with pytest.raises(APIError) as error:
        store.create_message_and_task(
            user_id,
            conversation["id"],
            "Cross agent",
            file_ids=[other_file["id"]],
        )
    assert getattr(error.value, "code", None) == "file_not_found"


def test_recalled_skill_context_stays_valid_and_bounded() -> None:
    context = TaskManager._skill_context([
        {
            "name": "long procedure",
            "trigger": "when needed",
            "instructions": "step " * 10_000,
            "evidence": "verified",
        }
    ])
    assert len(context) <= 12_000
    decoded = json.loads(context)
    assert decoded[0]["name"] == "long procedure"
    assert decoded[0]["instructions"]


def test_startup_recovery_discards_pending_skills(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, user_id, agent, conversation = make_store(tmp_path)
        _message, task, _agent = store.create_message_and_task(user_id, conversation["id"], "source")
        skills = LearnedSkills(store)
        skills.propose(
            user_id,
            agent["id"],
            task["id"],
            name="source procedure",
            trigger="source",
            instructions="Use the source procedure",
            evidence="Observed it work",
        )
        manager = TaskManager(store, Workspace(Settings(database_path=tmp_path / "bot.sqlite3", workspace_root=tmp_path / "workspaces")), BlockingRuntime())
        await manager.start()
        with store.db.read() as connection:
            row = connection.execute("SELECT state FROM learned_skills WHERE source_task_id = ?", (task["id"],)).fetchone()
        assert row["state"] == "discarded"

    asyncio.run(scenario())


class BlockingRuntime:
    def __init__(self) -> None:
        self.requests: list[TurnRequest] = []
        self.release = asyncio.Event()
        self.cancelled: list[str] = []
        self.started = asyncio.Event()

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(available=True)

    async def run_turn(self, request: TurnRequest):
        self.requests.append(request)
        self.started.set()
        yield RuntimeEvent("assistant.delta", {"text": "partial output"})
        await self.release.wait()
        yield RuntimeEvent("turn.completed", {"status": "completed"})

    async def cancel(self, task_id: str) -> None:
        self.cancelled.append(task_id)
        self.release.set()


class ArtifactRuntime:
    def __init__(self, file_id: str) -> None:
        self.file_id = file_id

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(available=True)

    async def run_turn(self, _request: TurnRequest):
        yield RuntimeEvent(
            "tool.completed",
            {
                "tool": "image_generate",
                "success": True,
                "result": {"file_id": self.file_id},
            },
        )
        yield RuntimeEvent("turn.completed", {"status": "completed"})


class CaptureRuntime:
    def __init__(self) -> None:
        self.requests: list[TurnRequest] = []

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(available=True)

    async def run_turn(self, request: TurnRequest):
        self.requests.append(request)
        yield RuntimeEvent("turn.completed", {"status": "completed"})


def test_task_turn_metadata_includes_selected_file_paths(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, user_id, agent, conversation = make_store(tmp_path)
        selected = store.create_file(
            user_id,
            agent_id=agent["id"],
            relative_path="reports/brief.txt",
            size=4,
            sha256="d" * 64,
            content_type="text/plain",
        )
        _message, task, _agent = store.create_message_and_task(
            user_id,
            conversation["id"],
            "Summarize the attachment",
            file_ids=[selected["id"]],
        )
        settings = Settings(database_path=tmp_path / "bot.sqlite3", workspace_root=tmp_path / "workspaces")
        runtime = CaptureRuntime()
        manager = TaskManager(store, Workspace(settings), runtime)
        manager.submit(user_id, str(task["id"]))
        for _ in range(100):
            if store.get_task(user_id, str(task["id"]))["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.005)
        assert store.get_task(user_id, str(task["id"]))["status"] == "completed"
        assert runtime.requests[0].metadata["file_attachments"][0]["path"] == "reports/brief.txt"
        assert "reports/brief.txt" in str(runtime.requests[0].metadata["file_context"])
        await manager.close()

    asyncio.run(scenario())


def test_successful_image_artifact_is_persisted_without_model_echo(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, user_id, agent, conversation = make_store(tmp_path)
        image = store.create_file(
            user_id,
            agent_id=agent["id"],
            relative_path="generated/result.png",
            size=4,
            sha256="c" * 64,
            content_type="image/png",
        )
        _message, task, _agent = store.create_message_and_task(
            user_id,
            conversation["id"],
            "Generate an image",
        )
        settings = Settings(database_path=tmp_path / "bot.sqlite3", workspace_root=tmp_path / "workspaces")
        manager = TaskManager(store, Workspace(settings), ArtifactRuntime(image["id"]))
        manager.submit(user_id, str(task["id"]))
        for _ in range(100):
            if store.get_task(user_id, str(task["id"]))["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.005)
        assert store.get_task(user_id, str(task["id"]))["status"] == "completed"
        messages = store.list_messages(user_id, conversation["id"], limit=20)
        assistant = [item for item in messages if item["role"] == "assistant"]
        assert assistant[-1]["content"] == f"![Generated image](/bot/api/files/{image['id']}/download)"
        await manager.close()

    asyncio.run(scenario())


def test_task_manager_binds_each_request_and_interrupts_cancelled_turn(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, user_id, agent, conversation = make_store(tmp_path)
        first_message, first_task, _agent = store.create_message_and_task(user_id, conversation["id"], "first prompt")
        second_message, second_task, _agent = store.create_message_and_task(user_id, conversation["id"], "second prompt")
        settings = Settings(database_path=tmp_path / "bot.sqlite3", workspace_root=tmp_path / "workspaces")
        runtime = BlockingRuntime()
        manager = TaskManager(store, Workspace(settings), runtime)
        manager.submit(user_id, str(first_task["id"]))
        manager.submit(user_id, str(second_task["id"]))

        for _ in range(100):
            if len(runtime.requests) == 2:
                break
            await asyncio.sleep(0.005)
        assert len(runtime.requests) == 2
        by_id = {request.message_id: request for request in runtime.requests}
        assert by_id[str(first_message["id"])].messages[-1]["content"] == "first prompt"
        assert by_id[str(second_message["id"])].messages[-1]["content"] == "second prompt"

        cancelled = await manager.cancel(user_id, str(first_task["id"]))
        assert cancelled["status"] == "cancelled"
        assert runtime.cancelled == [str(first_task["id"])]
        runtime.release.set()
        await asyncio.sleep(0.02)
        partial = [
            message
            for message in store.list_messages(user_id, conversation["id"], limit=20)
            if message["role"] == "assistant" and message["status"] == "partial"
        ]
        assert [message["content"] for message in partial] == ["partial output"]
        assert store.get_task(user_id, str(second_task["id"]))["status"] == "completed"
        await manager.close()

    asyncio.run(scenario())

