"""Small, server-side adapter for Composio's v3.1 tool router API.

The adapter deliberately keeps provider details at the HTTP boundary.  It does
not manage OAuth state, approvals, private values, or action retries; those
responsibilities belong to the application layer.  In particular, a timeout
while executing a tool is reported as an uncertain outcome and the request is
never retried here.

The request and response shapes are based on the official v3.1 references:

* https://docs.composio.dev/reference/api-reference/tool-router/postToolRouterSession
* https://docs.composio.dev/reference/api-reference/tool-router/getToolRouterSessionBySessionIdToolkits
* https://docs.composio.dev/reference/api-reference/tool-router/postToolRouterSessionBySessionIdLink
* https://docs.composio.dev/reference/api-reference/tool-router/postToolRouterSessionBySessionIdSearch
* https://docs.composio.dev/reference/api-reference/tool-router/postToolRouterSessionBySessionIdExecute
* https://docs.composio.dev/reference/api-reference/connected-accounts/getConnectedAccounts
* https://docs.composio.dev/reference/api-reference/connected-accounts/deleteConnectedAccountsByNanoid
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx

from .errors import APIError


COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v3.1"
MAX_USER_ID_LENGTH = 256
MAX_SESSION_ID_LENGTH = 256
MAX_TOOLKIT_LENGTH = 256
MAX_TOOL_SLUG_LENGTH = 256
MAX_ACCOUNT_ID_LENGTH = 256
MAX_QUERY_LENGTH = 1_000
MAX_CALLBACK_URL_LENGTH = 2_048
MAX_CURSOR_LENGTH = 1_024
MAX_ARGUMENTS_BYTES = 512 * 1024


class ProviderError(APIError):
    """An upstream or input error with no provider response body attached.

    ``APIError`` is used as the base so application routes can translate this
    error through the existing error handler.  The extra attributes are kept
    for the action broker and are intentionally absent from ``as_dict``: raw
    provider payloads often contain account or credential details.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        provider: str,
        request_id: str | None = None,
        retryable: bool = False,
        uncertain: bool = False,
    ) -> None:
        super().__init__(status_code, code, message)
        self.provider = provider
        self.request_id = request_id
        self.retryable = retryable
        self.uncertain = uncertain


ComposioProviderError = ProviderError


def _request_id(response: httpx.Response) -> str | None:
    """Return a bounded tracing ID without exposing arbitrary response data."""

    for name in (
        "x-request-id",
        "x-composio-request-id",
        "x-correlation-id",
        "x-generation-id",
    ):
        value = response.headers.get(name)
        if value and len(value) <= 128 and all(char.isalnum() or char in "._-" for char in value):
            return value
    return None


def _status_error(
    provider: str,
    status_code: int,
    *,
    request_id: str | None = None,
    uncertain: bool = False,
) -> ProviderError:
    """Map an upstream status to a stable, body-free application error."""

    if status_code == 400:
        code, message = "provider_bad_request", "The provider rejected this request."
    elif status_code == 401:
        code, message = "provider_auth_failed", "The provider authentication was rejected."
    elif status_code == 403:
        code, message = "provider_forbidden", "The provider denied this request."
    elif status_code == 402:
        code, message = "provider_payment_required", "The provider account cannot accept this request."
    elif status_code == 404:
        code, message = "provider_not_found", "The provider resource was not found."
    elif status_code == 409:
        code, message = "provider_conflict", "The provider reported a conflict."
    elif status_code == 413:
        code, message = "provider_payload_too_large", "The provider request is too large."
    elif status_code == 422:
        code, message = "provider_invalid_request", "The provider request is invalid."
    elif status_code == 429:
        code, message = "provider_rate_limited", "The provider is temporarily rate limited."
    elif status_code >= 500:
        code, message = "provider_unavailable", "The provider is temporarily unavailable."
    else:
        code, message = "provider_error", "The provider could not complete this request."

    if uncertain:
        message = "The provider result is unknown. Check the destination before trying again."
    return ProviderError(
        502 if status_code >= 500 else status_code,
        code,
        message,
        provider=provider,
        request_id=request_id,
        retryable=status_code in (408, 429) or status_code >= 500,
        uncertain=uncertain,
    )


def _text(value: Any, *, maximum: int = 8_192) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:maximum]
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def _json_value(value: Any, *, depth: int = 0) -> Any:
    """Copy JSON-shaped provider data while bounding pathological responses."""

    if depth > 8:
        return "[truncated]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value[:16_384] if isinstance(value, str) else value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 200:
                break
            result[str(key)[:256]] = _json_value(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item, depth=depth + 1) for item in list(value)[:200]]
    return None


def _input_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ProviderError(400, "provider_input_invalid", f"{field} must be a string.", provider="composio")
    value = value.strip()
    if not value:
        raise ProviderError(400, "provider_input_invalid", f"{field} is required.", provider="composio")
    if len(value) > maximum:
        raise ProviderError(400, "provider_input_invalid", f"{field} is too long.", provider="composio")
    return value


def _optional_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderError(400, "provider_input_invalid", "cursor must be a string.", provider="composio")
    value = value.strip()
    if len(value) > MAX_CURSOR_LENGTH:
        raise ProviderError(400, "provider_input_invalid", "cursor is too long.", provider="composio")
    return value or None


def _page(payload: Mapping[str, Any]) -> tuple[list[Any], str | None]:
    raw_items = payload.get("items")
    items = list(raw_items) if isinstance(raw_items, Sequence) and not isinstance(raw_items, (str, bytes, bytearray)) else []
    next_cursor = _text(payload.get("next_cursor") or payload.get("nextCursor"), maximum=MAX_CURSOR_LENGTH)
    return items, next_cursor


class ConnectionProvider:
    """Composio v3.1 adapter with an injectable HTTP transport."""

    provider_name = "composio"

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = COMPOSIO_BASE_URL,
        timeout: float = 15.0,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("A Composio API key is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "x-api-key": api_key,
            },
            timeout=httpx.Timeout(timeout),
            transport=transport,
            trust_env=False,
        )

    async def __aenter__(self) -> "ConnectionProvider":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    close = aclose

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Any = None,
        uncertain_on_timeout: bool = False,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, json=json_body, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                504,
                "provider_timeout",
                "The provider request timed out."
                if not uncertain_on_timeout
                else "The provider result is unknown. Check the destination before trying again.",
                provider=self.provider_name,
                retryable=False,
                uncertain=uncertain_on_timeout,
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                503,
                "provider_unavailable",
                "The provider could not be reached.",
                provider=self.provider_name,
                retryable=True,
            ) from exc

        if not 200 <= response.status_code < 300:
            raise _status_error(
                self.provider_name,
                response.status_code,
                request_id=_request_id(response),
                uncertain=uncertain_on_timeout and response.status_code in (408, 504),
            )
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                502,
                "provider_invalid_response",
                "The provider returned an invalid response.",
                provider=self.provider_name,
                request_id=_request_id(response),
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProviderError(
                502,
                "provider_invalid_response",
                "The provider returned an invalid response.",
                provider=self.provider_name,
                request_id=_request_id(response),
            )
        return dict(payload)

    @staticmethod
    def _toolkit(item: Any) -> dict[str, Any]:
        item = item if isinstance(item, Mapping) else {}
        meta = item.get("meta") if isinstance(item.get("meta"), Mapping) else {}
        connected = item.get("connected_account")
        connected_item = None
        if isinstance(connected, Mapping):
            connected_item = {
                "id": _text(connected.get("id"), maximum=MAX_ACCOUNT_ID_LENGTH),
                "user_id": _text(connected.get("user_id"), maximum=MAX_USER_ID_LENGTH),
                "status": _text(connected.get("status"), maximum=64),
                "created_at": _text(connected.get("created_at"), maximum=128),
            }
        slug = _text(item.get("slug"), maximum=MAX_TOOLKIT_LENGTH) or _text(item.get("id"), maximum=MAX_TOOLKIT_LENGTH) or ""
        name = _text(item.get("name"), maximum=256) or slug
        return {
            "slug": slug,
            "name": name,
            "description": _text(item.get("description"), maximum=4_096)
            or _text(meta.get("description"), maximum=4_096),
            "logo_url": _text(item.get("logo"), maximum=2_048) or _text(meta.get("logo"), maximum=2_048),
            "enabled": bool(item.get("enabled", True)),
            "is_no_auth": bool(item.get("is_no_auth", meta.get("isNoAuth", False))),
            "managed_auth_schemes": [
                value
                for value in (
                    _text(scheme, maximum=64)
                    for scheme in (item.get("composio_managed_auth_schemes") or [])
                )
                if value
            ],
            "connected": bool(item.get("is_connected", connected_item is not None)),
            "connected_account": connected_item,
        }

    @staticmethod
    def _account(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, Mapping):
            return None
        toolkit_value = item.get("toolkit")
        toolkit = (
            _text(toolkit_value.get("slug"), maximum=MAX_TOOLKIT_LENGTH)
            if isinstance(toolkit_value, Mapping)
            else _text(toolkit_value, maximum=MAX_TOOLKIT_LENGTH)
        )
        account_id = _text(item.get("id"), maximum=MAX_ACCOUNT_ID_LENGTH)
        user_id = _text(item.get("user_id"), maximum=MAX_USER_ID_LENGTH)
        if not account_id or not user_id:
            return None
        alias = _text(item.get("alias"), maximum=256)
        return {
            "id": account_id,
            "toolkit": toolkit or "",
            "name": alias or toolkit or account_id,
            "alias": alias,
            "user_id": user_id,
            "status": _text(item.get("status"), maximum=64) or "UNKNOWN",
            "account_type": _text(
                (item.get("experimental") or {}).get("account_type")
                if isinstance(item.get("experimental"), Mapping)
                else None,
                maximum=32,
            )
            or "PRIVATE",
            "is_disabled": bool(
                ((item.get("auth_config") or {}).get("is_disabled", False))
                if isinstance(item.get("auth_config"), Mapping)
                else item.get("is_disabled", False)
            ),
            "created_at": _text(item.get("created_at"), maximum=128),
            "updated_at": _text(item.get("updated_at"), maximum=128),
        }

    @staticmethod
    def _search_result(item: Any) -> dict[str, Any]:
        item = item if isinstance(item, Mapping) else {}

        def strings(key: str, maximum: int = 256) -> list[str]:
            raw = item.get(key)
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
                return []
            return [value for value in (_text(entry, maximum=maximum) for entry in raw[:100]) if value]

        return {
            "index": item.get("index") if isinstance(item.get("index"), int) else None,
            "use_case": _text(item.get("use_case"), maximum=2_000),
            "execution_guidance": _text(item.get("execution_guidance"), maximum=8_192),
            "difficulty": _text(item.get("difficulty"), maximum=64),
            "recommended_plan_steps": strings("recommended_plan_steps", 2_000),
            "known_pitfalls": strings("known_pitfalls", 2_000),
            "primary_tool_slugs": strings("primary_tool_slugs", MAX_TOOL_SLUG_LENGTH),
            "related_tool_slugs": strings("related_tool_slugs", MAX_TOOL_SLUG_LENGTH),
            "toolkits": strings("toolkits", MAX_TOOLKIT_LENGTH),
            "plan_id": _text(item.get("plan_id"), maximum=256),
            "error": _text(item.get("error"), maximum=2_000),
        }

    @staticmethod
    def _tool_schemas(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        schemas: dict[str, Any] = {}
        for key, item in list(value.items())[:200]:
            if not isinstance(item, Mapping):
                continue
            schemas[str(key)[:MAX_TOOL_SLUG_LENGTH]] = {
                "toolkit": _text(item.get("toolkit"), maximum=MAX_TOOLKIT_LENGTH),
                "tool_slug": _text(item.get("tool_slug"), maximum=MAX_TOOL_SLUG_LENGTH),
                "description": _text(item.get("description"), maximum=8_192),
                "input_schema": _json_value(item.get("input_schema")),
                "output_schema": _json_value(item.get("output_schema")),
                "has_full_schema": bool(item.get("hasFullSchema", item.get("has_full_schema", False))),
                "schema_ref": _json_value(item.get("schemaRef", item.get("schema_ref"))),
            }
        return schemas

    async def create_session(self, user_id: str, *, connected_accounts: Mapping[str, list[str]] | None = None) -> dict[str, Any]:
        """Create an isolated session with provider-side management disabled."""

        user_id = _input_text(user_id, "user_id", MAX_USER_ID_LENGTH)
        payload = await self._request(
            "POST",
            "/tool_router/session",
            json_body={
                "user_id": user_id,
                **({"connected_accounts": dict(connected_accounts)} if connected_accounts else {}),
                "manage_connections": {
                    "enable": False,
                    "enable_wait_for_connections": False,
                    "enable_connection_removal": False,
                },
                "workbench": {"enable": False, "enable_proxy_execution": False},
                "search": {"enable": True},
                "execute": {"enable_multi_execute": False},
            },
            uncertain_on_timeout=True,
        )
        session_id = _text(payload.get("session_id"), maximum=MAX_SESSION_ID_LENGTH)
        if not session_id:
            raise ProviderError(
                502,
                "provider_invalid_response",
                "The provider did not return a session ID.",
                provider=self.provider_name,
            )
        mcp = payload.get("mcp") if isinstance(payload.get("mcp"), Mapping) else {}
        config = payload.get("config") if isinstance(payload.get("config"), Mapping) else {}
        warnings = payload.get("warnings")
        safe_warnings = []
        if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes, bytearray)):
            for warning in list(warnings)[:50]:
                if isinstance(warning, Mapping):
                    safe_warnings.append(
                        {
                            "code": _text(warning.get("code"), maximum=128),
                            "message": _text(warning.get("message"), maximum=2_000),
                        }
                    )
        return {
            "session_id": session_id,
            "user_id": user_id,
            "mcp_url": _text(mcp.get("url"), maximum=2_048),
            "mcp": {
                "type": _text(mcp.get("type"), maximum=32),
                "url": _text(mcp.get("url"), maximum=2_048),
            },
            "tool_router_tools": [
                value
                for value in (
                    _text(tool, maximum=MAX_TOOL_SLUG_LENGTH)
                    for tool in (payload.get("tool_router_tools") or [])
                )
                if value
            ],
            "config": {
                "user_id": _text(config.get("user_id"), maximum=MAX_USER_ID_LENGTH) or user_id,
                "manage_connections": _json_value(config.get("manage_connections")),
                "workbench": _json_value(config.get("workbench")),
                "search": _json_value(config.get("search")),
                "execute": _json_value(config.get("execute")),
            },
            "config_version": payload.get("config_version") if isinstance(payload.get("config_version"), int) else None,
            "warnings": safe_warnings,
        }

    async def catalog(self, session_id: str, query: str = "", cursor: str | None = None) -> dict[str, Any]:
        """List session toolkits, using Composio's server-side search filter."""

        session_id = _input_text(session_id, "session_id", MAX_SESSION_ID_LENGTH)
        if not isinstance(query, str):
            raise ProviderError(400, "provider_input_invalid", "query must be a string.", provider=self.provider_name)
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise ProviderError(400, "provider_input_invalid", "query is too long.", provider=self.provider_name)
        cursor = _optional_cursor(cursor)
        params: list[tuple[str, str | int]] = [("limit", 50)]
        if query:
            params.append(("search", query))
        if cursor:
            params.append(("cursor", cursor))
        payload = await self._request(
            "GET",
            f"/tool_router/session/{session_id}/toolkits",
            params=params,
        )
        raw_items, next_cursor = _page(payload)
        items = [self._toolkit(item) for item in raw_items]
        return {
            "items": items,
            # ``catalog`` is retained as a small compatibility alias for the
            # application service while ``items`` mirrors Composio pagination.
            "catalog": items,
            "next_cursor": next_cursor,
            "query": query,
            "total_items": payload.get("total_items") if isinstance(payload.get("total_items"), int) else None,
        }

    async def link(self, session_id: str, toolkit: str, callback_url: str) -> dict[str, Any]:
        """Create a hosted managed-auth link for one selected toolkit."""

        session_id = _input_text(session_id, "session_id", MAX_SESSION_ID_LENGTH)
        toolkit = _input_text(toolkit, "toolkit", MAX_TOOLKIT_LENGTH)
        callback_url = _input_text(callback_url, "callback_url", MAX_CALLBACK_URL_LENGTH)
        parsed = urlsplit(callback_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderError(
                400,
                "provider_input_invalid",
                "callback_url must be an HTTPS URL.",
                provider=self.provider_name,
            )
        payload = await self._request(
            "POST",
            f"/tool_router/session/{session_id}/link",
            json_body={"toolkit": toolkit, "callback_url": callback_url},
            uncertain_on_timeout=True,
        )
        redirect_url = _text(payload.get("redirect_url"), maximum=2_048)
        if not redirect_url:
            raise ProviderError(
                502,
                "provider_invalid_response",
                "The provider did not return an authorization URL.",
                provider=self.provider_name,
            )
        return {
            "toolkit": toolkit,
            "link_token": _text(payload.get("link_token"), maximum=512),
            "redirect_url": redirect_url,
            "url": redirect_url,
            "connected_account_id": _text(payload.get("connected_account_id"), maximum=MAX_ACCOUNT_ID_LENGTH),
            "expires_at": _text(payload.get("expires_at"), maximum=128),
            "expires_in": payload.get("expires_in") if isinstance(payload.get("expires_in"), (int, float)) else None,
        }

    async def accounts(self, user_id: str) -> dict[str, Any]:
        """List only private connected accounts owned by ``user_id``."""

        user_id = _input_text(user_id, "user_id", MAX_USER_ID_LENGTH)
        payload = await self._request(
            "GET",
            "/connected_accounts",
            params=[("user_ids[]", user_id), ("account_type", "PRIVATE"), ("limit", 50)],
        )
        raw_items, next_cursor = _page(payload)
        items: list[dict[str, Any]] = []
        for raw_item in raw_items:
            account = self._account(raw_item)
            # Fail closed if a provider response ever contains an account for
            # another owner or omits its owner identity.
            if account and account["user_id"] == user_id:
                items.append(account)
        return {
            "items": items,
            # The service layer consumes this name; the canonical adapter
            # shape remains ``items`` to match Composio's response envelope.
            "accounts": items,
            "next_cursor": next_cursor,
            "user_id": user_id,
            "total_items": payload.get("total_items") if isinstance(payload.get("total_items"), int) else None,
        }

    async def disconnect(self, user_id: str, account_id: str) -> dict[str, Any]:
        """Delete an account only after proving it belongs to ``user_id``."""

        user_id = _input_text(user_id, "user_id", MAX_USER_ID_LENGTH)
        account_id = _input_text(account_id, "account_id", MAX_ACCOUNT_ID_LENGTH)
        accounts = await self.accounts(user_id)
        if not any(item.get("id") == account_id for item in accounts["items"]):
            raise ProviderError(
                404,
                "connected_account_not_owned",
                "The connected account was not found for this user.",
                provider=self.provider_name,
            )
        await self._request(
            "DELETE",
            f"/connected_accounts/{account_id}",
            uncertain_on_timeout=True,
        )
        return {"account_id": account_id, "deleted": True}

    async def search_tools(self, session_id: str, query: str) -> dict[str, Any]:
        """Search tool schemas for a use case within a session."""

        session_id = _input_text(session_id, "session_id", MAX_SESSION_ID_LENGTH)
        query = _input_text(query, "query", MAX_QUERY_LENGTH)
        payload = await self._request(
            "POST",
            f"/tool_router/session/{session_id}/search",
            json_body={"queries": [{"use_case": query}]},
            uncertain_on_timeout=True,
        )
        statuses = payload.get("toolkit_connection_statuses")
        safe_statuses = []
        if isinstance(statuses, Sequence) and not isinstance(statuses, (str, bytes, bytearray)):
            for status in list(statuses)[:200]:
                if not isinstance(status, Mapping):
                    continue
                accounts = status.get("accounts")
                safe_accounts = []
                if isinstance(accounts, Sequence) and not isinstance(accounts, (str, bytes, bytearray)):
                    for account in list(accounts)[:50]:
                        if isinstance(account, Mapping):
                            safe_accounts.append(
                                {
                                    "id": _text(account.get("id"), maximum=MAX_ACCOUNT_ID_LENGTH),
                                    "alias": _text(account.get("alias"), maximum=256),
                                    "status": _text(account.get("status"), maximum=64),
                                    "account_type": _text(account.get("account_type"), maximum=32),
                                    "is_default": bool(account.get("is_default", False)),
                                }
                            )
                safe_statuses.append(
                    {
                        "toolkit": _text(status.get("toolkit"), maximum=MAX_TOOLKIT_LENGTH),
                        "description": _text(status.get("description"), maximum=4_096),
                        "has_active_connection": bool(status.get("has_active_connection", False)),
                        "account_selection": _text(status.get("account_selection"), maximum=64),
                        "status_message": _text(status.get("status_message"), maximum=2_000),
                        "accounts": safe_accounts,
                    }
                )
        guidance = payload.get("next_steps_guidance")
        tool_schemas = self._tool_schemas(payload.get("tool_schemas"))
        tools = []
        for slug, schema in tool_schemas.items():
            if not isinstance(schema, Mapping):
                continue
            tools.append(
                {
                    "slug": schema.get("tool_slug") or slug,
                    "name": schema.get("tool_slug") or slug,
                    "toolkit": schema.get("toolkit"),
                    "description": schema.get("description"),
                    "input_schema": schema.get("input_schema"),
                    "output_schema": schema.get("output_schema"),
                }
            )
        return {
            "success": bool(payload.get("success", True)),
            "error": _text(payload.get("error"), maximum=2_000),
            "results": [
                self._search_result(item)
                for item in (
                    list(payload.get("results"))[:100]
                    if isinstance(payload.get("results"), Sequence)
                    and not isinstance(payload.get("results"), (str, bytes, bytearray))
                    else []
                )
            ],
            "toolkit_connection_statuses": safe_statuses,
            "tool_schemas": tool_schemas,
            "tools": tools,
            "next_steps_guidance": [
                value
                for value in (
                    _text(item, maximum=2_000)
                    for item in (
                        list(guidance)[:100]
                        if isinstance(guidance, Sequence)
                        and not isinstance(guidance, (str, bytes, bytearray))
                        else []
                    )
                )
                if value
            ],
        }

    async def execute(
        self,
        session_id: str,
        tool_slug: str,
        arguments: Mapping[str, Any],
        account_id: str | None,
    ) -> dict[str, Any]:
        """Execute one tool; caller owns approval, identity, and redaction."""

        session_id = _input_text(session_id, "session_id", MAX_SESSION_ID_LENGTH)
        tool_slug = _input_text(tool_slug, "tool_slug", MAX_TOOL_SLUG_LENGTH)
        if not isinstance(arguments, Mapping):
            raise ProviderError(400, "provider_input_invalid", "arguments must be an object.", provider=self.provider_name)
        arguments = dict(arguments)
        try:
            import json

            if len(json.dumps(arguments, ensure_ascii=False).encode("utf-8")) > MAX_ARGUMENTS_BYTES:
                raise ProviderError(400, "provider_input_invalid", "arguments are too large.", provider=self.provider_name)
        except (TypeError, ValueError) as exc:
            raise ProviderError(400, "provider_input_invalid", "arguments must be JSON-compatible.", provider=self.provider_name) from exc
        if account_id is not None:
            account_id = _input_text(account_id, "account_id", MAX_ACCOUNT_ID_LENGTH)
        body: dict[str, Any] = {
            "tool_slug": tool_slug,
            "arguments": arguments,
            # Keep workbench offload disabled per the product boundary.
            "enable_auto_workbench_offload": False,
        }
        if account_id:
            body["account"] = account_id
        payload = await self._request(
            "POST",
            f"/tool_router/session/{session_id}/execute",
            json_body=body,
            uncertain_on_timeout=True,
        )
        return {
            "data": _json_value(payload.get("data")),
            "error": _text(payload.get("error"), maximum=4_096),
            "log_id": _text(payload.get("log_id"), maximum=256),
        }


ComposioProvider = ConnectionProvider
ComposioConnectionProvider = ConnectionProvider


__all__ = [
    "COMPOSIO_BASE_URL",
    "ComposioConnectionProvider",
    "ComposioProvider",
    "ComposioProviderError",
    "ConnectionProvider",
    "ProviderError",
]

