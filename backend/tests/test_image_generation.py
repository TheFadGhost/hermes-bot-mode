from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.db import Database
from app.errors import APIError
from app.image_generation import (
    ImageGenerationConfig,
    ImageGenerationResult,
    KieImageGenerator,
    validate_public_https_url,
)
from app.store import Store
from app.workspace import Workspace


def _harness(
    tmp_path: Path,
    handler: httpx.AsyncBaseTransport | Any,
    *,
    key: str | None = "test-kie-secret",
    max_image_bytes: int = 1024,
    **config_overrides: Any,
) -> tuple[KieImageGenerator, Store, Workspace, httpx.AsyncClient]:
    settings = Settings(
        database_path=tmp_path / "bot.sqlite3",
        workspace_root=tmp_path / "workspaces",
        max_file_bytes=max_image_bytes,
    )
    store = Store(Database(settings.database_path))
    workspace = Workspace(settings)
    store.create_agent(
        "owner",
        name="Dad",
        instructions="",
        model="gpt-5.6-luna",
    )
    transport = handler if isinstance(handler, httpx.AsyncBaseTransport) else httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        transport=transport,
        # Regression coverage: the module must strip this default from image
        # asset requests while preserving explicit auth for KIE calls.
        headers={"Authorization": "Bearer client-default-secret"},
    )
    config_values: dict[str, Any] = {
        "api_key": key,
        "api_base_url": "https://api.kie.ai",
        "timeout_seconds": 2.0,
        "request_timeout_seconds": 1.0,
        "poll_interval_seconds": 0.001,
        "max_poll_interval_seconds": 0.01,
        "max_image_bytes": max_image_bytes,
    }
    config_values.update(config_overrides)
    config = ImageGenerationConfig(**config_values)
    generator = KieImageGenerator(store, workspace, config, http_client=client)
    return generator, store, workspace, client


def test_missing_key_is_truthful_and_does_not_call_provider(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    generator, _store, _workspace, client = _harness(tmp_path, handler, key=None)

    async def run() -> None:
        try:
            await generator.generate("owner", next(iter(_store.list_agents("owner")))["id"], "a cat")
        except APIError as exc:
            assert exc.status_code == 503
            assert exc.code == "image_generation_unavailable"
            assert "client-default-secret" not in str(exc)
        else:  # pragma: no cover - assertion branch
            raise AssertionError("missing KIE key should be rejected")

    try:
        asyncio.run(run())
    finally:
        asyncio.run(client.aclose())
    assert calls == []


def test_start_rejects_unbound_agent_and_long_prompt(tmp_path: Path) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 200, "data": {"taskId": "task-1"}})

    generator, _store, _workspace, client = _harness(
        tmp_path,
        handler,
        max_prompt_chars=4,
    )

    async def run() -> None:
        with pytest.raises(APIError) as missing_agent:
            await generator.start("owner", "forged-agent", "cat")
        assert missing_agent.value.code == "agent_not_found"
        agent_id = next(iter(_store.list_agents("owner")))["id"]
        with pytest.raises(APIError) as long_prompt:
            await generator.start("owner", agent_id, "a cat")
        assert long_prompt.value.code == "image_prompt_too_long"

    try:
        asyncio.run(run())
    finally:
        asyncio.run(client.aclose())


def test_generate_polls_downloads_without_leaking_auth_and_registers_file(tmp_path: Path) -> None:
    requests: list[tuple[str, str | None, dict[str, Any] | None]] = []
    poll_count = 0
    image_bytes = b"\x89PNG\r\n\x1a\nmock-image"

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        path = request.url.path
        auth = request.headers.get("authorization")
        if path.endswith("/jobs/createTask"):
            payload = json.loads(request.content.decode())
            requests.append((path, auth, payload))
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "task-1"}})
        if path.endswith("/jobs/recordInfo"):
            poll_count += 1
            requests.append((path, auth, None))
            if poll_count == 1:
                return httpx.Response(
                    200,
                    json={"code": 200, "data": {"taskId": "task-1", "state": "generating", "progress": 20}},
                )
            return httpx.Response(
                200,
                json={
                    "code": 505,
                    "data": {
                        "taskId": "task-1",
                        "state": "success",
                        "progress": 100,
                        "resultJson": json.dumps({"resultUrls": ["https://1.1.1.1/result.png"]}),
                    },
                },
            )
        if path == "/result.png":
            requests.append((path, auth, None))
            return httpx.Response(200, content=image_bytes, headers={"Content-Type": "image/png"})
        return httpx.Response(404)

    generator, store, workspace, client = _harness(tmp_path, handler)
    agent_id = next(iter(store.list_agents("owner")))["id"]
    progress: list[dict[str, Any]] = []

    async def run() -> ImageGenerationResult:
        return await generator.generate(
            "owner",
            agent_id,
            "A small paper boat under a moonlit sky",
            relative_path="generated/boat.png",
            on_progress=lambda item: progress.append(item.as_dict()),
        )

    try:
        result = asyncio.run(run())
    finally:
        asyncio.run(client.aclose())

    assert isinstance(result, ImageGenerationResult)
    assert result.file_id == result.file["id"]
    assert result.path == "generated/boat.png"
    assert result.mime == "image/png"
    assert result.image_bytes == image_bytes
    assert result.image == image_bytes
    assert result.image_data_url.startswith("data:image/png;base64,")
    assert result.download_url == f"/bot/api/files/{result.file_id}/download"
    assert workspace.path_for("owner", agent_id, result.path, must_exist=True).read_bytes() == image_bytes
    assert store.get_file("owner", result.file_id)["relative_path"] == result.path
    assert progress == [
        {"task_id": "task-1", "state": "generating", "progress": 20},
        {"task_id": "task-1", "state": "success", "progress": 100},
    ]
    provider_calls = [item for item in requests if item[0].endswith("Task") or item[0].endswith("recordInfo")]
    assert provider_calls and all(item[1] == "Bearer test-kie-secret" for item in provider_calls)
    asset_calls = [item for item in requests if item[0] == "/result.png"]
    assert asset_calls == [("/result.png", None, None)]


def test_redirect_to_private_or_http_host_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(APIError) as private:
        validate_public_https_url("https://127.0.0.1/result.png")
    assert private.value.code == "image_result_url_invalid"
    with pytest.raises(APIError) as insecure:
        validate_public_https_url("http://1.1.1.1/result.png")
    assert insecure.value.code == "image_result_url_invalid"

    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("createTask"):
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "task-1"}})
        if request.url.path.endswith("recordInfo"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "state": "success",
                        "resultJson": {"resultUrls": ["https://1.1.1.1/result.png"]},
                    },
                },
            )
        if request.url.path == "/result.png":
            return httpx.Response(302, headers={"Location": "http://1.1.1.1/internal"})
        return httpx.Response(200, content=b"bad", headers={"Content-Type": "image/png"})

    # Avoid a live DNS lookup for the test-only public IP result host.  The
    # private and scheme checks above still execute without a transport.
    monkeypatch.setattr("app.image_generation._resolve_public_addresses", lambda *_args: None)
    generator, store, _workspace, client = _harness(tmp_path, handler)
    agent_id = next(iter(store.list_agents("owner")))["id"]

    async def run() -> None:
        with pytest.raises(APIError) as invalid:
            await generator.generate("owner", agent_id, "cat", timeout_seconds=1)
        assert invalid.value.code == "image_result_url_invalid"

    try:
        asyncio.run(run())
    finally:
        asyncio.run(client.aclose())
    assert [request.url.path for request in requests if request.url.path == "/result.png"] == ["/result.png"]


def test_download_size_limit_and_cancellation(tmp_path: Path) -> None:
    async def oversized_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createTask"):
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "task-1"}})
        if request.url.path.endswith("recordInfo"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "state": "success",
                        "resultJson": {"resultUrls": ["https://1.1.1.1/result.png"]},
                    },
                },
            )
        return httpx.Response(200, content=b"x" * 33, headers={"Content-Type": "image/png"})

    generator, store, _workspace, client = _harness(tmp_path, oversized_handler, max_image_bytes=32)
    agent_id = next(iter(store.list_agents("owner")))["id"]

    async def run_size() -> None:
        with pytest.raises(APIError) as oversized:
            await generator.generate("owner", agent_id, "cat")
        assert oversized.value.code == "image_too_large"

    asyncio.run(run_size())
    asyncio.run(client.aclose())

    async def pending_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createTask"):
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "task-2"}})
        await asyncio.sleep(1)
        return httpx.Response(200, json={"code": 200, "data": {"state": "generating"}})

    generator, store, _workspace, client = _harness(tmp_path / "cancel", pending_handler)
    agent_id = next(iter(store.list_agents("owner")))["id"]
    cancel_event = asyncio.Event()

    async def run_cancel() -> None:
        task = asyncio.create_task(
            generator.generate("owner", agent_id, "cat", cancel_event=cancel_event, timeout_seconds=5)
        )
        await asyncio.sleep(0.01)
        cancel_event.set()
        with pytest.raises(APIError) as cancelled:
            await task
        assert cancelled.value.code == "image_generation_cancelled"

    try:
        asyncio.run(run_cancel())
    finally:
        asyncio.run(client.aclose())


def test_config_from_env_uses_safe_defaults_and_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIE_API_KEY", "secret-that-must-not-be-printed")
    monkeypatch.setenv("KIE_IMAGE_MODEL", "gpt-image-2-text-to-image")
    monkeypatch.setenv("KIE_IMAGE_TIMEOUT_SECONDS", "30")
    config = ImageGenerationConfig.from_env()
    assert config.configured is True
    assert config.model == "gpt-image-2-text-to-image"
    assert config.timeout_seconds == 30
    assert "secret-that-must-not-be-printed" not in repr(config)
    assert "secret-that-must-not-be-printed" not in str(config.public_dict())


def test_signed_cdn_urls_and_false_image_mime(monkeypatch):
    from app.image_generation import _mime_and_extension
    monkeypatch.setattr('app.image_generation._resolve_public_addresses', lambda host, port: None)
    url = 'https://cdn.example.test/image.png?token=signed-example&expires=123'
    assert validate_public_https_url(url) == url
    with pytest.raises(APIError):
        _mime_and_extension('image/png', url, b'not an image')

