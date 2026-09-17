import {
  Activity,
  ArrowLeft,
  ArrowDownToLine,
  ArrowUp,
  AlertCircle,
  ArrowUpRight,
  Brain,
  Check,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  FileText,
  FolderOpen,
  Laptop,
  Link2,
  Loader2,
  LockKeyhole,
  LogOut,
  MessageCircle,
  Monitor,
  Moon,
  PanelRight,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Trash2,
  Upload,
  UserRound,
  Users,
  Wifi,
  WifiOff,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, KeyboardEvent } from "react";
import { AgentAvatar, BotGlyph } from "./components/BotIdentity";
import type { AvatarStatus } from "./components/BotIdentity";
import BotCreator from "./components/BotCreator";
import GrokWorkspace from "./components/GrokWorkspace";
import { conversationTasks, watchTask } from "./lib/taskStream";
import { MessageContent } from "./components/MessageContent";
import { ImageGenerationCard, type ImageGenerationState } from "./components/ImageGeneration";
import {
  ApiError,
  compactConversation,
  cancelTask,
  completeOnboarding,
  createDesktop,
  createAgent,
  createConversation,
  createMemory,
  deleteSkill,
  deleteFile,
  deleteMemory,
  exchangeTelegramNonce,
  getRuntimeAccount,
  getRuntimeStatus,
  getRuntimeUsage,
  getDesktopStatus,
  getOnboarding,
  getSession,
  listActivity,
  listAgents,
  listConversations,
  listFiles,
  listMessages,
  listMemory,
  listSkills,
  logout,
  respondToApproval,
  startRuntimeLogin,
  startDesktop,
  stopDesktop,
  streamMessage,
  setSkillEnabled,
  updateAgent,
  uploadFile,
} from "./lib/api";
import type {
  ActivityItem,
  Agent,
  AgentInput,
  Approval,
  Conversation,
  FileAsset,
  LearnedSkill,
  InfoTab,
  MemoryItem,
  Message,
  RuntimeAccount,
  RuntimeLogin,
  RuntimeStatus,
  RuntimeUsage,
  DesktopStatus,
  Session,
  StreamEvent,
  Theme,
  View,
} from "./lib/types";

const TELEGRAM_URL = "https://t\.me/your-bot?start=bot";
const ONBOARDING_KEY = "hermes-bot-mode-onboarding-v1";

type HermesIconName = "chat" | "overview" | "memory" | "files" | "activity" | "computer" | "settings";

const NAV_ITEMS: Array<{ id: View; label: string; icon: HermesIconName }> = [
  { id: "chat", label: "Chat", icon: "chat" },
  { id: "memory", label: "Memory", icon: "memory" },
  { id: "files", label: "Files", icon: "files" },
  { id: "activity", label: "Activity", icon: "activity" },
  { id: "settings", label: "Settings", icon: "settings" },
];

const INFO_TABS: Array<{ id: InfoTab; label: string; icon: HermesIconName }> = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "memory", label: "Memory", icon: "memory" },
  { id: "files", label: "Files", icon: "files" },
  { id: "activity", label: "Activity", icon: "activity" },
  { id: "computer", label: "Computer", icon: "computer" },
];

function HermesIcon({ name, size = 18, className }: { name: HermesIconName; size?: number; className?: string }): JSX.Element {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 2.15, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    {name === "chat" ? <><path {...common} d="M5.5 5.5h13a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7l-4.5 3v-3h-1.5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z" /><path {...common} d="M8 10.5h.01M12 10.5h.01M16 10.5h.01" strokeWidth="2.8" /></>
      : name === "overview" ? <><path {...common} d="M12 3.5c1.4 0 2.6.8 3.1 2 .2.5.7.8 1.2.8 1.5 0 2.7 1.2 2.7 2.7 0 .6-.2 1.1-.5 1.6.7.7 1.1 1.7 1.1 2.7 0 2.1-1.7 3.7-3.8 3.7H11l-2.7 2v-2.1c-1.7-.3-3-1.8-3-3.6 0-1 .4-2 1.1-2.7-.3-.5-.5-1-.5-1.6 0-1.5 1.2-2.7 2.7-2.7.5 0 1-.3 1.2-.8.5-1.2 1.7-2 3.1-2Z" /><path {...common} d="M9 11.5h.01M15 11.5h.01" strokeWidth="2.8" /></>
      : name === "memory" ? <><path {...common} d="M4.5 6.5c2.2-.9 4.4-.7 7.5.8v11c-3-1.5-5.3-1.7-7.5-.8v-11ZM19.5 6.5c-2.2-.9-4.4-.7-7.5.8v11c3-1.5 5.3-1.7 7.5-.8v-11Z" /><path {...common} d="M6.8 9.5c1.5-.3 2.8-.1 4.2.5M17.2 9.5c-1.5-.3-2.8-.1-4.2.5" /></>
      : name === "files" ? <><path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-9Z" fill="currentColor" opacity=".12" /><path {...common} d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-9Z" /><path {...common} d="M4.5 10h16" /></>
      : name === "activity" ? <><path {...common} d="M3.5 12h4l2-5 3 10 2-5h6" /><circle cx="3.5" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="20.5" cy="12" r="1" fill="currentColor" stroke="none" /></>
      : name === "computer" ? <><rect {...common} x="3.5" y="4.5" width="17" height="11.5" rx="2.3" /><path {...common} d="M8 19.5h8M12 16v3.5" /></>
      : <><path {...common} d="M5 7.5h14M5 12h14M5 16.5h14" /><circle cx="9" cy="7.5" r="1.8" fill="var(--canvas, currentColor)" stroke="currentColor" strokeWidth="2" /><circle cx="15" cy="12" r="1.8" fill="var(--canvas, currentColor)" stroke="currentColor" strokeWidth="2" /><circle cx="10" cy="16.5" r="1.8" fill="var(--canvas, currentColor)" stroke="currentColor" strokeWidth="2" /></>}
  </svg>;
}

function getStoredTheme(): Theme {
  try {
    const value = window.localStorage.getItem("hermes-theme");
    return value === "light" || value === "dark" || value === "system" ? value : "light";
  } catch {
    return "light";
  }
}

function isAuthenticated(session: Session | null): boolean {
  if (!session) return false;
  if (session.authenticated === false) return false;
  return Boolean(session.user ?? session.authenticated);
}

function getNonceFromHash(hashValue = window.location.hash): string | null {
  const hash = hashValue.replace(/^#/, "");
  if (!hash) return null;
  const params = new URLSearchParams(hash);
  return params.get("nonce") ?? params.get("auth_nonce");
}

function getNonceFromAuthLink(value: string): string | null {
  try {
    const url = new URL(value.trim(), window.location.href);
    if (url.origin !== window.location.origin || url.pathname !== "/bot/") return null;
    return getNonceFromHash(url.hash);
  } catch {
    return null;
  }
}

function scrubHash(): void {
  window.history.replaceState({}, document.title, `${window.location.pathname}${window.location.search}`);
}

function makeLocalId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return `${prefix}-${crypto.randomUUID()}`;
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function asDate(value?: string | number | null): Date {
  if (value === null || value === undefined || value === "") return new Date(Number.NaN);
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isFinite(numeric)) return new Date(numeric < 1_000_000_000_000 ? numeric * 1000 : numeric);
  return new Date(value);
}

function formatTime(value?: string | number | null): string {
  if (!value) return "";
  const date = asDate(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
}

function formatDate(value?: string | number | null): string {
  if (!value) return "";
  const date = asDate(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function formatBytes(size?: number | null): string {
  if (size === null || size === undefined) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function usageSummary(usage: RuntimeUsage): string {
  if (usage.remaining !== null && usage.remaining !== undefined) {
    return usage.limit !== null && usage.limit !== undefined ? `${usage.remaining} remaining` : `${usage.remaining}% remaining`;
  }
  const remainingPercent = usage.windows?.[0]?.remaining_percent;
  return remainingPercent !== null && remainingPercent !== undefined ? `${Math.round(remainingPercent)}% remaining` : "Usage unavailable";
}

function usageResetAt(usage: RuntimeUsage): string | number | null {
  return usage.reset_at ?? usage.windows?.[0]?.reset_at ?? null;
}

function eventRecord(event: StreamEvent): Record<string, unknown> {
  if (typeof event.data === "object" && event.data !== null) return event.data;
  return {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function eventText(event: StreamEvent): string | null {
  if (typeof event.data === "string") return event.data === "[DONE]" ? null : event.data;
  const data = eventRecord(event);
  for (const key of ["text", "delta", "content", "output_text"]) {
    if (typeof data[key] === "string") return data[key] as string;
  }
  return null;
}

function eventMessage(event: StreamEvent): Message | null {
  const data = eventRecord(event);
  const value = data.message;
  if (!value || typeof value !== "object") return null;
  const message = value as Partial<Message>;
  if (typeof message.content !== "string" || typeof message.role !== "string") return null;
  return {
    id: typeof message.id === "string" ? message.id : makeLocalId("server-message"),
    conversation_id: typeof message.conversation_id === "string" ? message.conversation_id : "",
    role: message.role as Message["role"],
    content: message.content,
    created_at: message.created_at,
    status: message.status,
    metadata: message.metadata,
  };
}

function eventToolName(event: StreamEvent): string {
  const data = eventRecord(event);
  const nested = data.tool && typeof data.tool === "object" ? data.tool as Record<string, unknown> : null;
  for (const value of [data.tool, data.type, data.name, data.kind, nested?.name, nested?.type]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return event.type;
}

function isImageGenerationEvent(event: StreamEvent): boolean {
  return /image[_. -]?generat|image_generate|generate[_. -]?image/i.test(eventToolName(event))
    || /image[_. -]?generat|image_generate|generate[_. -]?image/i.test(event.type);
}

function imageSourceFromValue(value: unknown, depth = 0): string | null {
  if (depth > 5) return null;
  if (typeof value === "string" && /^\/bot\/api\/files\/[A-Za-z0-9_-]+\/download(?:\?.*)?$/i.test(value.trim())) return value.trim();
  if (Array.isArray(value)) {
    for (const item of value) {
      const source = imageSourceFromValue(item, depth + 1);
      if (source) return source;
    }
    return null;
  }
  if (!isRecord(value)) return null;
  for (const key of ["image_url", "imageUrl", "download_url", "downloadUrl", "url", "src", "uri", "output", "image", "images", "result", "data"]) {
    const source = imageSourceFromValue(value[key], depth + 1);
    if (source) return source;
  }
  return null;
}

function avatarStatus(isSending: boolean, progress: string, approval: Approval | null, error: string | null): AvatarStatus {
  if (error) return "error";
  if (approval) return "waiting";
  if (/tool|image|computer|using/i.test(progress)) return "tool";
  if (isSending && /typing|writing|answer/i.test(progress)) return "typing";
  return isSending ? "working" : "idle";
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "runtime_unavailable") return "The Codex runtime is not connected yet.";
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong. Try again.";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function App(): JSX.Element {
  const [theme, setTheme] = useState<Theme>(getStoredTheme);
  const [authState, setAuthState] = useState<"loading" | "signed-out" | "signed-in" | "error">("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [signOutError, setSignOutError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem("hermes-theme", theme);
    } catch {
      // Storage is optional; the theme still applies for this session.
    }
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    const nonce = getNonceFromHash();
    if (nonce) scrubHash();

    const load = async () => {
      try {
        const result = nonce ? await exchangeTelegramNonce(nonce) : await getSession();
        if (cancelled) return;
        if (isAuthenticated(result)) {
          setSession(result);
          setAuthState("signed-in");
        } else {
          setAuthState("signed-out");
        }
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) {
          setAuthState("signed-out");
        } else {
          setAuthError(errorMessage(error));
          setAuthState("error");
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const exchangeLoginLink = async (nonce: string): Promise<void> => {
    setAuthError(null);
    try {
      const result = await exchangeTelegramNonce(nonce);
      if (isAuthenticated(result)) {
        setSession(result);
        setAuthState("signed-in");
      } else {
        setAuthError("That sign-in link did not authenticate this session.");
      }
    } catch (error) {
      setAuthError(errorMessage(error));
    }
  };

  const retryAuth = () => {
    setAuthState("loading");
    setAuthError(null);
    void getSession()
      .then((result) => {
        if (isAuthenticated(result)) {
          setSession(result);
          setAuthState("signed-in");
        } else {
          setAuthState("signed-out");
        }
      })
      .catch((error: unknown) => {
        setAuthError(errorMessage(error));
        setAuthState("error");
      });
  };

  const signOut = async () => {
    setSignOutError(null);
    try {
      await logout();
    } catch (error) {
      setSignOutError(`Couldn’t sign out: ${errorMessage(error)}`);
      return;
    }
    setSession(null);
    setAuthState("signed-out");
  };

  if (authState === "loading") return <LoadingScreen />;
  if (authState === "error") return <LoginScreen error={authError} onRetry={retryAuth} onExchangeLink={exchangeLoginLink} />;
  if (authState === "signed-out" || !session) return <LoginScreen error={authError} onRetry={retryAuth} onExchangeLink={exchangeLoginLink} />;

  return <GrokWorkspace session={session} theme={theme} onThemeChange={setTheme} onLogout={signOut} logoutError={signOutError} />;
}

function LoadingScreen(): JSX.Element {
  return (
    <main className="auth-screen auth-loading">
      <div className="brand-lockup brand-lockup-centered">
        <BrandMark />
        <span>Hermes</span>
      </div>
      <Loader2 className="spin" size={20} aria-label="Loading" />
    </main>
  );
}

function LoginScreen({ error, onRetry, onExchangeLink }: { error: string | null; onRetry: () => void; onExchangeLink: (nonce: string) => Promise<void> }): JSX.Element {
  const [showLinkRecovery, setShowLinkRecovery] = useState(false);
  const [signInLink, setSignInLink] = useState("");
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linkBusy, setLinkBusy] = useState(false);

  const submitSignInLink = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const pastedLink = signInLink;
    setSignInLink("");
    setLinkError(null);
    const nonce = getNonceFromAuthLink(pastedLink);
    if (!nonce) {
      setLinkError("Paste the Bot Mode sign-in link from Telegram.");
      return;
    }
    setLinkBusy(true);
    try {
      await onExchangeLink(nonce);
    } finally {
      setLinkBusy(false);
    }
  };

  return (
    <main className="auth-screen">
      <section className="auth-intro">
        <div className="brand-lockup">
          <BrandMark />
          <span>Hermes</span>
        </div>
        <div className="auth-intro-copy">
          <div className="login-bots" aria-hidden="true"><BotGlyph color="#9257ed" /><BotGlyph color="#2d93fa" /><BotGlyph color="#1ac66b" /></div>
          <h1>Your bots.<br />Together in one place.</h1>
          <p className="auth-lede">Give each bot a job. Pick up the conversation on your phone or computer.</p>
        </div>
      </section>

      <section className="auth-card" aria-labelledby="login-title">
        <div className="telegram-badge"><MessageCircle size={18} /> Telegram sign-in</div>
        <h2 id="login-title">Welcome to Bot Mode</h2>
        <p className="auth-card-copy">Use Telegram to connect your account. Hermes never asks for your Telegram password.</p>
        <a className="button button-primary button-wide" href={TELEGRAM_URL} target="_blank" rel="noreferrer">
          <MessageCircle size={18} /> Open Telegram
          <ArrowUpRight size={16} />
        </a>
        <div className="login-steps">
          <div className="login-step"><span>1</span><p>Open the Hermes bot in Telegram.</p></div>
          <div className="login-step"><span>2</span><p>Send <code>/bot</code> to get your sign-in link.</p></div>
          <div className="login-step"><span>3</span><p>Tap the sign-in link and come back here.</p></div>
        </div>
        <p className="login-help"><LockKeyhole size={14} /> The sign-in link is one-time and expires quickly.</p>
        <button className="login-link-recovery-toggle" type="button" aria-expanded={showLinkRecovery} onClick={() => { setShowLinkRecovery((open) => !open); setLinkError(null); }}><Link2 size={14} /> Already have a sign-in link?</button>
        {showLinkRecovery ? (
          <form className="login-link-recovery" onSubmit={(event) => void submitSignInLink(event)}>
            <label htmlFor="telegram-sign-in-link">Paste the link from Telegram</label>
            <div className="login-link-recovery-row">
              <input id="telegram-sign-in-link" type="text" inputMode="url" autoComplete="off" value={signInLink} onChange={(event) => setSignInLink(event.target.value)} placeholder="https://…/bot/#nonce=…" aria-describedby="telegram-sign-in-link-note" />
              <button className="button button-primary button-small" type="submit" disabled={linkBusy || !signInLink.trim()}>{linkBusy ? <Loader2 size={14} className="spin" /> : "Use link"}</button>
            </div>
            <p className="login-link-recovery-note" id="telegram-sign-in-link-note">The link must point to this Bot Mode app.</p>
            {linkError ? <p className="form-error" role="alert"><AlertCircle size={14} /> {linkError}</p> : null}
          </form>
        ) : null}
        {error ? (
          <div className="inline-error" role="alert">
            <AlertCircle size={16} />
            <span>{error}</span>
            <button className="text-button" type="button" onClick={onRetry}>Retry</button>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function BrandMark(): JSX.Element {
  return <BotGlyph color="#2d93fa" />;
}

interface WorkspaceProps {
  session: Session;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  onLogout: () => Promise<void>;
  logoutError: string | null;
}

type ActiveRun = {
  agentId: string;
  conversationId: string;
  controller: AbortController;
  taskId?: string;
  detached: boolean;
  stopRequested: boolean;
};

export function Workspace({ session, theme, onThemeChange, onLogout, logoutError }: WorkspaceProps): JSX.Element {
  const [view, setView] = useState<View>("chat");
  const [infoTab, setInfoTab] = useState<InfoTab>("overview");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [memory, setMemory] = useState<MemoryItem[]>([]);
  const [skills, setSkills] = useState<LearnedSkill[]>([]);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [runtimeAccount, setRuntimeAccount] = useState<RuntimeAccount | null>(null);
  const [runtimeUsage, setRuntimeUsage] = useState<RuntimeUsage | null>(null);
  const [desktop, setDesktop] = useState<DesktopStatus | null>(null);
  const [desktopBusy, setDesktopBusy] = useState(false);
  const [desktopError, setDesktopError] = useState<string | null>(null);
  const [runtimeLogin, setRuntimeLogin] = useState<RuntimeLogin | null>(null);
  const [runtimeConnecting, setRuntimeConnecting] = useState(false);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const selectionKey = `hermes-selection:${session.user?.id ?? "session"}`;
  const [savedSelection] = useState<{ agentId?: string; conversationId?: string }>(() => {
    try { const value = JSON.parse(window.sessionStorage.getItem(selectionKey) ?? "{}"); return { agentId: typeof value.agentId === "string" ? value.agentId : undefined, conversationId: typeof value.conversationId === "string" ? value.conversationId : undefined }; } catch { return {}; }
  });
  const [selectedAgentId, setSelectedAgentId] = useState<string | undefined>(savedSelection.agentId);
  const [selectedConversationId, setSelectedConversationId] = useState<string | undefined>(savedSelection.conversationId);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [hasOlderMessages, setHasOlderMessages] = useState(false);
  const [olderMessagesLoading, setOlderMessagesLoading] = useState(false);
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [connection, setConnection] = useState<"checking" | "online" | "offline">("checking");
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");
  const [streamProgress, setStreamProgress] = useState("");
  const [streamError, setStreamError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [imageGeneration, setImageGeneration] = useState<ImageGenerationState | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const draftKey = `${selectedAgentId ?? "none"}:${selectedConversationId ?? "new"}`;
  const draft = drafts[draftKey] ?? "";
  const setDraft = (value: string) => setDrafts((items) => ({ ...items, [draftKey]: value }));
  const [approval, setApproval] = useState<Approval | null>(null);
  const [approvalTaskId, setApprovalTaskId] = useState<string | undefined>();
  const [mobileHome, setMobileHome] = useState(true);
  const [detailsOpen, setDetailsOpen] = useState(true);
  const [mobileInfoOpen, setMobileInfoOpen] = useState(false);
  const [newBotOpen, setNewBotOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [newConversationMode, setNewConversationMode] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const activeRunRef = useRef<ActiveRun | null>(null);
  const selectionRef = useRef<{ agentId?: string; conversationId?: string }>({});
  const workspaceLoadRef = useRef(0);
  const pendingStopRef = useRef(false);

  const currentAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) ?? null,
    [agents, selectedAgentId],
  );
  const agentConversations = useMemo(
    () => conversations.filter((conversation) => conversation.agent_id === selectedAgentId),
    [conversations, selectedAgentId],
  );
  const selectedConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === selectedConversationId) ?? null,
    [conversations, selectedConversationId],
  );
  const agentMemory = useMemo(
    () => memory.filter((item) => !item.agent_id || item.agent_id === selectedAgentId),
    [memory, selectedAgentId],
  );

  const isVisibleRun = (run: ActiveRun): boolean => (
    activeRunRef.current === run
    && !run.detached
    && selectionRef.current.agentId === run.agentId
    && selectionRef.current.conversationId === run.conversationId
  );

  const loadWorkspace = async () => {
    const loadId = workspaceLoadRef.current + 1;
    workspaceLoadRef.current = loadId;
    setWorkspaceLoading(true);
    setWorkspaceError(null);
    const [agentsResult, conversationsResult, memoryResult, filesResult, activityResult, runtimeResult, accountResult, usageResult, onboardingResult] = await Promise.allSettled([
      listAgents(),
      listConversations(),
      listMemory(),
      listFiles(),
      listActivity(),
      getRuntimeStatus(),
      getRuntimeAccount(),
      getRuntimeUsage(),
      getOnboarding(),
    ]);
    let succeeded = false;
    if (loadId !== workspaceLoadRef.current) return;
    if (agentsResult.status === "fulfilled") {
      setAgents(agentsResult.value);
      succeeded = true;
    }
    if (conversationsResult.status === "fulfilled") {
      setConversations(conversationsResult.value);
      succeeded = true;
    }
    if (memoryResult.status === "fulfilled") {
      setMemory(memoryResult.value);
      succeeded = true;
    }
    if (filesResult.status === "fulfilled") {
      setFiles(filesResult.value);
      succeeded = true;
    }
    if (activityResult.status === "fulfilled") {
      setActivity(activityResult.value);
      succeeded = true;
    }
    if (runtimeResult.status === "fulfilled") setRuntime(runtimeResult.value);
    if (accountResult.status === "fulfilled") setRuntimeAccount(accountResult.value);
    if (usageResult.status === "fulfilled") setRuntimeUsage(usageResult.value);
    // Setup stays available in Settings without interrupting the first bot.
    if (onboardingResult.status === "fulfilled" && onboardingResult.value.complete) {
      try { window.localStorage.setItem(ONBOARDING_KEY, "done"); } catch { /* Optional storage. */ }
    }
    setConnection(succeeded ? "online" : "offline");
    if (!succeeded) setWorkspaceError("Hermes is offline. Check the server and try again.");
    setWorkspaceLoading(false);
  };

  useEffect(() => {
    void loadWorkspace();
    const handleOnline = () => setConnection("online");
    const handleOffline = () => setConnection("offline");
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    if (workspaceLoading) return;
    if (agents.length === 0) {
      setSelectedAgentId(undefined);
      return;
    }
    if (!selectedAgentId || !agents.some((agent) => agent.id === selectedAgentId)) setSelectedAgentId(agents[0].id);
  }, [agents, selectedAgentId, workspaceLoading]);

  useEffect(() => {
    if (workspaceLoading) return;
    if (!selectedAgentId) {
      setSelectedConversationId(undefined);
      return;
    }
    if (newConversationMode) return;
    if (!selectedConversationId || !agentConversations.some((conversation) => conversation.id === selectedConversationId)) {
      setSelectedConversationId(agentConversations[0]?.id);
    }
  }, [agentConversations, newConversationMode, selectedAgentId, selectedConversationId, workspaceLoading]);

  useEffect(() => {
    if (workspaceLoading) return;
    try { window.sessionStorage.setItem(selectionKey, JSON.stringify({ agentId: selectedAgentId, conversationId: selectedConversationId })); } catch { /* Optional session persistence. */ }
  }, [selectionKey, workspaceLoading, selectedAgentId, selectedConversationId]);

  useEffect(() => {
    const previous = selectionRef.current;
    selectionRef.current = { agentId: selectedAgentId, conversationId: selectedConversationId };
    const activeRun = activeRunRef.current;
    if (activeRun && (activeRun.agentId !== selectedAgentId || activeRun.conversationId !== selectedConversationId)) {
      activeRun.detached = true;
      activeRun.controller.abort();
      setStreamingText("");
      setStreamProgress("");
      setStreamError(null);
      setApproval(null);
      setImageGeneration(null);
      setIsSending(false);
      setIsCancelling(false);
    }
    if (previous.agentId !== selectedAgentId || previous.conversationId !== selectedConversationId) {
      setMessages([]);
    }
  }, [selectedAgentId, selectedConversationId]);

  useEffect(() => {
    let active = true;
    if (!selectedConversationId) {
      setMessages([]);
      setMessagesLoading(false);
      return () => {
        active = false;
      };
    }
    setMessagesLoading(true);
    setHasOlderMessages(false);
    setOlderMessagesLoading(false);
    void listMessages(selectedConversationId)
      .then((result) => {
        if (active) { setMessages(result); setHasOlderMessages(result.length === 200); }
      })
      .catch((error: unknown) => {
        if (active) setWorkspaceError(errorMessage(error));
      })
      .finally(() => {
        if (active) setMessagesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedConversationId]);

  useEffect(() => {
    if (!selectedAgentId || !selectedConversationId) return;
    const controller = new AbortController();
    let active = true;
    void conversationTasks(selectedConversationId, controller.signal).then((tasks) => {
      if (!active || selectionRef.current.agentId !== selectedAgentId || selectionRef.current.conversationId !== selectedConversationId) return;
      const existing = activeRunRef.current;
      if (existing && !existing.detached && existing.conversationId === selectedConversationId) return;
      const task = tasks.find((item) => item.status === "running" || item.status === "queued");
      if (!task) return;
      const run: ActiveRun = { agentId: selectedAgentId, conversationId: selectedConversationId, taskId: task.id, controller, detached: false, stopRequested: false };
      void followRun(run);
    }).catch((error: unknown) => {
      if (active && !isAbortError(error)) setStreamError(errorMessage(error));
    });
    return () => { active = false; controller.abort(); };
  }, [selectedAgentId, selectedConversationId]);

  useEffect(() => {
    if (!selectedAgentId) {
      setFiles([]);
      setSkills([]);
      return;
    }
    let active = true;
    void listFiles(selectedAgentId)
      .then((result) => {
        if (active) setFiles(result);
      })
      .catch((error: unknown) => {
        if (active) setWorkspaceError(errorMessage(error));
      });
    return () => {
      active = false;
    };
  }, [selectedAgentId]);

  useEffect(() => {
    if (!selectedAgentId) return;
    let active = true;
    void listSkills(selectedAgentId)
      .then((result) => {
        if (active) setSkills(result);
      })
      .catch(() => {
        if (active) setSkills([]);
      });
    return () => {
      active = false;
    };
  }, [selectedAgentId]);

  useEffect(() => {
    if (!selectedAgentId) {
      setDesktop(null);
      return;
    }
    let active = true;
    setDesktopError(null);
    void getDesktopStatus(selectedAgentId)
      .then((result) => {
        if (active) setDesktop(result);
      })
      .catch((error: unknown) => {
        if (active) setDesktopError(errorMessage(error));
      });
    return () => {
      active = false;
    };
  }, [selectedAgentId]);

  useEffect(() => {
    if (!selectedAgentId) return;
    let active = true;
    void listMemory(selectedAgentId)
      .then((result) => {
        if (active) setMemory(result);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [selectedAgentId]);

  useEffect(() => {
    if (!runtimeConnecting) return undefined;
    const interval = window.setInterval(() => {
      void getRuntimeAccount()
        .then((account) => {
          setRuntimeAccount(account);
          if (account.connected) {
            setRuntimeConnecting(false);
            setRuntimeLogin(null);
          }
        })
        .catch(() => {
          // Keep the device sign-in card open while the server is finishing the exchange.
        });
    }, 2500);
    return () => window.clearInterval(interval);
  }, [runtimeConnecting]);

  const navigate = (nextView: View) => {
    setView(nextView);
    setMobileHome(false);
    setNewBotOpen(false);
    if (nextView !== "chat") setInfoTab(nextView === "memory" ? "memory" : nextView === "files" ? "files" : nextView === "activity" ? "activity" : "overview");
  };

  const handleSelectAgent = (id: string) => {
    const nextConversationId = conversations.find((conversation) => conversation.agent_id === id)?.id;
    selectionRef.current = { agentId: id, conversationId: nextConversationId };
    setSelectedAgentId(id);
    setSelectedConversationId(nextConversationId);
    setNewConversationMode(false);
    setView("chat");
    setMobileHome(false);
    setNewBotOpen(false);
  };

  const stopRun = async (run: ActiveRun | null = activeRunRef.current): Promise<void> => {
    if (!run || run.detached) return;
    if (!run.stopRequested) {
      run.stopRequested = true;
      if (isVisibleRun(run)) {
        setIsCancelling(true);
        setStreamError(null);
        setStreamProgress("Stopping…");
      }
    }
    if (!run.taskId) return;
    try {
      await cancelTask(run.taskId);
      if (isVisibleRun(run)) {
        setStreamProgress("Run cancelled");
        setImageGeneration((current) => current?.status === "generating" ? { ...current, status: "cancelled", message: "Stopped waiting for the image. The provider may still finish this request." } : current);
      }
      run.controller.abort();
    } catch (error) {
      run.stopRequested = false;
      if (isVisibleRun(run)) {
        setIsCancelling(false);
        setStreamProgress("Run still active");
        setStreamError(`Couldn’t stop this run: ${errorMessage(error)}`);
      }
    }
  };

  async function followRun(run: ActiveRun, input?: { content: string; fileIds: string[] }): Promise<boolean> {
    activeRunRef.current = run;
    abortRef.current = run.controller;
    setIsSending(true);
    setIsCancelling(false);
    setStreamingText("");
    setStreamError(null);
    setStreamProgress(input ? "Starting…" : "Reconnecting to your run…");
    setApproval(null);
    setImageGeneration(null);
    let streamBuffer = "";
    let streamFailure: string | null = null;
    let imageStarted = false;
    const onEvent = (event: StreamEvent) => {
        if (!isVisibleRun(run)) return;
        const eventData = eventRecord(event);
        const imageEvent = isImageGenerationEvent(event);
        if (event.type === "task.reconnecting") setStreamProgress("Reconnecting to your run…");
        if (event.type === "approval.decided") { setApproval(null); setApprovalTaskId(undefined); }
        if (event.type === "task.cancelled") { setStreamProgress("Run cancelled"); setApproval(null); setImageGeneration((current) => current?.status === "generating" ? { ...current, status: "cancelled", message: "Stopped waiting for the image. The provider may still finish this request." } : current); }
        if (event.type === "task.started") setStreamProgress("Task started");
        if (event.type === "turn.started") setStreamProgress("Planning the run");
        if (event.type === "tool.started") {
          const toolName = eventToolName(event);
          setStreamProgress(imageEvent ? "Generating an image" : `Using ${toolName}`);
          if (imageEvent) {
            imageStarted = true;
            setImageGeneration({ status: "generating", prompt: typeof eventData.prompt === "string" ? eventData.prompt : undefined, aspectRatio: typeof eventData.aspect_ratio === "string" ? eventData.aspect_ratio : "1:1" });
          }
        }
        if (event.type === "tool.completed" && imageEvent) {
          const source = imageSourceFromValue(eventData);
          setImageGeneration((current) => source && eventData.success !== false
            ? { ...current, status: "complete", src: source, alt: current?.prompt ?? "Generated image" }
            : { ...current, status: "error", message: typeof eventData.error === "string" ? eventData.error : "The image result did not include a preview." });
          setStreamProgress(source ? "Image ready" : "Image result unavailable");
        } else if (event.type === "tool.completed") {
          setStreamProgress("Tool step complete");
        }
        if (event.type === "plan") setStreamProgress("Following the plan");
        if (event.type === "context.compacted") setStreamProgress("Context compacted");
        if (event.type === "task.completed" || event.type === "turn.completed") {
          setStreamProgress("Finishing up");
          if (imageStarted) setImageGeneration((current) => current?.status === "generating" ? { status: "error", message: "The image result was interrupted." } : current);
        }
        const text = eventText(event);
        if (text) {
          streamBuffer += text;
          setStreamProgress("Typing");
          setStreamingText((value) => value + text);
        }
        const fullMessage = eventMessage(event);
        if (fullMessage) {
          streamBuffer = fullMessage.content;
          setStreamingText(fullMessage.content);
        }
        if (event.type === "approval" || event.type === "approval.requested") {
          const data = eventRecord(event);
          const value = (data.approval ?? data) as Partial<Approval> & { id?: string; task_id?: string };
          if (typeof value.description === "string") {
            setApproval({
              approval_id: typeof value.approval_id === "string" ? value.approval_id : typeof value.id === "string" ? value.id : makeLocalId("approval"),
              kind: typeof value.kind === "string" ? value.kind : "Action",
              description: value.description,
              status: typeof value.status === "string" ? value.status : "pending",
              data: typeof value.data === "object" && value.data !== null ? value.data as Record<string, unknown> : undefined,
            });
            setApprovalTaskId(typeof data.task_id === "string" ? data.task_id : typeof value.task_id === "string" ? value.task_id : run.taskId);
            setStreamProgress("Waiting for your approval");
          }
        }
        if (event.type === "error" || event.type === "task.error" || event.type === "task.failed") {
          const data = eventRecord(event);
          streamFailure = typeof data.message === "string" ? data.message : eventText(event) ?? "The run failed.";
          setStreamProgress("Run failed");
          if (imageStarted) setImageGeneration({ status: "error", message: streamFailure });
        }

    };
    try {
      if (input) {
        await streamMessage(run.conversationId, { content: input.content, agent_id: run.agentId, file_ids: input.fileIds }, onEvent, run.controller.signal, (taskId) => {
          run.taskId = taskId;
          if (run.stopRequested) void stopRun(run);
        });
      } else if (run.taskId) {
        await watchTask(run.taskId, onEvent, run.controller.signal);
      }
      if (streamFailure && isVisibleRun(run)) setStreamError(streamFailure);
    } catch (error) {
      if (isVisibleRun(run) && !isAbortError(error)) {
        setStreamError(errorMessage(error));
        setImageGeneration((current) => current?.status === "generating" ? { ...current, status: "error", message: "Connection lost. Reopen this chat to check the image request." } : current);
      }
    } finally {
      if (isVisibleRun(run)) {
        const fresh = await listMessages(run.conversationId).catch(() => null);
        if (isVisibleRun(run)) {
          if (fresh) { setMessages(fresh); setStreamingText(""); }
          else if (streamBuffer) setStreamingText(streamBuffer);
          setIsSending(false);
          setIsCancelling(false);
          setStreamProgress("");
          setApproval(null);
          if (fresh) setImageGeneration((current) => current?.status === "complete" && current.src && fresh.some((message) => message.role === "assistant" && message.content.includes(current.src!)) ? null : current);
          void Promise.all([listSkills(run.agentId), listFiles(run.agentId), getDesktopStatus(run.agentId), listActivity(run.agentId)]).then(([nextSkills, nextFiles, nextDesktop, nextActivity]) => {
            if (selectionRef.current.agentId !== run.agentId) return;
            setSkills(nextSkills); setFiles(nextFiles); setDesktop(nextDesktop); setActivity(nextActivity);
          }).catch(() => undefined);
        }
      }
      if (activeRunRef.current === run) { activeRunRef.current = null; abortRef.current = null; }
    }
    return Boolean(run.taskId);
  }

  const handleSend = async (contentOverride?: string, fileIds: string[] = []): Promise<{ accepted: boolean; conversationId?: string }> => {
    const content = (contentOverride ?? draft).trim();
    const sourceAgent = currentAgent;
    const sourceConversationId = selectedConversationId;
    if (!content || !sourceAgent || isSending) return { accepted: false };
    pendingStopRef.current = false;
    setStreamError(null);
    setIsSending(true);
    try {
      let conversation = selectedConversation;
      if (!conversation) {
        conversation = await createConversation(sourceAgent.id, content.slice(0, 48));
        if (pendingStopRef.current) { setStreamProgress("Run cancelled"); return { accepted: false }; }
        setConversations((items) => [conversation as Conversation, ...items]);
        if (selectionRef.current.agentId !== sourceAgent.id || selectionRef.current.conversationId !== sourceConversationId) return { accepted: false };
        selectionRef.current = { agentId: sourceAgent.id, conversationId: conversation.id };
        setSelectedConversationId(conversation.id);
        setNewConversationMode(false);
      }
      if (selectionRef.current.agentId !== sourceAgent.id || (sourceConversationId && selectionRef.current.conversationId !== sourceConversationId)) return { accepted: false };
      if (pendingStopRef.current) { setStreamProgress("Run cancelled"); return { accepted: false }; }
      const run: ActiveRun = { agentId: sourceAgent.id, conversationId: conversation.id, controller: new AbortController(), detached: false, stopRequested: false };
      setMessages((items) => [...items, { id: makeLocalId("local-user"), conversation_id: conversation.id, role: "user", content, created_at: new Date().toISOString(), status: "complete" }]);
      setDraft("");
      const accepted = await followRun(run, { content, fileIds });
      if (!accepted && selectionRef.current.agentId === sourceAgent.id && selectionRef.current.conversationId === conversation.id) setDrafts((items) => ({ ...items, [`${sourceAgent.id}:${conversation.id}`]: content }));
      return { accepted, conversationId: conversation.id };
    } catch (error) {
      if (selectionRef.current.agentId === sourceAgent.id && !isAbortError(error)) setStreamError(errorMessage(error));
      return { accepted: false };
    } finally {
      if (!activeRunRef.current) { setIsSending(false); setIsCancelling(false); }
      pendingStopRef.current = false;
    }
  };

  const loadOlderMessages = async () => {
    const conversationId = selectedConversationId;
    const oldest = messages[0]?.id;
    if (!conversationId || !oldest || olderMessagesLoading) return;
    setOlderMessagesLoading(true);
    try {
      const older = await listMessages(conversationId, oldest);
      if (selectionRef.current.conversationId !== conversationId) return;
      setMessages((current) => { const ids = new Set(current.map((m) => m.id)); return [...older.filter((m) => !ids.has(m.id)), ...current]; });
      setHasOlderMessages(older.length === 200);
    } catch (error) {
      if (selectionRef.current.conversationId === conversationId) setStreamError(errorMessage(error));
    } finally {
      if (selectionRef.current.conversationId === conversationId) setOlderMessagesLoading(false);
    }
  };

  const handleStop = (): void => {
    if (!activeRunRef.current) {
      pendingStopRef.current = true;
      setIsCancelling(true);
      setStreamProgress("Stopping…");
      return;
    }
    void stopRun();
  };

  const handleNewConversation = () => {
    if (!currentAgent) return;
    selectionRef.current = { agentId: currentAgent.id, conversationId: undefined };
    setNewConversationMode(true);
    setSelectedConversationId(undefined);
    setMessages([]);
    setStreamError(null);
    setView("chat");
  };

  const handleSelectConversation = (id: string) => {
    if (selectedAgentId) selectionRef.current = { agentId: selectedAgentId, conversationId: id };
    setNewConversationMode(false);
    setSelectedConversationId(id);
  };

  const handleNewBot = async (input: AgentInput) => {
    const agent = await createAgent(input);
    selectionRef.current = { agentId: agent.id, conversationId: undefined };
    setAgents((items) => [agent, ...items]);
    setSelectedAgentId(agent.id);
    setSelectedConversationId(undefined);
    setMessages([]);
    setView("chat");
    setNewBotOpen(false);
    setMobileHome(false);
  };

  const handleUpdateAgent = async (id: string, input: Partial<AgentInput>): Promise<void> => {
    const updated = await updateAgent(id, input);
    setAgents((items) => items.map((item) => item.id === id ? updated : item));
  };

  const handleAddMemory = async (content: string, scope: "shared" | "private") => {
    if (!content.trim()) return;
    const agentId = currentAgent?.id;
    const item = await createMemory({ content: content.trim(), scope, agent_id: scope === "private" ? agentId : undefined });
    if (scope === "shared" || selectionRef.current.agentId === agentId) setMemory((items) => [item, ...items]);
  };

  const handleDeleteMemory = async (id: string, agentId?: string) => {
    await deleteMemory(id, agentId);
    setMemory((items) => items.filter((item) => item.id !== id));
  };

  const handleToggleSkill = async (skillId: string, enabled: boolean): Promise<void> => {
    if (!currentAgent) return;
    const agentId = currentAgent.id;
    const updated = await setSkillEnabled(agentId, skillId, enabled);
    if (selectionRef.current.agentId === agentId) setSkills((items) => items.map((item) => item.id === skillId ? { ...item, ...(updated ?? {}), enabled } : item));
  };

  const handleDeleteSkill = async (skillId: string): Promise<void> => {
    if (!currentAgent) return;
    const agentId = currentAgent.id;
    await deleteSkill(agentId, skillId);
    if (selectionRef.current.agentId === agentId) setSkills((items) => items.filter((item) => item.id !== skillId));
  };

  const handleFileUpload = async (file: File): Promise<FileAsset> => {
    const agentId = currentAgent?.id;
    const uploaded = await uploadFile(file, agentId);
    if (!agentId || selectionRef.current.agentId === agentId) setFiles((items) => [uploaded, ...items]);
    return uploaded;
  };

  const handleDeleteFile = async (id: string) => {
    await deleteFile(id);
    setFiles((items) => items.filter((file) => file.id !== id));
  };

  const handleCompact = async () => {
    if (!selectedConversationId) return;
    try {
      await compactConversation(selectedConversationId);
      const next = await listMessages(selectedConversationId);
      setMessages(next);
    } catch (error) {
      setWorkspaceError(errorMessage(error));
    }
  };

  const handleConnectRuntime = async () => {
    setRuntimeError(null);
    setRuntimeConnecting(true);
    try {
      const login = await startRuntimeLogin();
      setRuntimeLogin(login);
    } catch (error) {
      setRuntimeConnecting(false);
      setRuntimeError(errorMessage(error));
    }
  };

  const refreshRuntime = async () => {
    setRuntimeError(null);
    try {
      const [account, usage, status] = await Promise.all([getRuntimeAccount(), getRuntimeUsage(), getRuntimeStatus()]);
      setRuntimeAccount(account);
      setRuntimeUsage(usage);
      setRuntime(status);
    } catch (error) {
      setRuntimeError(errorMessage(error));
    }
  };

  const handleDesktopAction = async (action: "create" | "start" | "stop") => {
    if (!currentAgent) return;
    const agentId = currentAgent.id;
    setDesktopBusy(true);
    setDesktopError(null);
    try {
      const next = action === "create" ? await createDesktop(agentId) : action === "start" ? await startDesktop(agentId) : await stopDesktop(agentId);
      if (selectionRef.current.agentId === agentId) setDesktop(next);
    } catch (error) {
      if (selectionRef.current.agentId === agentId) {
        setDesktopError(errorMessage(error));
        await getDesktopStatus(agentId).then((result) => {
          if (selectionRef.current.agentId === agentId) setDesktop(result);
        }).catch(() => undefined);
      }
    } finally {
      if (selectionRef.current.agentId === agentId) setDesktopBusy(false);
    }
  };

  const closeOnboarding = () => {
    try {
      window.localStorage.setItem(ONBOARDING_KEY, "done");
    } catch {
      // The modal can still be dismissed when storage is unavailable.
    }
    void completeOnboarding().catch(() => undefined);
    setOnboardingOpen(false);
  };

  const chooseInfoTab = (tab: InfoTab) => {
    setInfoTab(tab);
    if (tab === "memory") setView("memory");
    if (tab === "files") setView("files");
    if (tab === "activity") setView("activity");
    if (tab === "overview" || tab === "computer") setView("chat");
    if (tab !== "computer") setMobileInfoOpen(false);
  };

  const userName = session.user?.name ?? session.user?.username ?? "My account";
  const creatingBot = newBotOpen || (!workspaceLoading && agents.length === 0 && view === "chat");
  const openNewBot = () => { setNewBotOpen(true); setMobileHome(false); setView("chat"); };

  useEffect(() => {
    const onEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") { setMobileInfoOpen(false); setNewBotOpen(false); }
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, []);

  useEffect(() => {
    if (!mobileInfoOpen && !onboardingOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const panel = document.querySelector<HTMLElement>(onboardingOpen ? ".onboarding-card" : ".mobile-info-overlay");
    const focusable = () => Array.from(panel?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, textarea, [tabindex="0"]') ?? []).filter((node) => node.getClientRects().length > 0);
    focusable()[0]?.focus();
    const trap = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") { setMobileInfoOpen(false); setOnboardingOpen(false); }
      if (event.key !== "Tab") return;
      const nodes = focusable(); const first = nodes[0]; const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    panel?.addEventListener("keydown", trap);
    return () => { panel?.removeEventListener("keydown", trap); previous?.focus(); };
  }, [mobileInfoOpen, onboardingOpen]);

  return (
    <>
      <div inert={mobileInfoOpen || onboardingOpen} className={`app-shell view-${view} ${creatingBot ? "is-creating" : ""} ${detailsOpen ? "has-details" : ""} ${mobileHome ? "show-mobile-home" : ""}`}>
        <Sidebar
          agents={agents}
          conversations={conversations}
          creatingBot={creatingBot}
          selectedAgentId={selectedAgentId}
          activeView={view}
          userName={userName}
          onSelectAgent={handleSelectAgent}
          onNavigate={navigate}
          onNewBot={openNewBot}
          onLogout={onLogout}

        />
        <main className="main-column">
          {!creatingBot ? <MobileTopbar agent={currentAgent} view={view} onMenu={() => setMobileHome(true)} onInfo={() => setMobileInfoOpen(true)} /> : null}
          {connection === "offline" || workspaceError ? (
            <div className="connection-banner" role="status">
              <WifiOff size={15} />
              <span>{workspaceError ?? "You are offline. Reconnect and try again."}</span>
              <button className="text-button" type="button" onClick={() => void loadWorkspace()}><RefreshCw size={14} /> Retry</button>
            </div>
          ) : null}
          {logoutError ? <div className="connection-banner logout-banner" role="alert"><AlertCircle size={15} /><span>{logoutError}</span></div> : null}
          {creatingBot ? <BotCreator firstBot={agents.length === 0} onClose={() => { setNewBotOpen(false); setMobileHome(true); }} onCreate={handleNewBot} /> : view === "chat" ? (
            <ChatView
              agent={currentAgent}
              onDetails={() => { if (window.innerWidth > 1100) setDetailsOpen((open) => !open); else setMobileInfoOpen(true); }}
              onComputer={() => { setInfoTab("computer"); if (window.innerWidth > 1100) setDetailsOpen(true); else setMobileInfoOpen(true); }}
              conversations={agentConversations}
              selectedConversationId={selectedConversationId}
              onSelectConversation={handleSelectConversation}
              onNewConversation={handleNewConversation}
              messages={messages}
              messagesLoading={messagesLoading}
              hasOlderMessages={hasOlderMessages}
              olderMessagesLoading={olderMessagesLoading}
              onOlderMessages={loadOlderMessages}
              streamingText={streamingText}
              streamProgress={streamProgress}
              isSending={isSending}
              isCancelling={isCancelling}
              imageGeneration={imageGeneration}
              draft={draft}
              setDraft={setDraft}
              onSend={(content, fileIds) => handleSend(content, fileIds)}
              onStop={handleStop}
              streamError={streamError}
              approval={approval}
              onApprove={async () => {
                if (!approval || !approvalTaskId) return;
                try {
                  await respondToApproval(approvalTaskId, approval.approval_id, "accept");
                  setApproval(null);
                } catch (error) {
                  setStreamError(errorMessage(error));
                }
              }}
              onDeny={async () => {
                if (!approval || !approvalTaskId) return;
                try {
                  await respondToApproval(approvalTaskId, approval.approval_id, "decline");
                  setApproval(null);
                } catch (error) {
                  setStreamError(errorMessage(error));
                }
              }}
              onUpload={handleFileUpload}
              workspaceLoading={workspaceLoading}
              onNewBot={openNewBot}
            />
          ) : (
            <ResourceView
              view={view}
              agent={currentAgent}
              memory={agentMemory}
              skills={skills}
              files={files}
              activity={activity}
              theme={theme}
              runtimeAccount={runtimeAccount}
              runtimeUsage={runtimeUsage}
              runtimeLogin={runtimeLogin}
              runtimeConnecting={runtimeConnecting}
              runtimeError={runtimeError}
              onThemeChange={onThemeChange}
              onAddMemory={handleAddMemory}
              onDeleteMemory={handleDeleteMemory}
              onToggleSkill={handleToggleSkill}
              onDeleteSkill={handleDeleteSkill}
              onUpload={handleFileUpload}
              onDeleteFile={handleDeleteFile}
              onConnectRuntime={() => void handleConnectRuntime()}
              onRefreshRuntime={() => void refreshRuntime()}
              onResetOnboarding={() => setOnboardingOpen(true)}
              onLogout={onLogout}
              desktop={desktop}
              desktopBusy={desktopBusy}
              desktopError={desktopError}
              onDesktopAction={handleDesktopAction}
            />
          )}

        </main>
        {!creatingBot && detailsOpen ? <InfoPanel
          agent={currentAgent}
          activeTab={infoTab}
          onTabChange={chooseInfoTab}
          runtime={runtime}
          runtimeAccount={runtimeAccount}
          desktop={desktop}
          memory={agentMemory}
          skills={skills}
          files={files}
          activity={activity}
          selectedConversation={selectedConversation}
          onCompact={() => void handleCompact()}
          onConnectRuntime={() => void handleConnectRuntime()}
          onDesktopAction={handleDesktopAction}
          onUpdateAgent={handleUpdateAgent}
          onToggleSkill={handleToggleSkill}
          onDeleteSkill={handleDeleteSkill}
          onClose={() => setDetailsOpen(false)}
        /> : null}
        <MobileHome agents={agents} conversations={conversations} userName={userName} onSelectAgent={handleSelectAgent} onNewBot={openNewBot} onSettings={() => navigate("settings")} />
      </div>
      {mobileInfoOpen ? (
        <div className="mobile-overlay mobile-info-overlay" role="dialog" aria-modal="true" aria-label="Bot details">
          <button className="scrim" type="button" aria-label="Close details" onClick={() => setMobileInfoOpen(false)} />
          <InfoPanel
            agent={currentAgent}
            activeTab={infoTab}
            onTabChange={chooseInfoTab}
            runtime={runtime}
            runtimeAccount={runtimeAccount}
            desktop={desktop}
            memory={agentMemory}
            skills={skills}
            files={files}
            activity={activity}
            selectedConversation={selectedConversation}
            onCompact={() => void handleCompact()}
            onConnectRuntime={() => void handleConnectRuntime()}
            onDesktopAction={handleDesktopAction}
            onUpdateAgent={handleUpdateAgent}
            onToggleSkill={handleToggleSkill}
            onDeleteSkill={handleDeleteSkill}
            mobile
            onClose={() => setMobileInfoOpen(false)}
          />
        </div>
      ) : null}
      {onboardingOpen ? (
        <OnboardingModal
          userName={userName}
          runtimeAccount={runtimeAccount}
          runtimeLogin={runtimeLogin}
          runtimeConnecting={runtimeConnecting}
          runtimeError={runtimeError}
          onConnectRuntime={() => void handleConnectRuntime()}
          onClose={closeOnboarding}
        />
      ) : null}
    </>
  );
}

interface SidebarProps {
  agents: Agent[];
  conversations: Conversation[];
  selectedAgentId?: string;
  creatingBot: boolean;
  activeView: View;
  userName: string;
  onSelectAgent: (id: string) => void;
  onNavigate: (view: View) => void;
  onNewBot: () => void;
  onLogout: () => Promise<void>;
}

function recentChat(agent: Agent, conversations: Conversation[]): Conversation | undefined {
  return conversations.filter((chat) => chat.agent_id === agent.id).sort((a, b) => asDate(b.updated_at).getTime() - asDate(a.updated_at).getTime())[0];
}

function Sidebar({ agents, conversations, selectedAgentId, creatingBot, activeView, userName, onSelectAgent, onNavigate, onNewBot, onLogout }: SidebarProps): JSX.Element {
  const [query, setQuery] = useState("");
  const visibleAgents = agents.filter((agent) => `${agent.name} ${agent.description ?? ""}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <aside className="sidebar">
    <div className="sidebar-topline"><span className="sidebar-title">Bots</span><button className="icon-button" aria-label="New bot" title="New bot" onClick={onNewBot}><Plus size={18} /></button></div>
    {agents.length > 0 ? <div className="sidebar-search"><Search size={14} /><input aria-label="Search bots" placeholder="Search" value={query} onChange={(event) => setQuery(event.target.value)} />{query ? <button className="search-clear" aria-label="Clear search" onClick={() => setQuery("")}><X size={13}/></button> : null}</div> : null}
    {creatingBot ? <button className="bot-nav-item is-selected creator-nav" onClick={onNewBot}><BotGlyph color="#2d93fa" /><strong>{agents.length ? "New Bot" : "Create your first Bot"}</strong></button> : null}
    <div className="bot-list" aria-label="Your bots">
      {visibleAgents.map((agent) => {
        const chat = recentChat(agent, conversations);
        return <button className={`bot-nav-item ${selectedAgentId === agent.id && activeView === "chat" && !creatingBot ? "is-selected" : ""}`} key={agent.id} aria-label={`Open ${agent.name}`} aria-current={selectedAgentId === agent.id && !creatingBot ? "page" : undefined} onClick={() => onSelectAgent(agent.id)}>
          <AgentAvatar agent={agent} size="small" />
          <span className="bot-nav-copy"><span className="bot-row-title"><strong>{agent.name}</strong><time>{formatTime(chat?.updated_at)}</time></span><small>{chat?.title || agent.description || "Start a conversation"}</small></span>
        </button>;
      })}
      {!visibleAgents.length ? <div className="sidebar-empty">{query ? "No bots found" : "No chats yet"}</div> : null}
    </div>
    <nav className="sidebar-nav" aria-label="Workspace">{NAV_ITEMS.slice(1).map(({id, label, icon}) => <button className={`side-nav-item ${activeView === id ? "is-active" : ""}`} key={id} onClick={() => onNavigate(id)}><HermesIcon name={icon} size={17}/><span>{label}</span></button>)}</nav>
    <div className="sidebar-account"><button className="account-button" onClick={() => onNavigate("settings")}><span className="user-avatar"><UserRound size={16}/></span><span>{userName}</span></button><button className="icon-button" aria-label="Sign out" title="Sign out" onClick={() => void onLogout()}><LogOut size={16}/></button></div>
  </aside>;
}

function MobileHome({ agents, conversations, userName, onSelectAgent, onNewBot, onSettings }: { agents: Agent[]; conversations: Conversation[]; userName: string; onSelectAgent: (id: string) => void; onNewBot: () => void; onSettings: () => void }): JSX.Element {
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const shown = agents.filter((agent) => `${agent.name} ${agent.description ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="mobile-home" aria-label="Bots inbox">
    <header className="home-toolbar"><button className="icon-button home-account" aria-label={`Settings for ${userName}`} onClick={onSettings}><UserRound size={20}/></button><span className="home-toolbar-spacer"/><button className="icon-button" aria-label="Search bots" onClick={() => { setSearchOpen((open) => !open); setQuery(""); requestAnimationFrame(() => inputRef.current?.focus()); }}><Search size={20}/></button><button className="icon-button" aria-label="New bot" onClick={onNewBot}><Plus size={22}/></button></header>
    {searchOpen ? <div className="home-search sidebar-search"><Search size={16}/><input ref={inputRef} aria-label="Find a bot" placeholder="Search bots" value={query} onChange={(event) => setQuery(event.target.value)} /></div> : null}
    <div className="home-feed">
      {!query && agents.length ? <div className="featured-bots">{agents.slice(0,3).map((agent) => <button key={agent.id} aria-label={`Open ${agent.name}`} onClick={() => onSelectAgent(agent.id)}><AgentAvatar agent={agent} size="large"/><span>{agent.name}</span></button>)}</div> : null}
      <div className="home-bot-list">{(query ? shown : agents.slice(3)).map((agent) => { const chat = recentChat(agent, conversations); return <button className="home-bot-row" key={agent.id} aria-label={`Open ${agent.name}`} onClick={() => onSelectAgent(agent.id)}><AgentAvatar agent={agent}/><span className="bot-nav-copy"><span className="bot-row-title"><strong>{agent.name}</strong><time>{formatTime(chat?.updated_at)}</time></span><small>{chat?.title || agent.description || "Start a conversation"}</small></span></button>; })}</div>
      {!agents.length ? <div className="home-empty"><BotGlyph color="#2d93fa"/><h1>Your first bot</h1><p>Give it a name and a job to do.</p><button className="button button-primary" onClick={onNewBot}>Create a bot</button></div> : query && !shown.length ? <p className="home-no-results">No bots found</p> : null}
    </div>
  </section>;
}

function MobileTopbar({ agent, view, onMenu, onInfo }: { agent: Agent | null; view: View; onMenu: () => void; onInfo: () => void }): JSX.Element {
  return <header className="mobile-topbar"><button className="icon-button" aria-label="Back to bots" onClick={onMenu}><ArrowLeft size={21}/></button><div className="mobile-topbar-title">{view === "chat" ? <><AgentAvatar agent={agent} size="small"/><strong>{agent?.name ?? "Bots"}</strong></> : <strong>{NAV_ITEMS.find((item) => item.id === view)?.label}</strong>}</div><button className="icon-button" aria-label="Open bot details" onClick={onInfo}><PanelRight size={20}/></button></header>;
}

interface ChatViewProps {
  onDetails: () => void;
  onComputer: () => void;
  agent: Agent | null;
  conversations: Conversation[];
  selectedConversationId?: string;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  messages: Message[];
  messagesLoading: boolean;
  hasOlderMessages: boolean;
  olderMessagesLoading: boolean;
  onOlderMessages: () => Promise<void>;
  streamingText: string;
  streamProgress: string;
  isSending: boolean;
  isCancelling: boolean;
  imageGeneration: ImageGenerationState | null;
  draft: string;
  setDraft: (value: string) => void;
  onSend: (content?: string, fileIds?: string[]) => Promise<{ accepted: boolean; conversationId?: string }>;
  onStop: () => void;
  streamError: string | null;
  approval: Approval | null;
  onApprove: () => Promise<void>;
  onDeny: () => Promise<void>;
  onUpload: (file: File) => Promise<FileAsset>;
  workspaceLoading: boolean;
  onNewBot: () => void;
}

function ChatView({
  onDetails,
  onComputer,
  agent,
  conversations,
  selectedConversationId,
  onSelectConversation,
  onNewConversation,
  messages,
  messagesLoading,
  hasOlderMessages,
  olderMessagesLoading,
  onOlderMessages,
  streamingText,
  streamProgress,
  isSending,
  isCancelling,
  imageGeneration,
  draft,
  setDraft,
  onSend,
  onStop,
  streamError,
  approval,
  onApprove,
  onDeny,
  onUpload,
  workspaceLoading,
  onNewBot,
}: ChatViewProps): JSX.Element {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<FileAsset[]>([]);
  const [uploading, setUploading] = useState(false);
  const attachmentOwner = `${agent?.id ?? ""}:${selectedConversationId ?? "new"}`;
  const attachmentOwnerRef = useRef(attachmentOwner);
  attachmentOwnerRef.current = attachmentOwner;
  const [showLatest, setShowLatest] = useState(false);
  const [settledStatus, setSettledStatus] = useState<AvatarStatus>("idle");
  const hasMessages = messages.length > 0 || Boolean(streamingText);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const wasSending = useRef(false);
  useEffect(() => {
    nearBottom.current = true;
    setShowLatest(false);
    setAttachments([]);
    setUploading(false);
    setUploadError(null);
  }, [attachmentOwner]);
  useEffect(() => {
    if (nearBottom.current && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, streamingText, isSending]);
  useEffect(() => {
    if (isSending) {
      wasSending.current = true;
      return;
    }
    if (!wasSending.current) return;
    wasSending.current = false;
    setSettledStatus(streamError ? "error" : "complete");
    const timer = window.setTimeout(() => setSettledStatus("idle"), 700);
    return () => window.clearTimeout(timer);
  }, [isSending, streamError]);

  const scrollToLatest = () => {
    const element = scrollRef.current;
    if (!element) return;
    nearBottom.current = true;
    setShowLatest(false);
    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
  };

  const submitMessage = async () => {
    if (!agent || isSending || uploading || (!draft.trim() && attachments.length === 0)) return;
    const attachmentNames = attachments.map((file) => file.name).join(", ");
    const content = draft.trim() || `Please review these uploaded files: ${attachmentNames}. Summarize the key points.`;
    try {
      const owner = attachmentOwnerRef.current;
      const attached = attachments;
      const result = await onSend(content, attached.map((file) => file.id));
      if (result.accepted && attachmentOwnerRef.current === owner) setAttachments([]);
      if (!result.accepted && result.conversationId && attachmentOwnerRef.current === `${agent.id}:${result.conversationId}`) setAttachments(attached);
    } catch {
      // The parent renders the actionable send error and keeps the attachment tray intact.
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submitMessage();
    }
  };

  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || uploading) return;
    const owner = attachmentOwnerRef.current;
    setUploadError(null);
    setUploading(true);
    try {
      const uploaded = await onUpload(file);
      if (attachmentOwnerRef.current === owner) setAttachments((items) => [...items, uploaded]);
    } catch (error) {
      if (attachmentOwnerRef.current === owner) setUploadError(errorMessage(error));
    } finally {
      if (attachmentOwnerRef.current === owner) setUploading(false);
    }
  };

  return (
    <section className="chat-view">
      <div className="chat-toolbar">
        <div className="chat-heading">
          <AgentAvatar agent={agent} size="medium" status={isSending ? avatarStatus(isSending, streamProgress, approval, streamError) : settledStatus} statusLabel={isSending ? (streamProgress || "Working") : settledStatus === "complete" ? "Run complete" : settledStatus === "error" ? "Run failed" : undefined} />
          <div><div className="chat-heading-line"><h1>{agent?.name ?? "New Bot"}</h1></div><p>{agent?.description ?? "Create a bot to give your workspace a clear purpose."}</p></div>
        </div>
        <div className="toolbar-actions"><button className="icon-button" aria-label="Open computer" title="Computer" onClick={onComputer}><Monitor size={18}/></button><button className="icon-button" aria-label="Toggle bot details" title="Bot details" onClick={onDetails}><PanelRight size={18}/></button></div>
      </div>
      {conversations.length > 0 ? (
        <div className="conversation-strip" aria-label="Conversations">
          <span className="conversation-label">Chats</span>
          <div className="conversation-tabs">
            {conversations.map((conversation) => <button className={conversation.id === selectedConversationId ? "is-active" : ""} type="button" key={conversation.id} onClick={() => onSelectConversation(conversation.id)}>{conversation.title || "Untitled chat"}</button>)}
          </div>
          <button className="icon-button icon-button-small" type="button" aria-label="New chat" title="New chat" onClick={onNewConversation}><Plus size={16} /></button>
        </div>
      ) : null}
      <div ref={scrollRef} className={`chat-content ${hasMessages ? "has-messages" : ""}`} onScroll={() => { const el = scrollRef.current; if (el) { nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100; setShowLatest(!nearBottom.current && (messages.length > 0 || Boolean(streamingText))); } }}>
        {!hasMessages ? (
          <EmptyChat agent={agent} loading={workspaceLoading} onNewBot={onNewBot} onPrompt={(prompt) => setDraft(prompt)} />
        ) : (
          <div className="message-list" role="log" aria-live="polite"><div className="chat-date">{messages[0]?.created_at ? formatDate(messages[0].created_at) : "Today"}</div>
            {hasOlderMessages ? <button className="text-button load-older" type="button" disabled={olderMessagesLoading} onClick={async () => { const element = scrollRef.current; const height = element?.scrollHeight ?? 0; const top = element?.scrollTop ?? 0; nearBottom.current = false; await onOlderMessages(); requestAnimationFrame(() => { if (element && scrollRef.current === element) element.scrollTop = top + element.scrollHeight - height; }); }}>{olderMessagesLoading ? "Loading earlier messages…" : "Load earlier messages"}</button> : null}
            {messagesLoading ? <div className="message-loading"><Loader2 size={16} className="spin" /> Loading conversation</div> : null}
            {messages.map((message) => <MessageBubble key={message.id} message={message} agent={agent} />)}
            {streamingText ? <MessageBubble message={{ id: "streaming", conversation_id: selectedConversationId ?? "", role: "assistant", content: streamingText, status: "streaming" }} agent={agent} streaming /> : null}
            {imageGeneration ? <ImageGenerationCard state={imageGeneration} /> : null}
            {isSending ? <div className="typing-row" role="status"><AgentAvatar agent={agent} size="small" status={avatarStatus(isSending, streamProgress, approval, streamError)} statusLabel={streamProgress || "Working"} /><span className="typing-dots" aria-hidden="true"><i /><i /><i /></span><span>{streamProgress || "Working…"}</span></div> : null}
            {approval ? <ApprovalCard approval={approval} onApprove={() => void onApprove()} onDeny={() => void onDeny()} /> : null}
          </div>
        )}
        {showLatest ? <button className="jump-latest" type="button" onClick={scrollToLatest}><ArrowDownToLine size={15} /> Latest</button> : null}
      </div>
      {streamError || uploadError ? <div className="composer-error" role="alert"><AlertCircle size={15} /><span>{streamError ?? uploadError}</span></div> : null}
      <div className="composer-wrap">
        {attachments.length ? <div className="attachment-tray" aria-label="Files ready to send">{attachments.map((file) => <span className="attachment-chip" key={file.id}><FileText size={14} /><span>{file.name}</span><button type="button" aria-label={`Remove ${file.name}`} onClick={() => setAttachments((items) => items.filter((item) => item.id !== file.id))}><X size={13} /></button></span>)}<span className="attachment-note">Ready to include · send to review</span></div> : null}
        <div className="composer">
          <button className="composer-tool" type="button" aria-label={uploading ? "Uploading file" : "Attach a file"} disabled={uploading || isSending} title="Attach a file" onClick={() => fileInputRef.current?.click()}><Plus size={21} /></button>
          <input ref={fileInputRef} className="visually-hidden" type="file" onChange={(event) => void handleFile(event)} />
          <textarea aria-label={agent ? `Message ${agent.name}` : "Message"} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={handleKeyDown} placeholder={agent ? (attachments.length ? "Add a note or send the file for review…" : `Message ${agent.name}…`) : "Create a bot to start chatting…"} rows={1} disabled={!agent || isSending} />
          <div className="composer-end">
            <span className="composer-hint">{uploading ? "Uploading…" : isSending ? (isCancelling ? "Stopping…" : "Run in progress") : attachments.length && !draft.trim() ? "Send for review" : "Enter to send"}</span>
            <button className={`send-button ${isSending ? "is-stop" : ""}`} type="button" aria-label={isSending ? "Stop run" : attachments.length && !draft.trim() ? "Send attached files for review" : "Send message"} onClick={isSending ? onStop : () => void submitMessage()} disabled={(!isSending && (uploading || (!draft.trim() && attachments.length === 0))) || isCancelling}>{isSending ? <X size={17} /> : <ArrowUp size={19} />}</button>
          </div>
        </div>
      </div>
    </section>
  );
}

function EmptyChat({ agent, loading, onNewBot }: { agent: Agent | null; loading: boolean; onNewBot: () => void; onPrompt: (prompt: string) => void }): JSX.Element {
  return <div className="empty-chat"><AgentAvatar agent={agent} size="large"/>{loading ? <><Loader2 size={18} className="spin"/><p>Loading your bots…</p></> : <><h2>{agent?.name ?? "Your first bot"}</h2><p className="empty-copy">{agent?.description || "Ask a question or give your bot a task."}</p>{!agent ? <button className="button button-primary" onClick={onNewBot}>Create a bot</button> : null}</>}</div>;
}

function MessageBubble({ message, agent, streaming = false }: { message: Message; agent: Agent | null; streaming?: boolean }): JSX.Element {
  const isUser = message.role === "user";
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => { if (copyState === "idle") return; const timer = window.setTimeout(() => setCopyState("idle"), 1800); return () => window.clearTimeout(timer); }, [copyState]);
  const attachments = Array.isArray(message.metadata?.attachments) ? message.metadata.attachments.filter((file): file is {file_id: string; name: string} => file && typeof file.file_id === "string" && /^[a-zA-Z0-9_-]+$/.test(file.file_id) && typeof file.name === "string") : [];
  return (
    <article className={`message-row ${isUser ? "message-row-user" : "message-row-assistant"} ${streaming ? "message-row-streaming" : ""}`}>
      {!isUser ? <AgentAvatar agent={agent} size="small" status={streaming ? "typing" : "idle"} statusLabel={streaming ? "Typing" : undefined} /> : null}
      <div className="message-body">
        <div className="message-meta"><strong>{isUser ? "You" : agent?.name ?? "Hermes"}</strong>{message.created_at ? <time>{formatTime(message.created_at)}</time> : null}{streaming ? <span className="message-live"><span className="status-dot status-dot-green" /> Live</span> : null}</div>
        <div className="message-content"><MessageContent content={message.content} />
          {attachments.length ? <div className="message-attachments">{attachments.map((file) => <a key={file.file_id} href={`/bot/api/files/${file.file_id}/download`} download><FileText size={14} /><span>{file.name}</span><Download size={13} /></a>)}</div> : null}
        </div>
        {!streaming && message.content ? <button className="message-copy" type="button" aria-label={copyState === "copied" ? "Message copied" : copyState === "failed" ? "Copy failed, try again" : "Copy message"} onClick={() => { void navigator.clipboard.writeText(message.content).then(() => setCopyState("copied")).catch(() => setCopyState("failed")); }}>{copyState === "copied" ? <Check size={13} /> : <Copy size={13} />}<span>{copyState === "copied" ? "Copied" : copyState === "failed" ? "Try copying again" : "Copy"}</span></button> : null}
      </div>
      {isUser ? <div className="user-message-avatar"><UserRound size={14} /></div> : null}
    </article>
  );
}

function ApprovalCard({ approval, onApprove, onDeny }: { approval: Approval; onApprove: () => void; onDeny: () => void }): JSX.Element {
  return (
    <div className="approval-card" role="alert">
      <div className="approval-icon"><ShieldCheck size={18} /></div>
      <div className="approval-copy"><strong>Approval needed</strong><p>{approval.description}</p><small>{approval.kind}</small></div>
      <div className="approval-actions"><button className="button button-secondary button-small" type="button" onClick={onDeny}>Deny</button><button className="button button-primary button-small" type="button" onClick={onApprove}><Check size={14} /> Allow</button></div>
    </div>
  );
}

interface InfoPanelProps {
  agent: Agent | null;
  activeTab: InfoTab;
  onTabChange: (tab: InfoTab) => void;
  runtime: RuntimeStatus | null;
  runtimeAccount: RuntimeAccount | null;
  desktop: DesktopStatus | null;
  memory: MemoryItem[];
  skills: LearnedSkill[];
  files: FileAsset[];
  activity: ActivityItem[];
  selectedConversation: Conversation | null;
  onCompact: () => void;
  onConnectRuntime: () => void;
  onDesktopAction: (action: "create" | "start" | "stop") => Promise<void>;
  onUpdateAgent: (id: string, input: Partial<AgentInput>) => Promise<void>;
  onToggleSkill: (id: string, enabled: boolean) => Promise<void>;
  onDeleteSkill: (id: string) => Promise<void>;
  mobile?: boolean;
  onClose: () => void;
}

function InfoPanel({
  agent,
  activeTab,
  onTabChange,
  runtime,
  runtimeAccount,
  desktop,
  memory,
  skills,
  files,
  activity,
  selectedConversation,
  onCompact,
  onConnectRuntime,
  onDesktopAction,
  onUpdateAgent,
  onToggleSkill,
  onDeleteSkill,
  mobile = false,
  onClose,
}: InfoPanelProps): JSX.Element {
  return (
    <aside className={`info-panel ${mobile ? "info-panel-mobile" : ""}`}>
      <div className="info-header"><h2>Bot details</h2><button className="icon-button" type="button" aria-label="Close details" onClick={onClose}><X size={18} /></button></div>
      <div className="info-tabs" aria-label="Bot details">
        {INFO_TABS.map((tab) => {
          return <button className={activeTab === tab.id ? "is-active" : ""} type="button" aria-pressed={activeTab === tab.id} key={tab.id} onClick={() => onTabChange(tab.id)}><HermesIcon name={tab.icon} size={18} /><span>{tab.label}</span></button>;
        })}
      </div>
      <div className="info-scroll">
        {activeTab === "overview" ? <OverviewPanel desktop={desktop} onComputer={() => onTabChange("computer")} agent={agent} runtime={runtime} runtimeAccount={runtimeAccount} selectedConversation={selectedConversation} onCompact={onCompact} onConnectRuntime={onConnectRuntime} onUpdateAgent={onUpdateAgent} /> : null}
        {activeTab === "memory" ? <MemoryPanel memory={memory} skills={skills} compact onToggleSkill={onToggleSkill} onDeleteSkill={onDeleteSkill} /> : null}
        {activeTab === "files" ? <FilesPanel files={files} compact /> : null}
        {activeTab === "activity" ? <ActivityPanel activity={activity} compact /> : null}
        {activeTab === "computer" ? <ComputerPanel runtime={runtime} runtimeAccount={runtimeAccount} desktop={desktop} onConnectRuntime={onConnectRuntime} onDesktopAction={onDesktopAction} /> : null}
      </div>
    </aside>
  );
}

function OverviewPanel({
  desktop,
  onComputer,
  agent,
  runtime,
  runtimeAccount,
  selectedConversation,
  onCompact,
  onConnectRuntime,
  onUpdateAgent,
}: {
  desktop: DesktopStatus | null;
  onComputer: () => void;
  agent: Agent | null;
  runtime: RuntimeStatus | null;
  runtimeAccount: RuntimeAccount | null;
  selectedConversation: Conversation | null;
  onCompact: () => void;
  onConnectRuntime: () => void;
  onUpdateAgent: (id: string, input: Partial<AgentInput>) => Promise<void>;
}): JSX.Element {
  return (
    <div className="info-section-stack">
      {desktop?.running && desktop.view_url ? <div className="desktop-preview desktop-preview-mini"><iframe src={desktop.view_url} title="Live bot computer"/><a className="desktop-open-link" href={desktop.view_url} target="_blank" rel="noreferrer">Open computer <ExternalLink size={13}/></a></div> : null}
      <button className={`computer-preview-button ${desktop?.running && desktop.view_url ? "has-live-preview" : ""}`} onClick={onComputer}><span className="computer-preview-surface"><Monitor size={32}/><span>{desktop?.running ? "View computer" : desktop?.created ? "Computer paused" : "Set up computer"}</span></span><span>{agent ? `${agent.name}’s computer` : "Computer"}<ChevronRight size={14}/></span></button>
      <div className="bot-profile-card">
        <AgentAvatar agent={agent} size="large" />
        <h3>{agent?.name ?? "No bot selected"}</h3>
        <p>{agent?.description ?? "Choose a bot from the sidebar to see its role, memory and runs."}</p>
        {agent ? <div className="profile-tags"><span><Brain size={13} /> {agent.memory_scope === "shared" ? "Shared memory" : "Private memory"}</span>{agent.model ? <span><Zap size={13} /> {agent.model}</span> : null}</div> : null}
      </div>
      {agent ? <BotEditForm agent={agent} models={runtimeAccount?.models ?? []} onSave={onUpdateAgent} /> : null}
      <div className="info-card runtime-mini-card">
        <div className="card-label-row"><span className="card-label"><Monitor size={14} /> Connection</span><span className={`availability-label ${runtime?.available ? "is-ready" : ""}`}><span className="status-dot" />{runtime ? runtime.available ? "Ready" : "Offline" : "Checking"}</span></div>
        <p>{runtime?.available ? "ChatGPT connected" : runtime?.reason ?? "Connect ChatGPT to send tasks to your bots."}</p>
        {!runtime?.available && !runtimeAccount?.connected ? <button className="text-button text-button-accent" type="button" onClick={onConnectRuntime}>Connect ChatGPT <ArrowUpRight size={13} /></button> : null}
      </div>
      <div className="info-card quick-actions-card">
        <div className="card-label-row"><span className="card-label"><SlidersHorizontal size={14} /> Quick actions</span></div>
        <button className="quick-action" type="button" onClick={onCompact} disabled={!selectedConversation}><span><Sparkles size={15} /><strong>Compact this chat</strong></span><ChevronRight size={15} /></button>
        <button className="quick-action" type="button" onClick={() => onConnectRuntime()}><span><Link2 size={15} /><strong>Manage connections</strong></span><ChevronRight size={15} /></button>
      </div>
      <p className="info-footnote"><LockKeyhole size={13} /> Your memory and files are scoped to this workspace.</p>
    </div>
  );
}

function BotEditForm({ agent, models, onSave }: { agent: Agent; models: RuntimeAccount["models"]; onSave: (id: string, input: Partial<AgentInput>) => Promise<void> }): JSX.Element {
  const [name, setName] = useState(agent.name);
  const [description, setDescription] = useState(agent.description ?? "");
  const [model, setModel] = useState(agent.model ?? "");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setName(agent.name);
    setDescription(agent.description ?? "");
    setModel(agent.model ?? "");
    setEditing(false);
    setError(null);
    setSaved(false);
  }, [agent.id, agent.name, agent.description, agent.model]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await onSave(agent.id, { name: name.trim(), description: description.trim(), model: model || undefined });
      setEditing(false);
      setSaved(true);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  if (!editing) {
    return <div className="bot-edit-section"><div className="card-label-row"><span className="card-label"><SlidersHorizontal size={14} /> Bot settings</span><button className="text-button" type="button" onClick={() => { setSaved(false); setEditing(true); }}>Edit</button></div>{saved ? <p className="edit-saved" role="status"><Check size={13} /> Saved</p> : <p className="bot-edit-summary">Update the name, instructions, or model for this bot.</p>}</div>;
  }

  return <form className="bot-edit-section bot-edit-form" onSubmit={(event) => void submit(event)}>
    <div className="card-label-row"><span className="card-label"><SlidersHorizontal size={14} /> Bot settings</span><button className="text-button" type="button" onClick={() => { setEditing(false); setError(null); }}>Cancel</button></div>
    <label htmlFor={`bot-name-${agent.id}`}>Name</label>
    <input id={`bot-name-${agent.id}`} value={name} onChange={(event) => setName(event.target.value)} required />
    <label htmlFor={`bot-instructions-${agent.id}`}>Instructions</label>
    <textarea id={`bot-instructions-${agent.id}`} value={description} onChange={(event) => setDescription(event.target.value)} rows={3} placeholder="Give this bot a clear job." />
    <label htmlFor={`bot-model-${agent.id}`}>Model</label>
    <select id={`bot-model-${agent.id}`} value={model} onChange={(event) => setModel(event.target.value)}>
      <option value="">Runtime default</option>
      {agent.model && !models?.some((item) => item.id === agent.model) ? <option value={agent.model}>{agent.model}</option> : null}
      {models?.map((item) => <option value={item.id} key={item.id}>{item.name || item.id}</option>)}
    </select>
    {error ? <p className="form-error" role="alert"><AlertCircle size={14} /> {error}</p> : null}
    <button className="button button-secondary button-small" type="submit" disabled={!name.trim() || busy}>{busy ? <Loader2 size={14} className="spin" /> : <Check size={14} />} Save bot</button>
  </form>;
}

function ComputerPanel({ runtime, runtimeAccount, desktop, onConnectRuntime, onDesktopAction }: { runtime: RuntimeStatus | null; runtimeAccount: RuntimeAccount | null; desktop: DesktopStatus | null; onConnectRuntime: () => void; onDesktopAction: (action: "create" | "start" | "stop") => Promise<void> }): JSX.Element {
  const ready = Boolean(runtime?.available && runtimeAccount?.connected);
  const created = Boolean(desktop?.created);
  const running = Boolean(desktop?.running);
  return (
    <div className="info-section-stack">
      <div className="computer-hero"><div className="computer-screen"><div className="screen-top"><span /><span /><span /></div><div className="screen-lines"><i /><i /><i /><i /><i /></div><div className="screen-cursor" /></div><span className="computer-badge"><Monitor size={14} /> Agent computer</span><h3>{running ? "Computer is ready" : created ? "Computer is paused" : "Add an agent computer"}</h3><p>{running ? "Your bot can use the persistent browser profile when a task needs it." : "Create it once, then start it only when a run needs a browser or desktop."}</p></div>
      {running && desktop?.view_url ? <div className="desktop-preview desktop-preview-mini"><iframe src={desktop.view_url} title="Agent computer preview" /><a className="desktop-open-link" href={desktop.view_url} target="_blank" rel="noreferrer">Open full screen <ExternalLink size={13} /></a></div> : null}
      <div className="info-card"><div className="card-label-row"><span className="card-label"><Wifi size={14} /> Connection</span><span className={`availability-label ${ready ? "is-ready" : ""}`}><span className="status-dot" />{ready ? "Connected" : "Not connected"}</span></div><p>{runtime?.reason ?? (ready ? "ChatGPT runtime available." : "Connect ChatGPT before starting real work.")}</p>{!ready ? <button className="button button-secondary button-small button-wide" type="button" onClick={onConnectRuntime}>Connect ChatGPT <ArrowUpRight size={14} /></button> : null}</div>
      <div className="info-card"><div className="card-label-row"><span className="card-label"><Monitor size={14} /> Desktop</span><span className={`availability-label ${running ? "is-ready" : ""}`}><span className="status-dot" />{running ? "Running" : created ? "Paused" : "Not created"}</span></div><p>{desktop?.reason ?? (running ? "Persistent browser profile available." : "No desktop is running.")}</p>{!created ? <button className="button button-primary button-small button-wide" type="button" onClick={() => void onDesktopAction("create")}>Create computer <Plus size={14} /></button> : running ? <button className="button button-secondary button-small button-wide" type="button" onClick={() => void onDesktopAction("stop")}>Pause computer</button> : <button className="button button-primary button-small button-wide" type="button" onClick={() => void onDesktopAction("start")}>Resume computer <Zap size={14} /></button>}</div>
      <div className="info-card info-list-card"><div className="card-label-row"><span className="card-label"><ShieldCheck size={14} /> Human control</span></div><p>Watch the desktop and take over for sign-in or verification. Approval prompts appear when the runtime requests them.</p></div>
    </div>
  );
}

function MemoryPanel({ memory, skills, compact = false, onToggleSkill, onDeleteSkill }: { memory: MemoryItem[]; skills: LearnedSkill[]; compact?: boolean; onToggleSkill: (id: string, enabled: boolean) => Promise<void>; onDeleteSkill: (id: string) => Promise<void> }): JSX.Element {
  const items = compact ? memory.slice(0, 4) : memory;
  return (
    <div className="info-section-stack"><div className="resource-head"><div><h3>{memory.length ? `${memory.length} memory ${memory.length === 1 ? "item" : "items"}` : "No memory yet"}</h3></div><Brain size={18} className="resource-head-icon" /></div>{items.length > 0 ? <div className="mini-list">{items.map((item) => <div className="mini-list-item" key={item.id}><span className={`scope-mark scope-${item.scope}`} /> <p>{item.content}</p><small>{item.scope}</small></div>)}</div> : <EmptyResource icon={<Brain size={20} />} title="Memory grows with use" copy="Save a preference or a useful detail here for your bot to remember." />}<SkillPanel skills={skills} onToggle={onToggleSkill} onDelete={onDeleteSkill} /></div>
  );
}

function SkillPanel({ skills, onToggle, onDelete }: { skills: LearnedSkill[]; onToggle: (id: string, enabled: boolean) => Promise<void>; onDelete: (id: string) => Promise<void> }): JSX.Element {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toggle = async (skill: LearnedSkill) => {
    if (busyId) return;
    setBusyId(skill.id);
    setError(null);
    try { await onToggle(skill.id, !skill.enabled); } catch (reason) { setError(errorMessage(reason)); } finally { setBusyId(null); }
  };
  const remove = async (skill: LearnedSkill) => {
    if (busyId) return;
    setBusyId(skill.id);
    setError(null);
    try { await onDelete(skill.id); } catch (reason) { setError(errorMessage(reason)); } finally { setBusyId(null); }
  };
  return <div className="skill-panel"><div className="card-label-row"><span className="card-label"><Zap size={14} /> Learned procedures</span><span className="skill-panel-count">{skills.length}</span></div>{skills.length ? skills.slice(0, 4).map((skill) => <details className="skill-mini" key={skill.id}><summary><span className={`skill-state ${skill.enabled === false ? "is-disabled" : ""}`} /><span>{skill.name}</span><ChevronRight size={13} /></summary><div className="skill-mini-detail"><p>{skill.instructions || "No procedure details."}</p><div className="skill-actions"><button className="button button-secondary button-small" type="button" disabled={busyId === skill.id} onClick={() => void toggle(skill)}>{busyId === skill.id ? <Loader2 size={12} className="spin" /> : null}{skill.enabled === false ? "Enable" : "Disable"}</button><button className="text-button text-button-danger" type="button" disabled={busyId === skill.id} onClick={() => void remove(skill)}><Trash2 size={13} /></button></div></div></details>) : <p className="skill-empty">Verified procedures will appear after a successful run.</p>}{error ? <p className="form-error" role="alert"><AlertCircle size={13} /> {error}</p> : null}</div>;
}

function FilesPanel({ files, compact = false }: { files: FileAsset[]; compact?: boolean }): JSX.Element {
  const items = compact ? files.slice(0, 4) : files;
  return (
    <div className="info-section-stack"><div className="resource-head"><div><h3>{files.length ? `${files.length} ${files.length === 1 ? "file" : "files"}` : "No files yet"}</h3></div><FolderOpen size={18} className="resource-head-icon" /></div>{items.length > 0 ? <div className="mini-list">{items.map((file) => <div className="mini-list-item file-mini-item" key={file.id}><span className="file-type-icon"><FileText size={15} /></span><p>{file.name}<small>{formatBytes(file.size)}</small></p><span className="file-status">{file.status ?? "Ready"}</span></div>)}</div> : <EmptyResource icon={<FolderOpen size={20} />} title="Bring context with you" copy="Upload a file from the composer or Files to share it with your bot." />}</div>
  );
}

function ActivityPanel({ activity, compact = false }: { activity: ActivityItem[]; compact?: boolean }): JSX.Element {
  const items = compact ? activity.slice(0, 5) : activity;
  return (
    <div className="info-section-stack"><div className="resource-head"><div><h3>{activity.length ? "What’s happening" : "No activity yet"}</h3></div><Activity size={18} className="resource-head-icon" /></div>{items.length > 0 ? <div className="activity-list">{items.map((item) => <div className="activity-item" key={item.id}><span className={`activity-icon activity-${item.status ?? "complete"}`}>{item.status === "running" ? <Loader2 size={14} className="spin" /> : item.status === "failed" ? <AlertCircle size={14} /> : <Check size={14} />}</span><div><strong>{item.title}</strong><p>{item.detail ?? item.kind ?? "Run"}</p></div><time>{formatDate(item.created_at)}</time></div>)}</div> : <EmptyResource icon={<Activity size={20} />} title="Your run history lives here" copy="Completed work, approvals and errors will show up as they happen." />}</div>
  );
}

function EmptyResource({ icon, title, copy }: { icon: JSX.Element; title: string; copy: string }): JSX.Element {
  return <div className="empty-resource"><span>{icon}</span><strong>{title}</strong><p>{copy}</p></div>;
}

interface ResourceViewProps {
  onLogout: () => Promise<void>;
  view: View;
  agent: Agent | null;
  memory: MemoryItem[];
  skills: LearnedSkill[];
  files: FileAsset[];
  activity: ActivityItem[];
  theme: Theme;
  runtimeAccount: RuntimeAccount | null;
  runtimeUsage: RuntimeUsage | null;
  runtimeLogin: RuntimeLogin | null;
  runtimeConnecting: boolean;
  runtimeError: string | null;
  onThemeChange: (theme: Theme) => void;
  onAddMemory: (content: string, scope: "shared" | "private") => Promise<void>;
  onDeleteMemory: (id: string, agentId?: string) => Promise<void>;
  onToggleSkill: (id: string, enabled: boolean) => Promise<void>;
  onDeleteSkill: (id: string) => Promise<void>;
  onUpload: (file: File) => Promise<FileAsset>;
  onDeleteFile: (id: string) => Promise<void>;
  onConnectRuntime: () => void;
  onRefreshRuntime: () => void;
  onResetOnboarding: () => void;
  desktop: DesktopStatus | null;
  desktopBusy: boolean;
  desktopError: string | null;
  onDesktopAction: (action: "create" | "start" | "stop") => Promise<void>;
}

function ResourceView({
  onLogout,
  view,
  agent,
  memory,
  skills,
  files,
  activity,
  theme,
  runtimeAccount,
  runtimeUsage,
  runtimeLogin,
  runtimeConnecting,
  runtimeError,
  onThemeChange,
  onAddMemory,
  onDeleteMemory,
  onToggleSkill,
  onDeleteSkill,
  onUpload,
  onDeleteFile,
  onConnectRuntime,
  onRefreshRuntime,
  onResetOnboarding,
  desktop,
  desktopBusy,
  desktopError,
  onDesktopAction,
}: ResourceViewProps): JSX.Element {
  const title = view === "memory" ? "Memory" : view === "files" ? "Files" : view === "activity" ? "Activity" : "Settings";
  const description = view === "memory"
    ? "Context your bots can use across conversations."
    : view === "files"
      ? "Files you have shared with this workspace."
      : view === "activity"
        ? "A clear record of runs, approvals and results."
        : "Account, appearance and app settings.";
  return (
    <section className="resource-view">
      <div className="resource-toolbar"><div><h1>{title}</h1><p>{description}</p></div><div className="resource-toolbar-agent">{agent ? <><AgentAvatar agent={agent} size="small" /><span>{agent.name}</span></> : <span>All bots</span>}</div></div>
      {view === "memory" ? <MemoryResource memory={memory} agent={agent} skills={skills} onAdd={onAddMemory} onDelete={onDeleteMemory} onToggleSkill={onToggleSkill} onDeleteSkill={onDeleteSkill} /> : null}
      {view === "files" ? <FilesResource files={files} onUpload={onUpload} onDelete={onDeleteFile} /> : null}
      {view === "activity" ? <ActivityResource activity={activity} /> : null}
      {view === "settings" ? <SettingsResource theme={theme} runtimeAccount={runtimeAccount} runtimeUsage={runtimeUsage} runtimeLogin={runtimeLogin} runtimeConnecting={runtimeConnecting} runtimeError={runtimeError} desktop={desktop} desktopBusy={desktopBusy} desktopError={desktopError} onThemeChange={onThemeChange} onConnectRuntime={onConnectRuntime} onRefreshRuntime={onRefreshRuntime} onResetOnboarding={onResetOnboarding} onDesktopAction={onDesktopAction} /> : null}
      {view === "settings" ? <button className="button button-secondary settings-signout" onClick={() => void onLogout()}><LogOut size={15}/> Sign out</button> : null}
    </section>
  );
}

function MemoryResource({ memory, agent, skills, onAdd, onDelete, onToggleSkill, onDeleteSkill }: { memory: MemoryItem[]; agent: Agent | null; skills: LearnedSkill[]; onAdd: (content: string, scope: "shared" | "private") => Promise<void>; onDelete: (id: string, agentId?: string) => Promise<void>; onToggleSkill: (id: string, enabled: boolean) => Promise<void>; onDeleteSkill: (id: string) => Promise<void> }): JSX.Element {
  const [content, setContent] = useState("");
  const [scope, setScope] = useState<"shared" | "private">("private");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const submit = async () => {
    if (!content.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(content, scope);
      setContent("");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const remove = async (item: MemoryItem) => {
    if (deletingId) return;
    setDeletingId(item.id);
    setError(null);
    try {
      await onDelete(item.id, item.scope === "private" ? item.agent_id ?? agent?.id ?? undefined : undefined);
    } catch (reason) {
      setError(`Couldn’t delete memory: ${errorMessage(reason)}`);
    } finally {
      setDeletingId(null);
    }
  };
  return (
    <div className="resource-layout"><div className="resource-main-card"><div className="resource-card-heading"><div><span className="card-label"><Brain size={15} /> Add memory</span><h2>Save a preference or instruction</h2><p>Write a preference, instruction or fact. You choose who can use it.</p></div><span className="resource-count">{memory.length}</span></div><textarea aria-label="Memory content" className="resource-textarea" value={content} onChange={(event) => setContent(event.target.value)} placeholder={agent ? `e.g. ${agent.name} should keep answers short` : "e.g. Keep answers short"} rows={4} /><div className="resource-form-row"><div className="segmented-control" role="group" aria-label="Memory scope"><button type="button" className={scope === "private" ? "is-active" : ""} onClick={() => setScope("private")}><LockKeyhole size={14} /> Private</button><button type="button" className={scope === "shared" ? "is-active" : ""} onClick={() => setScope("shared")}><Users size={14} /> Shared</button></div><button className="button button-primary" type="button" disabled={!content.trim() || busy} onClick={() => void submit()}>{busy ? <Loader2 size={15} className="spin" /> : <Plus size={15} />} Save memory</button></div>{error ? <p className="form-error" role="alert"><AlertCircle size={14} /> {error}</p> : null}</div><div className="resource-list-card"><div className="list-card-heading"><h2>Saved context</h2><span>{memory.length}</span></div>{memory.length ? <div className="memory-list">{memory.map((item) => <div className="memory-item" key={item.id}><span className={`scope-mark scope-${item.scope}`} /><div><p>{item.content}</p><span><small>{item.scope === "shared" ? "Shared with all bots" : "Private to this bot"}</small>{item.updated_at ? <small>{formatDate(item.updated_at)}</small> : null}</span></div><button className="icon-button icon-button-small" type="button" aria-label={`Delete memory: ${item.content}`} disabled={Boolean(deletingId)} onClick={() => void remove(item)}>{deletingId === item.id ? <Loader2 size={15} className="spin" /> : <Trash2 size={15} />}</button></div>)}</div> : <EmptyResource icon={<Brain size={22} />} title="Nothing saved yet" copy="Add the details you want Hermes to remember." />}</div><SkillResource skills={skills} onToggle={onToggleSkill} onDelete={onDeleteSkill} /></div>
  );
}

function SkillResource({ skills, onToggle, onDelete }: { skills: LearnedSkill[]; onToggle: (id: string, enabled: boolean) => Promise<void>; onDelete: (id: string) => Promise<void> }): JSX.Element {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toggle = async (skill: LearnedSkill) => {
    if (busyId) return;
    setBusyId(skill.id);
    setError(null);
    try {
      await onToggle(skill.id, !skill.enabled);
    } catch (reason) {
      setError(`Couldn’t update procedure: ${errorMessage(reason)}`);
    } finally {
      setBusyId(null);
    }
  };
  const remove = async (skill: LearnedSkill) => {
    if (busyId) return;
    setBusyId(skill.id);
    setError(null);
    try {
      await onDelete(skill.id);
    } catch (reason) {
      setError(`Couldn’t delete procedure: ${errorMessage(reason)}`);
    } finally {
      setBusyId(null);
    }
  };
  return <section className="learned-skills-card" aria-labelledby="learned-skills-title"><div className="resource-card-heading"><div><span className="card-label"><Zap size={15} /> Learned procedures</span><h2 id="learned-skills-title">Procedures your bot verified</h2><p>Saved after a successful run. Disable one when you want to pause it.</p></div><span className="resource-count">{skills.length}</span></div>{skills.length ? <div className="skill-list">{skills.map((skill) => <details className="skill-item" key={skill.id}><summary><span className={`skill-state ${skill.enabled === false ? "is-disabled" : ""}`} /><span>{skill.name}</span><ChevronRight size={15} /></summary><div className="skill-detail"><p>{skill.instructions || "No procedure details were provided."}</p>{skill.trigger ? <span><strong>Trigger:</strong> {skill.trigger}</span> : null}{skill.evidence ? <span><strong>Evidence:</strong> {skill.evidence}</span> : null}{skill.revision ? <span>Revision {skill.revision}</span> : null}<div className="skill-actions"><button className="button button-secondary button-small" type="button" disabled={busyId === skill.id} onClick={() => void toggle(skill)}>{busyId === skill.id ? <Loader2 size={13} className="spin" /> : null}{skill.enabled === false ? "Enable" : "Disable"}</button><button className="text-button text-button-danger" type="button" disabled={busyId === skill.id} onClick={() => void remove(skill)}><Trash2 size={14} /> Delete</button></div></div></details>)}</div> : <EmptyResource icon={<Zap size={22} />} title="No learned procedures" copy="Verified procedures will appear here after a bot completes one." />}{error ? <p className="form-error" role="alert"><AlertCircle size={14} /> {error}</p> : null}</section>;
}

function FilesResource({ files, onUpload, onDelete }: { files: FileAsset[]; onUpload: (file: File) => Promise<FileAsset>; onDelete: (id: string) => Promise<void> }): JSX.Element {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await onUpload(file);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return <div className="resource-layout"><div className="upload-card"><div className="upload-icon"><Upload size={21} /></div><h2>Upload a file</h2><p>Upload notes, PDFs or documents to make a run more useful.</p><button className="button button-primary" type="button" disabled={busy} onClick={() => inputRef.current?.click()}>{busy ? <Loader2 size={15} className="spin" /> : <Upload size={15} />} Upload a file</button><input ref={inputRef} className="visually-hidden" type="file" onChange={(event) => void handleFile(event)} /><span className="upload-note">Files stay in your private workspace.</span>{error ? <p className="form-error"><AlertCircle size={14} /> {error}</p> : null}</div><div className="resource-list-card"><div className="list-card-heading"><h2>Workspace files</h2><span>{files.length}</span></div>{files.length ? <div className="files-list">{files.map((file) => <div className="file-row" key={file.id}><span className="file-type-icon"><FileText size={18} /></span><div><strong>{file.name}</strong><span>{formatBytes(file.size)}{file.created_at ? ` · ${formatDate(file.created_at)}` : ""}</span></div><span className="file-status">{file.status ?? "Ready"}</span><button className="icon-button icon-button-small" type="button" aria-label={`Delete ${file.name}`} onClick={() => void onDelete(file.id)}><Trash2 size={15} /></button></div>)}</div> : <EmptyResource icon={<FolderOpen size={22} />} title="No files shared" copy="Upload the first piece of context from here or the chat composer." />}</div></div>;
}

function ActivityResource({ activity }: { activity: ActivityItem[] }): JSX.Element {
  return <div className="resource-single-card resource-activity-card"><div className="resource-card-heading"><div><span className="card-label"><Activity size={15} /> Run history</span><h2>Recent activity</h2><p>Every run, approval and error has a place here.</p></div><span className="resource-count">{activity.length}</span></div>{activity.length ? <div className="activity-list activity-list-wide">{activity.map((item) => <div className="activity-item" key={item.id}><span className={`activity-icon activity-${item.status ?? "complete"}`}>{item.status === "running" ? <Loader2 size={14} className="spin" /> : item.status === "failed" ? <AlertCircle size={14} /> : <Check size={14} />}</span><div><strong>{item.title}</strong><p>{item.detail ?? item.kind ?? "Run"}</p></div><span className="activity-agent">{item.agent_id ? "Bot" : "Workspace"}</span><time>{formatDate(item.created_at)}</time></div>)}</div> : <EmptyResource icon={<Activity size={22} />} title="No runs yet" copy="When a bot starts work, progress and results will appear here." />}</div>;
}

interface SettingsResourceProps {
  theme: Theme;
  runtimeAccount: RuntimeAccount | null;
  runtimeUsage: RuntimeUsage | null;
  runtimeLogin: RuntimeLogin | null;
  runtimeConnecting: boolean;
  runtimeError: string | null;
  desktop: DesktopStatus | null;
  desktopBusy: boolean;
  desktopError: string | null;
  onThemeChange: (theme: Theme) => void;
  onConnectRuntime: () => void;
  onRefreshRuntime: () => void;
  onResetOnboarding: () => void;
  onDesktopAction: (action: "create" | "start" | "stop") => Promise<void>;
}

function SettingsResource({
  theme,
  runtimeAccount,
  runtimeUsage,
  runtimeLogin,
  runtimeConnecting,
  runtimeError,
  desktop,
  desktopBusy,
  desktopError,
  onThemeChange,
  onConnectRuntime,
  onRefreshRuntime,
  onResetOnboarding,
  onDesktopAction,
}: SettingsResourceProps): JSX.Element {
  return (
    <div className="settings-layout">
      <div className="settings-card">
        <div className="settings-card-head"><div><span className="card-label"><SlidersHorizontal size={15} /> Appearance</span><h2>Theme</h2><p>Choose your preferred appearance.</p></div><Sun size={19} className="resource-head-icon" /></div>
        <div className="theme-options" role="radiogroup" aria-label="Theme">
          <ThemeOption value="system" label="System" icon={<Monitor size={17} />} theme={theme} onThemeChange={onThemeChange} />
          <ThemeOption value="light" label="Light" icon={<Sun size={17} />} theme={theme} onThemeChange={onThemeChange} />
          <ThemeOption value="dark" label="Dark" icon={<Moon size={17} />} theme={theme} onThemeChange={onThemeChange} />
        </div>
      </div>
      <div className="settings-card">
        <div className="settings-card-head"><div><span className="card-label"><Link2 size={15} /> ChatGPT account</span><h2>Connect ChatGPT.</h2><p>Connect your ChatGPT account to run tasks.</p></div><span className={`settings-status ${runtimeAccount?.connected ? "is-connected" : ""}`}><span className="status-dot" />{runtimeAccount?.connected ? "Connected" : "Not connected"}</span></div>
        {runtimeAccount?.connected ? <div className="connected-account"><div className="connected-icon"><Check size={18} /></div><div><strong>{runtimeAccount.type ?? "ChatGPT account"}</strong><span>{runtimeAccount.plan ? `${runtimeAccount.plan} plan` : "Connected for this workspace"}</span></div><button className="button button-secondary button-small" type="button" onClick={onRefreshRuntime}><RefreshCw size={14} /> Refresh</button></div> : <RuntimeConnectCard login={runtimeLogin} connecting={runtimeConnecting} error={runtimeError} onConnect={onConnectRuntime} />}
        {runtimeUsage ? <div className="usage-row"><span><Activity size={14} /> Usage</span><strong>{usageSummary(runtimeUsage)}</strong>{usageResetAt(runtimeUsage) ? <small>Resets {formatDate(usageResetAt(runtimeUsage))}</small> : null}</div> : null}
      </div>
      <DesktopSettingsCard desktop={desktop} busy={desktopBusy} error={desktopError} onAction={onDesktopAction} />
      <div className="settings-card install-card"><div className="settings-card-head"><div><span className="card-label"><Download size={15} /> Get the app</span><h2>Install the app</h2><p>On iPhone, use Safari’s Share menu and choose Add to Home Screen. On desktop, use the install icon in your browser’s address bar.</p></div><Laptop size={19} className="resource-head-icon" /></div><button className="button button-secondary" type="button" onClick={onResetOnboarding}><Sparkles size={15} /> Show setup guide</button></div>
    </div>
  );
}

function ThemeOption({ value, label, icon, theme, onThemeChange }: { value: Theme; label: string; icon: JSX.Element; theme: Theme; onThemeChange: (theme: Theme) => void }): JSX.Element {
  return <button className={`theme-option ${theme === value ? "is-selected" : ""}`} type="button" role="radio" aria-checked={theme === value} onClick={() => onThemeChange(value)}>{icon}<span>{label}</span>{theme === value ? <Check size={15} /> : null}</button>;
}

function RuntimeConnectCard({ login, connecting, error, onConnect }: { login: RuntimeLogin | null; connecting: boolean; error: string | null; onConnect: () => void }): JSX.Element {
  return <div className="runtime-connect-card">{login ? <><div className="device-code-label"><span className="status-dot status-dot-green" />Waiting for confirmation</div><p>Open the official sign-in page, enter this code, then come back here.</p><div className="device-code-row"><code>{login.userCode}</code><button className="icon-button icon-button-small" type="button" aria-label="Copy sign-in code" title="Copy code" onClick={() => void navigator.clipboard?.writeText(login.userCode)}><Copy size={15} /></button></div><a className="button button-primary button-small button-wide" href={login.verificationUrl} target="_blank" rel="noreferrer">Open verification page <ExternalLink size={14} /></a><small>Hermes checks for completion only while this card is open.</small></> : <><p>Connect your ChatGPT account with a one-time device code. No password is copied into Hermes.</p><button className="button button-primary button-small" type="button" onClick={onConnect} disabled={connecting}>{connecting ? <><Loader2 size={14} className="spin" /> Starting sign-in…</> : <><Link2 size={14} /> Start device sign-in</>}</button></>}{error ? <p className="form-error"><AlertCircle size={14} /> {error}</p> : null}</div>;
}

function DesktopSettingsCard({ desktop, busy, error, onAction }: { desktop: DesktopStatus | null; busy: boolean; error: string | null; onAction: (action: "create" | "start" | "stop") => Promise<void> }): JSX.Element {
  const running = Boolean(desktop?.running);
  const created = Boolean(desktop?.created);
  return <div className="settings-card desktop-settings-card"><div className="settings-card-head"><div><span className="card-label"><Monitor size={15} /> Agent computer</span><h2>{running ? "Computer is running." : created ? "Computer is paused." : "Add an agent computer."}</h2><p>{running ? "Your bot can use the persistent browser profile when a task needs it." : "Create it once, then start it only when a run needs a browser or desktop."}</p></div><span className={`settings-status ${running ? "is-connected" : ""}`}><span className="status-dot" />{running ? "Running" : created ? "Paused" : "Not created"}</span></div>{running && desktop?.view_url ? <div className="desktop-preview"><iframe src={desktop.view_url} title="Agent computer preview" allow="clipboard-read; clipboard-write" /><a className="desktop-open-link" href={desktop.view_url} target="_blank" rel="noreferrer">Open full screen <ExternalLink size={13} /></a></div> : null}<div className="desktop-actions">{!created ? <button className="button button-primary button-small" type="button" onClick={() => void onAction("create")} disabled={busy}>{busy ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Create computer</button> : running ? <button className="button button-secondary button-small" type="button" onClick={() => void onAction("stop")} disabled={busy}>{busy ? <Loader2 size={14} className="spin" /> : <span className="pause-glyph" />} Pause</button> : <button className="button button-primary button-small" type="button" onClick={() => void onAction("start")} disabled={busy}>{busy ? <Loader2 size={14} className="spin" /> : <Zap size={14} />} Resume</button>}{error ? <span className="form-error"><AlertCircle size={14} /> {error}</span> : null}</div></div>;
}

function OnboardingModal({ userName, runtimeAccount, runtimeLogin, runtimeConnecting, runtimeError, onConnectRuntime, onClose }: { userName: string; runtimeAccount: RuntimeAccount | null; runtimeLogin: RuntimeLogin | null; runtimeConnecting: boolean; runtimeError: string | null; onConnectRuntime: () => void; onClose: () => void }): JSX.Element {
  const [step, setStep] = useState(0);
  const steps = [
    { eyebrow: "Start here", title: `Welcome, ${userName}.`, copy: "Create a bot, give it a job, and start a conversation.", icon: <Sparkles size={22} />, body: <div className="onboarding-points"><div><span>01</span><p><strong>Pick a bot</strong><br />Each one has its own role and context.</p></div><div><span>02</span><p><strong>Share context</strong><br />Memory and files stay close to the work.</p></div><div><span>03</span><p><strong>Stay in control</strong><br />Watch progress and stop a run at any time.</p></div></div> },
    { eyebrow: "On your phone", title: "Add Hermes to your Home Screen.", copy: "On iPhone, open Hermes in Safari, tap Share, then choose Add to Home Screen. Open it straight from your Home Screen when you’re ready.", icon: <Upload size={22} />, body: <div className="phone-guide"><div className="phone-guide-row"><span>1</span><p>Tap the <strong>Share</strong> button in Safari.</p></div><div className="phone-guide-row"><span>2</span><p>Choose <strong>Add to Home Screen</strong>.</p></div><div className="phone-guide-row"><span>3</span><p>Tap <strong>Add</strong>, then open Hermes from your Home Screen.</p></div></div> },
    { eyebrow: "On your computer", title: "Install it beside your other apps.", copy: "In Chrome or Edge, use the install icon in the address bar or the browser menu. Your bots will be waiting on the same account.", icon: <Laptop size={22} />, body: <div className="desktop-guide"><div className="browser-chrome"><span /><span /><span /><div className="browser-address">hermes / bot mode <Download size={13} /></div></div><p>Look for the install icon near the address bar, or open the browser menu and choose <strong>Install Hermes</strong>.</p></div> },
    { eyebrow: "Ready when you are", title: "Connect ChatGPT.", copy: runtimeAccount?.connected ? "Your ChatGPT runtime is connected. Create a bot and send it a task when you’re ready." : "Connect your ChatGPT account to start sending tasks. You can also do this later in Settings.", icon: <Link2 size={22} />, body: runtimeAccount?.connected ? <div className="onboarding-connected"><Check size={18} /><span>ChatGPT connected</span></div> : runtimeLogin || runtimeConnecting || runtimeError ? <RuntimeConnectCard login={runtimeLogin} connecting={runtimeConnecting} error={runtimeError} onConnect={onConnectRuntime} /> : <div className="onboarding-connect"><button className="button button-secondary" type="button" onClick={onConnectRuntime}><Link2 size={15} /> Connect ChatGPT</button><span>You can skip this and connect from Settings.</span></div> },
  ];
  const current = steps[step];
  return <div className="dialog-layer onboarding-layer"><button className="scrim" type="button" aria-label="Close setup guide" onClick={onClose} /><section className="onboarding-card" role="dialog" aria-modal="true" aria-labelledby="onboarding-title"><div className="onboarding-visual"><BrandMark /><div className="onboarding-orbit" aria-hidden="true"><span /><span /><span /></div><div className="onboarding-step-count">{String(step + 1).padStart(2, "0")} <span>/ 04</span></div></div><div className="onboarding-copy"><div className="dialog-head"><div><h2 id="onboarding-title">{current.title}</h2></div><button className="icon-button" type="button" aria-label="Close" onClick={onClose}><X size={19} /></button></div><p className="dialog-copy">{current.copy}</p><div className="onboarding-body-icon">{current.icon}</div>{current.body}<div className="onboarding-footer"><div className="step-dots">{steps.map((item, index) => <button type="button" key={item.eyebrow} aria-label={`Go to setup step ${index + 1}`} className={index === step ? "is-active" : ""} onClick={() => setStep(index)} />)}</div><button className="button button-primary" type="button" onClick={() => step === steps.length - 1 ? onClose() : setStep(step + 1)}>{step === steps.length - 1 ? "Done" : "Continue"}<ChevronRight size={16} /></button></div></div></section></div>;
}

export default App;

