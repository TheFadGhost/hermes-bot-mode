import { ChevronDown, LoaderCircle, X } from "lucide-react";
import { useRef, useState } from "react";
import type { CSSProperties, FormEvent, KeyboardEvent } from "react";
import type { AgentInput, AvatarShape } from "../lib/types";
import {
  AVATAR_COLORS,
  AVATAR_COLOR_NAMES,
  AVATAR_SHAPES,
  AVATAR_SHAPE_NAMES,
  BotGlyph,
} from "./BotIdentity";
import "./bot-creator.css";

export interface BotCreatorProps {
  onClose: () => void;
  onCreate: (input: AgentInput) => Promise<void>;
  firstBot?: boolean;
}

interface Suggestion {
  name: string;
  description: string;
  color: (typeof AVATAR_COLORS)[number];
  shape: AvatarShape;
  detail: string;
}

const SUGGESTIONS: readonly Suggestion[] = [
  {
    name: "Night Shift",
    description: "Review open tasks and prepare a concise morning digest. Flag urgent items and organize next steps. Ask before sending messages or making irreversible changes.",
    color: AVATAR_COLORS[3],
    shape: "lozenge",
    detail: "Review open tasks and prepare a morning digest",
  },
  {
    name: "Inbox Triage",
    description: "Sort pasted emails by urgency and topic, draft thoughtful replies in my voice, and leave anything uncertain for my approval. Never send a message without approval.",
    color: AVATAR_COLORS[8],
    shape: "cloud",
    detail: "Sort pasted emails and draft replies",
  },
];

function errorText(reason: unknown): string {
  if (reason instanceof Error && reason.message) return reason.message;
  return "We couldn’t create this Bot. Try again.";
}

function moveSelection<T extends string>(items: readonly T[], value: T, key: string): T {
  const current = Math.max(0, items.indexOf(value));
  if (key === "Home") return items[0];
  if (key === "End") return items[items.length - 1];
  if (key === "ArrowLeft" || key === "ArrowUp") return items[(current - 1 + items.length) % items.length];
  return items[(current + 1) % items.length];
}

export default function BotCreator({ onClose, onCreate }: BotCreatorProps): JSX.Element {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState<(typeof AVATAR_COLORS)[number]>(AVATAR_COLORS[6]);
  const [shape, setShape] = useState<AvatarShape>("blob");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const colorRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const shapeRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const nameRef = useRef<HTMLInputElement | null>(null);

  const nameError = touched && !name.trim() ? "Add a name to get started." : null;

  const onColorKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = moveSelection(AVATAR_COLORS, color, event.key);
    setColor(next);
    colorRefs.current[AVATAR_COLORS.indexOf(next)]?.focus();
  };

  const onShapeKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = moveSelection(AVATAR_SHAPES, shape, event.key);
    setShape(next);
    shapeRefs.current[AVATAR_SHAPES.indexOf(next)]?.focus();
  };

  const applySuggestion = (suggestion: Suggestion) => {
    setName(suggestion.name);
    setDescription(suggestion.description);
    setColor(suggestion.color);
    setShape(suggestion.shape);
    setDetailsOpen(true);
    setTouched(false);
    setError(null);
    nameRef.current?.focus();
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    setTouched(true);
    if (!trimmedName || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate({
        name: trimmedName,
        description: description.trim(),
        avatar: shape,
        color,
      });
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="bot-creator" aria-labelledby="bot-creator-title">
      <main className="bot-creator-main">
        <header className="bot-creator-header">
          <div className="bot-creator-heading-mark" aria-hidden="true"><BotGlyph shape={shape} color={color} size={22} /></div>
          <h1 id="bot-creator-title">New Bot</h1>
          <button className="bot-creator-close" type="button" aria-label="Close Bot creator" onClick={onClose}><X size={19} /></button>
        </header>

        <form className="bot-creator-form" onSubmit={(event) => void submit(event)} noValidate>
          <div className="bot-creator-form-scroll">
            <div className="bot-creator-identity" aria-live="polite">
              <BotGlyph shape={shape} color={color} size={80} title={`${AVATAR_SHAPE_NAMES[shape]} avatar`} />
            </div>

            <fieldset className="bot-creator-fieldset">
              <legend>Color</legend>
              <div className="bot-creator-swatches" role="radiogroup" aria-label="Bot color">
                {AVATAR_COLORS.map((value, index) => (
                  <button
                    aria-label={`${AVATAR_COLOR_NAMES[index]} color`}
                    aria-checked={color === value}
                    className={`bot-creator-swatch ${color === value ? "is-selected" : ""}`}
                    key={value}
                    onClick={() => setColor(value)}
                    onKeyDown={onColorKeyDown}
                    ref={(element) => { colorRefs.current[index] = element; }}
                    role="radio"
                    style={{ "--swatch-color": value } as CSSProperties}
                    tabIndex={color === value ? 0 : -1}
                    type="button"
                  />
                ))}
              </div>
            </fieldset>

            <fieldset className="bot-creator-fieldset bot-creator-shape-fieldset">
              <legend>Shape</legend>
              <div className="bot-creator-shapes" role="radiogroup" aria-label="Bot shape">
                {AVATAR_SHAPES.map((value, index) => (
                  <button
                    aria-label={`${AVATAR_SHAPE_NAMES[value]} shape`}
                    aria-checked={shape === value}
                    className={`bot-creator-shape ${shape === value ? "is-selected" : ""}`}
                    key={value}
                    onClick={() => setShape(value)}
                    onKeyDown={onShapeKeyDown}
                    ref={(element) => { shapeRefs.current[index] = element; }}
                    role="radio"
                    tabIndex={shape === value ? 0 : -1}
                    type="button"
                  >
                    <BotGlyph shape={value} color={color} size={27} />
                  </button>
                ))}
              </div>
            </fieldset>

            <div className="bot-creator-name-field">
              <label htmlFor="bot-creator-name">Name</label>
              <input
                aria-describedby={nameError ? "bot-creator-name-error" : undefined}
                aria-invalid={nameError ? true : undefined}
                autoComplete="off"
                id="bot-creator-name"
                maxLength={120}
                onBlur={() => setTouched(true)}
                onChange={(event) => { setName(event.target.value); if (error) setError(null); }}
                placeholder="New Bot"
                ref={nameRef}
                value={name}
              />
              {nameError ? <p className="bot-creator-error" id="bot-creator-name-error" role="alert">{nameError}</p> : null}
            </div>

            <details className="bot-creator-details" open={detailsOpen} onToggle={(event) => setDetailsOpen(event.currentTarget.open)}>
              <summary><span>Details</span><span className="bot-creator-optional">Optional</span><ChevronDown size={16} /></summary>
              <div className="bot-creator-details-body">
                <label htmlFor="bot-creator-description">What should this Bot help with?</label>
                <textarea
                  id="bot-creator-description"
                  maxLength={20_000}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="Give it a clear job and the boundaries it should follow."
                  rows={4}
                  value={description}
                />
                <p>These instructions guide the Bot when it works on your behalf.</p>
              </div>
            </details>

            <div className="bot-creator-actions">
              {error ? <p className="bot-creator-error" role="alert">{error}</p> : null}
              <button className="bot-creator-submit" disabled={!name.trim() || busy} type="submit">
                {busy ? <><LoaderCircle className="bot-creator-spinner" size={17} /> Creating…</> : "Get started"}
              </button>
            </div>

            <section className="bot-creator-suggestions" aria-labelledby="bot-creator-suggestions-title">
              <div className="bot-creator-suggestions-heading"><h2 id="bot-creator-suggestions-title">Suggestions</h2><span>Start with a clear job</span></div>
              <div className="bot-creator-suggestion-list">
                {SUGGESTIONS.map((suggestion) => (
                  <button className="bot-creator-suggestion" key={suggestion.name} onClick={() => applySuggestion(suggestion)} type="button">
                    <BotGlyph shape={suggestion.shape} color={suggestion.color} size={38} />
                    <span><strong>{suggestion.name}</strong><small>{suggestion.detail}</small></span>
                  </button>
                ))}
              </div>
              </section>
          </div>
        </form>
      </main>
    </section>
  );
}

