import {
  Activity,
  Archive,
  ArrowLeft,
  ArrowUp,
  Bot,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Copy,
  CornerUpLeft,
  Download,
  FileText,
  FolderOpen,
  Laptop,
  Loader2,
  MoreHorizontal,
  Moon,
  PanelRight,
  Pin,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  UserRound,
  Users,
  WifiOff,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, KeyboardEvent } from "react";
import BotCreator from "./BotCreator";
import { AgentAvatar, BotGlyph } from "./BotIdentity";
import type { AvatarStatus } from "./BotIdentity";
import { ImageGenerationCard, type ImageGenerationState } from "./ImageGeneration";
import { MessageContent } from "./MessageContent";
import { AccountPanel, BotSettingsEditor, MotionSettings, RuntimeConnectionCard, RuntimeUsageCard } from "./GrokBotSettings";
import { conversationTasks, watchTask } from "../lib/taskStream";
import {
  ApiError,
  bootstrapChief,
  cancelConversationRequest,
  cancelTask,
  continueRequest,
  createAgent,
  createConversation,
  createDesktop,
  createGroup,
  createMemory,
  createRoutine,
  decideRequest,
  deleteFile,
  deleteMemory,
  deleteRoutine,
  getAgentHome,
  getDesktopStatus,
  getExtensionsStatus,
  getExactMessage,
  getInbox,
  getRuntimeAccount,
  getRuntimeStatus,
  getRuntimeUsage,
  listActivity,
  listAgents,
  listConversationRequests,
  listConversations,
  listFiles,
  listMessages,
  listMemory,
  listRoutines,
  listSkills,
  listPrivateFields,
  listTeachings,
  markConversationRead,
  respondToApproval,
  runRoutine,
  runTeaching,
  sendConversationMessage,
  sendDesktopHeartbeat,
  searchWorkspace,
  setDesktopControl,
  setSkillEnabled,
  startDesktop,
  stopDesktop,
  updateGroup,
  updateConversationState,
  updateRoutine,
  uploadFile,
} from "../lib/api";
import type {
  ActivityItem,
  Agent,
  AgentInput,
  Approval,
  ChatRequest,
  Conversation,
  DesktopStatus,
  FileAsset,
  InboxEntry,
  InboxMember,
  InboxTask,
  LearnedSkill,
  MemoryItem,
  Message,
  ExtensionsStatus,
  PrivateField,
  Routine,
  RuntimeAccount,
  RuntimeStatus,
  RuntimeUsage,
  Session,
  StreamEvent,
  TaskEnvelope,
  Teaching,
  Theme,
} from "../lib/types";
import "./grok-workspace.css";
import {
  ActionMenu,
  ExpansionAction,
  actionItems,
  ConnectionSheet,
  ExpansionStatusCard,
  PrivateFieldsPanel,
  PrivateInputSheet,
  RequestCard,
  TeachingManager,
  TeachingRunDialog,
  TeachingSheet,
  VoiceDictation,
} from "./ExpansionFeatures";
import { Disclosure } from "./Disclosure";

type ResourceMode = "chat" | "memory" | "files" | "activity" | "settings";

type TaskState = TaskEnvelope & {
  text: string;
  progress: string;
  approval?: Approval;
  image?: ImageGenerationState;
  controller: AbortController;
  terminal?: boolean;
  stopRequested?: boolean;
};

type DraftAttempt = {
  conversationId: string;
  agentId: string;
  content: string;
  fileIds: string[];
  fileAssets: FileAsset[];
  mentionAgentIds: string[];
  replyToId?: string;
  clientRequestId: string;
};

interface GrokWorkspaceProps {
  session: Session;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  onLogout: () => Promise<void>;
  logoutError: string | null;
}

const ACTIVE_STATUSES = new Set(["queued", "running", "waiting", "starting", "reconnecting"]);
const TERMINAL_EVENTS = new Set(["task.completed", "task.error", "task.failed", "task.cancelled"]);
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function makeLocalId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return `${prefix}-${crypto.randomUUID()}`;
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function asDate(value?: string | number | null): Date {
  if (value === undefined || value === null || value === "") return new Date(Number.NaN);
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isFinite(numeric)) return new Date(numeric < 1_000_000_000_000 ? numeric * 1000 : numeric);
  return new Date(value);
}

function mergeMessages(older: Message[], newer: Message[]): Message[] {
  return [...new Map([...older, ...newer].map(message => [message.id, message])).values()]
    .sort((a, b) => (asDate(a.created_at).getTime() || 0) - (asDate(b.created_at).getTime() || 0));
}

function formatTime(value?: string | number | null): string {
  const date = asDate(value);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
}

function formatDate(value?: string | number | null): string {
  const date = asDate(value);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function formatBytes(size?: number | null): string {
  if (size === undefined || size === null) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong. Try again.";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function eventRecord(event: StreamEvent): Record<string, unknown> {
  return isRecord(event.data) ? event.data : {};
}

function eventText(event: StreamEvent): string | null {
  if (typeof event.data === "string") return event.data === "[DONE]" ? null : event.data;
  const data = eventRecord(event);
  for (const key of ["text", "delta", "content", "output_text"]) {
    if (typeof data[key] === "string") return data[key] as string;
  }
  return null;
}

function eventToolName(event: StreamEvent): string {
  const data = eventRecord(event);
  const nested = isRecord(data.tool) ? data.tool : {};
  for (const value of [data.tool, data.name, data.kind, nested.name, nested.type]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return event.type;
}

function humanToolName(value: string): string {
  const name = value.replace(/[._-]+/g, " ").trim().toLowerCase();
  const labels: Record<string, string> = {
    history_search: "Searching chat history",
    history_read: "Reading an earlier message",
    files_read: "Reading a file",
    files_list: "Checking your files",
    delegate_task: "Asking another Bot to help",
    memory_search: "Checking memory",
    desktop_screenshot: "Looking at the computer",
  };
  return labels[name] ?? name.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function isImageEvent(event: StreamEvent): boolean {
  return /image[_. -]?generat|generate[_. -]?image/i.test(event.type) || /image[_. -]?generat|generate[_. -]?image/i.test(eventToolName(event));
}

function imageSource(value: unknown, depth = 0): string | null {
  if (depth > 5) return null;
  if (typeof value === "string" && /^\/bot\/api\/files\/[A-Za-z0-9_-]+\/download(?:\?.*)?$/i.test(value.trim())) return value.trim();
  if (Array.isArray(value)) {
    for (const item of value) {
      const result = imageSource(item, depth + 1);
      if (result) return result;
    }
    return null;
  }
  if (!isRecord(value)) return null;
  for (const key of ["image_url", "imageUrl", "download_url", "downloadUrl", "url", "src", "uri", "output", "image", "images", "result", "data"]) {
    const result = imageSource(value[key], depth + 1);
    if (result) return result;
  }
  return null;
}

function normalizeLegacyInbox(agents: Agent[], conversations: Conversation[]): InboxEntry[] {
  return agents.map((agent) => {
    const conversation = conversations.filter((item) => item.agent_id === agent.id).sort((a, b) => asDate(b.updated_at).getTime() - asDate(a.updated_at).getTime())[0];
    return {
      conversation_id: conversation?.id ?? "",
      kind: "direct",
      agent_id: agent.id,
      name: agent.name,
      members: [{ agent_id: agent.id, name: agent.name, avatar: agent.avatar, avatar_url: agent.avatar_url, color: agent.color, role: "coordinator" }],
      preview: conversation?.title ?? agent.description ?? "Start a conversation",
      updated_at: conversation?.updated_at ?? agent.updated_at ?? null,
      unread_count: 0,
      pinned: false,
      archived: false,
      active_tasks: [],
      coordinator_id: agent.id,
    };
  });
}

function memberAgent(member: InboxMember): Agent {
  return { id: member.agent_id, name: member.name, avatar: member.avatar, avatar_url: member.avatar_url, color: member.color, description: "" };
}

function entryAgent(entry: InboxEntry, agents: Agent[]): Agent | null {
  const id = entry.agent_id ?? entry.coordinator_id ?? entry.members[0]?.agent_id;
  if (!id) return null;
  return agents.find((agent) => agent.id === id) ?? entry.members.map(memberAgent).find((agent) => agent.id === id) ?? null;
}

function entryMembers(entry: InboxEntry, agents: Agent[]): InboxMember[] {
  if (entry.members.length) return entry.members;
  const agent = entryAgent(entry, agents);
  return agent ? [{ agent_id: agent.id, name: agent.name, avatar: agent.avatar, avatar_url: agent.avatar_url, color: agent.color }] : [];
}

function directEntry(agent: Agent, conversation?: Conversation | null): InboxEntry {
  return {
    conversation_id: conversation?.id ?? "",
    kind: "direct",
    agent_id: agent.id,
    coordinator_id: agent.id,
    name: agent.name,
    members: [{ agent_id: agent.id, name: agent.name, avatar: agent.avatar, avatar_url: agent.avatar_url, color: agent.color, role: "coordinator" }],
    preview: conversation?.title ?? agent.description ?? "Start a conversation",
    updated_at: conversation?.updated_at ?? agent.updated_at ?? null,
    unread_count: 0,
    pinned: false,
    archived: false,
    active_tasks: [],
  };
}

function inboxKey(entry: InboxEntry): string {
  return entry.conversation_id || `agent:${entry.agent_id ?? entry.name}`;
}

function GroupAvatar({ entry, agents, size = "medium" }: { entry: InboxEntry; agents: Agent[]; size?: "small" | "medium" | "large" }): JSX.Element {
  const members = entryMembers(entry, agents).slice(0, 3);
  return <span className={`grok-group-avatar grok-group-avatar-${size}`} aria-label={`${entry.name}, ${members.length} members`}>
    {members.map((member, index) => <span key={member.agent_id} style={{ zIndex: 4 - index }}><AgentAvatar agent={memberAgent(member)} size="small" /></span>)}
    {!members.length ? <Users size={size === "large" ? 28 : 18} /> : null}
  </span>;
}

function Identity({ entry, agents, size = "medium", status }: { entry: InboxEntry; agents: Agent[]; size?: "small" | "medium" | "large"; status?: AvatarStatus }): JSX.Element {
  if (entry.kind === "group") return <GroupAvatar entry={entry} agents={agents} size={size} />;
  return <AgentAvatar agent={entryAgent(entry, agents)} size={size} status={status} />;
}

function taskStatusLabel(task: TaskState): string {
  if (task.status === "cancelled") return "Run stopped";
  if (task.status === "completed") return "Finished";
  if (task.status === "failed") return "Run failed";
  if (task.stopRequested) return "Stopping";
  if (task.status === "queued") return "Getting started";
  if (task.status === "reconnecting") return "Reconnecting";
  if (task.approval) return "Waiting for your approval";
  if (task.progress) return task.progress;
  if (task.status === "failed") return "Run failed";
  if (task.status === "cancelled") return "Run stopped";
  return "Working";
}

function taskAvatarStatus(task: TaskState): AvatarStatus {
  if (task.status === "failed") return "error";
  if (task.status === "cancelled") return "error";
  if (task.approval) return "waiting";
  if (/image|tool|computer|using/i.test(task.progress)) return "tool";
  if (/typing|writing/i.test(task.progress)) return "typing";
  return ACTIVE_STATUSES.has(task.status ?? "") ? "working" : "idle";
}

function MessageAuthor({ message, task, agents, entry }: { message: Message; task?: TaskState; agents: Agent[]; entry: InboxEntry }): JSX.Element {
  const id = task?.agent_id ?? message.author_agent_id ?? (isRecord(message.metadata) && typeof message.metadata.author_agent_id === "string" ? message.metadata.author_agent_id : null);
  const author = id ? agents.find((agent) => agent.id === id) ?? entry.members.map(memberAgent).find((agent) => agent.id === id) : null;
  return author ? <AgentAvatar agent={author} size="small" /> : <span className="grok-author-fallback" aria-hidden="true"><Bot size={15} /></span>;
}

function messageAttachments(message: Message): Array<{ id: string; name: string; url: string }> {
  const metadata = isRecord(message.metadata) ? message.metadata : {};
  const raw = Array.isArray(metadata.attachments) ? metadata.attachments : [];
  return raw.map((value, index) => {
    const item = isRecord(value) ? value : {};
    const id = String(item.file_id ?? item.id ?? `attachment-${index}`);
    const name = typeof item.name === "string" ? item.name : typeof item.filename === "string" ? item.filename : "Attached file";
    const directUrl = typeof item.url === "string" ? item.url : typeof item.download_url === "string" ? item.download_url : "";
    const url = directUrl || (/^[A-Za-z0-9_-]+$/.test(id) ? `/bot/api/files/${id}/download` : "");
    return { id, name, url };
  }).filter((item) => item.url);
}

function ApprovalBox({ task, onApprove, onDeny }: { task: TaskState; onApprove: (task: TaskState) => void; onDeny: (task: TaskState) => void }): JSX.Element | null {
  if (!task.approval) return null;
  return <div className="grok-approval" role="alert">
    <div className="grok-approval-icon"><ShieldCheck size={18} /></div>
    <div className="grok-approval-copy"><strong>Before I do that</strong><p>{task.approval.description}</p><small>{task.approval.kind}</small></div>
    <div className="grok-approval-actions"><button className="grok-button grok-button-quiet" type="button" onClick={() => onDeny(task)}>Decline</button><button className="grok-button grok-button-dark" type="button" onClick={() => onApprove(task)}><Check size={14} /> Allow</button></div>
  </div>;
}

function Bubble({ message, entry, agents, task, accountId, onCopy, onReply }: { message: Message; entry: InboxEntry; agents: Agent[]; task?: TaskState; accountId?: string; onCopy?: (message: Message) => Promise<void>; onReply?: (message: Message) => void }): JSX.Element {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  useEffect(() => { if (!copied) return; const timer = window.setTimeout(() => setCopied(false), 2000); return () => window.clearTimeout(timer); }, [copied]);
  const isUser = message.role === "user";
  if (message.role === "system" && isRecord(message.metadata) && message.metadata.collaboration_handoff === true) {
    return <div data-message-id={message.id} className="grok-handoff-event" role="status"><Users size={15} /><span>{message.content}</span></div>;
  }
  const authorName = task?.agent_id ? agents.find((agent) => agent.id === task.agent_id)?.name : message.author_agent_id ? agents.find((agent) => agent.id === message.author_agent_id)?.name : entry.name;
  const attachments = messageAttachments(message);
  const isLiveAssistant = message.role === "assistant" && (message.status === "streaming" || message.status === "pending");
  const longMessage = (message.role === "user" || message.role === "assistant") && message.content.length > 1200 && !isLiveAssistant;
  return <article data-message-id={message.id} className={`grok-message ${isUser ? "is-user" : "is-assistant"}`}>
    {!isUser ? <div className="grok-message-author"><MessageAuthor message={message} task={task} agents={agents} entry={entry} /><span>{authorName ?? "Assistant"}</span></div> : null}
    <div className="grok-message-line"><div className="grok-message-bubble">{longMessage ? <Disclosure accountId={accountId} section="message" id={message.id} label="message"><MessageContent content={message.content} /></Disclosure> : <MessageContent content={message.content} />}{attachments.length ? <div className="grok-message-attachments" aria-label="Attached files">{attachments.map((file) => <a key={file.id} href={file.url} download><FileText size={14} /><span>{file.name}</span><Download size={13} /></a>)}</div> : null}</div>{!isUser && onReply ? <button className="grok-message-action" type="button" aria-label="Reply to message" title="Reply to message" onClick={() => onReply(message)}><CornerUpLeft size={14} /></button> : null}{!isUser && onCopy ? <button className="grok-message-action" type="button" aria-label={copied ? "Copied" : copyError ? "Copy failed; try again" : "Copy message"} title={copied ? "Copied" : copyError ? "Copy failed; select the text to copy" : "Copy message"} onClick={() => { setCopyError(false); void onCopy(message).then(() => setCopied(true)).catch(() => setCopyError(true)); }}>{copied ? <Check size={14} /> : <Copy size={14} />}</button> : null}</div>
    <time className="grok-message-time">{formatTime(message.created_at)}</time>
  </article>;
}

function GroupCreatorDialog({ agents, onClose, onCreate }: { agents: Agent[]; onClose: () => void; onCreate: (name: string, ids: string[], coordinatorId: string) => Promise<void> }): JSX.Element {
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string[]>(agents.slice(0, 2).map((agent) => agent.id));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const coordinator = selected[0] ?? agents[0]?.id ?? "";
  const toggle = (id: string) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : current.length >= 6 ? current : [...current, id]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || selected.length < 2 || busy) { setError("Choose a name and at least two Bots."); return; }
    setBusy(true); setError(null);
    try { await onCreate(name.trim(), selected, coordinator); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  };
  return <div className="grok-modal-layer" role="dialog" aria-modal="true" aria-labelledby="group-create-title" onKeyDown={(event) => {
    if (event.key === "Escape") { event.preventDefault(); onClose(); }
    if (event.key === "Tab") {
      const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled)')];
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }}>
    <button className="grok-modal-scrim" type="button" aria-label="Close" onClick={onClose} />
    <form className="grok-modal" onSubmit={(event) => void submit(event)}>
      <header className="grok-modal-head"><div><h2 id="group-create-title">New group chat</h2><p>Choose the Bots who should work together.</p></div><button className="grok-icon-button" type="button" aria-label="Close group creator" onClick={onClose}><X size={18} /></button></header>
      <label className="grok-field-label" htmlFor="group-name">Group name</label><input id="group-name" className="grok-field" value={name} onChange={(event) => setName(event.target.value)} placeholder="Weekend plans" autoFocus />
      <fieldset className="grok-member-picker"><legend>Bots</legend>{agents.map((agent) => <label className={`grok-member-option ${selected.includes(agent.id) ? "is-selected" : ""}`} key={agent.id}><input type="checkbox" checked={selected.includes(agent.id)} onChange={() => toggle(agent.id)} /><AgentAvatar agent={agent} size="small" /><span><strong>{agent.name}</strong><small>{agent.description || "Ready to help"}</small></span><span className="grok-check"><Check size={14} /></span></label>)}</fieldset>
      {error ? <p className="grok-form-error" role="alert">{error}</p> : null}<footer className="grok-modal-actions"><button className="grok-button grok-button-quiet" type="button" onClick={onClose}>Cancel</button><button className="grok-button grok-button-dark" type="submit" disabled={busy}>{busy ? <Loader2 size={15} className="grok-spin" /> : <Plus size={15} />} Create group</button></footer>
    </form>
  </div>;
}

function MentionMenu({ entry, agents, selected, onSelect }: { entry: InboxEntry; agents: Agent[]; selected: string[]; onSelect: (id: string, name: string) => void }): JSX.Element {
  const members = entryMembers(entry, agents);
  return <div className="grok-mention-menu" role="listbox" aria-label="Mention a Bot" onKeyDown={(event) => {
    const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button")];
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); items[(current + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus(); }
  }}><button type="button" className="grok-mention-option" onClick={() => onSelect("__everyone__", "everyone")}><span className="grok-mention-everyone">@</span><span><strong>@everyone</strong><small>Ask all group members</small></span></button>{members.map((member) => <button type="button" className={`grok-mention-option ${selected.includes(member.agent_id) ? "is-selected" : ""}`} key={member.agent_id} onClick={() => onSelect(member.agent_id, member.name)}><AgentAvatar agent={memberAgent(member)} size="small" /><span><strong>@{member.name}</strong><small>{member.role === "coordinator" ? "Coordinator" : "Bot"}</small></span>{selected.includes(member.agent_id) ? <Check size={15} /> : null}</button>)}</div>;
}

function Composer({ entry, agents, draft, onDraft, onSend, onStop, isSending, isStopping, attachments, onAttach, onRemoveAttachment, uploading, mentionIds, onMentionIds, replyTo, onClearReply, error, onRetry, actions, onAction }: {
  entry: InboxEntry | null;
  agents: Agent[];
  draft: string;
  onDraft: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  isSending: boolean;
  isStopping: boolean;
  attachments: FileAsset[];
  onAttach: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemoveAttachment: (id: string) => void;
  uploading: boolean;
  mentionIds: string[];
  onMentionIds: (ids: string[]) => void;
  replyTo?: Message;
  onClearReply: () => void;
  error: string | null;
  onRetry: () => void;
  actions: ExpansionAction[];
  onAction: (action: ExpansionAction) => void;
}): JSX.Element {
  const [mentionOpen, setMentionOpen] = useState(false);
  const [actionOpen, setActionOpen] = useState(false);
  const [actionMode, setActionMode] = useState<"plus" | "slash">("plus");
  const [actionQuery, setActionQuery] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const executeAction = (action: ExpansionAction) => { if (action.id === "attach") fileRef.current?.click(); else onAction(action); };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (actionOpen && event.key === "ArrowDown") {
      event.preventDefault();
      textareaRef.current?.closest(".grok-composer-wrap")?.querySelector<HTMLButtonElement>(".hermes-action-menu button")?.focus();
      return;
    }
    if (actionOpen && event.key === "Escape") { event.preventDefault(); setActionOpen(false); setActionQuery(""); return; }
    if (actionOpen && event.key === "Enter" && !event.shiftKey && actionMode === "slash") {
      const first = actions.find((action) => !actionQuery.trim() || `${action.label} ${action.description}`.toLowerCase().includes(actionQuery.trim().toLowerCase()));
      if (first) { event.preventDefault(); onDraft(draft.replace(/(?:^|\s)\/[^\s]*$/, (match) => match.startsWith(" ") ? " " : "")); setActionOpen(false); setActionQuery(""); executeAction(first); return; }
    }
    if (mentionOpen && (event.key === "ArrowDown" || event.key === "Enter")) {
      event.preventDefault(); textareaRef.current?.closest(".grok-composer-wrap")?.querySelector<HTMLButtonElement>(".grok-mention-option")?.focus(); return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); }
    if (event.key === "Escape") setMentionOpen(false);
  };
  const pickMention = (id: string, name: string) => {
    const everyone = id === "__everyone__";
    const ids = everyone ? entryMembers(entry ?? { members: [], conversation_id: "", kind: "group", name: "", agent_id: null }, agents).map((member) => member.agent_id) : mentionIds.includes(id) ? mentionIds.filter((item) => item !== id) : [...mentionIds, id];
    onMentionIds(ids);
    if ((everyone || !mentionIds.includes(id)) && textareaRef.current) {
      const cleanDraft = draft.replace(/@[^@\n]*$/, "");
      const prefix = cleanDraft && !/\s$/.test(cleanDraft) ? `${cleanDraft} ` : cleanDraft;
      onDraft(`${prefix}@${name} `);
      requestAnimationFrame(() => textareaRef.current?.focus());
    }
    setMentionOpen(false);
  };
  const chooseAction = (action: ExpansionAction) => {
    if (actionMode === "slash") onDraft(draft.replace(/(?:^|\s)\/[^\s]*$/, (match) => match.startsWith(" ") ? " " : ""));
    setActionOpen(false); setActionQuery(""); executeAction(action);
  };
  const changeDraft = (value: string) => {
    onDraft(value);
    const slash = value.match(/(?:^|\s)\/([^\s]*)$/);
    if (slash) { setActionMode("slash"); setActionQuery(slash[1] ?? ""); setActionOpen(true); }
    else if (actionMode === "slash") { setActionOpen(false); setActionQuery(""); }
    if (entry?.kind === "group") setMentionOpen(/(?:^|\s)@[\s@]*$/.test(value));
  };
  return <div className="grok-composer-wrap">
    {error ? <div className="grok-composer-error" role="alert"><CircleHelp size={15} /><span>{error}</span><button type="button" onClick={onRetry}>Retry</button></div> : null}
    {replyTo ? <div className="grok-reply-strip"><span>Replying to <strong>{replyTo.role === "user" ? "you" : "this message"}</strong></span><button type="button" aria-label="Cancel reply" onClick={onClearReply}><X size={14} /></button></div> : null}
    {attachments.length ? <div className="grok-attachment-tray" aria-label="Attachments">{attachments.map((file) => <span className="grok-attachment" key={file.id}><FileText size={14} /><span>{file.name}</span><button type="button" aria-label={`Remove ${file.name}`} onClick={() => onRemoveAttachment(file.id)}><X size={13} /></button></span>)}</div> : null}
    <ActionMenu actions={actions} open={actionOpen} mode={actionMode} query={actionQuery} onQuery={setActionQuery} onSelect={chooseAction} onClose={() => { setActionOpen(false); setActionQuery(""); textareaRef.current?.focus(); }} />
    {mentionOpen && entry?.kind === "group" ? <MentionMenu entry={entry} agents={agents} selected={mentionIds} onSelect={pickMention} /> : null}
    <div className="grok-composer">
      <button className="grok-composer-button" type="button" aria-label="Open composer actions" title="Add or use a tool" disabled={entry?.archived || isSending} onClick={() => { setActionMode("plus"); setActionQuery(""); setActionOpen((value) => !value); }}><Plus size={20} /></button>
      <input className="grok-hidden-input" ref={fileRef} type="file" onChange={onAttach} />
      {entry?.kind === "group" ? <button className={`grok-composer-button grok-mention-trigger ${mentionOpen ? "is-active" : ""}`} type="button" aria-label="Mention a Bot" title="Mention a Bot" onClick={() => setMentionOpen((open) => !open)}><span>@</span></button> : null}
      <textarea ref={textareaRef} aria-label={entry ? `Message ${entry.name}` : "Message"} value={draft} onChange={(event) => changeDraft(event.target.value)} onKeyDown={keyDown} placeholder={entry ? `Message ${entry.name}…` : "Choose a Bot to start"} rows={1} disabled={!entry || isSending || entry.archived} />
      <span className="grok-composer-hint">{uploading ? "Uploading…" : isSending ? (isStopping ? "Stopping…" : "Working") : "Enter to send"}</span>
      <button className={`grok-send-button ${isSending ? "is-stop" : ""}`} type="button" aria-label={isSending ? "Stop work" : "Send message"} disabled={entry?.archived || uploading || isStopping || (!isSending && (!draft.trim() && !attachments.length))} onClick={isSending ? onStop : onSend}>{isSending ? <X size={17} /> : <ArrowUp size={19} />}</button>
    </div>
  </div>;
}

function RoutineSection({ agentId, routines, onRefresh, onTask }: { agentId?: string; routines: Routine[]; onRefresh: () => void; onTask: (task: TaskEnvelope) => void }): JSX.Element {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [instruction, setInstruction] = useState("");
  const [time, setTime] = useState("09:00");
  const [weekdays, setWeekdays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [busy, setBusy] = useState(false);
  const actionPending = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const toggleDay = (day: number) => setWeekdays((current) => current.includes(day) ? current.filter((item) => item !== day) : [...current, day].sort());
  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!agentId || !name.trim() || !instruction.trim() || !weekdays.length || busy) return;
    setBusy(true); setError(null);
    try { await createRoutine(agentId, { name: name.trim(), instruction: instruction.trim(), time, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, weekdays, enabled: true }); setName(""); setInstruction(""); setOpen(false); onRefresh(); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  };
  const perform = async (operation: () => Promise<void>) => {
    if (actionPending.current) return;
    actionPending.current = true; setBusy(true); setError(null);
    try { await operation(); onRefresh(); }
    catch (reason) { setError(errorText(reason)); }
    finally { actionPending.current = false; setBusy(false); }
  };
  const toggle = (routine: Routine) => perform(async () => { await updateRoutine(routine.id, { enabled: !routine.enabled }); });
  const run = (routine: Routine) => perform(async () => { const result = await runRoutine(routine.id, makeLocalId("routine")); result.tasks.forEach(onTask); });
  const remove = (routine: Routine) => perform(async () => { await deleteRoutine(routine.id); });
  return <section className="grok-detail-section grok-routines"><div className="grok-detail-heading"><div><span className="grok-section-kicker"><Clock3 size={14} /> Routines</span><h3>{routines.length ? `${routines.length} scheduled ${routines.length === 1 ? "routine" : "routines"}` : "Do something regularly"}</h3></div><button className="grok-icon-button" type="button" aria-label="Add routine" onClick={() => setOpen((value) => !value)}><Plus size={17} /></button></div>{routines.length ? <div className="grok-routine-list">{routines.map((routine) => <div className="grok-routine-row" key={routine.id}><span className={`grok-toggle-dot ${routine.enabled ? "is-on" : ""}`} /><div><strong>{routine.name}</strong><small>{routine.time} · {routine.weekdays.map((day) => WEEKDAYS[day]).join(", ")}</small></div><button type="button" className="grok-routine-action" disabled={busy} onClick={() => void toggle(routine)}>{routine.enabled ? "Pause" : "Resume"}</button><button type="button" className="grok-routine-action" disabled={busy} onClick={() => void run(routine)}>Run</button><button type="button" className="grok-routine-delete" disabled={busy} aria-label={`Delete ${routine.name}`} onClick={() => void remove(routine)}><Trash2 size={14} /></button></div>)}</div> : <p className="grok-detail-copy">Tell {agentId ? "this Bot" : "your Bot"} to remind you, check something, or prepare a regular update.</p>}{error && !open ? <p className="grok-form-error" role="alert">{error}</p> : null}{open ? <form className="grok-routine-form" onSubmit={(event) => void create(event)}><label>Name<input className="grok-field" value={name} onChange={(event) => setName(event.target.value)} placeholder="Morning check-in" /></label><label>What should happen?<textarea className="grok-field grok-textarea" value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Review my open tasks and tell me what needs attention." rows={3} /></label><div className="grok-routine-form-row"><label>Time<input className="grok-field" type="time" value={time} onChange={(event) => setTime(event.target.value)} /></label><span className="grok-weekdays-label">Days</span></div><div className="grok-weekdays" aria-label="Routine days">{WEEKDAYS.map((day, index) => <button key={day} className={weekdays.includes(index) ? "is-selected" : ""} type="button" aria-label={day} aria-pressed={weekdays.includes(index)} onClick={() => toggleDay(index)}>{day}</button>)}</div>{error ? <p className="grok-form-error" role="alert">{error}</p> : null}<button className="grok-button grok-button-dark" type="submit" disabled={busy || !agentId}>{busy ? <Loader2 size={15} className="grok-spin" /> : <Plus size={15} />} Save routine</button></form> : null}</section>;
}

function DesktopCard({ agentId, desktop, onRefresh, onChange }: { agentId?: string; desktop: DesktopStatus | null; onRefresh: () => void; onChange: (desktop: DesktopStatus) => void }): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [operation, setOperation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ready = Boolean(desktop?.available);
  const phase = busy && (operation === "create" || operation === "start") ? "starting" : desktop?.phase ?? (desktop?.running ? "running" : desktop?.created ? "paused" : ready ? "unavailable" : "unavailable");
  const action = async (kind: "create" | "start" | "stop" | "manual" | "bot") => {
    if (!agentId || busy) return;
    setBusy(true); setOperation(kind); setError(null);
    try {
      const next = kind === "create" ? await createDesktop(agentId) : kind === "start" ? await startDesktop(agentId) : kind === "stop" ? await stopDesktop(agentId) : await setDesktopControl(agentId, kind);
      onChange(next); onRefresh();
    } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); setOperation(null); }
  };
  return <section className="grok-detail-section grok-desktop-card"><div className="grok-detail-heading"><div><span className="grok-section-kicker"><Laptop size={14} /> Computer</span><h3>{phase === "running" ? "Computer is ready" : phase === "starting" ? "Starting computer…" : "Optional computer"}</h3></div><span className={`grok-status-chip ${phase === "running" ? "is-green" : ""}`}><i />{phase}</span></div>{desktop?.view_url && phase === "running" ? <div className="grok-desktop-preview"><iframe title="Bot computer preview" src={desktop.view_url} /><a href={desktop.view_url} target="_blank" rel="noreferrer">Open computer <ChevronRight size={13} /></a></div> : <p className="grok-detail-copy">Your Bot can use a private browser when a task needs it. You can take control for passwords or verification.</p>}{error ? <p className="grok-form-error" role="alert">{error}</p> : null}<div className="grok-desktop-actions">{!desktop?.created ? <button className="grok-button grok-button-dark" type="button" disabled={busy || !ready} onClick={() => void action("create")}>{busy ? <Loader2 size={15} className="grok-spin" /> : <Laptop size={15} />} Set up computer</button> : phase === "running" ? <><button className="grok-button grok-button-quiet" type="button" disabled={busy} onClick={() => void action("manual")}>Take control</button><button className="grok-button grok-button-quiet" type="button" disabled={busy} onClick={() => void action("stop")}>Pause</button></> : <button className="grok-button grok-button-dark" type="button" disabled={busy} onClick={() => void action("start")}>{busy ? <Loader2 size={15} className="grok-spin" /> : <RefreshCw size={15} />} Start computer</button>}{desktop?.control_mode === "manual" ? <button className="grok-button grok-button-quiet" type="button" disabled={busy} onClick={() => void action("bot")}>Return to Bot</button> : null}</div></section>;
}

function DetailsPanel({ entry, agents, routines, desktop, accountId, onClose, onRoutinesRefresh, onTask, onDesktopChange, memoryCount, fileCount, onResource }: { entry: InboxEntry | null; agents: Agent[]; routines: Routine[]; desktop: DesktopStatus | null; accountId?: string; onClose: () => void; onRoutinesRefresh: () => void; onTask: (task: TaskEnvelope) => void; onDesktopChange: (desktop: DesktopStatus) => void; memoryCount: number; fileCount: number; onResource: (mode: "memory" | "files" | "activity") => void }): JSX.Element {
  const coordinator = entry ? entryAgent(entry, agents) : null;
  const description = coordinator?.description ?? "";
  return <aside className="grok-details" aria-label="Details"><header className="grok-details-head"><div><span className="grok-section-kicker">Details</span><h2>{entry?.name ?? "Your workspace"}</h2></div><button className="grok-icon-button" type="button" aria-label="Close details" onClick={onClose}><X size={18} /></button></header>{entry ? <><section className="grok-detail-section grok-about"><div className="grok-detail-identity"><Identity entry={entry} agents={agents} size="large" /><div><strong>{entry.name}</strong><span>{entry.kind === "group" ? `${entryMembers(entry, agents).length} Bots` : "Personal Bot"}</span></div></div>{description ? description.length > 240 ? <Disclosure accountId={accountId} section="details" id={entry.conversation_id} label="description"><p className="grok-detail-copy">{description}</p></Disclosure> : <p className="grok-detail-copy">{description}</p> : null}{entry.kind === "group" ? <div className="grok-member-stack"><strong>Members</strong>{entryMembers(entry, agents).map((member) => <div key={member.agent_id}><AgentAvatar agent={memberAgent(member)} size="small" /><span>{member.name}</span>{member.role === "coordinator" ? <small>Coordinator</small> : null}</div>)}</div> : null}</section><DesktopCard agentId={coordinator?.id} desktop={desktop} onRefresh={() => undefined} onChange={onDesktopChange} /><RoutineSection agentId={coordinator?.id} routines={routines} onRefresh={onRoutinesRefresh} onTask={onTask} /><section className="grok-detail-section grok-resource-links"><button type="button" onClick={() => onResource("memory")}><Sparkles size={16} /><span><strong>Memory</strong><small>{memoryCount ? `${memoryCount} saved things` : "Nothing saved yet"}</small></span><ChevronRight size={15} /></button><button type="button" onClick={() => onResource("files")}><FolderOpen size={16} /><span><strong>Files</strong><small>{fileCount ? `${fileCount} files in context` : "No files yet"}</small></span><ChevronRight size={15} /></button><button type="button" onClick={() => onResource("activity")}><Activity size={16} /><span><strong>Activity</strong><small>Runs, approvals and results</small></span><ChevronRight size={15} /></button></section></> : <div className="grok-details-empty"><BotGlyph color="#2d93fa" size={48} /><p>Pick a Bot or group to see details here.</p></div>}</aside>;
}

function ResourcePage({ mode, agent, theme, onThemeChange, memory, files, activity, skills, runtime, account, usage, userName, extensionsStatus, privateFields, teachings, accountId, onOpenConnection, onOpenPrivate, onOpenTeaching, onPrivateFieldsChanged, onTeachingsChanged, onEditTeaching, onRunTeaching, onAddMemory, onDeleteMemory, onDeleteFile, onToggleSkill, onAgentSaved, onAccountChange, resourceError, onReload, onBack, onLogout, logoutError }: { mode: Exclude<ResourceMode, "chat">; agent: Agent | null; theme: Theme; onThemeChange: (theme: Theme) => void; memory: MemoryItem[]; files: FileAsset[]; activity: ActivityItem[]; skills: LearnedSkill[]; runtime: RuntimeStatus | null; account: RuntimeAccount | null; usage: RuntimeUsage | null; userName: string; extensionsStatus: ExtensionsStatus | null; privateFields: PrivateField[]; teachings: Teaching[]; accountId: string; onOpenConnection: () => void; onOpenPrivate: () => void; onOpenTeaching: () => void; onPrivateFieldsChanged: (fields: PrivateField[]) => void; onTeachingsChanged: (teachings: Teaching[]) => void; onEditTeaching: (teaching: Teaching) => void; onRunTeaching: (teaching: Teaching) => void; onAddMemory: (content: string, scope: "shared" | "private") => Promise<void>; onDeleteMemory: (id: string, agentId?: string) => Promise<void>; onDeleteFile: (id: string) => Promise<void>; onToggleSkill: (id: string, enabled: boolean) => Promise<void>; resourceError: string | null; onReload: () => void; onAgentSaved: (agent: Agent) => void; onAccountChange: (account: RuntimeAccount) => void; onBack: () => void; onLogout: () => Promise<void>; logoutError: string | null }): JSX.Element {
  const [memoryDraft, setMemoryDraft] = useState("");
  const [memoryScope, setMemoryScope] = useState<"shared" | "private">("private");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitMemory = async (event: FormEvent) => { event.preventDefault(); if (!memoryDraft.trim() || busy) return; setBusy(true); setError(null); try { await onAddMemory(memoryDraft, memoryScope); setMemoryDraft(""); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); } };
  const pageTitle = mode === "memory" ? "Memory" : mode === "files" ? "Files" : mode === "activity" ? "Activity" : "Settings";
  const title = pageTitle;
  return <section className="grok-resource-page"><header className="grok-resource-header"><button className="grok-icon-button" type="button" aria-label="Back to chat" onClick={onBack}><ArrowLeft size={19} /></button><div><span className="grok-section-kicker">Workspace</span><h1>{title}</h1></div></header>{error || resourceError ? <div className="grok-banner" role="alert">{error ?? resourceError}<button type="button" onClick={onReload}>Retry</button></div> : null}{mode === "memory" ? <div className="grok-resource-grid"><form className="grok-resource-form" onSubmit={(event) => void submitMemory(event)}><h2>Save something for {agent?.name ?? "this Bot"}</h2><p>Memory helps your Bot remember useful context between chats.</p><textarea className="grok-field grok-textarea" value={memoryDraft} onChange={(event) => setMemoryDraft(event.target.value)} placeholder="For example: Dad prefers short answers." rows={4} /><div className="grok-resource-form-row"><div className="grok-segmented"><button type="button" className={memoryScope === "private" ? "is-selected" : ""} onClick={() => setMemoryScope("private")}>Private</button><button type="button" className={memoryScope === "shared" ? "is-selected" : ""} onClick={() => setMemoryScope("shared")}>Shared</button></div><button className="grok-button grok-button-dark" type="submit" disabled={busy || !memoryDraft.trim()}>{busy ? <Loader2 size={15} className="grok-spin" /> : <Plus size={15} />} Save</button></div></form><div className="grok-resource-list"><h2>Saved memory <span>{memory.length}</span></h2>{memory.length ? memory.map((item) => <div className="grok-resource-row" key={item.id}><span className={`grok-memory-dot ${item.scope === "private" ? "is-private" : ""}`} /><div><p>{item.content}</p><small>{item.scope === "private" ? "Private" : "Shared"}</small></div><button type="button" aria-label="Delete memory" onClick={() => void onDeleteMemory(item.id, item.agent_id ?? undefined).catch(reason => setError(errorText(reason)))}><Trash2 size={14} /></button></div>) : <EmptyResource icon={<Sparkles size={19} />} text="Saved things will appear here." />}</div></div> : null}{mode === "files" ? <div className="grok-resource-list grok-resource-single"><div className="grok-resource-list-head"><div><h2>Files for {agent?.name ?? "this Bot"}</h2><p>Only files in this Bot’s workspace are included.</p></div><span>{files.length}</span></div>{files.length ? files.map((file) => <div className="grok-resource-row" key={file.id}><span className="grok-file-icon"><FileText size={17} /></span><div><p>{file.name}</p><small>{formatBytes(file.size)}{file.status ? ` · ${file.status}` : ""}</small></div>{file.url ? <a href={file.url} download aria-label={`Download ${file.name}`}><Download size={14} /></a> : null}<button type="button" aria-label={`Delete ${file.name}`} onClick={() => void onDeleteFile(file.id).catch(reason => setError(errorText(reason)))}><Trash2 size={14} /></button></div>) : <EmptyResource icon={<FolderOpen size={20} />} text="Attach a file in a chat to give your Bot context." />}</div> : null}{mode === "activity" ? <div className="grok-resource-list grok-resource-single"><div className="grok-resource-list-head"><div><h2>What happened</h2><p>Runs and approvals from your Bots.</p></div><span>{activity.length}</span></div>{activity.length ? activity.map((item) => <div className="grok-resource-row" key={item.id}><span className={`grok-activity-icon ${item.status === "failed" ? "is-failed" : item.status === "running" ? "is-running" : ""}`}>{item.status === "running" ? <Loader2 size={15} className="grok-spin" /> : item.status === "failed" ? <X size={15} /> : <Check size={15} />}</span><div><p>{item.title}</p><small>{item.detail ?? item.kind ?? "Run"} · {formatDate(item.created_at)}</small></div></div>) : <EmptyResource icon={<Activity size={20} />} text="Your run history will appear here." />}</div> : null}{mode === "settings" ? <div className="grok-settings-stack">{agent ? <BotSettingsEditor agent={agent} models={account?.models} accountId={accountId} onSaved={onAgentSaved} /> : null}<RuntimeConnectionCard account={account} onAccountChange={onAccountChange} /><ExpansionStatusCard status={extensionsStatus} onConnections={onOpenConnection} onPrivate={onOpenPrivate} onTeach={onOpenTeaching} />{agent ? <PrivateFieldsPanel agentId={agent.id} fields={privateFields} status={extensionsStatus} onOpen={onOpenPrivate} onChanged={onPrivateFieldsChanged} /> : null}<section className="grok-resource-list grok-resource-single"><div className="grok-resource-list-head"><div><h2>Appearance</h2><p>Choose how Hermes looks on this device.</p></div><Sun size={18} /></div><div className="grok-theme-grid">{(["light", "dark", "system"] as Theme[]).map((option) => <button key={option} className={theme === option ? "is-selected" : ""} type="button" onClick={() => onThemeChange(option)}>{option === "light" ? <Sun size={16} /> : option === "dark" ? <Moon size={16} /> : <Settings size={16} />}<span>{option[0].toUpperCase() + option.slice(1)}</span>{theme === option ? <Check size={15} /> : null}</button>)}</div></section><MotionSettings /><RuntimeUsageCard account={account} usage={usage} /><TeachingManager agent={agent} teachings={teachings} skills={skills} accountId={accountId} onEdit={(item) => onEditTeaching(item)} onRun={(item) => onRunTeaching(item)} onChanged={onTeachingsChanged} /><section className="grok-resource-list grok-resource-single"><div className="grok-resource-list-head"><div><h2>Learned skills</h2><p>Procedures your Bots have saved.</p></div><span>{skills.length}</span></div>{skills.map((skill) => <div className="grok-resource-row" key={skill.id}><span className={`grok-skill-dot ${skill.enabled !== false ? "is-on" : ""}`} /><div><p>{skill.name}</p><small>{skill.enabled === false ? "Paused" : "Ready to use"}</small></div><button type="button" onClick={() => void onToggleSkill(skill.id, skill.enabled === false).catch(reason => setError(errorText(reason)))}>{skill.enabled === false ? "Resume" : "Pause"}</button></div>)}</section><AccountPanel userName={userName} account={account} runtime={runtime} onLogout={onLogout} logoutError={logoutError} /></div> : null}</section>;
}

function EmptyResource({ icon, text }: { icon: JSX.Element; text: string }): JSX.Element {
  return <div className="grok-empty-resource"><span>{icon}</span><p>{text}</p></div>;
}

function InboxRow({ entry, agents, selected, onSelect }: { entry: InboxEntry; agents: Agent[]; selected: boolean; onSelect: () => void }): JSX.Element {
  const active = (entry.active_tasks ?? []).some((task) => ACTIVE_STATUSES.has(task.status ?? "running"));
  return <button type="button" className={`grok-inbox-row ${selected ? "is-selected" : ""}`} aria-current={selected ? "page" : undefined} onClick={onSelect}><Identity entry={entry} agents={agents} size="medium" status={active && entry.kind !== "group" ? "working" : "idle"} /><span className="grok-inbox-copy"><span className="grok-inbox-title"><strong>{entry.name}</strong>{entry.pinned ? <Pin size={12} /> : null}<time>{formatTime(entry.updated_at)}</time></span><small>{entry.preview || (entry.kind === "group" ? "Group chat" : "Ready when you are")}</small></span>{entry.unread_count ? <span className="grok-unread" aria-label={`${entry.unread_count} unread`}>{entry.unread_count > 9 ? "9+" : entry.unread_count}</span> : null}{active ? <span className="grok-active-dot" aria-label="Working" /> : null}</button>;
}

function Inbox({ entries, agents, selectedId, query, onQuery, onSelect, onNew, onNewGroup, onSettings, userName, connection }: { entries: InboxEntry[]; agents: Agent[]; selectedId?: string; query: string; onQuery: (value: string) => void; onSelect: (id: string) => void; onNew: () => void; onNewGroup: () => void; onSettings: () => void; userName: string; connection: "online" | "offline" | "checking" }): JSX.Element {
  const [createOpen, setCreateOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const visible = entries.filter((entry) => Boolean(entry.archived) === showArchived && `${entry.name} ${entry.preview ?? ""} ${entry.members.map((member) => member.name).join(" ")}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <aside className="grok-inbox" aria-label="Inbox"><header className="grok-inbox-head"><button className="grok-brand" type="button" onClick={onSettings} aria-label="Open Hermes settings"><BotGlyph color="#2d93fa" size={26} /><span>Hermes</span></button><div className="grok-inbox-actions"><button className="grok-icon-button" type="button" aria-label="New chat" title="New chat" onClick={() => setCreateOpen((open) => !open)}><Plus size={19} /></button><button className="grok-icon-button" type="button" aria-label={`Settings for ${userName}`} title="Settings" onClick={onSettings}><UserRound size={18} /></button></div>{createOpen ? <div className="grok-create-menu"><button type="button" onClick={() => { setCreateOpen(false); onNew(); }}><BotGlyph color="#2d93fa" size={21} /><span><strong>New Bot</strong><small>Give a Bot a clear job</small></span></button><button type="button" onClick={() => { setCreateOpen(false); onNewGroup(); }}><Users size={20} /><span><strong>New group chat</strong><small>Work with two or more Bots</small></span></button></div> : null}</header><div className="grok-inbox-search"><Search size={16} /><input aria-label="Search chats" placeholder="Search chats" value={query} onChange={(event) => onQuery(event.target.value)} />{query ? <button type="button" aria-label="Clear search" onClick={() => onQuery("")}><X size={14} /></button> : null}</div><div className="grok-inbox-label"><span>{showArchived ? "Archived" : "Chats"}</span>{entries.some(entry => entry.archived) || showArchived ? <button className="grok-archive-toggle" type="button" onClick={() => setShowArchived(value => !value)}>{showArchived ? "Back to chats" : "Archived chats"}</button> : null}<span className={connection === "online" ? "is-online" : connection === "offline" ? "is-offline" : ""}><i />{connection === "offline" ? "Offline" : connection === "checking" ? "Checking" : "Ready"}</span></div><div className="grok-inbox-list">{visible.length ? visible.map((entry) => <InboxRow key={`${entry.kind}:${inboxKey(entry)}`} entry={entry} agents={agents} selected={inboxKey(entry) === selectedId} onSelect={() => onSelect(inboxKey(entry))} />) : <div className="grok-inbox-empty"><BotGlyph color="#2d93fa" size={42} /><strong>{query ? "No matching chat names" : "No chats yet"}</strong><p>{query ? "Message matches appear in the search results." : "Create a Bot to get started."}</p>{!query ? <button className="grok-button grok-button-dark" type="button" onClick={onNew}><Plus size={15} /> New Bot</button> : null}</div>}</div><footer className="grok-inbox-footer"><button type="button" onClick={onSettings}><span className="grok-user-avatar"><UserRound size={15} /></span><span>{userName}</span><Settings size={15} /></button></footer></aside>;
}

export default function GrokWorkspace({ session, theme, onThemeChange, onLogout, logoutError }: GrokWorkspaceProps): JSX.Element {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [entries, setEntries] = useState<InboxEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [messages, setMessages] = useState<Record<string, Message[]>>({});
  const [tasks, setTasks] = useState<Record<string, TaskState>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [mentionIds, setMentionIds] = useState<Record<string, string[]>>({});
  const [attachments, setAttachments] = useState<Record<string, FileAsset[]>>({});
  const [replyIds, setReplyIds] = useState<Record<string, string | undefined>>({});
  const [loading, setLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const historyCursors = useRef<Record<string,string>>({});
  const [historyExhausted, setHistoryExhausted] = useState<Record<string, boolean>>({});
  const [connection, setConnection] = useState<"online" | "offline" | "checking">("checking");
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [resourceMode, setResourceMode] = useState<ResourceMode>("chat");
  const [mobileInbox, setMobileInbox] = useState(true);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [newBotOpen, setNewBotOpen] = useState(false);
  const [newGroupOpen, setNewGroupOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchMatches, setSearchMatches] = useState<Array<{ id: string; conversation_id?: string | null; message_id?: string | null; kind?: string; snippet?: string; name?: string }>>([]);
  const [searchBusy, setSearchBusy] = useState(false);
  const [chatMenuOpen, setChatMenuOpen] = useState(false);
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [desktop, setDesktop] = useState<DesktopStatus | null>(null);
  const [memory, setMemory] = useState<MemoryItem[]>([]);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [skills, setSkills] = useState<LearnedSkill[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [runtimeAccount, setRuntimeAccount] = useState<RuntimeAccount | null>(null);
  const [runtimeUsage, setRuntimeUsage] = useState<RuntimeUsage | null>(null);
  const [extensionsStatus, setExtensionsStatus] = useState<ExtensionsStatus | null>(null);
  const [requests, setRequests] = useState<Record<string, ChatRequest[]>>({});
  const [privateFields, setPrivateFields] = useState<Record<string, PrivateField[]>>({});
  const [teachings, setTeachings] = useState<Record<string, Teaching[]>>({});
  const [expansionSheet, setExpansionSheet] = useState<"connections" | "private" | "teach" | null>(null);
  const [privateRequest, setPrivateRequest] = useState<ChatRequest | null>(null);
  const [connectionRequest, setConnectionRequest] = useState<ChatRequest | null>(null);
  const [teachingEdit, setTeachingEdit] = useState<Teaching | null>(null);
  const [teachingRun, setTeachingRun] = useState<Teaching | null>(null);
  const [dictationTarget, setDictationTarget] = useState<{ key: string; draft: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submittingKey, setSubmittingKey] = useState<string | undefined>();
  const [lastAttempts, setLastAttempts] = useState<Record<string, DraftAttempt | null>>({});
  const [scrollTarget, setScrollTarget] = useState<string | undefined>();
  const taskControllers = useRef(new Map<string, AbortController>());
  const watchedTasks = useRef(new Set<string>());
  const selectedRef = useRef<string | undefined>(undefined);
  const resourceRequestRef = useRef(0);
  const submittingRef = useRef(false);
  const uploadingRef = useRef(false);
  const pendingSubmitRef = useRef<{ attempt: DraftAttempt; sourceKey: string; requestId?: string; stopRequested: boolean; cancelIssued: boolean } | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);

  const selectedEntry = useMemo(() => entries.find((entry) => inboxKey(entry) === selectedId) ?? null, [entries, selectedId]);
  const selectedAgent = useMemo(() => selectedEntry ? entryAgent(selectedEntry, agents) : null, [agents, selectedEntry]);
  const selectedMessages = selectedId ? messages[selectedId] ?? [] : [];
  const selectedTasks = useMemo(() => Object.values(tasks).filter((task) => task.conversation_id === selectedId), [selectedId, tasks]);
  const activeTasks = selectedTasks.filter((task) => ACTIVE_STATUSES.has(task.status ?? "running") || Boolean(task.approval));
  const draftKey = selectedId || selectedAgent?.id || "new";
  const currentSubmission = submitting && submittingKey === draftKey;
  const draft = drafts[draftKey] ?? "";
  const selectedAttachments = attachments[draftKey] ?? [];
  const selectedMentionIds = mentionIds[draftKey] ?? [];
  const replyTo = replyIds[draftKey] ? selectedMessages.find((message) => message.id === replyIds[draftKey]) : undefined;
  const streamError = errors[draftKey] ?? null;
  const lastAttempt = lastAttempts[draftKey] ?? null;
  const selectedRequests = selectedId ? requests[selectedId] ?? [] : [];
  const selectedPrivateFields = selectedAgent?.id ? privateFields[selectedAgent.id] ?? [] : [];
  const selectedTeachings = selectedAgent?.id ? teachings[selectedAgent.id] ?? [] : [];
  const userName = session.user?.name ?? session.user?.username ?? "My account";
  const accountId = session.user?.id ?? "account";

  const setScopedError = useCallback((key: string, message: string | null): void => {
    setErrors((current) => {
      if (message) return { ...current, [key]: message };
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }, []);

  const setTask = useCallback((taskId: string, update: (task: TaskState) => TaskState): void => {
    setTasks((current) => {
      const existing = current[taskId];
      return existing ? { ...current, [taskId]: update(existing) } : current;
    });
  }, []);

  const reconcileConversationTasks = useCallback((conversationId: string, related: Array<{ id: string; conversation_id: string; origin_conversation_id?: string | null; status?: string; phase?: string | null; error_message?: string | null }>): void => {
    setTasks((current) => {
      let changed = false;
      const next = { ...current };
      related.forEach((remote) => {
        const existing = next[remote.id];
        const visualConversationId = remote.origin_conversation_id || remote.conversation_id || conversationId;
        if (!existing || existing.conversation_id !== visualConversationId) return;
        const status = remote.status ?? existing.status ?? "running";
        const terminal = ["completed", "failed", "cancelled"].includes(status);
        const resetReplay = false;
        const progress = status === "completed" ? "Finished" : status === "failed" ? "Run failed" : status === "cancelled" ? "Run stopped" : existing.progress;
        next[remote.id] = { ...existing, status, phase: remote.phase ?? existing.phase, error_message: remote.error_message ?? existing.error_message, terminal: terminal || existing.terminal, stopRequested: terminal ? false : existing.stopRequested, progress: resetReplay ? remote.phase ?? "Working" : progress, text: resetReplay ? "" : existing.text, approval: terminal ? undefined : existing.approval, image: terminal && status !== "completed" && existing.image?.status === "generating" ? { ...existing.image, status: "error", message: "The image run ended before a preview was ready." } : existing.image };
        changed = true;
      });
      return changed ? next : current;
    });
  }, []);

  const refreshConversation = useCallback(async (conversationId: string): Promise<Message[] | null> => {
    try {
      const fresh = await listMessages(conversationId);
      setMessages((current) => ({ ...current, [conversationId]: mergeMessages(current[conversationId] ?? [], fresh) }));
      return fresh;
    } catch {
      // The active transcript remains visible and the next open retries the read.
      return null;
    }
  }, []);

  const refreshConversationRequests = useCallback(async (conversationId: string): Promise<void> => {
    if (!conversationId) return;
    try {
      const fresh = await listConversationRequests(conversationId);
      if (selectedRef.current === conversationId) setRequests((current) => ({ ...current, [conversationId]: fresh }));
    } catch {
      // Request cards are supplementary to the transcript; the next refresh retries.
    }
  }, []);

  const refreshInbox = useCallback(async (): Promise<void> => {
    const [agentResult, inboxResult] = await Promise.allSettled([listAgents(), getInbox(true)]);
    if (agentResult.status === "fulfilled") setAgents(agentResult.value);
    if (inboxResult.status === "fulfilled" && inboxResult.value.length) setEntries(inboxResult.value);
  }, []);

  const attachTask = useCallback((envelope: TaskEnvelope | InboxTask, defaultConversationId?: string, defaultAgentId?: string, defaultRequestId?: string): void => {
    const id = envelope.id;
    if (!id || watchedTasks.current.has(id)) return;
    const conversationId = ("origin_conversation_id" in envelope && envelope.origin_conversation_id) || defaultConversationId || envelope.conversation_id || "";
    if (!conversationId) return;
    const controller = new AbortController();
    watchedTasks.current.add(id);
    taskControllers.current.set(id, controller);
    const task: TaskState = {
      id,
      conversation_id: conversationId,
      agent_id: envelope.agent_id ?? defaultAgentId ?? null,
      request_id: envelope.request_id ?? defaultRequestId ?? null,
      status: envelope.status ?? "running",
      phase: envelope.phase ?? null,
      error_message: "error_message" in envelope && envelope.error_message ? String(envelope.error_message) : null,
      text: "",
      progress: envelope.phase ?? "Working",
      controller,
    };
    // A new watcher replays durable events from zero, rebuilding its display.
    setTasks((current) => ({ ...current, [id]: task }));
    const handleEvent = (event: StreamEvent) => {
      const eventData = eventRecord(event);
      const eventTaskId = typeof eventData.task_id === "string" ? eventData.task_id : isRecord(eventData.task) && typeof eventData.task.id === "string" ? eventData.task.id : null;
      if (eventTaskId && eventTaskId !== id && (eventData.parent_task_id === id || eventData.origin_conversation_id === conversationId)) {
        const eventAgent = typeof eventData.agent_id === "string" ? eventData.agent_id : isRecord(eventData.agent) && typeof eventData.agent.id === "string" ? eventData.agent.id : undefined;
        attachTask({ id: eventTaskId, conversation_id: typeof eventData.conversation_id === "string" ? eventData.conversation_id : conversationId, origin_conversation_id: typeof eventData.origin_conversation_id === "string" ? eventData.origin_conversation_id : conversationId, parent_task_id: id, agent_id: eventAgent ?? null, request_id: typeof eventData.request_id === "string" ? eventData.request_id : defaultRequestId ?? null, status: typeof eventData.status === "string" ? eventData.status : "running", phase: typeof eventData.phase === "string" ? eventData.phase : null }, conversationId, eventAgent, defaultRequestId);
      }
      if ((event.type === "tool.started" || event.type === "tool.completed") && conversationId) {
        void refreshConversationRequests(conversationId);
        void conversationTasks(conversationId).then((related) => related.filter((item) => ACTIVE_STATUSES.has(item.status)).forEach((relatedTask) => attachTask({ ...relatedTask, id: relatedTask.id, conversation_id: relatedTask.conversation_id || conversationId, origin_conversation_id: conversationId }, conversationId, relatedTask.agent_id ?? undefined, relatedTask.request_id ?? defaultRequestId))).catch(() => undefined);
      }
      setTask(id, (current) => {
        const data = eventData;
        const next = { ...current };
        const text = eventText(event);
        if (text) { next.text = `${next.text}${text}`; next.progress = "Typing"; }
        if (typeof data.agent_id === "string") next.agent_id = data.agent_id;
        if (typeof data.request_id === "string") next.request_id = data.request_id;
        if (isRecord(data.message) && typeof data.message.content === "string") { next.text = data.message.content; next.progress = "Typing"; }
        if (event.type === "task.reconnecting") { next.status = "reconnecting"; next.progress = "Reconnecting"; }
        if (event.type === "task.started") { next.status = "running"; next.progress = "Starting"; }
        if (event.type === "turn.started") { next.status = "running"; next.progress = "Thinking"; }
        if (event.type === "plan") next.progress = "Following the plan";
        if (event.type === "tool.started") {
          const toolName = eventToolName(event);
          next.progress = isImageEvent(event) ? "Generating an image" : humanToolName(toolName);
          if (isImageEvent(event)) next.image = { status: "generating", prompt: typeof data.prompt === "string" ? data.prompt : undefined, aspectRatio: typeof data.aspect_ratio === "string" ? data.aspect_ratio : "1:1" };
        }
        if (event.type === "tool.completed" && isImageEvent(event)) {
          const source = imageSource(data);
          next.image = source && data.success !== false ? { ...(next.image ?? {}), status: "complete", src: source, alt: next.image?.prompt ?? "Generated image" } : { ...(next.image ?? {}), status: "error", message: typeof data.error === "string" ? data.error : "The image result did not include a preview." };
          next.progress = source ? "Image ready" : "Image unavailable";
        } else if (event.type === "tool.completed") next.progress = "Tool step complete";
        if (event.type === "approval" || event.type === "approval.requested") {
          const raw = (data.approval ?? data) as Record<string, unknown>;
          if (typeof raw.description === "string") {
            next.approval = { approval_id: String(raw.approval_id ?? raw.id ?? makeLocalId("approval")), kind: typeof raw.kind === "string" ? raw.kind : "Action", description: raw.description, status: "pending", data: isRecord(raw.data) ? raw.data : undefined };
            next.progress = "Waiting for your approval";
            next.status = "waiting";
          }
        }
        if (event.type === "approval.decided") next.approval = undefined;
        if (event.type === "error" || event.type === "task.error" || event.type === "task.failed") {
          const message = typeof data.message === "string" ? data.message : isRecord(data.error) && typeof data.error.message === "string" ? data.error.message : eventText(event) ?? "The run failed.";
          next.status = "failed"; next.terminal = true; next.error_message = message; next.progress = "Run failed"; next.approval = undefined;
          if (next.image?.status === "generating") next.image = { ...next.image, status: "error", message: "The image run failed before a preview was ready." };
        }
        if (TERMINAL_EVENTS.has(event.type)) {
          next.status = event.type === "task.completed" ? "completed" : event.type === "task.cancelled" ? "cancelled" : "failed";
          next.terminal = true; next.stopRequested = false;
          next.progress = event.type === "task.cancelled" ? "Run stopped" : event.type === "task.completed" ? "Finished" : "Run failed";
          next.approval = undefined;
          if (event.type === "task.cancelled" && next.image?.status === "generating") next.image = { ...next.image, status: "cancelled", message: "Stopped waiting for the image. The provider may still finish this request." };
          if (event.type !== "task.completed" && event.type !== "task.cancelled" && next.image?.status === "generating") next.image = { ...next.image, status: "error", message: "The image run failed before a preview was ready." };
        }
        return next;
      });
    };
    void watchTask(id, handleEvent, controller.signal).catch((reason) => {
      if (!isAbortError(reason)) {
        // Keep the durable run visible and allow a later chat open or inbox
        // refresh to attach a fresh watcher with the same task identity.
        watchedTasks.current.delete(id);
        setTask(id, (current) => ({ ...current, status: "reconnecting", terminal: false, progress: "Connection lost · reopen to reconnect", error_message: errorText(reason), approval: undefined, image: current.image?.status === "generating" ? { ...current.image, status: "error", message: "The image run lost its connection. Reopen the chat to reconnect." } : current.image }));
      }
    }).finally(() => {
      taskControllers.current.delete(id);
      void refreshConversation(conversationId).then((fresh) => {
        // A completed streamed task is safe to collapse once its canonical
        // assistant message is present. Failed and cancelled runs stay in the
        // transcript so the user can understand what happened.
        if (fresh?.some((message) => message.source_task_id === id)) setTasks((current) => { if (!current[id] || current[id].status !== "completed") return current; const next = { ...current }; delete next[id]; return next; });
      });
      void refreshConversationRequests(conversationId);
      void refreshInbox();
    });
  }, [refreshConversation, refreshConversationRequests, refreshInbox, setTask]);

  const restoreTasks = useCallback(async (nextEntries: InboxEntry[]): Promise<void> => {
    const seeds: Array<{ task: InboxTask | TaskEnvelope; conversationId: string; agentId?: string | null; requestId?: string | null }> = [];
    nextEntries.forEach((entry) => (entry.active_tasks ?? []).forEach((task) => seeds.push({ task, conversationId: entry.conversation_id, agentId: task.agent_id ?? entry.agent_id ?? entry.coordinator_id, requestId: task.request_id })));
    const results = await Promise.allSettled(nextEntries.filter((entry) => entry.conversation_id).map(async (entry) => ({ entry, tasks: await conversationTasks(entry.conversation_id) })));
    results.forEach((result) => { if (result.status === "fulfilled") { reconcileConversationTasks(result.value.entry.conversation_id, result.value.tasks); result.value.tasks.filter((task) => ACTIVE_STATUSES.has(task.status)).forEach((task) => seeds.push({ task, conversationId: result.value.entry.conversation_id, agentId: task.agent_id, requestId: task.request_id })); } });
    const seen = new Set<string>();
    seeds.forEach(({ task, conversationId, agentId, requestId }) => { if (seen.has(task.id)) return; seen.add(task.id); attachTask({ ...task, id: task.id, conversation_id: task.conversation_id ?? conversationId }, conversationId, agentId ?? undefined, requestId ?? undefined); });
  }, [attachTask, reconcileConversationTasks]);

  const loadWorkspace = useCallback(async (): Promise<void> => {
    setLoading(true); setWorkspaceError(null); setConnection("checking");
    const chiefResult = await bootstrapChief().catch(() => null);
    const [agentsResult, inboxResult, conversationsResult, runtimeResult, accountResult, usageResult, extensionsResult] = await Promise.allSettled([listAgents(), getInbox(true), listConversations(), getRuntimeStatus(), getRuntimeAccount(), getRuntimeUsage(), getExtensionsStatus()]);
    const loadedAgents = agentsResult.status === "fulfilled" ? agentsResult.value : chiefResult ? [chiefResult] : [];
    if (chiefResult && !loadedAgents.some((agent) => agent.id === chiefResult.id)) loadedAgents.unshift(chiefResult);
    let loadedEntries: InboxEntry[] = inboxResult.status === "fulfilled" ? inboxResult.value : [];
    if (!loadedEntries.length && conversationsResult.status === "fulfilled") loadedEntries = normalizeLegacyInbox(loadedAgents, conversationsResult.value);
    if (chiefResult && !loadedEntries.some((entry) => entry.agent_id === chiefResult.id)) {
      const home = await getAgentHome(chiefResult.id).catch(() => null);
      if (home) loadedEntries = [directEntry(chiefResult, home), ...loadedEntries];
    }
    setAgents(loadedAgents); setEntries(loadedEntries); setConnection(loadedEntries.length || loadedAgents.length || inboxResult.status === "fulfilled" ? "online" : "offline"); setLoading(false);
    if (runtimeResult.status === "fulfilled") setRuntime(runtimeResult.value);
    if (accountResult.status === "fulfilled") setRuntimeAccount(accountResult.value);
    if (usageResult.status === "fulfilled") setRuntimeUsage(usageResult.value);
    if (extensionsResult.status === "fulfilled") setExtensionsStatus(extensionsResult.value);
    if (inboxResult.status === "rejected" && conversationsResult.status === "rejected" && !loadedAgents.length) setWorkspaceError("Hermes could not reach the workspace. Check the server and try again.");
    await restoreTasks(loadedEntries);
    const saved = window.localStorage.getItem("hermes-selected-chat");
    const preferred = saved && loadedEntries.some((entry) => inboxKey(entry) === saved) ? saved : loadedEntries[0] ? inboxKey(loadedEntries[0]) : undefined;
    if (preferred) { setSelectedId(preferred); selectedRef.current = preferred; }
  }, [restoreTasks]);

  useEffect(() => { void loadWorkspace(); const online = () => setConnection("online"); const offline = () => setConnection("offline"); window.addEventListener("online", online); window.addEventListener("offline", offline); return () => { window.removeEventListener("online", online); window.removeEventListener("offline", offline); }; }, [loadWorkspace]);

  const loadSelectedResources = useCallback(async (agentId: string | undefined, ownerKey?: string): Promise<void> => {
    const requestId = resourceRequestRef.current + 1;
    resourceRequestRef.current = requestId;
    if (!agentId) { setRoutines([]); setDesktop(null); setMemory([]); setFiles([]); setSkills([]); setActivity([]); return; }
    const results = await Promise.allSettled([listRoutines(agentId), getDesktopStatus(agentId), listMemory(agentId), listFiles(agentId), listSkills(agentId), listActivity(agentId), selectedId && !selectedId.startsWith("agent:") ? listConversationRequests(selectedId) : Promise.resolve([] as ChatRequest[]), listPrivateFields(agentId), listTeachings(agentId)]);
    if (resourceRequestRef.current !== requestId || ownerKey && selectedRef.current !== ownerKey) return;
    if (results[0].status === "fulfilled") setRoutines(results[0].value);
    if (results[1].status === "fulfilled") setDesktop(results[1].value);
    if (results[2].status === "fulfilled") setMemory(results[2].value);
    if (results[3].status === "fulfilled") setFiles(results[3].value);
    if (results[4].status === "fulfilled") setSkills(results[4].value);
    if (results[5].status === "fulfilled") setActivity(results[5].value);
    const requestsResult = results[6];
    const privateFieldsResult = results[7];
    const teachingsResult = results[8];
    if (requestsResult.status === "fulfilled" && selectedId) setRequests((current) => ({ ...current, [selectedId]: requestsResult.value }));
    if (privateFieldsResult.status === "fulfilled") setPrivateFields((current) => ({ ...current, [agentId]: privateFieldsResult.value }));
    if (teachingsResult.status === "fulfilled") setTeachings((current) => ({ ...current, [agentId]: teachingsResult.value }));
    const failed = results.map((result,index) => result.status === "rejected" ? ["routines","computer","memory","files","skills","activity","requests","private fields","teachings"][index] : null).filter(Boolean);
    if (failed.length && ownerKey) setScopedError(ownerKey, `Could not load ${failed.join(", ")}. Please try again.`);
  }, [selectedId, setScopedError]);

  const selectChat = useCallback(async (conversationId: string, agentIdOverride?: string): Promise<void> => {
    if (!conversationId) return;
    selectedRef.current = conversationId; stickToBottomRef.current = true; setSelectedId(conversationId); setMobileInbox(false); setResourceMode("chat"); setDetailsOpen(false); setScopedError(conversationId, null); setRoutines([]); setDesktop(null); setMemory([]); setFiles([]); setSkills([]); setActivity([]); setReplyIds((current) => ({ ...current, [conversationId]: undefined }));
    try { window.localStorage.setItem("hermes-selected-chat", conversationId); } catch { /* Optional storage. */ }
    setMessagesLoading(true);
    const entry = entries.find((item) => item.conversation_id === conversationId);
    const historyPromise = listMessages(conversationId).then((value) => { if (selectedRef.current !== conversationId) return; setMessages((current) => ({ ...current, [conversationId]: value })); historyCursors.current[conversationId] = value[0]?.id ?? ""; setHistoryExhausted(current => ({ ...current, [conversationId]: value.length < 100 })); const latest = value.at(-1); if (latest) void markConversationRead(conversationId, latest.id).catch(() => undefined); }).catch((reason) => { if (selectedRef.current === conversationId) setScopedError(conversationId, errorText(reason)); });
    const tasksPromise = conversationTasks(conversationId).then((related) => { if (selectedRef.current !== conversationId) return; reconcileConversationTasks(conversationId, related); related.filter((task) => ACTIVE_STATUSES.has(task.status)).forEach((task) => attachTask({ ...task, id: task.id, conversation_id: task.conversation_id || conversationId, origin_conversation_id: task.origin_conversation_id ?? conversationId }, conversationId, task.agent_id ?? undefined, task.request_id ?? undefined)); }).catch(() => undefined);
    await Promise.all([historyPromise, tasksPromise, loadSelectedResources(agentIdOverride ?? entryAgent(entry ?? { conversation_id: "", kind: "direct", name: "", members: [], agent_id: null }, agents)?.id, conversationId)]);
    if (selectedRef.current === conversationId) setMessagesLoading(false);
  }, [agents, attachTask, entries, loadSelectedResources, reconcileConversationTasks, setScopedError]);

  useEffect(() => {
    if (!selectedId || selectedId.startsWith("agent:")) {
      const entry = selectedId ? entries.find((item) => inboxKey(item) === selectedId) : undefined;
      if (entry) void loadSelectedResources(entryAgent(entry, agents)?.id, selectedId);
      return;
    }
    if (selectedRef.current !== selectedId) return;
    let active = true;
    setMessagesLoading(true);
    void loadSelectedResources(selectedAgent?.id, selectedId);
    void listMessages(selectedId).then((value) => { if (active && selectedRef.current === selectedId) { setMessages((current) => ({ ...current, [selectedId]: value })); historyCursors.current[selectedId] = value[0]?.id ?? ""; setHistoryExhausted(current => ({ ...current, [selectedId]: value.length < 100 })); } }).catch((reason) => { if (active && selectedRef.current === selectedId) setScopedError(selectedId, errorText(reason)); }).finally(() => { if (active && selectedRef.current === selectedId) setMessagesLoading(false); });
    return () => { active = false; };
  }, [loadSelectedResources, selectedAgent?.id, selectedId, setScopedError]);

  useEffect(() => {
    if (!selectedId || !activeTasks.length) { if (!submittingRef.current) setStopping(false); return; }
    const owner = selectedId;
    let reading = false;
    const timer = window.setInterval(() => {
      if (reading || document.hidden) return;
      reading = true;
      void conversationTasks(owner).then(related => {
        if (selectedRef.current !== owner) return;
        reconcileConversationTasks(owner, related.filter(task => !ACTIVE_STATUSES.has(task.status)));
        if (!related.some(task => ACTIVE_STATUSES.has(task.status))) {
          setStopping(false); void refreshConversation(owner); void refreshInbox();
        }
      }).catch(() => undefined).finally(() => { reading = false; });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [selectedId, activeTasks.length, reconcileConversationTasks, refreshConversation, refreshInbox]);

  useEffect(() => {
    if (!selectedId || selectedId.startsWith("agent:") || resourceMode !== "chat") return;
    const owner = selectedId;
    const refreshRequests = () => { void refreshConversationRequests(owner); };
    refreshRequests();
    const timer = window.setInterval(refreshRequests, 5000);
    const onVisibility = () => { if (!document.hidden) refreshRequests(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [refreshConversationRequests, resourceMode, selectedId]);

  useEffect(() => {
    if (!query.trim()) { setSearchMatches([]); setSearchBusy(false); return; }
    let active = true;
    const timer = window.setTimeout(() => { setSearchBusy(true); void searchWorkspace(query).then(value => { if (active) setSearchMatches(value); }).catch(() => { if (active) setSearchMatches([]); }).finally(() => { if (active) setSearchBusy(false); }); }, 240);
    return () => { active = false; window.clearTimeout(timer); };
  }, [query]);

  useEffect(() => {
    if (!selectedAgent?.id) return;
    const ownerKey = selectedRef.current;
    const timer = window.setInterval(() => {
      if (!detailsOpen || document.hidden || desktop?.phase !== "running") return;
      void sendDesktopHeartbeat(selectedAgent.id, desktop.generation).then((heartbeat) => {
        if (selectedRef.current !== ownerKey) return;
        setDesktop((current) => current ? { ...current, ...heartbeat, available: heartbeat.available ?? current.available, created: heartbeat.created ?? current.created, running: heartbeat.running ?? current.running, view_url: heartbeat.view_url ?? current.view_url, reason: heartbeat.reason ?? current.reason } : heartbeat);
      }).catch(() => undefined);
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [detailsOpen, desktop, selectedAgent?.id]);

  useEffect(() => {
    if (!detailsOpen || !selectedAgent?.id || desktop?.phase !== "running") return;
    const id = selectedAgent.id, generation = desktop.generation;
    return () => { void sendDesktopHeartbeat(id, generation, false).catch(() => undefined); };
  }, [detailsOpen, selectedAgent?.id, desktop?.phase, desktop?.generation]);

  useEffect(() => {
    const node = transcriptRef.current;
    if (!node || messagesLoading) return;
    if (scrollTarget) {
      const target = [...node.querySelectorAll<HTMLElement>("[data-message-id]")].find((item) => item.dataset.messageId === scrollTarget);
      if (target) target.scrollIntoView({ block: "center", behavior: "smooth" });
      setScrollTarget(undefined);
      return;
    }
    if (stickToBottomRef.current) node.scrollTop = node.scrollHeight;
  }, [messagesLoading, scrollTarget, selectedId, selectedMessages.length, selectedTasks]);

  const loadEarlier = async () => {
    if (!selectedId || !selectedMessages.length || historyLoading) return;
    const owner = selectedId;
    const node = transcriptRef.current;
    const previousHeight = node?.scrollHeight ?? 0;
    const previousTop = node?.scrollTop ?? 0;
    stickToBottomRef.current = false; setHistoryLoading(true);
    try {
      const earlier = await listMessages(owner, historyCursors.current[owner] || selectedMessages[0].id);
      if (selectedRef.current !== owner) return;
      if (earlier[0]) historyCursors.current[owner] = earlier[0].id;
      setHistoryExhausted(current => ({ ...current, [owner]: earlier.length < 100 }));
      setMessages(current => ({ ...current, [owner]: mergeMessages(earlier, current[owner] ?? []) }));
      requestAnimationFrame(() => { if (node && selectedRef.current === owner) node.scrollTop = previousTop + node.scrollHeight - previousHeight; });
    } catch (reason) { setScopedError(owner, errorText(reason)); }
    finally { setHistoryLoading(false); }
  };
  const chooseSearch = async (match: { conversation_id?: string | null; message_id?: string | null }) => {
    if (!match.conversation_id) return;
    const owner = match.conversation_id;
    await selectChat(owner);
    if (match.message_id) {
      try {
        const exact = await getExactMessage(match.message_id);
        if (selectedRef.current !== owner) return;
        stickToBottomRef.current = false;
        setMessages(current => ({ ...current, [owner]: mergeMessages([exact], current[owner] ?? []) }));
        setScrollTarget(exact.id);
      } catch (reason) { setScopedError(owner, errorText(reason)); }
    }
    setQuery("");
  };
  const updateSelectedGroup = async (change: { pinned?: boolean; archived?: boolean }) => {
    if (!selectedEntry) return;
    try {
      if (selectedEntry.kind === "group") await updateGroup(selectedEntry.conversation_id, change);
      else await updateConversationState(selectedEntry.conversation_id, change);
      setEntries((current) => current.map((entry) => entry.conversation_id === selectedEntry.conversation_id ? { ...entry, ...change } : entry));
      setChatMenuOpen(false);
      if (change.archived) { setSelectedId(undefined); setMobileInbox(true); }
    } catch (reason) { setScopedError(selectedEntry.conversation_id, errorText(reason)); }
  };

  const handleSend = async (attemptOverride?: DraftAttempt): Promise<void> => {
    if (submittingRef.current || uploadingRef.current) return;
    const entry = selectedEntry;
    const agent = selectedAgent;
    if (!agent || activeTasks.length || !entry && !agent) return;
    const sourceKey = draftKey;
    const sourceOwnerKey = selectedRef.current;
    const selectedAttachmentItems = attemptOverride?.fileAssets ?? selectedAttachments;
    const selectedFiles = attemptOverride?.fileIds ?? selectedAttachmentItems.map((file) => file.id);
    const selectedMentions = attemptOverride?.mentionAgentIds ?? selectedMentionIds;
    const selectedReply = attemptOverride?.replyToId ?? replyIds[sourceKey];
    const rawContent = attemptOverride?.content ?? draft;
    const content = rawContent.trim() || (selectedFiles.length ? "Please review the attached file(s)" : "");
    if (!content && !selectedFiles.length) return;
    const key = attemptOverride?.clientRequestId ?? makeLocalId("request");
    let conversationId = attemptOverride?.conversationId ?? entry?.conversation_id ?? "";
    let attempt: DraftAttempt = { conversationId, agentId: agent.id, content, fileIds: selectedFiles, fileAssets: selectedAttachmentItems, mentionAgentIds: selectedMentions, replyToId: selectedReply, clientRequestId: key };
    let optimistic: Message | null = null;
    const restoreDraft = (restoreKey: string, canonicalKey?: string) => {
      setDrafts((current) => ({ ...current, [restoreKey]: content, ...(canonicalKey && canonicalKey !== restoreKey ? { [canonicalKey]: content } : {}) }));
      setAttachments((current) => ({ ...current, [restoreKey]: selectedAttachmentItems, ...(canonicalKey && canonicalKey !== restoreKey ? { [canonicalKey]: selectedAttachmentItems } : {}) }));
      setMentionIds((current) => ({ ...current, [restoreKey]: selectedMentions, ...(canonicalKey && canonicalKey !== restoreKey ? { [canonicalKey]: selectedMentions } : {}) }));
      setReplyIds((current) => ({ ...current, [restoreKey]: selectedReply, ...(canonicalKey && canonicalKey !== restoreKey ? { [canonicalKey]: selectedReply } : {}) }));
    };
    submittingRef.current = true;
    setSubmitting(true);
    setSubmittingKey(sourceKey);
    setStopping(false);
    pendingSubmitRef.current = { attempt, sourceKey, stopRequested: false, cancelIssued: false };
    try {
      if (!conversationId) {
        const home = await getAgentHome(agent.id).catch(() => null);
        const conversation = home ?? await createConversation(agent.id, content.slice(0, 48));
        conversationId = conversation.id;
        attempt = { ...attempt, conversationId };
        const nextEntry = directEntry(agent, conversation);
        setEntries((current) => [nextEntry, ...current.filter((item) => item.agent_id !== agent.id)]);
        setSubmittingKey(conversationId);
        if (selectedRef.current === sourceOwnerKey) {
          selectedRef.current = conversationId;
          setSelectedId(conversationId);
          setMobileInbox(false);
        }
      }
      pendingSubmitRef.current = { ...(pendingSubmitRef.current as { attempt: DraftAttempt; sourceKey: string; stopRequested: boolean; cancelIssued: boolean }), attempt };
      const pending = pendingSubmitRef.current;
      setScopedError(conversationId, null);
      setLastAttempts((current) => ({ ...current, [conversationId]: attempt }));
      if (pending?.stopRequested) {
        restoreDraft(sourceKey, conversationId);
        return;
      }
      optimistic = { id: `local-${key}`, conversation_id: conversationId, role: "user", content, created_at: new Date().toISOString(), status: "complete", request_id: key, reply_to_id: selectedReply };
      setMessages((current) => ({ ...current, [conversationId]: [...(current[conversationId] ?? []).filter((message) => message.id !== optimistic?.id), optimistic!] }));
      setDrafts((current) => ({ ...current, [sourceKey]: "", ...(conversationId !== sourceKey ? { [conversationId]: "" } : {}) }));
      setAttachments((current) => ({ ...current, [sourceKey]: [], ...(conversationId !== sourceKey ? { [conversationId]: [] } : {}) }));
      setMentionIds((current) => ({ ...current, [sourceKey]: [], ...(conversationId !== sourceKey ? { [conversationId]: [] } : {}) }));
      setReplyIds((current) => ({ ...current, [sourceKey]: undefined, ...(conversationId !== sourceKey ? { [conversationId]: undefined } : {}) }));
      const result = await sendConversationMessage(conversationId, { content, file_ids: selectedFiles, mention_agent_ids: selectedMentions, reply_to_id: selectedReply, client_request_id: key });
      const activePending = pendingSubmitRef.current;
      if (activePending) activePending.requestId = result.request_id;
      const resultTasks = result.tasks.length ? result.tasks : result.task ? [result.task] : [];
      if (activePending?.stopRequested) {
        let cancelled = Boolean(activePending.cancelIssued);
        if (!activePending.cancelIssued) {
          try {
            await cancelConversationRequest(conversationId, result.request_id);
            activePending.cancelIssued = true;
            cancelled = true;
          } catch (reason) {
            setScopedError(conversationId, `Could not stop this work: ${errorText(reason)} The run is still visible below.`);
          }
        }
        if (!cancelled) {
          if (result.message) setMessages((current) => ({ ...current, [conversationId]: [...(current[conversationId] ?? []).filter((message) => message.id !== optimistic?.id && message.id !== result.message?.id), result.message!] }));
          resultTasks.forEach((task) => attachTask(task, conversationId, task.agent_id ?? agent.id, result.request_id));
          setLastAttempts((current) => ({ ...current, [conversationId]: null, ...(sourceKey !== conversationId ? { [sourceKey]: null } : {}) }));
          setEntries((current) => current.map((item) => item.conversation_id === conversationId ? { ...item, preview: content, updated_at: new Date().toISOString(), unread_count: 0, active_tasks: resultTasks.map((task) => ({ id: task.id, agent_id: task.agent_id, request_id: result.request_id, status: task.status })) } : item));
          return;
        }
        setMessages((current) => ({ ...current, [conversationId]: (current[conversationId] ?? []).filter((message) => message.id !== optimistic?.id) }));
        restoreDraft(sourceKey, conversationId);
        setLastAttempts((current) => ({ ...current, [conversationId]: attempt }));
        setEntries((current) => current.map((item) => item.conversation_id === conversationId ? { ...item, active_tasks: [] } : item));
        return;
      }
      if (result.message) setMessages((current) => ({ ...current, [conversationId]: [...(current[conversationId] ?? []).filter((message) => message.id !== optimistic?.id && message.id !== result.message?.id), result.message!] }));
      resultTasks.forEach((task) => attachTask(task, conversationId, task.agent_id ?? agent.id, result.request_id));
      setLastAttempts((current) => ({ ...current, [conversationId]: null, ...(sourceKey !== conversationId ? { [sourceKey]: null } : {}) }));
      setScopedError(conversationId, null);
      setEntries((current) => current.map((item) => item.conversation_id === conversationId ? { ...item, preview: content, updated_at: new Date().toISOString(), unread_count: 0, active_tasks: resultTasks.map((task) => ({ id: task.id, agent_id: task.agent_id, request_id: result.request_id, status: task.status })) } : item));
    } catch (reason) {
      const currentPending = pendingSubmitRef.current;
      const stopped = Boolean(currentPending?.stopRequested);
      const errorKey = conversationId || sourceKey;
      if (!stopped) { setScopedError(errorKey, errorText(reason)); setLastAttempts((current) => ({ ...current, [errorKey]: attempt })); }
      if (conversationId && optimistic) setMessages((current) => ({ ...current, [conversationId]: (current[conversationId] ?? []).filter((message) => message.id !== optimistic?.id) }));
      restoreDraft(sourceKey, conversationId || undefined);
    } finally {
      if (pendingSubmitRef.current?.attempt.clientRequestId === key) pendingSubmitRef.current = null;
      submittingRef.current = false;
      setSubmitting(false);
      setSubmittingKey(undefined);
      setStopping(false);
    }
  };

  const stopWork = async (): Promise<void> => {
    const pending = pendingSubmitRef.current;
    if (pending) {
      pending.stopRequested = true;
      setStopping(true);
      if (pending.requestId && pending.attempt.conversationId && !pending.cancelIssued) {
        try {
          await cancelConversationRequest(pending.attempt.conversationId, pending.requestId);
          pending.cancelIssued = true;
        } catch (reason) {
          setScopedError(pending.attempt.conversationId, `Could not stop this work: ${errorText(reason)}`);
        }
      }
      if (!activeTasks.length) return;
    }
    if (!selectedId || !activeTasks.length) return;
    setStopping(true); setScopedError(selectedId, null);
    const requestPairs = [...new Map(activeTasks.filter((task) => task.request_id).map((task) => [task.request_id!, task.conversation_id])).entries()];
    try {
      if (requestPairs.length) await Promise.all(requestPairs.map(([requestId, conversationId]) => cancelConversationRequest(conversationId, requestId)));
      else await Promise.all(activeTasks.map((task) => cancelTask(task.id)));
      activeTasks.forEach((task) => { setTask(task.id, (current) => ({ ...current, status: "cancelled", terminal: true, stopRequested: false, progress: "Run stopped", approval: undefined, image: current.image?.status === "generating" ? { ...current.image, status: "cancelled", message: "Stopped waiting for the image. The provider may still finish this request." } : current.image })); taskControllers.current.get(task.id)?.abort(); });
      setEntries((current) => current.map((entry) => entry.conversation_id === selectedId ? { ...entry, active_tasks: [] } : entry));
    } catch (reason) { setScopedError(selectedId, `Could not stop this work: ${errorText(reason)}`); } finally { if (!pending) setStopping(false); }
  };

  const approve = async (task: TaskState, decision: "accept" | "decline") => { if (!task.approval) return; try { await respondToApproval(task.id, task.approval.approval_id, decision); setTask(task.id, (current) => ({ ...current, approval: undefined, progress: decision === "accept" ? "Continuing" : "Declined" })); } catch (reason) { setScopedError(task.conversation_id, errorText(reason)); } };

  const attachFile = async (event: ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; event.target.value = ""; if (!file || !selectedAgent || uploadingRef.current) return; uploadingRef.current = true; setUploading(true); setScopedError(draftKey, null); try { const uploaded = await uploadFile(file, selectedAgent.id); setAttachments((current) => ({ ...current, [draftKey]: [...(current[draftKey] ?? []), uploaded] })); } catch (reason) { setScopedError(draftKey, errorText(reason)); } finally { uploadingRef.current = false; setUploading(false); } };

  const createBot = async (input: AgentInput) => { const agent = await createAgent(input); setAgents((current) => [agent, ...current]); const entry = directEntry(agent); setEntries((current) => [entry, ...current]); const key = inboxKey(entry); selectedRef.current = key; setSelectedId(key); setNewBotOpen(false); setMobileInbox(false); setResourceMode("chat"); };
  const createGroupChat = async (name: string, ids: string[], coordinatorId: string) => { const conversation = await createGroup(name, ids, coordinatorId); const members = ids.map((id) => agents.find((agent) => agent.id === id)).filter((agent): agent is Agent => Boolean(agent)).map((agent) => ({ agent_id: agent.id, name: agent.name, role: agent.id === coordinatorId ? "coordinator" : "member", avatar: agent.avatar, avatar_url: agent.avatar_url, color: agent.color })); const entry: InboxEntry = { conversation_id: conversation.id, kind: "group", agent_id: coordinatorId, coordinator_id: coordinatorId, name, members, preview: "New group chat", updated_at: new Date().toISOString(), unread_count: 0, pinned: false, archived: false, active_tasks: [] }; setEntries((current) => [entry, ...current]); setSelectedId(conversation.id); selectedRef.current = conversation.id; setMobileInbox(false); setNewGroupOpen(false); await selectChat(conversation.id, coordinatorId); };
  const refreshRoutines = () => { const owner = selectedId; if (selectedAgent?.id) void listRoutines(selectedAgent.id).then(value => { if (selectedRef.current === owner) setRoutines(value); }).catch(reason => { if (owner) setScopedError(owner, errorText(reason)); }); };
  const addMemory = async (content: string, scope: "shared" | "private") => { const owner = selectedId; const item = await createMemory({ content: content.trim(), scope, agent_id: scope === "private" ? selectedAgent?.id : undefined }); if (selectedRef.current === owner) setMemory((current) => [item, ...current]); };
  const removeMemory = async (id: string, agentId?: string) => { await deleteMemory(id, agentId); setMemory((current) => current.filter((item) => item.id !== id)); };
  const removeFile = async (id: string) => { await deleteFile(id); setFiles((current) => current.filter((file) => file.id !== id)); };
  const toggleSkill = async (id: string, enabled: boolean) => { if (!selectedAgent) return; const updated = await setSkillEnabled(selectedAgent.id, id, enabled); if (updated) setSkills((current) => current.map((skill) => skill.id === id ? updated : skill)); };

  const updateRequest = (next: ChatRequest) => setRequests((current) => ({ ...current, [next.conversation_id]: (current[next.conversation_id] ?? []).map((item) => item.id === next.id ? next : item) }));
  const openPrivateInput = (request?: ChatRequest) => { setPrivateRequest(request ?? null); setExpansionSheet("private"); };
  const openConnection = (request?: ChatRequest) => { setConnectionRequest(request ?? null); setExpansionSheet("connections"); };
  const openTeaching = (teaching: Teaching | null = null) => { setTeachingEdit(teaching); setExpansionSheet("teach"); };
  const openDictation = () => { setDictationTarget({ key: draftKey, draft }); };
  const handleExpansionAction = (action: ExpansionAction) => {
    if (action.id === "dictate") openDictation();
    if (action.id === "private") openPrivateInput();
    if (action.id === "connections") openConnection();
    if (action.id === "teach") openTeaching();
    if (action.id === "computer") setDetailsOpen(true);
    if (action.id === "settings") { setResourceMode("settings"); setMobileInbox(false); }
    if (action.id === "procedure" && action.teachingId) { const item = selectedTeachings.find((teaching) => teaching.id === action.teachingId); if (item) setTeachingRun(item); }
  };
  const handleRequestDecision = async (request: ChatRequest, decision: "approve" | "deny") => {
    try { updateRequest(await decideRequest(request.id, decision)); }
    catch (reason) { setScopedError(request.conversation_id, errorText(reason)); }
  };
  const continueRequestFlow = async (request: ChatRequest): Promise<void> => {
    try {
      const result = await continueRequest(request.id);
      const conversationId = result.conversation?.id || request.conversation_id;
      updateRequest({ ...request, status: "executing" });
      await selectChat(conversationId, request.agent_id);
      if (result.message) setMessages((current) => ({ ...current, [conversationId]: mergeMessages(current[conversationId] ?? [], [result.message!]) }));
      result.tasks.forEach((task) => attachTask(task, conversationId, request.agent_id, result.request_id));
    } catch (reason) { setScopedError(request.conversation_id, errorText(reason)); }
  };
  const handlePrivateSaved = (updated?: ChatRequest, field?: PrivateField) => {
    if (updated) updateRequest(updated);
    if (field && selectedAgent?.id) setPrivateFields((current) => ({ ...current, [selectedAgent.id]: [field, ...(current[selectedAgent.id] ?? [])] }));
  };
  const handleTeachingSaved = (updated: Teaching) => setTeachings((current) => ({ ...current, [updated.agent_id]: [...(current[updated.agent_id] ?? []).filter((item) => item.id !== updated.id), updated] }));
  const handleTeachingChanged = (updated: Teaching[]) => { if (selectedAgent?.id) setTeachings((current) => ({ ...current, [selectedAgent.id]: updated })); };
  const runTeachingFlow = async (teaching: Teaching, input: string): Promise<void> => {
    const result = await runTeaching(teaching.agent_id, teaching.id, input, makeLocalId("teaching"));
    const conversationId = result.conversation?.id || selectedId;
    if (!conversationId) throw new Error("The procedure did not return a conversation.");
    setResourceMode("chat"); setMobileInbox(false); selectedRef.current = conversationId; setSelectedId(conversationId);
    if (result.message) setMessages((current) => ({ ...current, [conversationId]: mergeMessages(current[conversationId] ?? [], [result.message!]) }));
    result.tasks.forEach((task) => attachTask(task, conversationId, teaching.agent_id, result.request_id));
  };
  const handleVoiceInsert = (targetKey: string, text: string, mode: "replace" | "append") => setDrafts((current) => {
    const existing = current[targetKey] ?? "";
    const next = mode === "replace" ? text : existing.trim() ? `${existing.trim()} ${text}` : text;
    return { ...current, [targetKey]: next };
  });

  const renderTranscript = () => {
    const orderedTasks = selectedTasks.filter((task) => (ACTIVE_STATUSES.has(task.status ?? "") || task.text || task.approval || task.status === "failed" || task.status === "cancelled") && (!selectedMessages.some((message) => message.source_task_id === task.id) || task.status === "failed" || task.status === "cancelled"));
    return <div ref={transcriptRef} className="grok-transcript" role="log" aria-live="off" onScroll={(event) => { const node = event.currentTarget; stickToBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80; }}>{selectedMessages.length && !historyExhausted[selectedId ?? ""] ? <button className="grok-button grok-button-quiet grok-earlier" type="button" disabled={historyLoading} onClick={() => void loadEarlier()}>{historyLoading ? "Loading…" : "Load earlier messages"}</button> : null}{selectedMessages.length ? <div className="grok-date-divider">{formatDate(selectedMessages[0].created_at) || "Today"}</div> : null}{messagesLoading ? <div className="grok-loading-line"><Loader2 size={16} className="grok-spin" /> Loading this chat</div> : null}{selectedMessages.map((message) => <Bubble key={message.id} message={message} entry={selectedEntry!} agents={agents} accountId={accountId} onReply={(item) => setReplyIds((current) => ({ ...current, [draftKey]: item.id }))} onCopy={async (item) => { if (!navigator.clipboard) throw new Error("Clipboard unavailable"); await navigator.clipboard.writeText(item.content); }} />)}{orderedTasks.map((task) => <div className="grok-live-task" key={task.id}><div className="grok-message-author"><MessageAuthor message={{ id: task.id, conversation_id: task.conversation_id, role: "assistant", content: task.text }} task={task} agents={agents} entry={selectedEntry!} /><span>{agents.find((agent) => agent.id === task.agent_id)?.name ?? selectedEntry?.name ?? "Assistant"}</span></div>{task.image ? <ImageGenerationCard state={task.image} /> : null}{task.text && !selectedMessages.some(message => message.source_task_id === task.id) ? <div className="grok-message-line"><div className="grok-message-bubble"><MessageContent content={task.text} /></div></div> : null}<div className={`grok-working-line ${task.status === "failed" ? "is-error" : task.status === "cancelled" ? "is-cancelled" : ""}`}><AgentAvatar agent={agents.find((agent) => agent.id === task.agent_id) ?? selectedAgent} size="small" status={taskAvatarStatus(task)} statusLabel={taskStatusLabel(task)} /><span>{taskStatusLabel(task)}</span>{task.error_message ? <small>{task.error_message}</small> : null}</div>{task.status === "failed" ? <button type="button" className="grok-button grok-button-quiet" onClick={() => {
        const previous = lastAttempts[task.conversation_id];
        if (previous && previous.clientRequestId === task.request_id) { setDrafts(current => ({ ...current, [draftKey]: previous.content })); setAttachments(current => ({ ...current, [draftKey]: previous.fileAssets })); setMentionIds(current => ({ ...current, [draftKey]: previous.mentionAgentIds })); }
        else { const request = selectedMessages.find(message => message.role === "user" && message.request_id === task.request_id); if (request) setDrafts(current => ({ ...current, [draftKey]: request.content })); }
      }}>Edit and retry</button> : null}<ApprovalBox task={task} onApprove={(item) => void approve(item, "accept")} onDeny={(item) => void approve(item, "decline")} /></div>)}{selectedRequests.length ? <section className="grok-request-tray" aria-label="Requests needing your attention">{selectedRequests.map((request) => <RequestCard key={request.id} request={request} accountId={accountId} agentName={selectedEntry?.name} onPrivate={openPrivateInput} onConnection={openConnection} onDecision={(item, decision) => void handleRequestDecision(item, decision)} onContinue={(item) => void continueRequestFlow(item)} />)}</section> : null}</div>;
  };

  const selectInbox = (id: string) => {
    if (!id) return;
    if (id.startsWith("agent:")) {
      selectedRef.current = id; setSelectedId(id); setMobileInbox(false); setResourceMode("chat"); setDetailsOpen(false); setScopedError(id, null); setRoutines([]); setDesktop(null); setMemory([]); setFiles([]); setSkills([]); setActivity([]);
      try { window.localStorage.setItem("hermes-selected-chat", id); } catch { /* Optional storage. */ }
      return;
    }
    void selectChat(id);
  };
  const currentMode = resourceMode === "chat" ? "chat" : resourceMode;
  if (loading) return <div className="grok-loading-screen"><BotGlyph color="#2d93fa" size={48} /><Loader2 size={18} className="grok-spin" /><span>Loading your Bots…</span></div>;
  return <div className={`grok-app ${detailsOpen && currentMode === "chat" ? "has-details" : ""} ${mobileInbox ? "mobile-inbox" : "mobile-chat"}`}>
    <Inbox entries={entries} agents={agents} selectedId={selectedId} query={query} onQuery={setQuery} onSelect={selectInbox} onNew={() => setNewBotOpen(true)} onNewGroup={() => setNewGroupOpen(true)} onSettings={() => { setResourceMode("settings"); setMobileInbox(false); }} userName={userName} connection={connection} />
    <main className="grok-main">
      {currentMode !== "chat" ? <ResourcePage key={`${selectedId}:${currentMode}`} resourceError={streamError} onReload={() => { setScopedError(draftKey, null); void loadSelectedResources(selectedAgent?.id, selectedId); }} mode={currentMode} agent={selectedAgent} theme={theme} onThemeChange={onThemeChange} memory={memory} files={files} activity={activity} skills={skills} runtime={runtime} account={runtimeAccount} usage={runtimeUsage} userName={userName} extensionsStatus={extensionsStatus} privateFields={selectedPrivateFields} teachings={selectedTeachings} accountId={accountId} onOpenConnection={() => openConnection()} onOpenPrivate={() => openPrivateInput()} onOpenTeaching={() => openTeaching()} onPrivateFieldsChanged={(fields) => { if (selectedAgent?.id) setPrivateFields((current) => ({ ...current, [selectedAgent.id]: fields })); }} onTeachingsChanged={handleTeachingChanged} onEditTeaching={(item) => { setTeachingEdit(item); setExpansionSheet("teach"); }} onRunTeaching={(item) => setTeachingRun(item)} onAddMemory={addMemory} onDeleteMemory={removeMemory} onDeleteFile={removeFile} onToggleSkill={toggleSkill} onAgentSaved={(updated) => { setAgents(current => current.map(item => item.id === updated.id ? updated : item)); void refreshInbox(); }} onAccountChange={(updated) => { setRuntimeAccount(updated); void getRuntimeStatus().then(setRuntime).catch(() => undefined); }} onBack={() => setResourceMode("chat")} onLogout={onLogout} logoutError={logoutError} /> : <>
        <header className="grok-chat-header"><button className="grok-chat-back grok-icon-button" type="button" aria-label="Back to inbox" onClick={() => setMobileInbox(true)}><ArrowLeft size={19} /></button>{selectedEntry ? <Identity entry={selectedEntry} agents={agents} size="small" status={activeTasks.length ? taskAvatarStatus(activeTasks[0]) : "idle"} /> : <BotGlyph color="#2d93fa" size={27} />}<div className="grok-chat-title"><h1>{selectedEntry?.name ?? "Your Bots"}</h1>{selectedEntry?.kind === "group" ? <p>{entryMembers(selectedEntry, agents).map((member) => member.name).join(", ")}</p> : null}</div><div className="grok-chat-actions"><button className="grok-icon-button" type="button" aria-label="Toggle details" title="Details" onClick={() => setDetailsOpen((open) => !open)}><PanelRight size={18} /></button><button className="grok-icon-button" type="button" aria-label="Chat options" title="Chat options" onClick={() => setChatMenuOpen((open) => !open)}><MoreHorizontal size={18} /></button>{chatMenuOpen && selectedEntry ? <div className="grok-chat-menu">{selectedEntry.kind !== "group" ? <button type="button" onClick={() => { setResourceMode("settings"); setChatMenuOpen(false); }}><Settings size={16} /> Bot settings</button> : null}<button type="button" onClick={() => void updateSelectedGroup({ pinned: !selectedEntry.pinned })}><Pin size={14} /> {selectedEntry.pinned ? "Unpin chat" : "Pin chat"}</button>{!selectedEntry.archived ? <button type="button" onClick={() => void updateSelectedGroup({ archived: true })}><Archive size={14} /> Archive chat</button> : null}</div> : null}</div></header>
        {workspaceError || streamError && !selectedEntry ? <div className="grok-banner" role="alert"><WifiOff size={15} /><span>{workspaceError ?? streamError}</span><button type="button" onClick={() => void loadWorkspace()}><RefreshCw size={14} /> Retry</button></div> : null}
        {!selectedEntry ? <div className="grok-empty-chat"><BotGlyph color="#2d93fa" size={78} /><h2>{agents.length ? "Choose a Bot" : "Your first Bot"}</h2><p>{agents.length ? "Pick a chat from the inbox, or create a group." : "Give it a name and a clear job to get started."}</p><div><button className="grok-button grok-button-dark" type="button" onClick={() => setNewBotOpen(true)}><Plus size={15} /> New Bot</button>{agents.length > 1 ? <button className="grok-button grok-button-quiet" type="button" onClick={() => setNewGroupOpen(true)}><Users size={15} /> New group</button> : null}</div></div> : <>{selectedEntry.archived ? <div className="grok-banner"><span>This chat is archived.</span><button type="button" onClick={() => void updateSelectedGroup({ archived: false })}>Restore chat</button></div> : null}{renderTranscript()}<Composer entry={selectedEntry} agents={agents} draft={draft} onDraft={(value) => setDrafts((current) => ({ ...current, [draftKey]: value }))} onSend={() => void handleSend()} onStop={() => void stopWork()} isSending={activeTasks.length > 0 || currentSubmission} isStopping={stopping && (currentSubmission || activeTasks.length > 0)} attachments={selectedAttachments} onAttach={(event) => void attachFile(event)} onRemoveAttachment={(id) => setAttachments((current) => ({ ...current, [draftKey]: (current[draftKey] ?? []).filter((file) => file.id !== id) }))} uploading={uploading} mentionIds={selectedMentionIds} onMentionIds={(ids) => setMentionIds((current) => ({ ...current, [draftKey]: ids }))} replyTo={replyTo} onClearReply={() => setReplyIds((current) => ({ ...current, [draftKey]: undefined }))} error={streamError} onRetry={() => { if (lastAttempt && lastAttempt.conversationId === selectedId) void handleSend(lastAttempt); }} actions={actionItems(extensionsStatus, selectedTeachings, skills)} onAction={handleExpansionAction} /></>}
      </>}
    </main>
    {currentMode === "chat" && detailsOpen ? <DetailsPanel entry={selectedEntry} agents={agents} routines={routines} desktop={desktop} accountId={accountId} onClose={() => setDetailsOpen(false)} onRoutinesRefresh={refreshRoutines} onTask={(task) => attachTask(task, selectedId, selectedAgent?.id)} onDesktopChange={(value) => { if (selectedRef.current === selectedId) setDesktop(value); }} memoryCount={memory.length} fileCount={files.length} onResource={(mode) => setResourceMode(mode)} /> : null}
    <ConnectionSheet open={expansionSheet === "connections"} status={extensionsStatus} initialToolkit={connectionRequest && typeof connectionRequest.data.toolkit === "string" ? connectionRequest.data.toolkit : undefined} onClose={() => { setExpansionSheet(null); setConnectionRequest(null); }} onConnected={() => { if (selectedId) void listConversationRequests(selectedId).then((value) => setRequests((current) => ({ ...current, [selectedId]: value }))).catch(() => undefined); }} />
    <PrivateInputSheet open={expansionSheet === "private"} agentId={selectedAgent?.id} request={privateRequest} status={extensionsStatus} onClose={() => { setExpansionSheet(null); setPrivateRequest(null); }} onSaved={handlePrivateSaved} />
    <TeachingSheet open={expansionSheet === "teach"} agentId={teachingEdit?.agent_id ?? selectedAgent?.id} teaching={teachingEdit} onClose={() => { setExpansionSheet(null); setTeachingEdit(null); }} onSaved={handleTeachingSaved} />
    <TeachingRunDialog teaching={teachingRun} open={Boolean(teachingRun)} onClose={() => setTeachingRun(null)} onRun={runTeachingFlow} />
    {dictationTarget ? <VoiceDictation open targetKey={dictationTarget.key} draftSnapshot={dictationTarget.draft} currentDraft={drafts[dictationTarget.key] ?? dictationTarget.draft} status={extensionsStatus} onClose={() => setDictationTarget(null)} onInsert={handleVoiceInsert} /> : null}
    {newBotOpen ? <div className="grok-creator-layer"><BotCreator onClose={() => setNewBotOpen(false)} onCreate={createBot} /></div> : null}
    {newGroupOpen ? <GroupCreatorDialog agents={agents} onClose={() => setNewGroupOpen(false)} onCreate={createGroupChat} /> : null}
    {query && searchMatches.length ? <div className="grok-search-popover" role="listbox" aria-label="Search results">{searchMatches.slice(0, 8).map((match) => <button type="button" key={match.id} onClick={() => void chooseSearch(match)}><Search size={14} /><span><strong>{match.name ?? "Message"}</strong><small>{match.snippet ?? "Open result"}</small></span></button>)}</div> : searchBusy ? <div className="grok-search-popover is-loading"><Loader2 size={15} className="grok-spin" /> Searching…</div> : null}
  </div>;
}

