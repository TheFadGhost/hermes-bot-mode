"""Durable asynchronous chat task orchestration."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Mapping
from typing import Any

from .contracts import RuntimeEvent, TurnRequest
from .errors import APIError
from .learned_skills import LearnedSkills
from .runtime import RuntimeUnavailable, runtime_status
from .store import Store
from .workspace import Workspace


TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
INTERRUPTED_TURN_STATUSES = {"interrupted", "cancelled", "canceled"}
SKILL_CONTEXT_LIMIT = 12_000
FILE_CONTEXT_LIMIT = 12_000


class RuntimeTurnInterrupted(RuntimeError):
    """The app-server ended a turn without completing it."""


def _event_parts(event: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(event, RuntimeEvent):
        return event.event_type, dict(event.data)
    if isinstance(event, Mapping):
        event_type = str(event.get("event_type", event.get("type", "runtime.event")))
        data = event.get("data", event)
        return event_type, dict(data) if isinstance(data, Mapping) else {"value": data}
    return "runtime.event", {"value": str(event)}


class TaskManager:
    def __init__(self, store: Store, workspace: Workspace, runtime: Any, *, messenger: Any = None, history: Any = None, desktop: Any = None):
        self.store = store
        self.workspace = workspace
        self.runtime = runtime
        self.messenger = messenger
        self.history = history
        self.desktop = desktop
        self.learned_skills = LearnedSkills(store)
        self._handles: dict[str, asyncio.Task[Any]] = {}
        self._cancel_requested: set[str] = set()
        self._closed = False

    async def start(self) -> None:
        # Startup recovery marks in-flight work failed in one transaction. Keep
        # the source IDs so pending learned procedures from those turns are
        # discarded along with the durable task outcome.
        with self.store.db.read() as connection:
            restarted = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM tasks WHERE status IN ('queued', 'running')"
                ).fetchall()
            ]
        self.store.mark_restarted_tasks_failed()
        for task_id in restarted:
            self._finalize_skills(task_id, succeeded=False)
        starter = getattr(self.runtime, "start", None)
        if callable(starter):
            result = starter()
            if inspect.isawaitable(result):
                await result

    async def close(self) -> None:
        self._closed = True
        handles = list(self._handles.values())
        for handle in handles:
            handle.cancel()
        if handles:
            await asyncio.gather(*handles, return_exceptions=True)
        closer = getattr(self.runtime, "close", None)
        if callable(closer):
            result = closer()
            if inspect.isawaitable(result):
                await result

    def submit(self, user_id: str, task_id: str) -> None:
        if self._closed:
            raise APIError(503, "service_unavailable", "Bot mode is shutting down")
        if task_id in self._handles or self.store.get_task(user_id, task_id)["status"] != "queued":
            return
        handle = asyncio.create_task(self._run(user_id, task_id), name=f"bot-task-{task_id}")
        self._handles[task_id] = handle
        handle.add_done_callback(lambda _: self._handles.pop(task_id, None))

    def _finalize_skills(self, task_id: str, *, succeeded: bool) -> None:
        # A procedure proposal is auxiliary task data. A storage problem in
        # that table must never rewrite the durable result of the chat turn.
        try:
            self.learned_skills.finalize_task(task_id, succeeded=succeeded)
        except Exception:
            pass

    def _append_partial_output(
        self,
        user_id: str,
        task_id: str,
        text_parts: list[str],
        image_artifacts: list[Mapping[str, Any]] | None = None,
    ) -> str | None:
        text = self._output_with_image_artifacts("".join(text_parts).strip(), image_artifacts or [])
        if not text:
            return None
        message_id = self.store.append_assistant_message(
            user_id,
            task_id,
            text,
            status="partial",
            metadata={"partial": True, "task_id": task_id},
        )
        self.store.append_task_event(task_id, "assistant.partial", {"message_id": message_id})
        return message_id

    def _record_cancelled(
        self,
        user_id: str,
        task_id: str,
        *,
        reason: str,
        error_code: str = "cancelled",
        error_message: str = "Task cancelled",
        partial_message_id: str | None = None,
    ) -> None:
        changed = self.store.cancel_task(
            task_id,
            error_code=error_code,
            error_message=error_message,
        )
        if not changed:
            return
        data: dict[str, Any] = {"reason": reason}
        if partial_message_id:
            data["message_id"] = partial_message_id
        self.store.append_task_event(task_id, "task.cancelled", data)
        self.store.activity(user_id, "task.cancelled", {"task_id": task_id, "reason": reason})
        self._finalize_skills(task_id, succeeded=False)

    def _record_failure(
        self,
        user_id: str,
        task_id: str,
        *,
        code: str,
        message: str,
    ) -> None:
        current = self.store.get_task(user_id, task_id)
        if current["status"] in TERMINAL_TASK_STATUSES:
            return
        self.store.finish_task(task_id, status="failed", error_code=code, error_message=message)
        self.store.append_task_event(task_id, "task.error", {"code": code, "message": message})
        self.store.activity(user_id, "task.failed", {"task_id": task_id, "code": code})
        self._finalize_skills(task_id, succeeded=False)

    def _cancel_was_requested(self, task_id: str) -> bool:
        return task_id in self._cancel_requested

    def _source_attachments(
        self,
        user_id: str,
        agent_id: str,
        target: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        metadata = target.get("metadata")
        raw_attachments = metadata.get("attachments", []) if isinstance(metadata, Mapping) else []
        if not isinstance(raw_attachments, (list, tuple)):
            return []
        attachments: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in raw_attachments:
            if not isinstance(raw, Mapping):
                continue
            file_id = str(raw.get("file_id", "")).strip()
            if not file_id or file_id in seen:
                continue
            try:
                file = self.store.get_file(user_id, file_id)
            except APIError:
                continue
            allowed = str(file.get("agent_id")) == str(agent_id)
            if self.messenger and target.get("conversation_id"):
                allowed = self.messenger.file_allowed(user_id, agent_id, str(target["conversation_id"]), file_id)
            if not allowed:
                continue
            path = str(file.get("relative_path", ""))
            if not path:
                continue
            attachments.append(
                {
                    "file_id": file_id,
                    "path": path,
                    "name": str(raw.get("name") or path.rsplit("/", 1)[-1]),
                    "content_type": str(file.get("content_type", "application/octet-stream")),
                }
            )
            seen.add(file_id)
        return attachments

    @staticmethod
    def _attachment_context(attachments: list[Mapping[str, str]]) -> str:
        def encode(items: list[Mapping[str, str]]) -> str:
            return json.dumps(items, ensure_ascii=False, separators=(",", ":"))

        selected: list[Mapping[str, str]] = []
        for attachment in attachments:
            candidate = encode([*selected, attachment])
            if len(candidate) > FILE_CONTEXT_LIMIT:
                break
            selected.append(attachment)
        return encode(selected)

    @staticmethod
    def _output_with_image_artifacts(
        text: str,
        image_artifacts: list[Mapping[str, Any]],
    ) -> str:
        parts = [text] if text else []
        for artifact in image_artifacts:
            file_id = str(artifact.get("file_id", "")).strip()
            if not file_id or file_id in text:
                continue
            parts.append(f"![Generated image](/bot/api/files/{file_id}/download)")
        return "\n\n".join(parts).strip()

    def _validated_image_artifact(
        self,
        user_id: str,
        agent_id: str,
        data: Mapping[str, Any],
    ) -> dict[str, str] | None:
        tool_name = str(data.get("tool") or data.get("name") or "").strip().casefold()
        if tool_name != "image_generate" or data.get("success") is not True:
            return None
        result = data.get("result")
        if not isinstance(result, Mapping):
            return None
        file_id = str(result.get("file_id", "")).strip()
        if not file_id:
            return None
        try:
            file = self.store.get_file(user_id, file_id)
        except APIError:
            return None
        if str(file.get("agent_id")) != str(agent_id):
            return None
        return {"file_id": file_id}

    @staticmethod
    def _memory_context(rows: list[Mapping[str, Any]]) -> str:
        selected: list[dict[str, Any]] = []
        for row in rows:
            item = {key: row.get(key) for key in (
                "id", "scope", "memory_key", "source", "confidence", "supersedes_id", "updated_at"
            )}
            item["content"] = str(row.get("content", ""))[:6000]
            candidate = json.dumps([*selected, item], ensure_ascii=False, separators=(",", ":"))
            if len(candidate) <= 24_000:
                selected.append(item)
        return json.dumps(selected, ensure_ascii=False, separators=(",", ":")) if selected else ""

    @staticmethod
    def _skill_context(rows: list[Mapping[str, Any]]) -> str:
        """Serialize recalled procedures without cutting JSON mid-value."""

        def encode(items: list[Mapping[str, Any]]) -> str:
            return json.dumps(items, ensure_ascii=False, separators=(",", ":"))

        selected: list[dict[str, Any]] = []
        for row in rows:
            item = {
                "name": str(row.get("name", "")),
                "trigger": str(row.get("trigger", "")),
                "instructions": str(row.get("instructions", "")),
                "evidence": str(row.get("evidence", "")),
            }
            candidate = encode([*selected, item])
            if len(candidate) > SKILL_CONTEXT_LIMIT:
                if selected:
                    break
                # Keep a single oversized procedure useful while preserving a
                # valid bounded JSON document. Names and triggers are retained;
                # only the long procedural text is shortened.
                instructions = item["instructions"]
                low, high = 0, len(instructions)
                while low < high:
                    middle = (low + high + 1) // 2
                    item["instructions"] = instructions[:middle]
                    if len(encode([item])) <= SKILL_CONTEXT_LIMIT:
                        low = middle
                    else:
                        high = middle - 1
                item["instructions"] = instructions[:low]
                if len(encode([item])) <= SKILL_CONTEXT_LIMIT:
                    selected.append(item)
                break
            selected.append(item)
        return encode(selected)

    async def _cancel_tree(self, user_id: str, roots: list[str]) -> list[dict[str, Any]]:
        # Hold the SQLite writer lock while discovering descendants and marking
        # the entire tree. A concurrent delegation then sees a terminal parent.
        import time
        targets = list(dict.fromkeys(roots))
        changed: list[str] = []
        timestamp = int(time.time())
        with self.store.db.transaction(immediate=True) as db:
            self.store._ensure_lineage_table(db)
            frontier = list(targets)
            while frontier:
                marks = ",".join("?" for _ in frontier)
                rows = db.execute(
                    f"SELECT child_task_id FROM tool_task_lineage WHERE user_id=? AND parent_task_id IN ({marks})",
                    (user_id, *frontier),
                ).fetchall()
                frontier = [str(row[0]) for row in rows if str(row[0]) not in targets]
                targets.extend(frontier)
            for task_id in targets:
                row = db.execute("SELECT status FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)).fetchone()
                if row is None:
                    raise APIError(404, "task_not_found", "Task was not found")
                if row[0] in {"queued", "running"}:
                    changed.append(task_id)
                    self._cancel_requested.add(task_id)
                    db.execute("UPDATE tasks SET status='cancelled',error_code='cancelled',error_message='Task cancelled',updated_at=?,completed_at=? WHERE id=? AND user_id=?", (timestamp, timestamp, task_id, user_id))
                    db.execute("INSERT INTO task_events(task_id,event_type,data_json,created_at) VALUES(?,'task.cancelled',?,?)", (task_id, json.dumps({"reason": "user_requested"}), timestamp))
                elif row[0] == "cancelled" and task_id in self._handles:
                    self._cancel_requested.add(task_id)
        for task_id in changed:
            self.store.activity(user_id, "task.cancelled", {"task_id": task_id, "reason": "user_requested"})
            self._finalize_skills(task_id, succeeded=False)

        async def interrupt(task_id: str) -> None:
            if task_id not in self._cancel_requested:
                return
            try:
                canceller = getattr(self.runtime, "cancel", None)
                if callable(canceller):
                    result = canceller(task_id)
                    if inspect.isawaitable(result):
                        await result
            except Exception:
                pass
            finally:
                handle = self._handles.get(task_id)
                if handle and handle is not asyncio.current_task() and not handle.done():
                    handle.cancel()

        # All durable state is already cancelled before any interrupt can yield.
        await asyncio.gather(*(interrupt(task_id) for task_id in targets))
        # Workers synchronously save partial text on their cancellation boundary.
        await asyncio.sleep(0)
        for task_id in targets:
            handle = self._handles.get(task_id)
            if not handle or handle.done():
                self._cancel_requested.discard(task_id)
        return [self.store.get_task(user_id, task_id) for task_id in targets]

    async def cancel_request(self, user_id: str, conversation_id: str, request_id: str) -> list[dict[str, Any]]:
        if self.messenger is None:
            raise APIError(503, "messenger_unavailable", "Request cancellation is unavailable")
        roots = self.messenger.request_task_ids(user_id, conversation_id, request_id)
        if not roots:
            raise APIError(404, "request_not_found", "The request was not found")
        return await self._cancel_tree(user_id, roots)

    async def cancel(self, user_id: str, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(user_id, task_id)
        targets = [task_id]
        if self.messenger is not None and task.get("request_id"):
            origin = str(task.get("origin_conversation_id") or task["conversation_id"])
            targets = self.messenger.request_task_ids(user_id, origin, str(task["request_id"]))
            if task_id not in targets:
                targets.append(task_id)
        await self._cancel_tree(user_id, targets)
        return self.store.get_task(user_id, task_id)

    async def _run(self, user_id: str, task_id: str) -> None:
        text_parts: list[str] = []
        image_artifacts: list[dict[str, str]] = []
        try:
            if not self.store.mark_task_running(task_id):
                current = self.store.get_task(user_id, task_id)
                if current["status"] in TERMINAL_TASK_STATUSES:
                    return
                raise APIError(409, "task_not_queued", "The task is no longer queued")
            if self._cancel_was_requested(task_id):
                raise asyncio.CancelledError
            self.store.append_task_event(task_id, "task.started", {})
            task = self.store.get_task(user_id, task_id)
            message_id = task.get("message_id")
            if not message_id:
                raise APIError(409, "task_message_missing", "The task has no source user message")
            retrieval_context = "[]"
            if self.messenger and self.history:
                conversation = self.messenger.conversation(user_id, task["conversation_id"])
                agent = self.store.get_agent(user_id, task["agent_id"])
                messages, retrieval_context, metrics = self.history.prepare(user_id, conversation["id"], agent["id"], task_id, str(message_id))
                self.store.append_task_event(task_id, "context.prepared", metrics)
            else:
                conversation, agent, messages = self.store.conversation_turn_context(user_id, task["conversation_id"], message_id=str(message_id))
            target = next(
                (
                    item
                    for item in messages
                    if str(item.get("id")) == str(message_id) and item.get("role") == "user"
                ),
                None,
            )
            if target is None:
                raise APIError(409, "task_message_missing", "The task's source user message is unavailable")
            latest_text = str(target.get("content", ""))
            attachments = self._source_attachments(user_id, str(agent["id"]), target)
            memory_rows = (
                self.store.search_memory(
                    user_id,
                    latest_text,
                    agent_id=agent["id"],
                    limit=20,
                )
                if latest_text
                else []
            )
            memory_context = self._memory_context(memory_rows)
            skill_rows = (
                self.learned_skills.list(
                    user_id,
                    str(agent["id"]),
                    query=latest_text,
                    enabled_only=True,
                )
                if latest_text
                else []
            )
            teachings = getattr(self, 'teachings', None)
            if teachings is not None:
                skill_rows.extend(teachings.context(user_id, str(agent['id']), latest_text))
            skill_context = self._skill_context(skill_rows)
            file_context = self._attachment_context(attachments)
            request_metadata: dict[str, Any] = {
                "retrieval_context": retrieval_context,
                "conversation_kind": conversation.get("kind", "direct"),
                "request_id": task.get("request_id"),
                "parent_task_id": task.get("parent_task_id"),
                "memory_context": memory_context,
                "learned_skills_context": skill_context,
                "workspace_path": str(self.workspace.agent_root(user_id, agent["id"])),
                "shared_workspace_path": str(self.workspace.agent_root(user_id, "shared")),
            }
            if attachments:
                # Keep both structured data for adapters and a bounded string
                # for runtimes that pass references directly into the prompt.
                request_metadata["file_attachments"] = attachments
                request_metadata["file_context"] = file_context
            request = TurnRequest(
                task_id=task_id,
                user_id=user_id,
                conversation_id=conversation["id"],
                agent_id=agent["id"],
                model=agent["model"],
                instructions=agent["instructions"],
                messages=tuple(messages),
                metadata=request_metadata,
                message_id=str(message_id),
            )
            if self._cancel_was_requested(task_id):
                raise asyncio.CancelledError
            starter = getattr(self.runtime,"start",None)
            if callable(starter):
                started = starter()
                if inspect.isawaitable(started):
                    await started
            status = runtime_status(self.runtime)
            if not status.available:
                raise RuntimeUnavailable(status.reason or "Codex app-server runtime is unavailable")
            runner = self.runtime.run_turn(request)
            if inspect.isawaitable(runner):
                runner = await runner
            async for event in runner:
                if self._cancel_was_requested(task_id):
                    raise asyncio.CancelledError
                event_type, data = _event_parts(event)
                if event_type in {"assistant.delta", "assistant.message", "assistant.completed"}:
                    value = data.get("text", data.get("content", ""))
                    if value:
                        text_parts.append(str(value))
                if event_type in {"tool.completed", "scoped_tool.completed"}:
                    artifact = self._validated_image_artifact(user_id, str(agent["id"]), data)
                    if artifact and artifact["file_id"] not in {item["file_id"] for item in image_artifacts}:
                        image_artifacts.append(artifact)
                if event_type == "approval":
                    approval = self.store.upsert_approval(user_id, task_id, data)
                    data = {**data, "approval": approval}
                if event_type == "context.compacted" and self.history:
                    self.history.compacted(task_id)
                self.store.append_task_event(task_id, event_type, data)
                if event_type == "error":
                    raise RuntimeUnavailable(str(data.get("message", "Runtime reported an error")))
                if event_type == "turn.completed":
                    turn_status = str(data.get("status", "completed")).casefold()
                    if turn_status in {"failed", "error"}:
                        raise RuntimeUnavailable(str(data.get("message", "Runtime turn failed")))
                    if turn_status in INTERRUPTED_TURN_STATUSES:
                        raise RuntimeTurnInterrupted("The Codex turn was interrupted")
                    if turn_status != "completed":
                        raise RuntimeUnavailable(f"Runtime ended the turn with status {turn_status}")
            if self._cancel_was_requested(task_id):
                raise asyncio.CancelledError
            assistant_message_id = None
            assistant_text = "".join(text_parts).strip()
            assistant_text = self._output_with_image_artifacts(assistant_text, image_artifacts)
            if assistant_text:
                assistant_message_id = self.store.append_assistant_message(user_id, task_id, assistant_text)
            self.store.finish_task(task_id, status="completed")
            self._finalize_skills(task_id, succeeded=True)
            self.store.append_task_event(
                task_id,
                "task.completed",
                {"message_id": assistant_message_id} if assistant_message_id else {},
            )
            self.store.activity(user_id, "task.completed", {"task_id": task_id})
            if self.messenger and task.get("parent_task_id") and assistant_text:
                parent = self.store.get_task(user_id, task["parent_task_id"])
                self.store.append_collaboration_message(user_id, parent["conversation_id"], agent["id"], assistant_text,
                    source_task_id=task_id, request_id=task.get("request_id"))
        except asyncio.CancelledError:
            # Explicit user cancellation records durable partial output. A
            # service shutdown leaves the task running for startup recovery.
            if self._cancel_was_requested(task_id):
                partial_message_id = self._append_partial_output(user_id, task_id, text_parts, image_artifacts)
                self._record_cancelled(
                    user_id,
                    task_id,
                    reason="user_requested",
                    partial_message_id=partial_message_id,
                )
            raise
        except RuntimeTurnInterrupted as exc:
            partial_message_id = self._append_partial_output(user_id, task_id, text_parts, image_artifacts)
            requested = self._cancel_was_requested(task_id)
            self._record_cancelled(
                user_id,
                task_id,
                reason="user_requested" if requested else "runtime_interrupted",
                error_code="cancelled" if requested else "runtime_interrupted",
                error_message="Task cancelled" if requested else str(exc),
                partial_message_id=partial_message_id,
            )
        except RuntimeUnavailable as exc:
            message = str(exc)[:500] or "Codex app-server runtime is unavailable"
            if self._cancel_was_requested(task_id):
                partial_message_id = self._append_partial_output(user_id, task_id, text_parts, image_artifacts)
                self._record_cancelled(
                    user_id,
                    task_id,
                    reason="user_requested",
                    partial_message_id=partial_message_id,
                )
            else:
                self._record_failure(
                    user_id,
                    task_id,
                    code="runtime_unavailable",
                    message=message,
                )
        except APIError as exc:
            if self._cancel_was_requested(task_id):
                partial_message_id = self._append_partial_output(user_id, task_id, text_parts, image_artifacts)
                self._record_cancelled(
                    user_id,
                    task_id,
                    reason="user_requested",
                    partial_message_id=partial_message_id,
                )
            else:
                self._record_failure(user_id, task_id, code=exc.code, message=exc.message)
        except Exception as exc:  # runtime errors must be visible and durable
            message = str(exc)[:500] or "The runtime failed to process the task"
            if self._cancel_was_requested(task_id):
                partial_message_id = self._append_partial_output(user_id, task_id, text_parts, image_artifacts)
                self._record_cancelled(
                    user_id,
                    task_id,
                    reason="user_requested",
                    partial_message_id=partial_message_id,
                )
            else:
                self._record_failure(user_id, task_id, code="runtime_error", message=message)
        finally:
            self._cancel_requested.discard(task_id)
            if self.desktop and callable(getattr(self.desktop, "release_task", None)):
                try:
                    task = self.store.get_task(user_id, task_id)
                    await self.desktop.release_task(task["agent_id"], task_id)
                except Exception:
                    pass

