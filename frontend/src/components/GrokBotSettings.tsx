import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Activity, Check, Copy, ExternalLink, Loader2, LogOut, Monitor, Pause, Pencil, Play, RefreshCw, UserRound } from "lucide-react";
import { getRuntimeAccount, getRuntimeUsage, startRuntimeLogin, updateAgent } from "../lib/api";
import { applyMotionPreference, readMotionPreference, useReducedMotion } from "../lib/motion";
import type { Agent, AvatarShape, MotionPreference, RuntimeAccount, RuntimeLogin, RuntimeStatus, RuntimeUsage, RuntimeUsageWindow } from "../lib/types";
import { AVATAR_COLORS, AVATAR_COLOR_NAMES, AVATAR_SHAPES, AVATAR_SHAPE_NAMES, BotGlyph, getAgentColor, getAgentShape } from "./BotIdentity";
import { AgentAvatar } from "./BotIdentity";
import { Disclosure } from "./Disclosure";
import "./grok-bot-settings.css";

const message = (reason: unknown) => reason instanceof Error ? reason.message : "That did not work. Please try again.";

export function BotSettingsEditor({ agent, models, accountId, onSaved }: {
  agent: Agent;
  models?: RuntimeAccount["models"];
  accountId?: string;
  onSaved: (agent: Agent) => void;
}) {
  const prefix = useId();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(agent.name);
  const [instructions, setInstructions] = useState(agent.description ?? "");
  const [model, setModel] = useState(agent.model ?? "gpt-5.6-luna");
  const [color, setColor] = useState(getAgentColor(agent));
  const [shape, setShape] = useState<AvatarShape>(getAgentShape(agent));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const identity = useRef(agent.id);
  const previousAgent = useRef(agent.id);
  const editButton = useRef<HTMLButtonElement>(null);
  const submitting = useRef(false);
  useEffect(() => {
    identity.current = agent.id;
    setName(agent.name); setInstructions(agent.description ?? "");
    setModel(agent.model ?? "gpt-5.6-luna"); setColor(getAgentColor(agent)); setShape(getAgentShape(agent));
    setEditing(false); setBusy(false); setError(null); submitting.current = false;
    if (previousAgent.current !== agent.id) setSaved(false);
    previousAgent.current = agent.id;
    return () => { identity.current = ""; };
  }, [agent.id, agent.name, agent.description, agent.model, agent.color, agent.avatar]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || submitting.current) return;
    const id = agent.id;
    submitting.current = true; setBusy(true); setError(null);
    try {
      const updated = await updateAgent(id, { name: name.trim(), description: instructions.trim(), model, color, avatar: shape });
      onSaved(updated);
      if (identity.current === id) { setEditing(false); setSaved(true); window.requestAnimationFrame(() => editButton.current?.focus()); }
    } catch (reason) { if (identity.current === id) setError(message(reason)); }
    finally { if (identity.current === id) { submitting.current = false; setBusy(false); } }
  };
  return <section className="grok-bot-settings" aria-label="Bot settings">
    <div className="grok-settings-title"><h3>Bot settings</h3>{!editing && <button ref={editButton} type="button" onClick={() => { setEditing(true); setSaved(false); }}><Pencil size={16} /> Edit</button>}</div>
    {!editing ? <><p>Change {agent.name}’s name, role or appearance.</p>{agent.description ? <Disclosure accountId={accountId} section="bot-instructions" id={agent.id} label="instructions"><p className="grok-settings-description">{agent.description}</p></Disclosure> : null}{saved && <p className="grok-settings-success" role="status"><Check size={15} /> Saved</p>}</> : <form onSubmit={event => void save(event)}>
      <fieldset disabled={busy}>
        <label htmlFor={`${prefix}-name`}>Name</label>
        <input id={`${prefix}-name`} value={name} maxLength={80} onChange={event => setName(event.target.value)} required />
        <label htmlFor={`${prefix}-instructions`}>What should this bot do?</label>
        <textarea id={`${prefix}-instructions`} rows={4} value={instructions} maxLength={12000} onChange={event => setInstructions(event.target.value)} />
        <details><summary>Appearance</summary><div className="grok-settings-preview"><BotGlyph color={color} shape={shape} size={52} /></div><div className="grok-settings-swatches" role="group" aria-label="Bot color">{AVATAR_COLORS.map((value, index) => <button type="button" key={value} aria-label={AVATAR_COLOR_NAMES[index]} aria-pressed={value === color} onClick={() => setColor(value)}><span style={{ background: value }}>{value === color ? <Check size={15} /> : null}</span></button>)}</div><div className="grok-settings-swatches" role="group" aria-label="Bot shape">{AVATAR_SHAPES.map(value => <button type="button" key={value} aria-label={AVATAR_SHAPE_NAMES[value]} aria-pressed={value === shape} onClick={() => setShape(value)}><BotGlyph color={color} shape={value} size={24} /></button>)}</div></details>
        <details><summary>Advanced</summary><label htmlFor={`${prefix}-model`}>Model</label><select id={`${prefix}-model`} value={model} onChange={event => setModel(event.target.value)}>{!models?.some(item => item.id === model) && <option value={model}>{model}</option>}{models?.map(item => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}</select><p>Choose from models available on your connected account.</p></details>
        {error && <p className="grok-settings-error" role="alert">{error}</p>}
        <div className="grok-settings-actions"><button className="grok-settings-primary" type="submit" disabled={!name.trim() || busy}>{busy ? <Loader2 size={16} className="grok-spin" /> : <Check size={16} />} Save changes</button><button type="button" onClick={() => { setName(agent.name); setInstructions(agent.description ?? ""); setModel(agent.model ?? "gpt-5.6-luna"); setColor(getAgentColor(agent)); setShape(getAgentShape(agent)); setEditing(false); setError(null); window.requestAnimationFrame(() => editButton.current?.focus()); }}>Cancel</button></div>
      </fieldset>
    </form>}
  </section>;
}

export function RuntimeConnectionCard({ account, onAccountChange }: {
  account: RuntimeAccount | null;
  onAccountChange: (account: RuntimeAccount) => void;
}) {
  const [login, setLogin] = useState<RuntimeLogin | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const mounted = useRef(true);
  const callback = useRef(onAccountChange);
  callback.current = onAccountChange;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!login) return;
    let active = true;
    let pending = false;
    const refresh = async () => {
      if (pending || document.hidden) return;
      pending = true;
      try {
        const next = await getRuntimeAccount();
        if (active && mounted.current) { callback.current(next); if (next.connected) { setLogin(null); setError(null); } }
      } catch (reason) { if (active && mounted.current) setError(message(reason)); }
      finally { pending = false; }
    };
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [login]);
  const connect = async () => {
    if (busy) return;
    setBusy(true); setError(null); setCopied(false);
    try { const value = await startRuntimeLogin(); if (mounted.current) setLogin(value); }
    catch (reason) { if (mounted.current) setError(message(reason)); }
    finally { if (mounted.current) setBusy(false); }
  };
  const refresh = async () => {
    setBusy(true); setError(null);
    try { const next = await getRuntimeAccount(); if (mounted.current) callback.current(next); }
    catch (reason) { if (mounted.current) setError(message(reason)); }
    finally { if (mounted.current) setBusy(false); }
  };
  const copy = async () => {
    if (!login) return;
    try { await navigator.clipboard.writeText(login.userCode); if (mounted.current) setCopied(true); }
    catch { if (mounted.current) setError("Could not copy. Select the sign-in code and copy it manually."); }
  };
  const verification = login?.verificationUrl?.startsWith("https://") ? login.verificationUrl : undefined;
  return <section className="grok-bot-settings" aria-label="ChatGPT connection"><div className="grok-settings-title"><h3>ChatGPT</h3>{account?.connected && <span className="grok-settings-success"><Check size={15} /> Connected</span>}</div>
    {account?.connected && !login ? <><p>Your bots use this account{account.plan ? ` (${account.plan})` : ""}.</p><button type="button" disabled={busy} onClick={() => void refresh()}><RefreshCw size={16} className={busy ? "grok-spin" : ""} /> Check connection</button></> : login ? <><p>Open the sign-in page, enter this code, then come back here.</p><div className="grok-settings-code"><code>{login.userCode}</code><button type="button" onClick={() => void copy()} aria-label="Copy sign-in code">{copied ? <Check size={17} /> : <Copy size={17} />}</button></div>{verification && <a className="grok-settings-primary" href={verification} target="_blank" rel="noreferrer">Open sign-in page <ExternalLink size={16} /></a>}<p role="status">Waiting for confirmation…{copied ? " Code copied." : ""}</p><button type="button" disabled={busy} onClick={() => void connect()}>Get a new code</button></> : <><p>Connect your ChatGPT account to start chatting.</p><button className="grok-settings-primary" type="button" disabled={busy} onClick={() => void connect()}>{busy && <Loader2 size={16} className="grok-spin" />} Connect ChatGPT</button></>}
    {error && <p className="grok-settings-error" role="alert">{error}</p>}
  </section>;
}

const MOTION_OPTIONS: Array<{ value: MotionPreference; label: string; description: string; icon: typeof Monitor }> = [
  { value: "system", label: "System", description: "Follow your device setting", icon: Monitor },
  { value: "on", label: "On", description: "Show gentle active states", icon: Play },
  { value: "off", label: "Off", description: "Keep the interface still", icon: Pause },
];

const MOTION_PREVIEW_AGENT: Agent = {
  id: "settings-motion-preview",
  name: "Motion preview",
  avatar: "blob",
  color: "#ff3347",
};

export function MotionSettings(): JSX.Element {
  const [preference, setPreference] = useState<MotionPreference>(() => readMotionPreference());
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    const onChange = (event: Event) => {
      const next = (event as CustomEvent<MotionPreference>).detail;
      if (next === "system" || next === "on" || next === "off") setPreference(next);
    };
    window.addEventListener("hermes-motion-change", onChange);
    return () => window.removeEventListener("hermes-motion-change", onChange);
  }, []);

  const choose = (next: MotionPreference) => {
    setPreference(next);
    applyMotionPreference(next);
  };

  const previewCopy = preference === "off"
    ? "Motion is off."
    : preference === "system" && reducedMotion
    ? "Your device asks for less motion."
    : "This is how an active Bot gently responds.";

  return <section className="grok-bot-settings grok-motion-settings" aria-label="Motion">
    <div className="grok-settings-title"><div><h3>Motion</h3><p>Choose how active Bots show progress.</p></div><Activity size={18} aria-hidden="true" /></div>
    <div className="grok-motion-options" role="radiogroup" aria-label="Motion preference">
      {MOTION_OPTIONS.map(({ value, label, description, icon: Icon }) => <button key={value} type="button" role="radio" aria-checked={preference === value} className={preference === value ? "is-selected" : ""} onClick={() => choose(value)}><Icon size={16} aria-hidden="true" /><span><strong>{label}</strong><small>{description}</small></span>{preference === value ? <Check size={15} aria-hidden="true" /> : null}</button>)}
    </div>
    <div className="grok-motion-preview" data-motion-preference={preference}>
      <AgentAvatar agent={MOTION_PREVIEW_AGENT} size="large" status="working" statusLabel="Motion preview" />
      <div><strong>Live preview</strong><span>{previewCopy}</span></div>
    </div>
    <p className="grok-settings-hint">System follows your device preference. On is an explicit choice and can show the preview even when your device asks for reduced motion.</p>
  </section>;
}

function usagePercent(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return "Unavailable";
  const rounded = Math.round(value * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}% remaining`;
}

function usageWindowLabel(window: RuntimeUsageWindow, index: number): string {
  if (window.window_duration_mins === 300) return "5 hour window";
  if (window.window_duration_mins === 10080) return "Weekly window";
  const id = window.id?.toLowerCase() ?? "";
  if (id.includes("secondary") || id.includes("week")) return "Weekly window";
  if (id.includes("primary") || id.includes("five") || id.includes("hour")) return "5 hour window";
  return window.id ? window.id.split(".").filter(Boolean).join(" ") : `Usage window ${index + 1}`;
}

function resetLabel(value?: string | null): string {
  if (!value) return "Reset time unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Reset time unavailable";
  return `Resets ${new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date)} local time`;
}

export function RuntimeUsageCard({ account, usage: initialUsage }: { account: RuntimeAccount | null; usage: RuntimeUsage | null }): JSX.Element {
  const [usage, setUsage] = useState(initialUsage);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setUsage(initialUsage), [initialUsage]);
  const refresh = async () => {
    setBusy(true); setError(null);
    try { setUsage(await getRuntimeUsage()); }
    catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const windows = usage?.windows?.length ? usage.windows : usage ? [{ id: "account", remaining_percent: usage.remaining ?? null, reset_at: usage.reset_at ?? null, window_duration_mins: null }] : [];
  const plan = account?.plan ?? (typeof usage?.planType === "string" ? usage.planType : null);
  return <section className="grok-resource-list grok-resource-single grok-usage-card" aria-label="GPT usage">
    <div className="grok-resource-list-head"><div><h2>GPT usage</h2><p>{plan ? `Your ${plan} ChatGPT account` : "Usage from your connected ChatGPT account"}</p></div><button type="button" className="grok-icon-button" aria-label="Refresh GPT usage" title="Refresh usage" disabled={busy} onClick={() => void refresh()}><RefreshCw size={17} className={busy ? "grok-spin" : ""} aria-hidden="true" /></button></div>
    {error ? <p className="grok-usage-empty" role="alert">Could not refresh usage. Previously loaded values may be out of date. {error}</p> : null}
    {!account?.connected && !usage ? <p className="grok-usage-empty">Connect ChatGPT to see usage for this account.</p> : !windows.length ? <p className="grok-usage-empty">Usage is unavailable right now. Try again later.</p> : <div className="grok-usage-windows">{windows.map((item, index) => <div className="grok-usage-window" key={`${item.id ?? "window"}-${index}`}><div><strong>{usageWindowLabel(item, index)}</strong><small>{resetLabel(item.reset_at)}</small></div><span>{usagePercent(item.remaining_percent)}</span></div>)}</div>}
  </section>;
}

export function AccountPanel({ userName, account, runtime, onLogout, logoutError }: { userName: string; account: RuntimeAccount | null; runtime: RuntimeStatus | null; onLogout: () => Promise<void>; logoutError: string | null }): JSX.Element {
  const accountLabel = account?.connected ? `${account.plan ?? "ChatGPT"} account connected` : runtime?.available ? "Workspace runtime available" : "ChatGPT account not connected";
  return <section className="grok-resource-list grok-resource-single grok-account-settings" aria-label="Account">
    <div className="grok-resource-list-head"><div><h2>Account</h2><p>Signed in to Hermes as {userName}.</p></div><UserRound size={18} aria-hidden="true" /></div>
    <div className="grok-account-summary"><span className="grok-account-avatar"><UserRound size={16} aria-hidden="true" /></span><div><strong>{userName}</strong><small>{accountLabel}</small></div></div>
    <button className="grok-account-signout" type="button" onClick={() => void onLogout()}><LogOut size={16} aria-hidden="true" /><span><strong>Sign out</strong><small>End this Hermes session</small></span></button>
    {logoutError ? <p className="grok-form-error" role="alert">{logoutError}</p> : null}
  </section>;
}

