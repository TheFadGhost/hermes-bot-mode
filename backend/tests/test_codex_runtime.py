import asyncio
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from app.codex_runtime import CodexRuntime
from app.contracts import RuntimeStatus, TurnRequest


def request(task="task-1", prompt="hello", conversation="conversation-1"):
    return TurnRequest(task, "123", conversation, "agent-1", "gpt-5.6-luna", "Help the owner", [{"role": "user", "content": prompt}])


def test_transport_resume_and_approval(tmp_path):
    async def scenario():
        runtime = CodexRuntime(tmp_path, command=[sys.executable, str(Path(__file__).with_name("fake_codex.py"))])
        await runtime.start()
        assert runtime.status().available
        first = [event async for event in runtime.run_turn(request())]
        second = [event async for event in runtime.run_turn(request(task="task-2"))]
        assert first[0].data["thread_id"] == second[0].data["thread_id"]
        assert "".join(str(event.data["text"]) for event in first if event.event_type == "assistant.delta") == "fixture reply"
        assert first[-1].event_type == "turn.completed"
        async for event in runtime.run_turn(request(task="task-3", prompt="approval")):
            if event.event_type == "approval":
                approvals = await runtime.list_approvals("task-3")
                assert len(approvals) == 1
                await runtime.respond_approval("task-3", approvals[0].approval_id, "decline")
        assert not await runtime.list_approvals("task-3")
        await runtime.close()
    asyncio.run(scenario())


def test_missing_runtime_fails_closed(tmp_path):
    async def scenario():
        runtime = CodexRuntime(tmp_path, command=["a-codex-binary-that-does-not-exist"])
        await runtime.start()
        assert not runtime.status().available
        assert "not installed" in runtime.status().reason
        await runtime.close()
    asyncio.run(scenario())


def test_resume_refreshes_instructions_and_reuses_persisted_tools(tmp_path):
    async def scenario():
        runtime = CodexRuntime(tmp_path)
        runtime.proc = SimpleNamespace(returncode=None)
        runtime.account = {"type": "chatgpt"}
        runtime.models = [{"model": "gpt-5.6-luna"}]
        runtime.tools = [{"type": "function", "name": "memory_search", "description": "search", "inputSchema": {}}]
        calls = []

        async def fake_start():
            return None

        async def fake_rpc(method, params, timeout=45):
            calls.append((method, dict(params)))
            if method == "thread/start":
                return {"thread": {"id": "thread-1"}}
            if method == "thread/resume":
                return {"thread": {"id": params["threadId"]}}
            if method == "turn/start":
                await runtime.queues[params["threadId"]].put(
                    ("turn/completed", {"turn": {"id": "turn-1", "status": "completed"}})
                )
                return {"turn": {"id": "turn-1"}}
            raise AssertionError(f"unexpected RPC {method}")

        runtime.start = fake_start
        runtime.rpc = fake_rpc
        first_request = request(prompt="one")
        first_request = TurnRequest(
            first_request.task_id,
            first_request.user_id,
            first_request.conversation_id,
            first_request.agent_id,
            first_request.model,
            "first policy",
            first_request.messages,
        )
        [event async for event in runtime.run_turn(first_request)]
        second_request = TurnRequest(
            "task-2",
            "123",
            "conversation-1",
            "agent-1",
            "gpt-5.6-luna",
            "updated policy",
            [{"role": "user", "content": "two"}],
        )
        [event async for event in runtime.run_turn(second_request)]

        start = next(params for method, params in calls if method == "thread/start")
        resume = next(params for method, params in calls if method == "thread/resume")
        assert "first policy" in start["developerInstructions"]
        assert "updated policy" in resume["developerInstructions"]
        assert "dynamicTools" in start
        assert "dynamicTools" not in resume
        runtime.db.close()

    asyncio.run(scenario())


def test_changed_tools_start_fresh_thread_with_bounded_prior_transcript(tmp_path):
    async def scenario():
        runtime = CodexRuntime(tmp_path)
        runtime.proc = SimpleNamespace(returncode=None)
        runtime.account = {"type": "chatgpt"}
        runtime.models = [{"model": "gpt-5.6-luna"}]
        runtime.tools = [{"type": "function", "name": "old_tool", "description": "old", "inputSchema": {}}]
        calls = []
        starts = 0

        async def fake_start():
            return None

        async def fake_rpc(method, params, timeout=45):
            nonlocal starts
            calls.append((method, dict(params)))
            if method == "thread/start":
                starts += 1
                return {"thread": {"id": f"thread-{starts}"}}
            if method == "thread/resume":
                return {"thread": {"id": params["threadId"]}}
            if method == "turn/start":
                await runtime.queues[params["threadId"]].put(
                    ("turn/completed", {"turn": {"id": f"turn-{starts}", "status": "completed"}})
                )
                return {"turn": {"id": f"turn-{starts}"}}
            raise AssertionError(f"unexpected RPC {method}")

        runtime.start = fake_start
        runtime.rpc = fake_rpc
        first = TurnRequest(
            "task-1", "123", "conversation-1", "agent-1", "gpt-5.6-luna", "policy",
            [{"id": "message-1", "role": "user", "content": "first request"}],
            message_id="message-1",
        )
        [event async for event in runtime.run_turn(first)]

        runtime.tools = [{"type": "function", "name": "new_tool", "description": "new", "inputSchema": {}}]
        second = TurnRequest(
            "task-2", "123", "conversation-1", "agent-1", "gpt-5.6-luna", "policy",
            [
                {"id": "message-1", "role": "user", "content": "first request"},
                {"id": "assistant-1", "role": "assistant", "content": "first response"},
                {"id": "message-2", "role": "user", "content": "second request"},
            ],
            message_id="message-2",
        )
        [event async for event in runtime.run_turn(second)]

        start_calls = [params for method, params in calls if method == "thread/start"]
        resume_calls = [params for method, params in calls if method == "thread/resume"]
        assert len(start_calls) == 2
        assert not resume_calls
        assert start_calls[1]["dynamicTools"] == runtime.tools
        turn_input = next(params for method, params in calls if method == "turn/start" and params["threadId"] == "thread-2")
        prompt = turn_input["input"][0]["text"]
        assert "first response" in prompt
        assert prompt.endswith("User request:\nsecond request")
        runtime.db.close()

    asyncio.run(scenario())


def test_dynamic_tool_events_redact_payloads_and_cancel_tool_work(tmp_path):
    async def scenario():
        runtime = CodexRuntime(tmp_path)
        request_value = request()
        queue = asyncio.Queue()
        runtime.queues["thread-1"] = queue
        runtime.active[request_value.task_id] = {
            "thread": "thread-1",
            "request": request_value,
            "turn": "turn-1",
            "turn_start_done": True,
            "tool_tasks": set(),
        }
        sent = []

        async def fake_send(message):
            sent.append(message)

        async def image_handler(_request, _tool, _args):
            return {
                "file_id": "file-1",
                "path": "generated/image.png",
                "mime": "image/png",
                "download_url": "/bot/api/files/file-1/download",
                "markdown": "![Generated image](/bot/api/files/file-1/download)",
                "image_url": "data:image/png;base64,secret",
                "content": "private payload",
            }

        runtime._send = fake_send
        runtime.tool_handler = image_handler
        await runtime._server_request(
            {
                "id": 7,
                "method": "item/tool/call",
                "params": {"threadId": "thread-1", "tool": "image_generate", "arguments": {"prompt": "sunset"}},
            }
        )
        started = await queue.get()
        completed = await queue.get()
        assert started[0] == "scoped_tool.started"
        assert started[1]["prompt"] == "sunset"
        assert "aspect_ratio" not in started[1]
        assert completed[0] == "scoped_tool.completed"
        assert completed[1]["result"] == {
            "file_id": "file-1",
            "path": "generated/image.png",
            "mime": "image/png",
            "download_url": "/bot/api/files/file-1/download",
            "markdown": "![Generated image](/bot/api/files/file-1/download)",
        }
        assert "image_url" not in completed[1]["result"]
        assert "content" not in completed[1]["result"]
        assert sent and sent[0]["id"] == 7

        started_work = asyncio.Event()
        cancelled_work = asyncio.Event()

        async def blocking_handler(_request, _tool, _args):
            started_work.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled_work.set()
                raise

        async def interrupt_rpc(method, params, timeout=45):
            assert method == "turn/interrupt"
            return {}

        runtime.tool_handler = blocking_handler
        runtime.rpc = interrupt_rpc
        blocked = asyncio.create_task(
            runtime._server_request(
                {
                    "id": 8,
                    "method": "item/tool/call",
                    "params": {"threadId": "thread-1", "tool": "files_read", "arguments": {"path": "x"}},
                }
            )
        )
        await started_work.wait()
        await runtime.cancel(request_value.task_id)
        await asyncio.sleep(0)
        assert blocked.cancelled()
        assert cancelled_work.is_set()
        runtime.db.close()

    asyncio.run(scenario())


def test_run_turn_maps_scoped_tool_events_without_dynamic_echo(tmp_path):
    async def scenario():
        runtime = CodexRuntime(tmp_path)
        runtime.proc = SimpleNamespace(returncode=None)
        runtime.account = {"type": "chatgpt"}
        runtime.models = [{"model": "gpt-5.6-luna"}]

        async def fake_start():
            return None

        async def fake_rpc(method, params, timeout=45):
            if method == "thread/start":
                return {"thread": {"id": "thread-1"}}
            if method == "turn/start":
                queue = runtime.queues[params["threadId"]]
                await queue.put(("scoped_tool.started", {"tool": "image_generate", "call_id": "7"}))
                await queue.put(("scoped_tool.completed", {"tool": "image_generate", "call_id": "7", "success": True, "result": {"download_url": "/bot/api/files/7/download"}}))
                await queue.put(("item/completed", {"item": {"type": "dynamicToolCall", "tool": "image_generate", "contentItems": [{"type": "inputImage", "imageUrl": "data:image/png;base64,secret"}]}}))
                await queue.put(("turn/completed", {"turn": {"id": "turn-1", "status": "completed"}}))
                return {"turn": {"id": "turn-1"}}
            raise AssertionError(f"unexpected RPC {method}")

        runtime.start = fake_start
        runtime.rpc = fake_rpc
        events = [event async for event in runtime.run_turn(request())]
        tool_events = [event for event in events if event.event_type.startswith("tool.")]
        assert [event.event_type for event in tool_events] == ["tool.started", "tool.completed"]
        assert tool_events[1].data["result"]["download_url"].endswith("/download")
        runtime.db.close()

    asyncio.run(scenario())


def test_cancel_drains_tool_work_when_interrupt_rpc_fails(tmp_path):
    async def scenario():
        runtime = CodexRuntime(tmp_path)
        request_value = request()
        queue = asyncio.Queue()
        runtime.queues["thread-1"] = queue
        runtime.active[request_value.task_id] = {
            "thread": "thread-1",
            "request": request_value,
            "turn": "turn-1",
            "turn_start_done": True,
            "tool_tasks": set(),
        }
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocking_handler(_request, _tool, _args):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def failing_interrupt(method, params, timeout=45):
            assert method == "turn/interrupt"
            raise TimeoutError("interrupt timed out")

        runtime.tool_handler = blocking_handler
        runtime.rpc = failing_interrupt
        server_task = asyncio.create_task(
            runtime._server_request(
                {
                    "id": 9,
                    "method": "item/tool/call",
                    "params": {"threadId": "thread-1", "tool": "computer_action", "arguments": {}},
                }
            )
        )
        await started.wait()
        with pytest.raises(TimeoutError):
            await runtime.cancel(request_value.task_id)
        await asyncio.sleep(0)
        assert server_task.cancelled()
        assert cancelled.is_set()
        runtime.db.close()

    asyncio.run(scenario())


def test_cancel_rejects_new_scoped_tool_calls(tmp_path):
    async def scenario():
        runtime = CodexRuntime(tmp_path)
        request_value = request()
        runtime.active[request_value.task_id] = {
            "thread": "thread-1",
            "request": request_value,
            "cancel_requested": True,
            "tool_tasks": set(),
        }
        sent = []
        called = False

        async def handler(_request, _tool, _args):
            nonlocal called
            called = True
            return {"content": "should not run"}

        async def fake_send(message):
            sent.append(message)

        runtime.tool_handler = handler
        runtime._send = fake_send
        await runtime._server_request(
            {
                "id": 10,
                "method": "item/tool/call",
                "params": {"threadId": "thread-1", "tool": "computer_action", "arguments": {"action": "click"}},
            }
        )
        assert not called
        assert sent[0]["id"] == 10
        assert sent[0]["error"]["code"] == -32800
        runtime.db.close()

    asyncio.run(scenario())


def test_history_reference_keeps_newest_preceding_messages(tmp_path):
    messages = [
        {"id": f"message-{index}", "role": "user", "content": f"context-{index}"}
        for index in range(8)
    ]
    messages.append({"id": "target", "role": "user", "content": "current"})
    reference = CodexRuntime._history_reference(messages, "target", limit=150)
    decoded = json.loads(reference)
    assert len(reference) <= 150
    assert decoded[-1]["content"] == "context-7"
    assert [item["content"] for item in decoded] == sorted(
        (item["content"] for item in decoded),
        key=lambda value: int(value.rsplit("-", 1)[1]),
    )
    assert "context-0" not in {item["content"] for item in decoded}

