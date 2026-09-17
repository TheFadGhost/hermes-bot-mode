import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileImage,
  Link2,
  Loader2,
  LockKeyhole,
  Mic,
  Monitor,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { LucideIcon } from "lucide-react";
import {
  createConnectionLink,
  createPrivateField,
  createTeaching,
  deletePrivateField,
  deleteTeaching,
  disconnectConnection,
  listConnections,
  submitPrivateRequest,
  transcribeVoice,
  updateTeaching,
  uploadFile,
} from "../lib/api";
import type {
  Agent,
  ChatRequest,
  ConnectionAccount,
  ConnectionCatalogItem,
  ConnectionsResponse,
  ExtensionsStatus,
  LearnedSkill,
  PrivateField,
  Teaching,
} from "../lib/types";
import { Disclosure } from "./Disclosure";

export type ExpansionSheet = "connections" | "private" | "teach" | null;

export type ExpansionActionId =
  | "attach"
  | "dictate"
  | "private"
  | "connections"
  | "teach"
  | "computer"
  | "settings"
  | "procedure";

export type ExpansionAction = {
  id: ExpansionActionId;
  label: string;
  description: string;
  icon: LucideIcon;
  kind?: "Action" | "Procedure";
  teachingId?: string;
};

function textValue(data: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = data[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function payloadText(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (value === null || value === undefined) return null;
  if (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0) return null;
  try {
    const serialized = JSON.stringify(value, null, 2);
    return typeof serialized === "string" && serialized !== "{}" ? serialized : null;
  } catch {
    return null;
  }
}

function formatDate(value?: string | number | null): string {
  if (value === undefined || value === null || value === "") return "";
  const numeric = typeof value === "number" || /^\d+(?:\.\d+)?$/.test(String(value)) ? Number(value) : Number.NaN;
  const date = Number.isFinite(numeric) ? new Date(numeric < 1_000_000_000_000 ? numeric * 1000 : numeric) : new Date(String(value));
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function errorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong. Try again.";
}

function stopTracks(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop());
}

export function actionItems(status: ExtensionsStatus | null, teachings: Teaching[], skills: LearnedSkill[]): ExpansionAction[] {
  const actions: ExpansionAction[] = [
    { id: "attach", label: "Attach a file", description: "Add a document or image to this draft.", icon: Plus },
    { id: "dictate", label: "Dictate", description: status?.voice.configured === false ? "Voice setup is needed first." : "Record a short note for review.", icon: Mic },
    { id: "private", label: "Private input", description: status?.private_input.available === false ? "Private input is unavailable right now." : "Save a labelled value outside chat.", icon: LockKeyhole },
    { id: "connections", label: "Connections", description: status?.connections.configured === false ? "Connections setup is needed first." : "Connect a business service.", icon: Link2 },
    { id: "teach", label: "Teach a task", description: "Write and review a procedure with optional stills.", icon: Play },
    { id: "computer", label: "Computer", description: "Open the Bot computer and take control.", icon: Monitor },
    { id: "settings", label: "Settings", description: "Open Bot and account settings.", icon: Zap },
  ];
  const procedures = [
    ...teachings.map((teaching) => ({ id: "procedure" as const, label: teaching.name, description: "Human-taught procedure", icon: Play, kind: "Procedure" as const, teachingId: teaching.id })),
    ...skills.map((skill) => ({ id: "procedure" as const, label: skill.name, description: "Verified procedure", icon: Check, kind: "Procedure" as const })),
  ];
  return [...actions, ...procedures];
}

export function ActionMenu({ actions, open, mode, query, onQuery, onSelect, onClose }: {
  actions: ExpansionAction[];
  open: boolean;
  mode: "plus" | "slash";
  query: string;
  onQuery: (value: string) => void;
  onSelect: (action: ExpansionAction) => void;
  onClose: () => void;
}): JSX.Element | null {
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return actions.filter((action) => !needle || `${action.label} ${action.description}`.toLowerCase().includes(needle)).slice(0, 12);
  }, [actions, query]);

  useEffect(() => {
    setActive(0);
    if (open && mode === "plus") requestAnimationFrame(() => inputRef.current?.focus());
  }, [mode, open, query]);

  if (!open) return null;
  const choose = (index: number) => { const action = filtered[index]; if (action) onSelect(action); };
  return <div className={`hermes-action-menu hermes-action-menu-${mode}`} role="listbox" aria-label={mode === "slash" ? "Slash commands" : "Composer actions"} onKeyDown={(event) => {
    if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
    if (event.key === "ArrowDown") { event.preventDefault(); setActive((value) => filtered.length ? (value + 1) % filtered.length : 0); return; }
    if (event.key === "ArrowUp") { event.preventDefault(); setActive((value) => filtered.length ? (value + filtered.length - 1) % filtered.length : 0); return; }
    if (event.key === "Enter") { event.preventDefault(); choose(active); }
  }}>
    {mode === "plus" ? <label className="hermes-action-search"><Search size={14} aria-hidden="true" /><input ref={inputRef} aria-label="Search actions" value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search actions" /></label> : <div className="hermes-action-menu-label">Commands</div>}
    {filtered.length ? filtered.map((action, index) => { const Icon = action.icon; return <button key={`${action.id}:${action.teachingId ?? action.label}`} className={index === active ? "is-active" : ""} type="button" role="option" aria-selected={index === active} onMouseEnter={() => setActive(index)} onClick={() => choose(index)}><Icon size={16} aria-hidden="true" /><span><strong>{mode === "slash" && action.id !== "procedure" ? `/${action.label.toLowerCase().replace(/\s+/g, "-")}` : action.label}</strong><small>{action.description}</small></span><em>{action.kind ?? "Action"}</em></button>; }) : <p className="hermes-action-empty">No matching actions.</p>}
  </div>;
}

export function RequestCard({ request, accountId, agentName, onPrivate, onConnection, onDecision, onContinue }: {
  request: ChatRequest;
  accountId?: string;
  agentName?: string;
  onPrivate: (request: ChatRequest) => void;
  onConnection: (request: ChatRequest) => void;
  onDecision: (request: ChatRequest, decision: "approve" | "deny") => void;
  onContinue: (request: ChatRequest) => void;
}): JSX.Element {
  const safeDestination = textValue(request.data, ["destination", "service", "toolkit_name", "toolkit"]);
  const safeAccount = textValue(request.data, ["account_name", "account", "connected_account"]);
  const safeTool = textValue(request.data, ["tool_name", "tool_slug", "tool", "action"]);
  const safeArguments = ["arguments", "redacted_arguments", "args", "parameters"].map((key) => request.data[key]).map(payloadText).find((value): value is string => Boolean(value));
  const safeResult = payloadText(request.result);
  const fields = Array.isArray(request.data.private_fields) ? request.data.private_fields.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item.trim()];
    if (typeof item === "object" && item !== null && "label" in item && typeof item.label === "string" && item.label.trim()) return [item.label.trim()];
    return [];
  }) : [];
  const pending = request.status === "pending" || request.status === "ready";
  const statusLabel = request.status === "pending" ? "Needs you" : request.status === "ready" ? "Ready for approval" : request.status === "executing" ? "Working" : request.status[0]?.toUpperCase() + request.status.slice(1);
  const expires = formatDate(request.expires_at);
  const isCompleted = ["completed", "denied", "expired", "failed", "uncertain"].includes(request.status);
  return <article className={`hermes-request-card hermes-request-${request.status}`} aria-label={request.title}>
    <div className="hermes-request-icon" aria-hidden="true">{request.kind === "private_input" ? <LockKeyhole size={17} /> : request.kind === "connection" ? <Link2 size={17} /> : <ShieldCheck size={17} />}</div>
    <div className="hermes-request-body">
      <div className="hermes-request-heading"><strong>{request.title}</strong><span>{statusLabel}</span></div>
      {request.purpose ? <p>{request.purpose}</p> : null}
      {safeDestination || safeAccount || safeTool ? <div className="hermes-request-meta">{safeDestination ? <span>{safeDestination}</span> : null}{safeAccount ? <span>{safeAccount}</span> : null}{safeTool ? <span>{safeTool}</span> : null}</div> : null}
      {fields.length ? <p className="hermes-request-fields">Uses labelled private fields: {fields.join(", ")}</p> : null}
      {request.kind === "connector_action" && safeArguments ? <div className="hermes-request-arguments"><strong>Review before approving</strong><pre>{safeArguments}</pre></div> : null}
      {expires && pending ? <small className="hermes-request-expiry">Available until {expires}</small> : null}
      {request.error ? <p className="hermes-expansion-error" role="alert">{request.error}</p> : null}
      {isCompleted && safeResult ? <Disclosure accountId={accountId} section="request" id={request.id} label="result"><pre className="hermes-safe-result">{safeResult}</pre></Disclosure> : null}
      {pending ? <div className="hermes-request-actions">{request.kind === "private_input" ? <button className="hermes-expansion-button hermes-expansion-button-primary" type="button" onClick={() => onPrivate(request)}><LockKeyhole size={14} /> Enter value</button> : request.kind === "connection" ? <button className="hermes-expansion-button hermes-expansion-button-primary" type="button" onClick={() => onConnection(request)}><Link2 size={14} /> Connect</button> : <><button className="hermes-expansion-button hermes-expansion-button-primary" type="button" onClick={() => onDecision(request, "approve")}><Check size={14} /> Approve</button><button className="hermes-expansion-button" type="button" onClick={() => onDecision(request, "deny")}>Decline</button></>}</div> : request.status === "completed" ? <div className="hermes-request-actions"><button className="hermes-expansion-button hermes-expansion-button-primary" type="button" onClick={() => onContinue(request)}><ChevronRight size={14} /> Continue with {agentName ?? "this Bot"}</button></div> : null}
    </div>
  </article>;
}

export function ConnectionSheet({ open, status, initialToolkit, onClose, onConnected }: {
  open: boolean;
  status: ExtensionsStatus | null;
  initialToolkit?: string;
  onClose: () => void;
  onConnected?: () => void;
}): JSX.Element | null {
  const [query, setQuery] = useState("");
  const [data, setData] = useState<ConnectionsResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [link, setLink] = useState<{ toolkit: string; url: string } | null>(null);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = async (append = false) => {
    if (append) setLoadingMore(true); else setBusy(true);
    setError(null);
    try {
      const next = await listConnections(query, append ? data?.next_cursor : null);
      setData((current) => append ? { ...next, catalog: [...(current?.catalog ?? []), ...next.catalog] } : next);
    } catch (reason) { setError(errorText(reason)); }
    finally { if (append) setLoadingMore(false); else setBusy(false); }
  };
  useEffect(() => {
    if (!open) return;
    setLink(null); setNotice(null); setDisconnecting(null); void refresh();
    const onFocus = () => { void refresh(); onConnected?.(); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => void refresh(), 240);
    return () => window.clearTimeout(timer);
  }, [open, query]);

  if (!open) return null;
  const connect = async (toolkit: string) => {
    setBusy(true); setError(null); setNotice(null);
    try { const result = await createConnectionLink(toolkit); setLink({ toolkit, url: result.url }); setNotice("Open the sign-in page, then return to Hermes. Connection status is checked again when you come back."); }
    catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  };
  const disconnect = async (account: ConnectionAccount) => {
    if (disconnecting !== account.id) { setDisconnecting(account.id); return; }
    setBusy(true); setError(null);
    try { await disconnectConnection(account.id); setDisconnecting(null); setNotice(`${account.name} disconnected.`); await refresh(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  };
  const accounts = data?.accounts ?? [];
  const catalog = data?.catalog ?? [];
  return <div className="hermes-sheet-layer" role="presentation"><button className="hermes-sheet-scrim" type="button" aria-label="Close connections" onClick={onClose} /><section className="hermes-sheet hermes-connections-sheet" role="dialog" aria-modal="true" aria-labelledby="connections-title"><header className="hermes-sheet-head"><div><span className="grok-section-kicker">Workspace</span><h2 id="connections-title">Connections</h2><p>Connect a service when a task needs it. Each account stays tied to this Hermes user.</p></div><button className="grok-icon-button" type="button" aria-label="Close connections" onClick={onClose}><X size={18} /></button></header>{status?.connections.configured === false || data?.configured === false ? <div className="hermes-expansion-empty"><Link2 size={20} /><strong>Connections need setup</strong><p>An administrator needs to configure the connection service before a service can be connected.</p></div> : <><label className="hermes-sheet-search"><Search size={15} aria-hidden="true" /><input aria-label="Search connections" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search services" /></label>{link ? <div className="hermes-connection-link" role="status"><div><strong>Continue connecting {link.toolkit}</strong><p>{notice}</p></div><a className="hermes-expansion-button hermes-expansion-button-primary" href={link.url} target="_blank" rel="noreferrer">Open sign-in <ExternalLink size={14} /></a></div> : null}{notice && !link ? <p className="hermes-expansion-notice" role="status">{notice}</p> : null}{busy && !data ? <div className="hermes-expansion-loading"><Loader2 size={16} className="hermes-spin" /> Loading connections…</div> : <><div className="hermes-connection-list">{catalog.length ? catalog.map((item) => <ConnectionCatalogRow key={item.slug} item={item} busy={busy || loadingMore} preferred={item.slug === initialToolkit} onConnect={() => void connect(item.slug)} />) : <p className="hermes-expansion-empty">No services match this search.</p>}</div>{data?.next_cursor ? <button className="hermes-expansion-button hermes-connections-more" type="button" disabled={busy || loadingMore} onClick={() => void refresh(true)}>{loadingMore ? <Loader2 size={14} className="hermes-spin" /> : <ChevronDown size={14} />} {loadingMore ? "Loading…" : "Show more services"}</button> : null}{accounts.length ? <div className="hermes-connected-list"><h3>Connected accounts</h3>{accounts.map((account) => <ConnectedAccountRow key={account.id} account={account} confirming={disconnecting === account.id} busy={busy || loadingMore} onDisconnect={() => void disconnect(account)} onCancel={() => setDisconnecting(null)} />)}</div> : null}</>}</>}{error ? <p className="hermes-expansion-error" role="alert"><AlertCircle size={14} /> {error}</p> : null}<footer className="hermes-sheet-actions"><button className="hermes-expansion-button" type="button" disabled={busy || loadingMore} onClick={() => void refresh()}><RefreshCw size={14} /> Refresh</button><button className="hermes-expansion-button" type="button" onClick={onClose}>Done</button></footer></section></div>;
}

function ConnectionCatalogRow({ item, busy, preferred, onConnect }: { item: ConnectionCatalogItem; busy: boolean; preferred: boolean; onConnect: () => void }): JSX.Element {
  return <div className={`hermes-connection-row ${preferred ? "is-preferred" : ""}`}><span className="hermes-connection-icon"><Link2 size={16} /></span><div><strong>{item.name}</strong><small>{item.description || "Connect this service when a Bot needs it."}</small></div>{item.connected ? <span className="hermes-connection-state"><Check size={14} /> Connected</span> : <button className="hermes-expansion-button" type="button" disabled={busy} onClick={onConnect}>Connect</button>}</div>;
}

function ConnectedAccountRow({ account, confirming, busy, onDisconnect, onCancel }: { account: ConnectionAccount; confirming: boolean; busy: boolean; onDisconnect: () => void; onCancel: () => void }): JSX.Element {
  return <div className="hermes-connection-row"><span className="hermes-connection-icon"><Check size={16} /></span><div><strong>{account.name}</strong><small>{account.toolkit} · {account.status}</small></div>{confirming ? <span className="hermes-confirm-actions"><button className="hermes-expansion-button hermes-expansion-button-danger" type="button" disabled={busy} onClick={onDisconnect}>Confirm</button><button className="hermes-expansion-button" type="button" onClick={onCancel}>Cancel</button></span> : <button className="hermes-expansion-button" type="button" disabled={busy} onClick={onDisconnect}>Disconnect</button>}</div>;
}

export function PrivateInputSheet({ open, agentId, request, status, onClose, onSaved }: {
  open: boolean;
  agentId?: string;
  request?: ChatRequest | null;
  status: ExtensionsStatus | null;
  onClose: () => void;
  onSaved?: (request?: ChatRequest, field?: PrivateField) => void;
}): JSX.Element | null {
  const requestData = request?.data ?? {};
  const [label, setLabel] = useState("");
  const [purpose, setPurpose] = useState("");
  const [value, setValue] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isRequest = Boolean(request);
  useEffect(() => {
    if (!open) {
      setLabel(""); setPurpose(""); setValue(""); setRemember(false); setError(null);
      return;
    }
    setLabel(request ? textValue(requestData, ["label", "field_label"]) ?? request.title : "");
    setPurpose(request?.purpose ?? textValue(requestData, ["purpose"]) ?? "");
    setValue(""); setRemember(false); setError(null);
  }, [open, request?.id]);
  if (!open) return null;
  const destination = textValue(requestData, ["destination", "service", "toolkit_name", "toolkit"]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!value || busy || (!isRequest && (!agentId || !label.trim() || !purpose.trim()))) return;
    setBusy(true); setError(null);
    try {
      if (request) { const next = await submitPrivateRequest(request.id, value, remember); onSaved?.(next); }
      else { const field = await createPrivateField(agentId!, { label: label.trim(), purpose: purpose.trim(), value, remember }); onSaved?.(undefined, field); }
      setValue(""); onClose();
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  };
  return <div className="hermes-sheet-layer" role="presentation"><button className="hermes-sheet-scrim" type="button" aria-label="Close private input" onClick={onClose} /><section className="hermes-sheet hermes-private-sheet" role="dialog" aria-modal="true" aria-labelledby="private-title"><header className="hermes-sheet-head"><div><span className="grok-section-kicker">Private input</span><h2 id="private-title">{isRequest ? label || "Enter a private value" : "Save a private value"}</h2><p>{purpose || "This value stays out of chat and model context."}</p></div><button className="grok-icon-button" type="button" aria-label="Close private input" onClick={onClose}><X size={18} /></button></header><div className="hermes-private-note"><LockKeyhole size={16} /><span>Only the approved service receives this value when you confirm its action.</span></div>{destination ? <p className="hermes-private-destination">Intended destination: <strong>{destination}</strong></p> : null}{status?.private_input.available === false ? <div className="hermes-expansion-empty"><strong>Private input is unavailable</strong><p>An administrator needs to configure protected input before you can save a value.</p></div> : <form className="hermes-private-form" onSubmit={(event) => void submit(event)}>{!isRequest ? <><label>Label<input className="grok-field" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Supplier portal password" /></label><label>Purpose<textarea className="grok-field grok-textarea" value={purpose} onChange={(event) => setPurpose(event.target.value)} placeholder="Used to sign in to the supplier portal" rows={3} /></label></> : null}<label>Value<input className="grok-field" type="password" autoComplete="new-password" value={value} onChange={(event) => setValue(event.target.value)} autoFocus placeholder="Enter it here" /></label><label className="hermes-private-remember"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /><span><strong>Remember for later</strong><small>{remember ? "Stored for up to 30 days." : "Use once, then expire within an hour."}</small></span></label>{error ? <p className="hermes-expansion-error" role="alert"><AlertCircle size={14} /> {error}</p> : null}<footer className="hermes-sheet-actions"><button className="hermes-expansion-button" type="button" onClick={onClose}>Cancel</button><button className="hermes-expansion-button hermes-expansion-button-primary" type="submit" disabled={busy || !value || (!isRequest && (!label.trim() || !purpose.trim()))}>{busy ? <Loader2 size={15} className="hermes-spin" /> : <LockKeyhole size={15} />} {isRequest ? "Save and continue" : "Save private value"}</button></footer></form>}</section></div>;
}

export function PrivateFieldsPanel({ agentId, fields, status, onOpen, onChanged }: { agentId?: string; fields: PrivateField[]; status: ExtensionsStatus | null; onOpen: () => void; onChanged: (fields: PrivateField[]) => void }): JSX.Element {
  const [busyId, setBusyId] = useState<string | null>(null);
  const remove = async (field: PrivateField) => {
    if (!agentId || busyId) return;
    setBusyId(field.id);
    try { await deletePrivateField(agentId, field.id); onChanged(fields.filter((item) => item.id !== field.id)); }
    catch { /* Keep the field visible; the next refresh can recover the state. */ }
    finally { setBusyId(null); }
  };
  return <section className="hermes-expansion-card hermes-private-fields" aria-label="Private fields"><div className="hermes-expansion-card-head"><div><span className="grok-section-kicker"><LockKeyhole size={14} /> Private input</span><h2>Protected values</h2><p>Labels and expiry are visible here; values stay out of chat.</p></div><span className="hermes-expansion-count">{fields.length}</span></div>{status?.private_input.available === false ? <p className="hermes-expansion-empty-copy">Protected input needs administrator setup.</p> : fields.length ? <div className="hermes-private-field-list">{fields.map((field) => <div className="hermes-private-field-row" key={field.id}><span className="hermes-connection-icon"><LockKeyhole size={15} /></span><div><strong>{field.label}</strong><small>{field.purpose}{field.one_time ? " · One use" : " · Remembered"}</small></div><button className="hermes-expansion-icon-button" type="button" aria-label={`Delete ${field.label}`} disabled={busyId === field.id} onClick={() => void remove(field)}>{busyId === field.id ? <Loader2 size={14} className="hermes-spin" /> : <Trash2 size={14} />}</button></div>)}</div> : <p className="hermes-expansion-empty-copy">No protected values saved yet.</p>}<button className="hermes-expansion-button" type="button" disabled={!agentId || status?.private_input.available === false} onClick={onOpen}><Plus size={14} /> Add private value</button></section>;
}

export function ExpansionStatusCard({ status, onConnections, onPrivate, onTeach }: { status: ExtensionsStatus | null; onConnections: () => void; onPrivate: () => void; onTeach: () => void }): JSX.Element {
  const configured = (value: boolean | undefined): string => value === undefined ? "Checking" : value ? "Ready" : "Setup needed";
  return <section className="hermes-expansion-card hermes-status-card" aria-label="Workspace tools"><div className="hermes-expansion-card-head"><div><span className="grok-section-kicker"><Zap size={14} /> Workspace tools</span><h2>Connections and tools</h2><p>Open a tool only when a task needs it.</p></div></div><div className="hermes-status-list"><div><span><Link2 size={15} /> Connections</span><strong className={status?.connections.configured ? "is-ready" : ""}>{configured(status?.connections.configured)}</strong><button className="hermes-expansion-button" type="button" onClick={onConnections}>Manage</button></div><div><span><LockKeyhole size={15} /> Private input</span><strong className={status?.private_input.available ? "is-ready" : ""}>{configured(status?.private_input.available)}</strong><button className="hermes-expansion-button" type="button" onClick={onPrivate}>Manage</button></div><div><span><Mic size={15} /> Dictation</span><strong className={status?.voice.configured ? "is-ready" : ""}>{configured(status?.voice.configured)}</strong><small>{status?.voice.model ?? "Administrator setup controls this."}</small></div><div><span><Play size={15} /> Teach a task</span><strong className="is-ready">Ready</strong><button className="hermes-expansion-button" type="button" onClick={onTeach}>Open</button></div><div><span><Link2 size={15} /> Telegram</span><strong className={status?.telegram.configured ? "is-ready" : ""}>{configured(status?.telegram.configured)}</strong></div></div></section>;
}

type LocalFrame = { id: string; blob: Blob; url: string };

export function TeachingSheet({ open, agentId, teaching, onClose, onSaved }: { open: boolean; agentId?: string; teaching?: Teaching | null; onClose: () => void; onSaved: (teaching: Teaching) => void }): JSX.Element | null {
  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState("");
  const [steps, setSteps] = useState<string[]>([""]);
  const [notes, setNotes] = useState("");
  const [frames, setFrames] = useState<LocalFrame[]>([]);
  const [recording, setRecording] = useState(false);
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const stopCapture = () => { stopTracks(streamRef.current); streamRef.current = null; if (videoRef.current) videoRef.current.srcObject = null; setRecording(false); setPaused(false); };
  useEffect(() => {
    if (!open) return;
    setName(teaching?.name ?? ""); setTrigger(teaching?.trigger ?? ""); setSteps(teaching?.steps?.length ? [...teaching.steps] : [""]); setNotes(teaching?.notes ?? ""); setError(null); setFrames([]); stopCapture();
    return () => { stopCapture(); setFrames((current) => { current.forEach((frame) => URL.revokeObjectURL(frame.url)); return []; }); };
  }, [open, teaching?.id]);
  useEffect(() => () => stopCapture(), []);
  useEffect(() => { if (videoRef.current && streamRef.current && videoRef.current.srcObject !== streamRef.current) { videoRef.current.srcObject = streamRef.current; void videoRef.current.play().catch(() => undefined); } }, [recording]);

  if (!open) return null;
  const startCapture = async () => {
    if (!navigator.mediaDevices?.getDisplayMedia) { setError("Screen capture is unavailable in this browser. Add written steps instead."); return; }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      streamRef.current = stream; setRecording(true); setPaused(false);
      stream.getVideoTracks()[0]?.addEventListener("ended", stopCapture, { once: true });
    } catch (reason) { setError(reason instanceof DOMException && reason.name === "NotAllowedError" ? "Screen sharing was cancelled. You can continue with written steps." : errorText(reason)); }
  };
  const togglePause = () => { const next = !paused; streamRef.current?.getVideoTracks().forEach((track) => { track.enabled = !next; }); setPaused(next); };
  const captureFrame = () => {
    const video = videoRef.current;
    if (!video || paused || video.readyState < 2) { setError("Wait for the shared screen preview before capturing a step."); return; }
    const canvas = document.createElement("canvas"); canvas.width = video.videoWidth || 960; canvas.height = video.videoHeight || 540;
    const context = canvas.getContext("2d"); if (!context) { setError("This browser could not capture a still."); return; }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => { if (!blob) { setError("This browser could not capture a still."); return; } setFrames((current) => [...current, { id: `frame-${Date.now()}-${current.length}`, blob, url: URL.createObjectURL(blob) }]); }, "image/png");
  };
  const removeFrame = (frame: LocalFrame) => { URL.revokeObjectURL(frame.url); setFrames((current) => current.filter((item) => item.id !== frame.id)); };
  const updateStep = (index: number, value: string) => setSteps((current) => current.map((step, stepIndex) => stepIndex === index ? value : step));
  const moveStep = (index: number, direction: -1 | 1) => setSteps((current) => { const next = [...current]; const target = index + direction; if (target < 0 || target >= next.length) return current; [next[index], next[target]] = [next[target], next[index]]; return next; });
  const save = async (event: FormEvent) => {
    event.preventDefault();
    const cleanSteps = steps.map((step) => step.trim()).filter(Boolean);
    if (!agentId || !name.trim() || !trigger.trim() || !cleanSteps.length || busy) { setError("Add a name, when to use it, and at least one step."); return; }
    setBusy(true); setError(null);
    try {
      const frameFileIds: string[] = [];
      for (const [index, frame] of frames.entries()) frameFileIds.push((await uploadFile(new File([frame.blob], `teaching-step-${index + 1}.png`, { type: "image/png" }), agentId)).id);
      const input = { name: name.trim(), trigger: trigger.trim(), steps: cleanSteps, ...(notes.trim() ? { notes: notes.trim() } : {}), ...(frameFileIds.length ? { frame_file_ids: frameFileIds } : {}) };
      const saved = teaching ? await updateTeaching(agentId, teaching.id, input) : await createTeaching(agentId, input);
      onSaved(saved); onClose();
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  };
  return <div className="hermes-sheet-layer" role="presentation"><button className="hermes-sheet-scrim" type="button" aria-label="Close teaching" onClick={onClose} /><section className="hermes-sheet hermes-teaching-sheet" role="dialog" aria-modal="true" aria-labelledby="teach-title"><header className="hermes-sheet-head"><div><span className="grok-section-kicker"><Play size={14} /> Procedure</span><h2 id="teach-title">{teaching ? "Edit taught task" : "Teach a task"}</h2><p>Write the steps you trust. Optional screen stills stay local until you save.</p></div><button className="grok-icon-button" type="button" aria-label="Close teaching" onClick={onClose}><X size={18} /></button></header><form className="hermes-teaching-form" onSubmit={(event) => void save(event)}><label>Name<input className="grok-field" value={name} onChange={(event) => setName(event.target.value)} placeholder="Prepare the supplier update" autoFocus /></label><label>When should Chief use it?<input className="grok-field" value={trigger} onChange={(event) => setTrigger(event.target.value)} placeholder="When I ask for the supplier update" /></label><fieldset className="hermes-steps"><legend>Steps</legend>{steps.map((step, index) => <div className="hermes-step-row" key={`step-${index}`}><span>{index + 1}</span><textarea className="grok-field grok-textarea" value={step} onChange={(event) => updateStep(index, event.target.value)} placeholder="Describe one clear action" rows={2} /><button className="hermes-expansion-icon-button" type="button" aria-label={`Move step ${index + 1} up`} disabled={index === 0} onClick={() => moveStep(index, -1)}><ChevronDown size={14} className="hermes-step-up" /></button><button className="hermes-expansion-icon-button" type="button" aria-label={`Move step ${index + 1} down`} disabled={index === steps.length - 1} onClick={() => moveStep(index, 1)}><ChevronDown size={14} /></button><button className="hermes-expansion-icon-button" type="button" aria-label={`Remove step ${index + 1}`} disabled={steps.length === 1} onClick={() => setSteps((current) => current.filter((_, stepIndex) => stepIndex !== index))}><Trash2 size={14} /></button></div>)}<button className="hermes-expansion-button" type="button" onClick={() => setSteps((current) => [...current, ""])}><Plus size={14} /> Add step</button></fieldset><label>Notes (optional)<textarea className="grok-field grok-textarea" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="What counts as success? Keep private values as labels." rows={3} /></label><div className="hermes-capture"><div className="hermes-capture-head"><div><strong>Optional screen stills</strong><p>No microphone audio is recorded. Capture a few stills and review them before saving.</p></div>{!recording ? <button className="hermes-expansion-button" type="button" onClick={() => void startCapture()}><Monitor size={14} /> Share screen</button> : <div className="hermes-capture-actions"><button className="hermes-expansion-button" type="button" onClick={togglePause}>{paused ? <Play size={14} /> : <Pause size={14} />} {paused ? "Resume" : "Pause"}</button><button className="hermes-expansion-button" type="button" onClick={captureFrame}><FileImage size={14} /> Capture still</button><button className="hermes-expansion-button" type="button" onClick={stopCapture}>Stop</button></div>}</div>{recording ? <video ref={videoRef} className="hermes-capture-preview" autoPlay muted playsInline aria-label="Screen sharing preview" /> : <p className="hermes-capture-note">Written steps are enough. Screen sharing is optional and explicit.</p>}{frames.length ? <div className="hermes-frame-list" aria-label="Captured stills">{frames.map((frame, index) => <figure key={frame.id}><img src={frame.url} alt={`Captured step ${index + 1}`} /><button type="button" aria-label={`Remove captured step ${index + 1}`} onClick={() => removeFrame(frame)}><X size={13} /></button></figure>)}</div> : null}</div>{error ? <p className="hermes-expansion-error" role="alert"><AlertCircle size={14} /> {error}</p> : null}<footer className="hermes-sheet-actions"><button className="hermes-expansion-button" type="button" onClick={onClose}>Cancel</button><button className="hermes-expansion-button hermes-expansion-button-primary" type="submit" disabled={busy}>{busy ? <Loader2 size={15} className="hermes-spin" /> : <Check size={15} />} {teaching ? "Save changes" : "Save procedure"}</button></footer></form></section></div>;
}

export function TeachingRunDialog({ teaching, open, onClose, onRun }: { teaching: Teaching | null; open: boolean; onClose: () => void; onRun: (teaching: Teaching, input: string) => Promise<void> }): JSX.Element | null {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setInput(""); setBusy(false); setError(null); } }, [open, teaching?.id]);
  if (!open || !teaching) return null;
  const run = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(null); try { await onRun(teaching, input); onClose(); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); } };
  return <div className="hermes-sheet-layer" role="presentation"><button className="hermes-sheet-scrim" type="button" aria-label="Close procedure run" onClick={onClose} /><section className="hermes-sheet hermes-run-sheet" role="dialog" aria-modal="true" aria-labelledby="run-teaching-title"><header className="hermes-sheet-head"><div><span className="grok-section-kicker">Procedure</span><h2 id="run-teaching-title">Run {teaching.name}</h2><p>{teaching.trigger}</p></div><button className="grok-icon-button" type="button" aria-label="Close procedure run" onClick={onClose}><X size={18} /></button></header><form onSubmit={(event) => void run(event)}><label>Optional input<textarea className="grok-field grok-textarea" value={input} onChange={(event) => setInput(event.target.value)} placeholder="Add a name, date, or other safe context" rows={3} /></label><p className="hermes-private-note"><ShieldCheck size={15} /> The run opens in the Bot’s continuing chat and still follows approval rules.</p>{error ? <p className="hermes-expansion-error" role="alert"><AlertCircle size={14} /> {error}</p> : null}<footer className="hermes-sheet-actions"><button className="hermes-expansion-button" type="button" onClick={onClose}>Cancel</button><button className="hermes-expansion-button hermes-expansion-button-primary" type="submit" disabled={busy}>{busy ? <Loader2 size={15} className="hermes-spin" /> : <Play size={15} />} Run now</button></footer></form></section></div>;
}

export function TeachingManager({ agent, teachings, skills, accountId, onEdit, onRun, onChanged }: { agent: Agent | null; teachings: Teaching[]; skills: LearnedSkill[]; accountId?: string; onEdit: (teaching: Teaching) => void; onRun: (teaching: Teaching) => void; onChanged: (teachings: Teaching[]) => void }): JSX.Element {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const update = async (teaching: Teaching, input: Parameters<typeof updateTeaching>[2]) => {
    if (!agent || busyId) return;
    setBusyId(teaching.id); setError(null);
    try { const next = await updateTeaching(agent.id, teaching.id, input); onChanged(teachings.map((item) => item.id === teaching.id ? next : item)); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusyId(null); }
  };
  const remove = async (teaching: Teaching) => {
    if (!agent || busyId) return;
    setBusyId(teaching.id); setError(null);
    try { await deleteTeaching(agent.id, teaching.id); onChanged(teachings.filter((item) => item.id !== teaching.id)); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusyId(null); }
  };
  return <section className="hermes-expansion-card hermes-teaching-manager" aria-label="Taught procedures"><div className="hermes-expansion-card-head"><div><span className="grok-section-kicker"><Play size={14} /> Procedures</span><h2>Human-taught procedures</h2><p>Review text and stills before each procedure becomes verified.</p></div><span className="hermes-expansion-count">{teachings.length + skills.length}</span></div>{teachings.length ? <div className="hermes-teaching-list">{teachings.map((teaching) => <div className="hermes-teaching-row" key={teaching.id}><span className={`hermes-teaching-dot ${teaching.enabled ? "is-on" : ""}`} /><div className="hermes-teaching-copy"><strong>{teaching.name}</strong><small>{teaching.status === "verified" ? "Verified" : "Unverified"} · Revision {teaching.revision ?? 1}{teaching.enabled ? "" : " · Paused"}</small><Disclosure accountId={accountId} section="teaching" id={teaching.id} label="steps"><ol>{teaching.steps.map((step, index) => <li key={`${teaching.id}:${index}`}>{step}</li>)}</ol>{teaching.notes ? <p>{teaching.notes}</p> : null}</Disclosure></div><div className="hermes-teaching-actions"><button className="hermes-expansion-icon-button" type="button" aria-label={`Edit ${teaching.name}`} onClick={() => onEdit(teaching)}><Pencil size={14} /></button><button className="hermes-expansion-icon-button" type="button" aria-label={`Run ${teaching.name}`} disabled={busyId === teaching.id} onClick={() => onRun(teaching)}><Play size={14} /></button><button className="hermes-expansion-button" type="button" disabled={busyId === teaching.id} onClick={() => void update(teaching, { enabled: !teaching.enabled })}>{teaching.enabled ? "Pause" : "Resume"}</button>{teaching.status !== "verified" ? <button className="hermes-expansion-button" type="button" disabled={busyId === teaching.id} onClick={() => void update(teaching, { verified: true } as Parameters<typeof updateTeaching>[2])}>Mark tested</button> : null}<button className="hermes-expansion-icon-button hermes-expansion-icon-danger" type="button" aria-label={`Delete ${teaching.name}`} disabled={busyId === teaching.id} onClick={() => void remove(teaching)}>{busyId === teaching.id ? <Loader2 size={14} className="hermes-spin" /> : <Trash2 size={14} />}</button></div></div>)}</div> : null}{skills.length ? <div className="hermes-learned-list"><h3>Verified skills</h3>{skills.map((skill) => <div className="hermes-learned-row" key={skill.id}><span className={`hermes-teaching-dot ${skill.enabled === false ? "" : "is-on"}`} /><span>{skill.name}</span><small>Verified</small></div>)}</div> : null}{!teachings.length && !skills.length ? <p className="hermes-expansion-empty-copy">No procedures yet. Teach one from the composer when a task is clear.</p> : null}{error ? <p className="hermes-expansion-error" role="alert"><AlertCircle size={14} /> {error}</p> : null}</section>;
}

export function VoiceDictation({ open, targetKey, draftSnapshot, currentDraft, status, onClose, onInsert }: { open: boolean; targetKey: string; draftSnapshot: string; currentDraft: string; status: ExtensionsStatus | null; onClose: () => void; onInsert: (targetKey: string, text: string, mode: "replace" | "append") => void }): JSX.Element | null {
  const [phase, setPhase] = useState<"ready" | "recording" | "transcribing" | "review" | "error">("ready");
  const [seconds, setSeconds] = useState(0);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const cancelledRef = useRef(false);
  const openRef = useRef(open);
  const operationRef = useRef(0);
  const snapshotRef = useRef(draftSnapshot);
  const mountedRef = useRef(true);
  const maxSeconds = status?.voice.max_seconds ?? 120;
  const maxBytes = status?.voice.max_bytes ?? 10 * 1024 * 1024;
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; openRef.current = false; cancelledRef.current = true; operationRef.current += 1; recorderRef.current?.stop(); stopTracks(streamRef.current); }; }, []);
  useEffect(() => {
    openRef.current = open;
    operationRef.current += 1;
    if (open) { setPhase("ready"); setSeconds(0); setTranscript(""); setError(null); snapshotRef.current = draftSnapshot; cancelledRef.current = false; }
    else { cancelledRef.current = true; recorderRef.current?.stop(); stopTracks(streamRef.current); streamRef.current = null; recorderRef.current = null; chunksRef.current = []; setPhase("ready"); setSeconds(0); setTranscript(""); setError(null); }
  }, [open, targetKey]);
  useEffect(() => { if (phase !== "recording") return; const timer = window.setInterval(() => setSeconds((value) => { if (value + 1 >= maxSeconds) { window.clearInterval(timer); recorderRef.current?.stop(); } return value + 1; }), 1000); return () => window.clearInterval(timer); }, [maxSeconds, phase]);
  if (!open) return null;
  const cleanupRecording = () => { stopTracks(streamRef.current); streamRef.current = null; recorderRef.current = null; chunksRef.current = []; };
  const beginTranscription = async (blob: Blob) => {
    if (cancelledRef.current || !mountedRef.current || !openRef.current) { cleanupRecording(); return; }
    if (blob.size > maxBytes) { cleanupRecording(); if (mountedRef.current) { setError(`That recording is larger than ${Math.round(maxBytes / (1024 * 1024))} MB.`); setPhase("error"); } return; }
    setPhase("transcribing");
    try { const result = await transcribeVoice(blob); if (!mountedRef.current || !openRef.current || cancelledRef.current) return; if (!result.text.trim()) throw new Error("No words were detected. Try again."); setTranscript(result.text.trim()); setPhase("review"); }
    catch (reason) { if (!mountedRef.current || !openRef.current || cancelledRef.current) return; setError(errorText(reason)); setPhase("error"); }
    finally { cleanupRecording(); }
  };
  const start = async () => {
    if (status?.voice.configured === false) { setError("Voice setup is not configured yet. Ask an administrator to add the transcription provider."); setPhase("error"); return; }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") { setError("Voice dictation is unavailable in this browser. You can keep typing instead."); setPhase("error"); return; }
    const operation = operationRef.current;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current || !openRef.current || cancelledRef.current || operation !== operationRef.current) { stopTracks(stream); return; }
      streamRef.current = stream; chunksRef.current = []; cancelledRef.current = false;
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((candidate) => MediaRecorder.isTypeSupported(candidate));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data); };
      recorder.onerror = () => { if (mountedRef.current) { setError("The recording could not be read. Try again."); setPhase("error"); } cleanupRecording(); };
      recorder.onstop = () => { const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" }); void beginTranscription(blob); };
      recorder.start(); setSeconds(0); setError(null); setPhase("recording");
    } catch (reason) {
      stopTracks(streamRef.current); streamRef.current = null;
      if (!mountedRef.current || !openRef.current || cancelledRef.current || operation !== operationRef.current) return;
      setError(reason instanceof DOMException && reason.name === "NotAllowedError" ? "Microphone access was denied. Allow it in the browser or keep typing." : errorText(reason)); setPhase("error");
    }
  };
  const stop = () => { if (phase === "recording") recorderRef.current?.stop(); };
  const cancel = () => { cancelledRef.current = true; openRef.current = false; operationRef.current += 1; recorderRef.current?.stop(); cleanupRecording(); setPhase("ready"); onClose(); };
  const stale = currentDraft !== snapshotRef.current;
  const insert = (mode: "replace" | "append") => { if (!transcript.trim()) return; onInsert(targetKey, transcript.trim(), mode); onClose(); };
  return <div className="hermes-sheet-layer" role="presentation"><button className="hermes-sheet-scrim" type="button" aria-label="Close dictation" onClick={cancel} /><section className="hermes-sheet hermes-voice-sheet" role="dialog" aria-modal="true" aria-labelledby="voice-title"><header className="hermes-sheet-head"><div><span className="grok-section-kicker"><Mic size={14} /> Dictation</span><h2 id="voice-title">Add words to your draft</h2><p>Record up to {maxSeconds} seconds. Review the text before it enters chat.</p></div><button className="grok-icon-button" type="button" aria-label="Close dictation" onClick={cancel}><X size={18} /></button></header>{phase === "ready" ? <div className="hermes-voice-ready"><Mic size={28} /><p>Microphone access starts only after you choose Record. Stopping sends the recording to OpenRouter for Microsoft MAI Transcribe 2. Review the text before adding it to chat.</p><button className="hermes-expansion-button hermes-expansion-button-primary" type="button" onClick={() => void start()}><Mic size={15} /> Record</button></div> : phase === "recording" ? <div className="hermes-voice-recording"><span className="hermes-recording-dot" /><strong>Recording {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}</strong><small>For passwords or codes, use Private input.</small><div className="hermes-sheet-actions"><button className="hermes-expansion-button hermes-expansion-button-primary" type="button" onClick={stop}><Check size={15} /> Stop and review</button><button className="hermes-expansion-button" type="button" onClick={cancel}>Cancel</button></div></div> : phase === "transcribing" ? <div className="hermes-expansion-loading"><Loader2 size={17} className="hermes-spin" /> Transcribing…</div> : phase === "review" ? <div className="hermes-voice-review"><label>Review transcript<textarea className="grok-field grok-textarea" value={transcript} onChange={(event) => setTranscript(event.target.value)} rows={5} /></label>{stale ? <p className="hermes-expansion-notice">This draft changed while you were recording. Choose how to add the reviewed text.</p> : null}<div className="hermes-sheet-actions"><button className="hermes-expansion-button" type="button" onClick={() => { setPhase("ready"); setTranscript(""); }}>Discard</button>{stale ? <><button className="hermes-expansion-button" type="button" onClick={() => insert("append")}>Append</button><button className="hermes-expansion-button hermes-expansion-button-primary" type="button" onClick={() => insert("replace")}>Replace</button></> : <button className="hermes-expansion-button hermes-expansion-button-primary" type="button" onClick={() => insert("append")}>Insert into draft</button>}</div></div> : <div className="hermes-voice-ready"><AlertCircle size={25} /><p role="alert">{error}</p><button className="hermes-expansion-button hermes-expansion-button-primary" type="button" onClick={() => { setError(null); setPhase("ready"); }}>Try again</button></div>}</section></div>;
}

