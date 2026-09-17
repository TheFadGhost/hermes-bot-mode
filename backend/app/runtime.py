"""Runtime seam for the real Codex app-server integration.

This module contains no simulated assistant.  Until the parent integration
provides a real adapter, requests fail with an explicit unavailable status.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from .contracts import ApprovalRequest, RuntimeEvent, RuntimeStatus, TurnRequest


class RuntimeUnavailable(RuntimeError):
    """Raised when the configured agent runtime cannot accept a turn."""

    code = "runtime_unavailable"


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Adapter implemented by the Codex app-server owner.

    ``run_turn`` must yield real app-server derived events.  Returning a
    canned response is not a valid implementation.  Optional approval
    methods may be omitted; the API reports 503 when they are unavailable.
    """

    def status(self) -> RuntimeStatus:
        """Return current availability without starting work."""

    async def run_turn(self, request: TurnRequest) -> AsyncIterator[RuntimeEvent]:
        """Start one turn and yield real runtime events."""

    async def cancel(self, task_id: str) -> None:
        """Request cancellation of a running turn."""

    async def list_approvals(self, task_id: str) -> list[ApprovalRequest]:
        """Optional approval inspection hook."""

    async def respond_approval(
        self, task_id: str, approval_id: str, decision: str
    ) -> None:
        """Optional approval decision hook."""


class UnavailableRuntime:
    """Safe default until a real Codex app-server adapter is configured."""

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            available=False,
            provider="codex-app-server",
            reason="Codex app-server runtime is not configured",
        )

    async def run_turn(self, request: TurnRequest) -> AsyncIterator[RuntimeEvent]:
        raise RuntimeUnavailable("Codex app-server runtime is not configured")
        yield  # pragma: no cover - keeps this method an async generator type

    async def cancel(self, task_id: str) -> None:
        raise RuntimeUnavailable("Codex app-server runtime is not configured")

    async def list_approvals(self, task_id: str) -> list[ApprovalRequest]:
        raise RuntimeUnavailable("Codex app-server runtime is not configured")

    async def respond_approval(
        self, task_id: str, approval_id: str, decision: str
    ) -> None:
        raise RuntimeUnavailable("Codex app-server runtime is not configured")


def runtime_status(runtime: Any) -> RuntimeStatus:
    """Normalize adapter status implementations for the HTTP layer."""

    value = runtime.status() if callable(getattr(runtime, "status", None)) else runtime.status
    if isinstance(value, RuntimeStatus):
        return value
    if isinstance(value, dict):
        return RuntimeStatus(
            available=bool(value.get("available", False)),
            provider=str(value.get("provider", "codex-app-server")),
            model=value.get("model"),
            reason=value.get("reason"),
        )
    return RuntimeStatus(available=bool(value), reason=None if value else "runtime unavailable")


