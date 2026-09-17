"""Small, stable values shared by API and runtime integrations.

The runtime implementation is intentionally kept behind the Protocol in
``app.runtime``.  A real Codex app-server adapter can be added without
changing the persistence or HTTP layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RuntimeStatus:
    """Current availability of the external agent runtime."""

    available: bool
    provider: str = "codex-app-server"
    model: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TurnRequest:
    """Input supplied to one runtime turn."""

    task_id: str
    user_id: str
    conversation_id: str
    agent_id: str
    model: str
    instructions: str
    messages: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # The user message that caused this turn.  Keeping this separate from the
    # bounded history prevents a concurrent send from changing the prompt the
    # worker selects from that history.
    message_id: str | None = None


@dataclass(frozen=True)
class RuntimeEvent:
    """One event emitted by a runtime turn.

    ``event_type`` values are deliberately open.  The API stores and forwards
    them so new app-server events do not require a database migration.
    Common values are ``assistant.delta``, ``turn.completed``, ``approval``
    and ``error``.  Text deltas belong in ``data['text']``.
    """

    event_type: str
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalRequest:
    """Approval information exposed when a runtime supports approvals."""

    approval_id: str
    kind: str
    description: str
    status: str = "pending"
    data: Mapping[str, Any] = field(default_factory=dict)

