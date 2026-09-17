"""Pydantic request models kept small so the API contract stays readable."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class NonceRequest(BaseModel):
    # Telegram transports numeric IDs, while integrations and fixtures often
    # serialize them as strings. Normalize and validate at the route boundary
    # so Pydantic's string-only length constraints cannot raise a TypeError on
    # an integer input.
    user_id: str | int
    chat_id: str | int | None = None


class ExchangeRequest(BaseModel):
    nonce: str = Field(min_length=16, max_length=512)


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default="", max_length=20_000)
    model: str = Field(default="gpt-5.6-luna", min_length=1, max_length=200)
    status: Literal["active", "paused", "archived"] = "active"
    avatar: str | None = Field(default=None, min_length=1, max_length=32)
    color: str | None = Field(default=None, min_length=1, max_length=32)


class AgentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    instructions: str | None = Field(default=None, max_length=20_000)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "paused", "archived"] | None = None
    avatar: str | None = Field(default=None, min_length=1, max_length=32)
    color: str | None = Field(default=None, min_length=1, max_length=32)


class ConversationCreate(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=200)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    file_ids: list[str] = Field(default_factory=list, max_length=20)
    mention_agent_ids: list[str] = Field(default_factory=list, max_length=6)
    reply_to_id: str | None = Field(default=None, max_length=128)
    # Older callers omitted this value.  The messenger generates a UUID in
    # that case, while new clients can safely retry with the same key.
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    agent_ids: list[str] = Field(min_length=2, max_length=6)
    coordinator_id: str | None = Field(default=None, max_length=128)


class GroupPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    agent_ids: list[str] | None = Field(default=None, min_length=2, max_length=6)
    coordinator_id: str | None = Field(default=None, max_length=128)
    archived: bool | None = None
    pinned: bool | None = None


class ReadMark(BaseModel):
    through_message_id: str = Field(min_length=1, max_length=128)


class FileGrantCreate(BaseModel):
    file_ids: list[str] = Field(min_length=1, max_length=20)
    granted_by_agent_id: str | None = Field(default=None, max_length=128)


class MemoryCreate(BaseModel):
    scope: Literal["shared", "private"] = "shared"
    content: str = Field(min_length=1, max_length=50_000)
    agent_id: str | None = Field(default=None, max_length=128)
    memory_key: str = Field(default="", max_length=200)
    source: str = Field(default="user", max_length=200)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    supersedes_id: int | None = Field(default=None, ge=1)


class MemoryPatch(BaseModel):
    memory_key: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=50_000)
    source: str | None = Field(default=None, max_length=200)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    supersedes_id: int | None = Field(default=None, ge=1)


class ApprovalDecision(BaseModel):
    decision: Literal["accept", "decline", "cancel"]


class CompactRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


def model_values(model: BaseModel, *, exclude_unset: bool = False) -> dict[str, Any]:
    """Support both Pydantic 1 and 2 while the service is upgraded."""

    dumper = getattr(model, "model_dump", None)
    if dumper:
        return dumper(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)

