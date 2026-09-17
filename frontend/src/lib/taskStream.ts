import type { StreamEvent } from "./types";

export interface DurableTask {
  id: string;
  conversation_id: string;
  origin_conversation_id?: string | null;
  parent_task_id?: string | null;
  agent_id?: string | null;
  request_id?: string | null;
  phase?: string | null;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  error_message?: string;
}

const base = "/bot/api";
const terminal = new Set(["task.completed", "task.error", "task.failed", "task.cancelled"]);

export async function conversationTasks(conversationId: string, signal?: AbortSignal): Promise<DurableTask[]> {
  const response = await fetch(`${base}/conversations/${encodeURIComponent(conversationId)}/tasks`, { credentials: "include", signal });
  if (!response.ok) throw new Error("Couldn’t check this conversation’s active runs.");
  const body = await response.json() as { tasks?: unknown[]; data?: { tasks?: unknown[] } };
  const tasks = Array.isArray(body.tasks) ? body.tasks : Array.isArray(body.data?.tasks) ? body.data.tasks : [];
  return tasks.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")).map((item) => ({
    ...(() => {
      const error = item.error && typeof item.error === "object" ? item.error as Record<string, unknown> : null;
      return { error_message: typeof item.error_message === "string" ? item.error_message : error && typeof error.message === "string" ? error.message : undefined };
    })(),
    id: String(item.id ?? item.task_id ?? ""),
    conversation_id: String(item.conversation_id ?? conversationId),
    origin_conversation_id: item.origin_conversation_id === null || item.origin_conversation_id === undefined ? null : String(item.origin_conversation_id),
    parent_task_id: item.parent_task_id === null || item.parent_task_id === undefined ? null : String(item.parent_task_id),
    agent_id: item.agent_id === null || item.agent_id === undefined ? null : String(item.agent_id),
    request_id: item.request_id === null || item.request_id === undefined ? null : String(item.request_id),
    phase: typeof item.phase === "string" ? item.phase : null,
    status: (typeof item.status === "string" ? item.status : "running") as DurableTask["status"],
  })).filter((item) => item.id);
}

function pause(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
    const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, 1000);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
}

/** Replay durable events once, resume by cursor on transport failure, and never
 * confuse EOF with task completion. The caller owns the displayed transcript. */
export async function watchTask(taskId: string, onEvent: (event: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  let cursor = 0;
  let finished = false;
  let attempts = 0;
  while (!finished) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    try {
      const response = await fetch(`${base}/tasks/${encodeURIComponent(taskId)}/events?after_id=${cursor}`, {
        credentials: "include", headers: { Accept: "text/event-stream" }, signal,
      });
      if (!response.ok || !response.body) throw new Error(`Couldn’t reconnect to the run (${response.status}).`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const emit = (block: string) => {
        let type = "message";
        let id = 0;
        const parts: string[] = [];
        for (const line of block.split(/\r?\n/)) {
          if (line.startsWith("id:")) id = Number(line.slice(3).trim());
          if (line.startsWith("event:")) type = line.slice(6).trim();
          if (line.startsWith("data:")) parts.push(line.slice(5).trimStart());
        }
        if (!parts.length || (id && id <= cursor)) return;
        if (id) cursor = id;
        let data: StreamEvent["data"];
        try { data = JSON.parse(parts.join("\n")) as StreamEvent["data"]; }
        catch { data = parts.join("\n"); }
        onEvent({ type, data });
        if (terminal.has(type)) finished = true;
      };
      try {
        while (!finished) {
          const { done, value } = await reader.read();
          buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
          const blocks = buffer.split(/\r?\n\r?\n/);
          buffer = blocks.pop() ?? "";
          blocks.forEach(emit);
          if (done) { if (buffer.trim()) emit(buffer); break; }
        }
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
      if (finished) return;
      const stateResponse = await fetch(`${base}/tasks/${encodeURIComponent(taskId)}`, { credentials: "include", signal });
      if (!stateResponse.ok) throw new Error("Couldn’t verify whether this run finished.");
      const { task } = await stateResponse.json() as { task: DurableTask & { error?: { message?: unknown } } };
      if (["completed", "failed", "cancelled"].includes(task.status)) {
        const errorMessage = task.error_message ?? (typeof task.error?.message === "string" ? task.error.message : "");
        onEvent({ type: task.status === "failed" ? "task.error" : `task.${task.status}`, data: { message: errorMessage } });
        return;
      }
      throw new Error("The connection ended while this run was still active.");
    } catch (error) {
      if (signal?.aborted || (error instanceof DOMException && error.name === "AbortError")) throw error;
      attempts += 1;
      if (attempts > 3) throw new Error("Connection lost. Your run may still be active. Reopen this chat to reconnect and stop it.");
      onEvent({ type: "task.reconnecting", data: { attempt: attempts } });
      await pause(signal);
    }
  }
}

