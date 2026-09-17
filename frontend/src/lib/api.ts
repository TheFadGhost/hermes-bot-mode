import { watchTask } from "./taskStream";
import type {
  ActivityItem,
  Agent,
  AgentInput,
  Approval,
  Conversation,
  FileAsset,
  InboxEntry,
  InboxMember,
  InboxTask,
  LearnedSkill,
  MemoryInput,
  MemoryItem,
  Message,
  Routine,
  RuntimeStatus,
  RuntimeAccount,
  RuntimeLogin,
  RuntimeUsage,
  RuntimeUsageWindow,
  DesktopStatus,
  ExtensionsStatus,
  ConnectionCatalogItem,
  ConnectionAccount,
  ConnectionsResponse,
  ChatRequest,
  PrivateField,
  Teaching,
  OnboardingState,
  Session,
  StreamEvent,
  TaskEnvelope,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined ?? "/bot/api").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function unwrap<T>(value: unknown, key?: string): T {
  if (key && isRecord(value) && key in value) return value[key] as T;
  if (isRecord(value) && "data" in value) return value.data as T;
  return value as T;
}

function listFrom<T>(value: unknown, key: string): T[] {
  const unwrapped = unwrap<unknown>(value, key);
  if (Array.isArray(unwrapped)) return unwrapped as T[];
  if (isRecord(unwrapped) && Array.isArray(unwrapped.items)) return unwrapped.items as T[];
  return [];
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null;
}

function normalizeAgent(value: Agent): Agent {
  const raw = value as Agent & { instructions?: string; status?: string; avatar_shape?: string };
  return {
    ...value,
    description: value.description ?? raw.instructions ?? "",
    avatar: value.avatar ?? raw.avatar_shape ?? null,
    color: value.color ?? null,
    memory_scope: value.memory_scope ?? "private",
    is_active: value.is_active ?? raw.status === "active",
  };
}

function normalizeFile(value: FileAsset): FileAsset {
  const raw = value as FileAsset & { relative_path?: string; size_bytes?: number };
  return {
    ...value,
    name: value.name || raw.relative_path || "Untitled file",
    size: value.size ?? raw.size_bytes ?? null,
  };
}

function activityTitle(eventType: string): string {
  const words = eventType.replace(/[._-]+/g, " ").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "Workspace activity";
  return words.map((word) => `${word[0]?.toUpperCase() ?? ""}${word.slice(1)}`).join(" ");
}

function normalizeActivity(value: unknown): ActivityItem {
  const raw = (isRecord(value) ? value : {}) as Record<string, unknown>;
  const payload = isRecord(raw.payload) ? raw.payload : {};
  const eventType = typeof raw.event_type === "string" ? raw.event_type : typeof raw.kind === "string" ? raw.kind : "workspace.activity";
  const timestamp = raw.created_at;
  const createdAt = typeof timestamp === "number" ? new Date(timestamp * 1000).toISOString() : typeof timestamp === "string" ? timestamp : undefined;
  const payloadMessage = typeof payload.message === "string" ? payload.message : typeof payload.detail === "string" ? payload.detail : null;
  return {
    id: String(raw.id ?? `${eventType}-${String(timestamp ?? "now")}`),
    kind: eventType,
    title: activityTitle(eventType),
    detail: payloadMessage,
    status: eventType.includes("failed") || eventType.includes("error") ? "failed" : eventType.includes("started") || eventType.includes("submitted") ? "running" : "complete",
    created_at: createdAt,
    agent_id: typeof payload.agent_id === "string" ? payload.agent_id : null,
    conversation_id: typeof payload.conversation_id === "string" ? payload.conversation_id : null,
  };
}

function normalizeSession(value: unknown): Session {
  const raw = isRecord(value) ? value : {};
  const nested = isRecord(raw.session) ? raw.session : {};
  const user = isRecord(raw.user) ? raw.user : isRecord(nested.user) ? nested.user : undefined;
  return {
    authenticated: raw.authenticated !== undefined ? Boolean(raw.authenticated) : Boolean(user),
    user: user ? { id: String(user.id ?? ""), name: typeof user.name === "string" ? user.name : undefined, username: typeof user.username === "string" ? user.username : undefined, avatar_url: typeof user.avatar_url === "string" ? user.avatar_url : null } : undefined,
    expires_at: typeof raw.expires_at === "string" ? raw.expires_at : typeof nested.expires_at === "string" ? nested.expires_at : null,
  };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    const message = isRecord(body) && isRecord(body.error) && typeof body.error.message === "string"
      ? body.error.message
      : isRecord(body) && typeof body.detail === "string"
      ? body.detail
      : isRecord(body) && typeof body.message === "string"
        ? body.message
        : `Request failed (${response.status})`;
    const code = isRecord(body) && isRecord(body.error) && typeof body.error.code === "string" ? body.error.code : isRecord(body) && typeof body.code === "string" ? body.code : undefined;
    throw new ApiError(message, response.status, code);
  }

  return body as T;
}

function encode(value: string | number): string {
  return encodeURIComponent(value);
}

export async function getSession(): Promise<Session> {
  const value = await request<unknown>("/auth/me");
  return normalizeSession(value);
}

export async function exchangeTelegramNonce(nonce: string): Promise<Session> {
  const value = await request<unknown>("/auth/exchange", {
    method: "POST",
    body: JSON.stringify({ nonce }),
  });
  return normalizeSession(value);
}

export async function logout(): Promise<void> {
  await request<void>("/auth/logout", { method: "POST" });
}

export async function listAgents(): Promise<Agent[]> {
  return listFrom<Agent>(await request("/agents"), "agents").map(normalizeAgent);
}

export async function createAgent(input: AgentInput): Promise<Agent> {
  const body = {
    name: input.name,
    instructions: input.description ?? "",
    model: input.model ?? "gpt-5.6-luna",
    status: "active",
    ...(input.avatar === undefined ? {} : { avatar: input.avatar }),
    ...(input.color === undefined ? {} : { color: input.color }),
  };
  return normalizeAgent(unwrap<Agent>(await request("/agents", { method: "POST", body: JSON.stringify(body) }), "agent"));
}

export async function updateAgent(id: string, input: Partial<AgentInput>): Promise<Agent> {
  const body = {
    ...(input.name === undefined ? {} : { name: input.name }),
    ...(input.description === undefined ? {} : { instructions: input.description }),
    ...(input.model === undefined ? {} : { model: input.model }),
    ...(input.avatar === undefined ? {} : { avatar: input.avatar }),
    ...(input.color === undefined ? {} : { color: input.color }),
  };
  return normalizeAgent(unwrap<Agent>(await request(`/agents/${encode(id)}`, { method: "PATCH", body: JSON.stringify(body) }), "agent"));
}

export async function deleteAgent(id: string): Promise<void> {
  await request<void>(`/agents/${encode(id)}`, { method: "DELETE" });
}

export async function listConversations(agentId?: string): Promise<Conversation[]> {
  const query = agentId ? `?agent_id=${encode(agentId)}` : "";
  return listFrom<Conversation>(await request(`/conversations${query}`), "conversations");
}

export async function createConversation(agentId: string, title?: string): Promise<Conversation> {
  return unwrap<Conversation>(await request("/conversations", {
    method: "POST",
    body: JSON.stringify({ agent_id: agentId, title }),
  }), "conversation");
}

export async function deleteConversation(id: string): Promise<void> {
  await request<void>(`/conversations/${encode(id)}`, { method: "DELETE" });
}

export async function listMessages(conversationId: string, beforeId?: string): Promise<Message[]> {
  return listFrom<unknown>(await request(`/conversations/${encode(conversationId)}/messages?limit=100${beforeId ? `&before_id=${encode(beforeId)}` : ""}`), "messages").map(normalizeMessage);
}

export async function listMemory(agentId?: string, scope?: string): Promise<MemoryItem[]> {
  const params = new URLSearchParams();
  if (agentId) params.set("agent_id", agentId);
  if (scope) params.set("scope", scope);
  const query = params.toString() ? `?${params.toString()}` : "";
  return listFrom<MemoryItem>(await request(`/memory${query}`), "memory");
}

export async function createMemory(input: MemoryInput): Promise<MemoryItem> {
  return unwrap<MemoryItem>(await request("/memory", {
    method: "POST",
    body: JSON.stringify(input),
  }), "memory");
}

export async function deleteMemory(id: string | number, agentId?: string): Promise<void> {
  const query = agentId ? `?agent_id=${encode(agentId)}` : "";
  await request<void>(`/memory/${encode(id)}${query}`, { method: "DELETE" });
}

export async function listSkills(agentId: string): Promise<LearnedSkill[]> {
  return listFrom<LearnedSkill>(await request(`/agents/${encode(agentId)}/skills`), "skills");
}

export async function setSkillEnabled(agentId: string, skillId: string, enabled: boolean): Promise<LearnedSkill | void> {
  const value = await request<unknown>(`/agents/${encode(agentId)}/skills/${encode(skillId)}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
  const unwrapped = unwrap<unknown>(value, "skill");
  return isRecord(unwrapped) ? unwrapped as LearnedSkill : undefined;
}

export async function deleteSkill(agentId: string, skillId: string): Promise<void> {
  await request<void>(`/agents/${encode(agentId)}/skills/${encode(skillId)}`, { method: "DELETE" });
}

export async function listFiles(agentId?: string): Promise<FileAsset[]> {
  const query = agentId ? `?agent_id=${encode(agentId)}` : "";
  return listFrom<FileAsset>(await request(`/files${query}`), "files").map(normalizeFile);
}

export async function uploadFile(file: File, agentId?: string): Promise<FileAsset> {
  const form = new FormData();
  form.append("file", file);
  if (agentId) form.append("agent_id", agentId);
  return normalizeFile(unwrap<FileAsset>(await request("/files", { method: "POST", body: form }), "file"));
}

export async function deleteFile(id: string): Promise<void> {
  await request<void>(`/files/${encode(id)}`, { method: "DELETE" });
}

export async function listActivity(agentId?: string): Promise<ActivityItem[]> {
  const query = agentId ? `?agent_id=${encode(agentId)}` : "";
  return listFrom<ActivityItem>(await request(`/activity${query}`), "events").map(normalizeActivity);
}

export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  return unwrap<RuntimeStatus>(await request("/runtime/status"), "runtime");
}

export async function getRuntimeAccount(): Promise<RuntimeAccount> {
  return unwrap<RuntimeAccount>(await request("/runtime/account"), "account");
}

export async function startRuntimeLogin(): Promise<RuntimeLogin> {
  return unwrap<RuntimeLogin>(await request("/runtime/login", { method: "POST" }), "login");
}

export async function getRuntimeUsage(): Promise<RuntimeUsage> {
  return normalizeRuntimeUsage(await request("/runtime/usage"));
}

function normalizeExtensionsStatus(value: unknown): ExtensionsStatus {
  const raw = isRecord(value) ? value : {};
  const connections = isRecord(raw.connections) ? raw.connections : {};
  const voice = isRecord(raw.voice) ? raw.voice : {};
  const privateInput = isRecord(raw.private_input) ? raw.private_input : isRecord(raw.privateInput) ? raw.privateInput : {};
  const telegram = isRecord(raw.telegram) ? raw.telegram : {};
  return {
    connections: { configured: Boolean(connections.configured) },
    voice: {
      configured: Boolean(voice.configured),
      model: typeof voice.model === "string" ? voice.model : undefined,
      max_bytes: numberValue(voice.max_bytes ?? voice.maxBytes) ?? undefined,
      max_seconds: numberValue(voice.max_seconds ?? voice.maxSeconds) ?? undefined,
    },
    private_input: { available: Boolean(privateInput.available) },
    telegram: { configured: Boolean(telegram.configured) },
  };
}

export async function getExtensionsStatus(): Promise<ExtensionsStatus> {
  return normalizeExtensionsStatus(await request("/extensions/status"));
}

function normalizeConnectionCatalog(value: unknown): ConnectionCatalogItem[] {
  return Array.isArray(value) ? value.filter(isRecord).map((item) => ({
    slug: String(item.slug ?? ""),
    name: typeof item.name === "string" ? item.name : String(item.slug ?? "Connection"),
    description: typeof item.description === "string" ? item.description : undefined,
    connected: Boolean(item.connected),
  })).filter((item) => item.slug) : [];
}

function normalizeConnectionAccounts(value: unknown): ConnectionAccount[] {
  return Array.isArray(value) ? value.filter(isRecord).map((item) => ({
    id: String(item.id ?? item.account_id ?? ""),
    toolkit: String(item.toolkit ?? item.toolkit_slug ?? ""),
    name: typeof item.name === "string" ? item.name : "Connected account",
    status: typeof item.status === "string" ? item.status : "unknown",
  })).filter((item) => item.id) : [];
}

export async function listConnections(query = "", cursor?: string | null): Promise<ConnectionsResponse> {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  if (cursor) params.set("cursor", cursor);
  const raw = await request<unknown>(`/connections${params.toString() ? `?${params.toString()}` : ""}`);
  const value = unwrap<unknown>(raw);
  const record = isRecord(value) ? value : {};
  return {
    configured: Boolean(record.configured),
    catalog: normalizeConnectionCatalog(record.catalog),
    accounts: normalizeConnectionAccounts(record.accounts),
    next_cursor: typeof record.next_cursor === "string" ? record.next_cursor : null,
  };
}

export async function createConnectionLink(toolkit: string): Promise<{ url: string; expires_at?: string | number | null }> {
  const raw = await request<unknown>("/connections/link", { method: "POST", body: JSON.stringify({ toolkit }) });
  const value = unwrap<unknown>(raw);
  const record = isRecord(value) ? value : {};
  const url = typeof record.url === "string" ? record.url : "";
  if (!url) throw new ApiError("The connection link was unavailable.", 502, "connection_link_missing");
  return { url, expires_at: typeof record.expires_at === "string" || typeof record.expires_at === "number" ? record.expires_at : null };
}

export async function disconnectConnection(accountId: string): Promise<void> {
  await request<void>(`/connections/${encode(accountId)}`, { method: "DELETE" });
}

function normalizeChatRequest(value: unknown, fallbackConversationId: string): ChatRequest {
  const raw = isRecord(value) ? value : {};
  return {
    id: String(raw.id ?? raw.request_id ?? ""),
    agent_id: String(raw.agent_id ?? ""),
    conversation_id: String(raw.conversation_id ?? fallbackConversationId),
    kind: typeof raw.kind === "string" ? raw.kind : "connector_action",
    title: typeof raw.title === "string" ? raw.title : "Action needed",
    purpose: typeof raw.purpose === "string" ? raw.purpose : null,
    status: typeof raw.status === "string" ? raw.status : "pending",
    created_at: typeof raw.created_at === "string" || typeof raw.created_at === "number" ? raw.created_at : null,
    expires_at: typeof raw.expires_at === "string" || typeof raw.expires_at === "number" ? raw.expires_at : null,
    data: isRecord(raw.data) ? raw.data : {},
    result: isRecord(raw.result) ? raw.result : undefined,
    error: typeof raw.error === "string" ? raw.error : null,
  };
}

export async function listConversationRequests(conversationId: string): Promise<ChatRequest[]> {
  const raw = await request<unknown>(`/conversations/${encode(conversationId)}/requests`);
  const value = unwrap<unknown>(raw, "requests");
  return Array.isArray(value) ? value.map((item) => normalizeChatRequest(item, conversationId)).filter((item) => item.id) : [];
}

export async function submitPrivateRequest(requestId: string, value: string, remember: boolean): Promise<ChatRequest> {
  const raw = await request<unknown>(`/requests/${encode(requestId)}/private`, { method: "POST", body: JSON.stringify({ value, remember }) });
  return normalizeChatRequest(unwrap<unknown>(raw, "request"), "");
}

export async function decideRequest(requestId: string, decision: "approve" | "deny"): Promise<ChatRequest> {
  const raw = await request<unknown>(`/requests/${encode(requestId)}/decision`, { method: "POST", body: JSON.stringify({ decision }) });
  return normalizeChatRequest(unwrap<unknown>(raw, "request"), "");
}

export async function continueRequest(requestId: string): Promise<SendConversationMessageResult> {
  const raw = await request<unknown>(`/requests/${encode(requestId)}/continue`, { method: "POST" });
  const value = unwrap<unknown>(raw);
  const record = isRecord(value) ? value : {};
  const conversationValue = isRecord(record.conversation) ? record.conversation : null;
  const conversation = conversationValue ? { ...(conversationValue as Conversation), id: String(conversationValue.id ?? conversationValue.conversation_id ?? "") } : undefined;
  const conversationId = conversation?.id ?? String(record.conversation_id ?? "");
  const task = isRecord(record.task) ? normalizeTaskEnvelope(record.task, conversationId) : undefined;
  const tasks = Array.isArray(record.tasks) ? record.tasks.map((item) => normalizeTaskEnvelope(item, conversationId)).filter((item) => item.id) : [];
  if (task?.id && !tasks.some((item) => item.id === task.id)) tasks.unshift(task);
  return { conversation, message: record.message ? normalizeMessage(record.message) : undefined, task, tasks, request_id: typeof record.request_id === "string" ? record.request_id : `continue-${Date.now()}` };
}

function normalizePrivateField(value: unknown): PrivateField {
  const raw = isRecord(value) ? value : {};
  return {
    id: String(raw.id ?? ""),
    label: typeof raw.label === "string" ? raw.label : "Private value",
    purpose: typeof raw.purpose === "string" ? raw.purpose : "Used only when you approve it.",
    expires_at: typeof raw.expires_at === "string" || typeof raw.expires_at === "number" ? raw.expires_at : null,
    one_time: Boolean(raw.one_time),
  };
}

export async function listPrivateFields(agentId: string): Promise<PrivateField[]> {
  const raw = await request<unknown>(`/agents/${encode(agentId)}/private-fields`);
  const value = unwrap<unknown>(raw, "fields");
  return Array.isArray(value) ? value.map(normalizePrivateField).filter((item) => item.id) : [];
}

export async function createPrivateField(agentId: string, input: { label: string; purpose: string; value: string; remember: boolean }): Promise<PrivateField> {
  const raw = await request<unknown>(`/agents/${encode(agentId)}/private-fields`, { method: "POST", body: JSON.stringify(input) });
  return normalizePrivateField(unwrap<unknown>(raw, "field"));
}

export async function deletePrivateField(agentId: string, fieldId: string): Promise<void> {
  await request<void>(`/agents/${encode(agentId)}/private-fields/${encode(fieldId)}`, { method: "DELETE" });
}

function normalizeTeaching(value: unknown, fallbackAgentId: string): Teaching {
  const raw = isRecord(value) ? value : {};
  const steps = Array.isArray(raw.steps) ? raw.steps.filter((step): step is string => typeof step === "string") : [];
  return {
    id: String(raw.id ?? ""),
    agent_id: String(raw.agent_id ?? fallbackAgentId),
    name: typeof raw.name === "string" ? raw.name : "Untitled procedure",
    trigger: typeof raw.trigger === "string" ? raw.trigger : "",
    steps,
    notes: typeof raw.notes === "string" ? raw.notes : null,
    frame_file_ids: Array.isArray(raw.frame_file_ids) ? raw.frame_file_ids.filter((id): id is string => typeof id === "string") : [],
    status: typeof raw.status === "string" ? raw.status : "unverified",
    revision: numberValue(raw.revision) ?? undefined,
    enabled: raw.enabled !== false,
    created_at: typeof raw.created_at === "string" || typeof raw.created_at === "number" ? raw.created_at : null,
    updated_at: typeof raw.updated_at === "string" || typeof raw.updated_at === "number" ? raw.updated_at : null,
    last_task_id: typeof raw.last_task_id === "string" ? raw.last_task_id : null,
  };
}

export async function listTeachings(agentId: string): Promise<Teaching[]> {
  const raw = await request<unknown>(`/agents/${encode(agentId)}/teachings`);
  const value = unwrap<unknown>(raw, "teachings");
  return Array.isArray(value) ? value.map((item) => normalizeTeaching(item, agentId)).filter((item) => item.id) : [];
}

export async function createTeaching(agentId: string, input: { name: string; trigger: string; steps: string[]; notes?: string; frame_file_ids?: string[] }): Promise<Teaching> {
  const raw = await request<unknown>(`/agents/${encode(agentId)}/teachings`, { method: "POST", body: JSON.stringify(input) });
  return normalizeTeaching(unwrap<unknown>(raw, "teaching"), agentId);
}

export async function updateTeaching(agentId: string, teachingId: string, input: Partial<{ name: string; trigger: string; steps: string[]; notes: string; frame_file_ids: string[]; enabled: boolean; verified: boolean }>): Promise<Teaching> {
  const raw = await request<unknown>(`/agents/${encode(agentId)}/teachings/${encode(teachingId)}`, { method: "PATCH", body: JSON.stringify(input) });
  return normalizeTeaching(unwrap<unknown>(raw, "teaching"), agentId);
}

export async function deleteTeaching(agentId: string, teachingId: string): Promise<void> {
  await request<void>(`/agents/${encode(agentId)}/teachings/${encode(teachingId)}`, { method: "DELETE" });
}

export async function runTeaching(agentId: string, teachingId: string, input: string | undefined, clientRequestId: string): Promise<SendConversationMessageResult> {
  const raw = await request<unknown>(`/agents/${encode(agentId)}/teachings/${encode(teachingId)}/run`, { method: "POST", body: JSON.stringify({ ...(input?.trim() ? { input: input.trim() } : {}), client_request_id: clientRequestId }) });
  const value = unwrap<unknown>(raw);
  const record = isRecord(value) ? value : {};
  const conversationValue = isRecord(record.conversation) ? record.conversation : null;
  const conversation = conversationValue ? { ...(conversationValue as Conversation), id: String(conversationValue.id ?? conversationValue.conversation_id ?? ""), agent_id: String(conversationValue.agent_id ?? agentId) } : undefined;
  const task = isRecord(record.task) ? normalizeTaskEnvelope(record.task, conversation?.id ?? String(record.conversation_id ?? "")) : undefined;
  const tasks = Array.isArray(record.tasks) ? record.tasks.map((item) => normalizeTaskEnvelope(item, conversation?.id ?? String(record.conversation_id ?? ""))).filter((item) => item.id) : [];
  if (task?.id && !tasks.some((item) => item.id === task.id)) tasks.unshift(task);
  return { conversation, message: record.message ? normalizeMessage(record.message) : undefined, task, tasks, request_id: typeof record.request_id === "string" ? record.request_id : clientRequestId };
}

export interface VoiceTranscription {
  text: string;
  model?: string;
  usage?: { seconds?: number; cost?: number };
}

export async function transcribeVoice(file: Blob, language?: string): Promise<VoiceTranscription> {
  const form = new FormData();
  const extension = file.type.includes("mp4") ? "mp4" : file.type.includes("ogg") ? "ogg" : file.type.includes("wav") ? "wav" : "webm";
  form.append("file", file, file instanceof File && file.name ? file.name : `hermes-dictation.${extension}`);
  if (language) form.append("language", language);
  const raw = await request<unknown>("/voice/transcribe", { method: "POST", body: form });
  const value = unwrap<unknown>(raw);
  const record = isRecord(value) ? value : {};
  const usage = isRecord(record.usage) ? record.usage : {};
  return {
    text: typeof record.text === "string" ? record.text : "",
    model: typeof record.model === "string" ? record.model : undefined,
    usage: Object.keys(usage).length ? { seconds: numberValue(usage.seconds) ?? undefined, cost: numberValue(usage.cost) ?? undefined } : undefined,
  };
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function percentValue(value: unknown): number | null {
  const numeric = numberValue(value);
  return numeric === null ? null : Math.max(0, Math.min(100, numeric));
}

function dateValue(value: unknown): string | null {
  if (typeof value === "string") return value;
  const numeric = numberValue(value);
  if (numeric === null) return null;
  const date = new Date(numeric < 1_000_000_000_000 ? numeric * 1000 : numeric);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** Normalize the several rate-limit shapes returned by the runtime provider. */
export function normalizeRuntimeUsage(value: unknown): RuntimeUsage {
  const rawValue = unwrap<unknown>(value, "usage");
  const raw = isRecord(rawValue) ? rawValue : {};
  const windows: RuntimeUsageWindow[] = [];
  const visited = new Set<object>();
  const byLimitId = raw.rateLimitsByLimitId ?? raw.rate_limits_by_limit_id;
  const legacyLimits = raw.rateLimits ?? raw.rate_limits;
  const windowSource = isRecord(byLimitId) ? byLimitId : isRecord(legacyLimits) ? legacyLimits : raw;
  const walk = (candidate: unknown, path: string[], depth: number) => {
    if (!isRecord(candidate) || depth > 5 || visited.has(candidate)) return;
    visited.add(candidate);
    const usedPercent = percentValue(candidate.usedPercent ?? candidate.used_percent);
    const remainingPercent = percentValue(candidate.remainingPercent ?? candidate.remaining_percent);
    const resetAt = dateValue(candidate.resetsAt ?? candidate.resetAt ?? candidate.reset_at);
    const duration = numberValue(candidate.windowDurationMins ?? candidate.window_duration_mins);
    if (usedPercent !== null || remainingPercent !== null || resetAt !== null || duration !== null) {
      windows.push({
        id: path.join("."),
        used_percent: usedPercent,
        remaining_percent: remainingPercent ?? (usedPercent === null ? null : Math.max(0, 100 - usedPercent)),
        window_duration_mins: duration,
        reset_at: resetAt,
      });
    }
    Object.entries(candidate).forEach(([key, child]) => walk(child, [...path, key], depth + 1));
  };
  walk(windowSource, [], 0);

  const directUsed = numberValue(raw.used);
  const directLimit = numberValue(raw.limit);
  const directRemaining = numberValue(raw.remaining);
  const primary = windows[0];
  return {
    ...raw,
    used: directUsed ?? primary?.used_percent ?? null,
    limit: directLimit,
    remaining: directRemaining ?? primary?.remaining_percent ?? null,
    reset_at: dateValue(raw.reset_at ?? raw.resetAt ?? raw.resetsAt) ?? primary?.reset_at ?? null,
    windows,
  };
}

export async function compactConversation(id: string): Promise<void> {
  await request<void>(`/conversations/${encode(id)}/compact`, { method: "POST" });
}

export async function getOnboarding(): Promise<OnboardingState> {
  return unwrap<OnboardingState>(await request("/onboarding"));
}

export async function completeOnboarding(): Promise<void> {
  await request<void>("/onboarding/complete", { method: "POST" });
}

export async function getDesktopStatus(agentId: string): Promise<DesktopStatus> {
  return unwrap<DesktopStatus>(await request(`/agents/${encode(agentId)}/desktop`), "desktop");
}

export async function createDesktop(agentId: string): Promise<DesktopStatus> {
  return unwrap<DesktopStatus>(await request(`/agents/${encode(agentId)}/desktop`, { method: "POST" }), "desktop");
}

export async function startDesktop(agentId: string): Promise<DesktopStatus> {
  return unwrap<DesktopStatus>(await request(`/agents/${encode(agentId)}/desktop`, { method: "POST" }), "desktop");
}

export async function stopDesktop(agentId: string): Promise<DesktopStatus> {
  const value = await request<unknown>(`/agents/${encode(agentId)}/desktop`, { method: "DELETE" });
  return unwrap<DesktopStatus>(value, "desktop");
}

/*
 * Canonical inbox and group APIs. These helpers intentionally live beside the
 * legacy endpoints so the UI can migrate without dropping existing accounts.
 * Every normalizer accepts both the audited response shape and the older
 * `{data: ...}`/singular wrappers used by early Bot Mode servers.
 */
function normalizeInboxMember(value: unknown): InboxMember {
  const raw = isRecord(value) ? value : {};
  return {
    agent_id: String(raw.agent_id ?? raw.id ?? ""),
    name: typeof raw.name === "string" ? raw.name : "Bot",
    role: typeof raw.role === "string" ? raw.role : undefined,
    avatar: typeof raw.avatar === "string" ? raw.avatar : typeof raw.avatar_shape === "string" ? raw.avatar_shape : null,
    avatar_url: typeof raw.avatar_url === "string" ? raw.avatar_url : null,
    color: typeof raw.color === "string" ? raw.color : null,
  };
}

function normalizeInboxTask(value: unknown): InboxTask {
  const raw = isRecord(value) ? value : {};
  const error = isRecord(raw.error) ? raw.error : null;
  return {
    id: String(raw.id ?? raw.task_id ?? ""),
    agent_id: raw.agent_id === null || raw.agent_id === undefined ? null : String(raw.agent_id),
    conversation_id: raw.conversation_id === null || raw.conversation_id === undefined ? null : String(raw.conversation_id),
    origin_conversation_id: raw.origin_conversation_id === null || raw.origin_conversation_id === undefined ? null : String(raw.origin_conversation_id),
    parent_task_id: raw.parent_task_id === null || raw.parent_task_id === undefined ? null : String(raw.parent_task_id),
    request_id: raw.request_id === null || raw.request_id === undefined ? null : String(raw.request_id),
    status: typeof raw.status === "string" ? raw.status : undefined,
    phase: typeof raw.phase === "string" ? raw.phase : null,
    error_message: typeof raw.error_message === "string" ? raw.error_message : error && typeof error.message === "string" ? error.message : null,
  };
}

function normalizeInboxEntry(value: unknown): InboxEntry {
  const raw = isRecord(value) ? value : {};
  const members = Array.isArray(raw.members) ? raw.members.map(normalizeInboxMember).filter((member) => member.agent_id) : [];
  const activeTasks = Array.isArray(raw.active_tasks) ? raw.active_tasks.map(normalizeInboxTask).filter((task) => task.id) : [];
  return {
    conversation_id: String(raw.conversation_id ?? raw.id ?? ""),
    kind: typeof raw.kind === "string" ? raw.kind : "direct",
    agent_id: raw.agent_id === null || raw.agent_id === undefined ? null : String(raw.agent_id),
    name: typeof raw.name === "string" ? raw.name : members[0]?.name ?? "Conversation",
    members,
    preview: typeof raw.preview === "string" ? raw.preview : typeof raw.title === "string" ? raw.title : null,
    updated_at: typeof raw.updated_at === "string" || typeof raw.updated_at === "number" ? String(raw.updated_at) : null,
    unread_count: typeof raw.unread_count === "number" ? raw.unread_count : Number(raw.unread_count ?? 0) || 0,
    pinned: Boolean(raw.pinned),
    archived: Boolean(raw.archived),
    active_tasks: activeTasks,
    coordinator_id: raw.coordinator_id === null || raw.coordinator_id === undefined ? null : String(raw.coordinator_id),
  };
}

function normalizeMessage(value: unknown): Message {
  const raw = isRecord(value) ? value : {};
  const metadata = isRecord(raw.metadata) ? raw.metadata as Record<string, unknown> : undefined;
  return {
    id: String(raw.id ?? `message-${Date.now()}`),
    conversation_id: String(raw.conversation_id ?? raw.origin_conversation_id ?? ""),
    role: typeof raw.role === "string" ? raw.role as Message["role"] : "assistant",
    content: typeof raw.content === "string" ? raw.content : typeof raw.text === "string" ? raw.text : "",
    created_at: typeof raw.created_at === "string" || typeof raw.created_at === "number" ? String(raw.created_at) : undefined,
    status: typeof raw.status === "string" ? raw.status : undefined,
    metadata,
    author_agent_id: raw.author_agent_id === null || raw.author_agent_id === undefined ? null : String(raw.author_agent_id),
    source_task_id: raw.source_task_id === null || raw.source_task_id === undefined ? null : String(raw.source_task_id),
    request_id: raw.request_id === null || raw.request_id === undefined ? null : String(raw.request_id),
    origin_conversation_id: raw.origin_conversation_id === null || raw.origin_conversation_id === undefined ? null : String(raw.origin_conversation_id),
    reply_to_id: raw.reply_to_id === null || raw.reply_to_id === undefined ? null : String(raw.reply_to_id),
  };
}

function normalizeTaskEnvelope(value: unknown, fallbackConversationId: string): TaskEnvelope {
  const raw = isRecord(value) ? value : {};
  const nestedAgent = isRecord(raw.agent) && (raw.agent.id !== undefined || raw.agent.agent_id !== undefined) ? raw.agent : null;
  const error = isRecord(raw.error) ? raw.error : null;
  return {
    id: String(raw.id ?? raw.task_id ?? ""),
    agent_id: raw.agent_id === null || raw.agent_id === undefined ? nestedAgent ? String(nestedAgent.id ?? nestedAgent.agent_id) : null : String(raw.agent_id),
    conversation_id: String(raw.conversation_id ?? fallbackConversationId),
    origin_conversation_id: raw.origin_conversation_id === null || raw.origin_conversation_id === undefined ? null : String(raw.origin_conversation_id),
    parent_task_id: raw.parent_task_id === null || raw.parent_task_id === undefined ? null : String(raw.parent_task_id),
    request_id: raw.request_id === null || raw.request_id === undefined ? null : String(raw.request_id),
    status: typeof raw.status === "string" ? raw.status : undefined,
    phase: typeof raw.phase === "string" ? raw.phase : null,
    error_message: typeof raw.error_message === "string" ? raw.error_message : error && typeof error.message === "string" ? error.message : null,
  };
}

export interface SendConversationMessageInput {
  content: string;
  file_ids?: string[];
  mention_agent_ids?: string[];
  reply_to_id?: string;
  client_request_id: string;
}

export interface SendConversationMessageResult {
  conversation?: Conversation;
  message?: Message;
  task?: TaskEnvelope;
  tasks: TaskEnvelope[];
  request_id: string;
}

export async function bootstrapChief(): Promise<Agent | null> {
  const raw = await request<unknown>("/bootstrap", { method: "POST", body: JSON.stringify({}) });
  const value = unwrap<unknown>(raw);
  const record = isRecord(value) ? value : {};
  const candidate = record.chief ?? record.agent ?? value;
  return isRecord(candidate) && (candidate.id !== undefined || candidate.agent_id !== undefined)
    ? normalizeAgent(candidate as Agent)
    : null;
}

export async function getInbox(includeArchived = false): Promise<InboxEntry[]> {
  const raw = await request<unknown>(`/inbox${includeArchived ? "?include_archived=true" : ""}`);
  return listFrom<unknown>(raw, "items").map(normalizeInboxEntry).filter((item) => item.conversation_id);
}

export async function getAgentHome(agentId: string): Promise<Conversation | null> {
  const raw = await request<unknown>(`/agents/${encode(agentId)}/home`);
  const value = unwrap<unknown>(raw, "conversation");
  return isRecord(value) ? {
    ...(value as Conversation),
    id: String(value.id ?? value.conversation_id ?? ""),
    agent_id: String(value.agent_id ?? agentId),
    kind: typeof value.kind === "string" ? value.kind : "direct",
  } : null;
}

export async function createGroup(name: string, agentIds: string[], coordinatorId?: string): Promise<Conversation> {
  const raw = await request<unknown>("/groups", {
    method: "POST",
    body: JSON.stringify({ name, agent_ids: agentIds, ...(coordinatorId ? { coordinator_id: coordinatorId } : {}) }),
  });
  const value = unwrap<unknown>(raw, "conversation");
  if (!isRecord(value)) throw new ApiError("The server did not return the new group.", 502, "group_missing");
  return { ...(value as Conversation), id: String(value.id ?? value.conversation_id ?? ""), agent_id: String(value.agent_id ?? coordinatorId ?? agentIds[0] ?? ""), kind: "group" };
}

export async function updateGroup(groupId: string, input: { name?: string; agent_ids?: string[]; coordinator_id?: string; archived?: boolean; pinned?: boolean }): Promise<Conversation | null> {
  const raw = await request<unknown>(`/groups/${encode(groupId)}`, { method: "PATCH", body: JSON.stringify(input) });
  const value = unwrap<unknown>(raw, "conversation");
  return isRecord(value) ? value as Conversation : null;
}

export async function updateConversationState(id: string, change: { archived?: boolean; pinned?: boolean }): Promise<void> {
  if (change.archived !== undefined) await request(`/conversations/${encode(id)}/${change.archived ? "archive" : "restore"}`, { method: "POST" });
  if (change.pinned !== undefined) await request(`/conversations/${encode(id)}/pin?pinned=${change.pinned}`, { method: "POST" });
}

export async function markConversationRead(conversationId: string, throughMessageId: string): Promise<void> {
  await request<void>(`/conversations/${encode(conversationId)}/read`, { method: "POST", body: JSON.stringify({ through_message_id: throughMessageId }) });
}

export async function sendConversationMessage(conversationId: string, input: SendConversationMessageInput): Promise<SendConversationMessageResult> {
  const raw = await request<unknown>(`/conversations/${encode(conversationId)}/messages`, { method: "POST", body: JSON.stringify({
    content: input.content,
    file_ids: input.file_ids ?? [],
    ...(input.mention_agent_ids?.length ? { mention_agent_ids: input.mention_agent_ids } : {}),
    ...(input.reply_to_id ? { reply_to_id: input.reply_to_id } : {}),
    client_request_id: input.client_request_id,
  }) });
  const value = unwrap<unknown>(raw);
  const record = isRecord(value) ? value : {};
  const taskValue = record.task;
  const task = isRecord(taskValue) ? normalizeTaskEnvelope(taskValue, conversationId) : undefined;
  const tasks = Array.isArray(record.tasks) ? record.tasks.map((item) => normalizeTaskEnvelope(item, conversationId)).filter((item) => item.id) : [];
  if (task?.id && !tasks.some((item) => item.id === task.id)) tasks.unshift(task);
  const requestId = typeof record.request_id === "string" ? record.request_id : input.client_request_id;
  return { message: record.message ? normalizeMessage(record.message) : undefined, task, tasks, request_id: requestId };
}

export async function cancelConversationRequest(conversationId: string, requestId: string): Promise<TaskEnvelope[]> {
  const raw = await request<unknown>(`/conversations/${encode(conversationId)}/requests/${encode(requestId)}/cancel`, { method: "POST" });
  const value = unwrap<unknown>(raw);
  const record = isRecord(value) ? value : {};
  return (Array.isArray(record.tasks) ? record.tasks : []).map((item) => normalizeTaskEnvelope(item, conversationId)).filter((item) => item.id);
}

export interface SearchMatch {
  id: string;
  conversation_id?: string | null;
  message_id?: string | null;
  kind?: string;
  snippet?: string;
  name?: string;
  created_at?: string | null;
}

export async function searchWorkspace(query: string): Promise<SearchMatch[]> {
  const raw = await request<unknown>(`/search?q=${encode(query.trim())}`);
  const value = unwrap<unknown>(raw, "matches");
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((item) => ({
    id: String(item.id ?? item.message_id ?? `match-${Date.now()}`),
    conversation_id: item.conversation_id === null || item.conversation_id === undefined ? null : String(item.conversation_id),
    message_id: item.message_id === null || item.message_id === undefined ? null : String(item.message_id),
    kind: typeof item.kind === "string" ? item.kind : undefined,
    snippet: typeof item.snippet === "string" ? item.snippet : typeof item.content === "string" ? item.content : undefined,
    name: typeof item.name === "string" ? item.name : undefined,
    created_at: typeof item.created_at === "string" ? item.created_at : null,
  }));
}

export async function getExactMessage(messageId: string): Promise<Message> {
  const raw = await request<unknown>(`/messages/${encode(messageId)}`);
  return normalizeMessage(unwrap<unknown>(raw, "message"));
}

export async function listRoutines(agentId: string): Promise<Routine[]> {
  return listFrom<Routine>(await request(`/agents/${encode(agentId)}/routines`), "routines").map((value) => ({
    ...value,
    id: String(value.id),
    name: value.name ?? "Routine",
    instruction: value.instruction ?? "",
    time: value.time ?? "09:00",
    timezone: value.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
    weekdays: Array.isArray(value.weekdays) ? value.weekdays.map(Number).filter(Number.isFinite) : [0, 1, 2, 3, 4],
    enabled: value.enabled !== false,
  }));
}

export async function createRoutine(agentId: string, input: Omit<Routine, "id" | "next_due" | "last_run_at">): Promise<Routine> {
  const raw = await request<unknown>(`/agents/${encode(agentId)}/routines`, { method: "POST", body: JSON.stringify(input) });
  return unwrap<Routine>(raw, "routine");
}

export async function updateRoutine(routineId: string, input: Partial<Omit<Routine, "id">>): Promise<Routine> {
  const raw = await request<unknown>(`/routines/${encode(routineId)}`, { method: "PATCH", body: JSON.stringify(input) });
  return unwrap<Routine>(raw, "routine");
}

export async function runRoutine(routineId: string, clientRequestId: string): Promise<SendConversationMessageResult> {
  const raw = await request<unknown>(`/routines/${encode(routineId)}/run`, { method: "POST", body: JSON.stringify({ client_request_id: clientRequestId }) });
  const value = unwrap<unknown>(raw);
  const record = isRecord(value) ? value : {};
  const task = isRecord(record.task) ? normalizeTaskEnvelope(record.task, String(record.conversation_id ?? "")) : undefined;
  return { task, tasks: task ? [task] : [], request_id: typeof record.request_id === "string" ? record.request_id : clientRequestId };
}

export async function deleteRoutine(routineId: string): Promise<void> {
  await request<void>(`/routines/${encode(routineId)}`, { method: "DELETE" });
}

export async function setDesktopControl(agentId: string, mode: "manual" | "bot"): Promise<DesktopStatus> {
  return unwrap<DesktopStatus>(await request(`/agents/${encode(agentId)}/desktop/control`, { method: "POST", body: JSON.stringify({ mode }) }), "desktop");
}

export async function sendDesktopHeartbeat(agentId: string, generation: number | string | null | undefined, visible = true): Promise<DesktopStatus> {
  return unwrap<DesktopStatus>(await request(`/agents/${encode(agentId)}/desktop/heartbeat`, { method: "POST", body: JSON.stringify({ generation, visible }) }), "desktop");
}

export async function listApprovals(taskId: string): Promise<Approval[]> {
  return listFrom<Approval>(await request(`/tasks/${encode(taskId)}/approvals`), "approvals");
}

export async function cancelTask(taskId: string): Promise<void> {
  await request<void>(`/tasks/${encode(taskId)}/cancel`, { method: "POST" });
}

export async function respondToApproval(taskId: string, approvalId: string, decision: "accept" | "decline" | "cancel"): Promise<void> {
  await request<void>(`/tasks/${encode(taskId)}/approvals/${encode(approvalId)}`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}

export async function streamMessage(
  conversationId: string,
  input: { content: string; agent_id?: string; file_ids?: string[] },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
  onTaskId?: (taskId: string) => void,
): Promise<string> {
  const submitResponse = await fetch(`${API_BASE}/conversations/${encode(conversationId)}/messages`, {
    method: "POST",
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      content: input.content,
      ...(input.agent_id ? { agent_id: input.agent_id } : {}),
      ...(input.file_ids?.length ? { file_ids: input.file_ids } : {}),
    }),
    signal,
  });

  if (!submitResponse.ok) {
    const text = await submitResponse.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) as unknown : null;
    } catch {
      body = text;
    }
    const message = isRecord(body) && typeof body.error?.message === "string" ? body.error.message : isRecord(body) && typeof body.detail === "string" ? body.detail : `Message failed (${submitResponse.status})`;
    const code = isRecord(body) && isRecord(body.error) && typeof body.error.code === "string" ? body.error.code : isRecord(body) && typeof body.code === "string" ? body.code : undefined;
    throw new ApiError(message, submitResponse.status, code);
  }

  const submitted = await submitResponse.json() as unknown;
  const submittedData = unwrap<Record<string, unknown>>(submitted);
  const task = submittedData.task;
  const taskId = isRecord(task) && typeof task.id === "string" ? task.id : undefined;
  if (!taskId) throw new ApiError("The server did not return a task to follow", 502, "task_missing");
  onTaskId?.(taskId);

  await watchTask(taskId, onEvent, signal);
  return taskId;
}

