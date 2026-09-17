import asyncio
from types import SimpleNamespace

import pytest

from app.codex_runtime import CodexRuntime
from app.contracts import TurnRequest
from app.errors import APIError
from app.runtime import RuntimeUnavailable


@pytest.mark.parametrize("failed", [False, True])
def test_native_images_use_subscription_events_and_never_expose_payload(tmp_path, failed):
    async def scenario():
        runtime = CodexRuntime(tmp_path)
        runtime.proc = SimpleNamespace(returncode=None)
        runtime.account = {"type": "chatgpt"}
        runtime.register_tools([
            {"name": "image_generate"}, {"name": "memory_search"}
        ], lambda *_: None)
        assert [tool["name"] for tool in runtime.tools] == ["memory_search"]
        saved = []

        def persist(request, item):
            saved.append((request.user_id, request.agent_id, item))
            if failed:
                raise APIError(429, "image_limit", "Your image allowance is used up.")
            return {"file_id": "image-1", "download_url": "/bot/api/files/image-1/download"}

        runtime.register_image_handler(persist)

        async def start():
            pass

        async def rpc(method, params, timeout=45):
            if method == "thread/start":
                assert params["config"]["features.image_generation"] is True
                return {"thread": {"id": "native-thread"}}
            if method == "turn/start":
                queue = runtime.queues[params["threadId"]]
                await queue.put(("item/started", {"item": {"type": "agentMessage", "id": "intro"}}))
                await queue.put(("item/agentMessage/delta", {"itemId": "intro", "delta": "Making your image."}))
                await queue.put(("item/completed", {"item": {"type": "agentMessage", "id": "intro", "text": "Making your image."}}))
                await queue.put(("item/started", {"item": {"type": "imageGeneration", "id": "img-call"}}))
                await queue.put(("item/completed", {"item": {"type": "imageGeneration", "id": "img-call", "status": "completed", "result": "PRIVATE_BASE64"}}))
                await queue.put(("item/completed", {"item": {"type": "agentMessage", "id": "answer", "text": "Here it is."}}))
                await queue.put(("turn/completed", {"turn": {"id": "t1", "status": "completed"}}))
                return {"turn": {"id": "t1"}}
            raise AssertionError(method)

        runtime.start, runtime.rpc = start, rpc
        request = TurnRequest("t1", "owner", "chat", "bot", "gpt-5.6-luna", "Help", [{"role": "user", "content": "Draw a flower"}])
        events = []
        try:
            async for event in runtime.run_turn(request):
                events.append(event)
        except RuntimeUnavailable as exc:
            assert failed and "allowance" in str(exc)
        else:
            assert not failed
        assert saved[0][:2] == ("owner", "bot")
        started = next(e for e in events if e.event_type == "tool.started")
        completed = next(e for e in events if e.event_type == "tool.completed")
        assert started.data["tool"] == "image_generate"
        assert started.data["prompt"] == "Draw a flower"
        assert completed.data["success"] is (not failed)
        assert "PRIVATE_BASE64" not in str(events)
        if not failed:
            assert ''.join(e.data['text'] for e in events if e.event_type == 'assistant.delta') == 'Making your image.\n\nHere it is.'
        runtime.db.close()

    asyncio.run(scenario())

