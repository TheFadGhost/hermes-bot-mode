"""Contract tests for the Composio adapter; no network calls are made."""

from __future__ import annotations

import json

import httpx
import pytest

from app.connection_provider import ConnectionProvider, ProviderError


def _response(request: httpx.Request, body: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, request=request, json=body)


@pytest.mark.asyncio
async def test_create_session_uses_v31_and_disables_model_side_capabilities() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _response(
            request,
            {
                "session_id": "trs_123",
                "mcp": {"type": "http", "url": "https://app.composio.dev/mcp/trs_123"},
                "config": {"user_id": "dad"},
                "config_version": 2,
            },
            201,
        )

    provider = ConnectionProvider("composio-secret", transport=httpx.MockTransport(handler))
    try:
        result = await provider.create_session("dad")
    finally:
        await provider.aclose()

    assert result["session_id"] == "trs_123"
    assert result["mcp_url"] == "https://app.composio.dev/mcp/trs_123"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v3.1/tool_router/session"
    assert request.headers["x-api-key"] == "composio-secret"
    body = json.loads(request.content)
    assert body["user_id"] == "dad"
    assert body["manage_connections"] == {
        "enable": False,
        "enable_wait_for_connections": False,
        "enable_connection_removal": False,
    }
    assert body["workbench"] == {"enable": False, "enable_proxy_execution": False}
    assert body["search"] == {"enable": True}
    assert body["execute"] == {"enable_multi_execute": False}


@pytest.mark.asyncio
async def test_catalog_uses_server_search_and_normalizes_toolkits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v3.1/tool_router/session/trs_123/toolkits"
        assert request.url.params["search"] == "mail"
        assert request.url.params["cursor"] == "next"
        assert request.url.params["limit"] == "50"
        return _response(
            request,
            {
                "items": [
                    {
                        "slug": "GMAIL",
                        "name": "Gmail",
                        "meta": {"description": "Mail", "logo": "https://cdn.example/gmail.svg"},
                        "enabled": True,
                        "is_no_auth": False,
                        "composio_managed_auth_schemes": ["OAUTH2"],
                        "connected_account": {"id": "ca_1", "user_id": "dad", "status": "ACTIVE"},
                    }
                ],
                "next_cursor": "after",
                "total_items": 1,
            },
        )

    provider = ConnectionProvider("secret", transport=httpx.MockTransport(handler))
    try:
        result = await provider.catalog("trs_123", "mail", "next")
    finally:
        await provider.aclose()

    assert result["next_cursor"] == "after"
    expected_item = {
        "slug": "GMAIL",
        "name": "Gmail",
        "description": "Mail",
        "logo_url": "https://cdn.example/gmail.svg",
        "enabled": True,
        "is_no_auth": False,
        "managed_auth_schemes": ["OAUTH2"],
        "connected": True,
        "connected_account": {
            "id": "ca_1",
            "user_id": "dad",
            "status": "ACTIVE",
            "created_at": None,
        },
    }
    assert result["items"] == [expected_item]
    assert result["catalog"] == [expected_item]


@pytest.mark.asyncio
async def test_link_uses_tool_router_managed_auth_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3.1/tool_router/session/trs_123/link"
        assert json.loads(request.content) == {
            "toolkit": "GMAIL",
            "callback_url": "https://hermes.example/bot/?connections=return",
        }
        return _response(
            request,
            {
                "link_token": "lt_1",
                "redirect_url": "https://app.composio.dev/link/lt_1",
                "connected_account_id": "ca_1",
            },
            201,
        )

    provider = ConnectionProvider("secret", transport=httpx.MockTransport(handler))
    try:
        result = await provider.link("trs_123", "GMAIL", "https://hermes.example/bot/?connections=return")
    finally:
        await provider.aclose()

    assert result == {
        "toolkit": "GMAIL",
        "link_token": "lt_1",
        "redirect_url": "https://app.composio.dev/link/lt_1",
        "url": "https://app.composio.dev/link/lt_1",
        "connected_account_id": "ca_1",
        "expires_at": None,
        "expires_in": None,
    }


@pytest.mark.asyncio
async def test_accounts_filters_to_requested_owner_and_does_not_return_provider_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3.1/connected_accounts"
        assert request.url.params.get_list("user_ids[]") == ["alice"]
        assert request.url.params["account_type"] == "PRIVATE"
        return _response(
            request,
            {
                "items": [
                    {
                        "id": "ca_alice",
                        "user_id": "alice",
                        "alias": "Work Gmail",
                        "toolkit": {"slug": "GMAIL"},
                        "status": "ACTIVE",
                        "state": {"val": {"oauth_token": "should-never-escape"}},
                    },
                    {"id": "ca_bob", "user_id": "bob", "toolkit": {"slug": "SLACK"}, "status": "ACTIVE"},
                ],
                "next_cursor": None,
            },
        )

    provider = ConnectionProvider("secret", transport=httpx.MockTransport(handler))
    try:
        result = await provider.accounts("alice")
    finally:
        await provider.aclose()

    assert [item["id"] for item in result["items"]] == ["ca_alice"]
    assert "oauth_token" not in json.dumps(result)
    assert result["items"][0]["name"] == "Work Gmail"


@pytest.mark.asyncio
async def test_disconnect_checks_ownership_before_delete() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return _response(
                request,
                {"items": [{"id": "ca_alice", "user_id": "alice", "toolkit": {"slug": "GMAIL"}}]},
            )
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3.1/connected_accounts/ca_alice"
        return httpx.Response(204, request=request)

    provider = ConnectionProvider("secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as exc_info:
            await provider.disconnect("alice", "ca_bob")
        assert exc_info.value.code == "connected_account_not_owned"
        assert methods == ["GET"]

        result = await provider.disconnect("alice", "ca_alice")
    finally:
        await provider.aclose()

    assert result == {"account_id": "ca_alice", "deleted": True}
    assert methods == ["GET", "GET", "DELETE"]


@pytest.mark.asyncio
async def test_search_and_execute_follow_v31_body_shapes() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path.endswith("/search"):
            return _response(
                request,
                {
                    "success": True,
                    "results": [{"index": 0, "use_case": "Send mail", "primary_tool_slugs": ["GMAIL_SEND_EMAIL"]}],
                    "tool_schemas": {
                        "GMAIL_SEND_EMAIL": {
                            "toolkit": "GMAIL",
                            "tool_slug": "GMAIL_SEND_EMAIL",
                            "input_schema": {"type": "object"},
                            "hasFullSchema": True,
                        }
                    },
                },
            )
        assert request.url.path.endswith("/execute")
        return _response(request, {"data": {"status": "queued"}, "log_id": "log_1"})

    provider = ConnectionProvider("secret", transport=httpx.MockTransport(handler))
    try:
        search = await provider.search_tools("trs_123", "Send mail")
        execution = await provider.execute("trs_123", "GMAIL_SEND_EMAIL", {"to": "dad@example.com"}, "ca_1")
    finally:
        await provider.aclose()

    assert seen[0] == (
        "/api/v3.1/tool_router/session/trs_123/search",
        {"queries": [{"use_case": "Send mail"}]},
    )
    assert seen[1] == (
        "/api/v3.1/tool_router/session/trs_123/execute",
        {
            "tool_slug": "GMAIL_SEND_EMAIL",
            "arguments": {"to": "dad@example.com"},
            "account": "ca_1",
            "enable_auto_workbench_offload": False,
        },
    )
    assert search["tool_schemas"]["GMAIL_SEND_EMAIL"]["has_full_schema"] is True
    assert execution == {"data": {"status": "queued"}, "error": None, "log_id": "log_1"}


@pytest.mark.asyncio
async def test_execute_timeout_is_uncertain_and_never_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("accepted upstream, response lost", request=request)

    provider = ConnectionProvider("secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as exc_info:
            await provider.execute("trs_123", "GMAIL_SEND_EMAIL", {}, "ca_1")
    finally:
        await provider.aclose()

    assert calls == 1
    assert exc_info.value.uncertain is True
    assert exc_info.value.retryable is False
    assert "accepted upstream" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_upstream_error_body_and_api_key_are_not_exposed() -> None:
    secret = "composio-secret-do-not-leak"

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(request, {"detail": secret, "token": "upstream-token"}, 401)

    provider = ConnectionProvider(secret, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as exc_info:
            await provider.catalog("trs_123")
    finally:
        await provider.aclose()

    assert exc_info.value.code == "provider_auth_failed"
    assert secret not in str(exc_info.value)
    assert "upstream-token" not in str(exc_info.value)

