import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import type { Agent, AvatarShape } from "../lib/types";
import "./bot-identity-motion.css";

/** The creator palette, ordered to match the reference swatch row. */
export const AVATAR_COLORS = [
  "#996638",
  "#ff3347",
  "#ff6713",
  "#ff9d0a",
  "#17c765",
  "#0eb8b0",
  "#2d93fa",
  "#8754f5",
  "#ff36a0",
  "#7a7a7a",
] as const;

export const AVATAR_COLOR_NAMES = [
  "Cedar",
  "Coral",
  "Tangerine",
  "Marigold",
  "Meadow",
  "Teal",
  "Sky",
  "Iris",
  "Pink",
  "Graphite",
] as const;

/** Eight small, organic contours used by the Bot creator and roster. */
export const AVATAR_SHAPES: readonly AvatarShape[] = [
  "blob",
  "orb",
  "capsule",
  "lozenge",
  "peak",
  "hex",
  "cloud",
  "drop",
];

export const AVATAR_SHAPE_NAMES: Record<AvatarShape, string> = {
  blob: "Blob",
  orb: "Orb",
  capsule: "Capsule",
  lozenge: "Lozenge",
  peak: "Peak",
  hex: "Hex",
  cloud: "Cloud",
  drop: "Drop",
};

export type AvatarStatus = "idle" | "working" | "typing" | "tool" | "waiting" | "complete" | "error";

const SHAPE_PATHS: Record<AvatarShape, string> = {
  blob: "M50 5C67 5 82 13 90 27C99 42 96 61 89 75C81 90 65 96 48 95C29 94 14 85 8 71C2 57 6 39 15 25C24 11 35 5 50 5Z",
  orb: "M50 5C70 5 87 19 93 38C99 57 91 76 75 88C59 100 38 96 22 87C7 78 3 60 7 43C12 22 29 5 50 5Z",
  capsule: "M28 8C18 8 10 16 10 26V74C10 84 18 92 28 92H72C82 92 90 84 90 74V26C90 16 82 8 72 8H28Z",
  lozenge: "M25 22C13 22 6 33 6 50C6 67 13 78 25 78H75C87 78 94 67 94 50C94 33 87 22 75 22H25Z",
  peak: "M50 8C53 8 56 10 58 14L91 76C95 84 89 92 80 92H20C11 92 5 84 9 76L42 14C44 10 47 8 50 8Z",
  hex: "M31 9C34 7 38 6 42 6H58C62 6 66 7 69 9L87 22C90 24 92 28 92 32V68C92 72 90 76 87 78L69 91C66 93 62 94 58 94H42C38 94 34 93 31 91L13 78C10 76 8 72 8 68V32C8 28 10 24 13 22L31 9Z",
  cloud: "M19 68C11 68 6 62 6 54C6 46 12 40 20 39C20 24 32 13 47 13C60 13 70 22 73 34C84 33 94 41 94 52C94 62 86 68 76 68H19Z",
  drop: "M50 5C60 19 78 37 86 52C94 67 85 84 71 91C57 99 40 97 27 89C14 81 7 67 13 52C19 37 37 20 50 5Z",
};

const EYE_PATH = "M34 52C36 47 41 47 43 51L41 61C40 65 35 65 33 61C32 59 33 55 34 52ZM58 51C60 47 65 47 67 51L69 59C70 63 66 66 63 63C61 61 60 58 59 55C58 54 58 52 58 51Z";
const EYE_TRANSFORMS: Record<AvatarShape, string> = {
  blob: "rotate(-7 50 55)",
  orb: "rotate(5 50 53)",
  capsule: "rotate(-3 50 53)",
  lozenge: "rotate(7 50 53)",
  peak: "rotate(-10 50 58)",
  hex: "rotate(4 50 53)",
  cloud: "rotate(-5 50 53)",
  drop: "rotate(11 50 58)",
};
const HEX_COLOR = /^#[0-9a-f]{6}$/i;

function isAvatarShape(value: unknown): value is AvatarShape {
  return typeof value === "string" && value in SHAPE_PATHS;
}

function isAvatarColor(value: unknown): value is string {
  return typeof value === "string" && HEX_COLOR.test(value);
}

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function getAgentColor(agent: Agent | null | undefined, index = 0): string {
  if (isAvatarColor(agent?.color)) return agent.color;
  const seed = agent?.id ?? `agent-${index}`;
  return AVATAR_COLORS[stableHash(seed) % AVATAR_COLORS.length];
}

export function getAgentShape(agent: Agent | null | undefined, index = 0): AvatarShape {
  if (isAvatarShape(agent?.avatar)) return agent.avatar;
  const seed = agent?.id ?? `agent-${index}`;
  return AVATAR_SHAPES[stableHash(`${seed}:shape`) % AVATAR_SHAPES.length];
}

export interface BotGlyphProps {
  shape?: AvatarShape | string | null;
  color?: string | null;
  size?: number | string;
  className?: string;
  title?: string;
}

/**
 * A bounded vector identity. The two eye marks stay consistent across all
 * shapes, which makes the creator's compact icon row read as one family.
 */
export function BotGlyph({ shape = "blob", color = AVATAR_COLORS[6], size = 32, className, title }: BotGlyphProps): JSX.Element {
  const identity = useId().replace(/:/g, "");
  const resolvedShape = isAvatarShape(shape) ? shape : "blob";
  const resolvedColor = isAvatarColor(color) ? color : AVATAR_COLORS[6];
  const dimension = typeof size === "number" ? `${size}px` : size;
  const classes = ["bot-glyph", className].filter(Boolean).join(" ");

  return (
    <svg
      className={classes || undefined}
      width={dimension}
      height={dimension}
      viewBox="0 0 100 100"
      fill="none"
      style={{ color: resolvedColor } as CSSProperties}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <defs>
        <clipPath id={`bot-clip-${identity}`}><path d={SHAPE_PATHS[resolvedShape]} /></clipPath>
        <linearGradient id={`bot-shine-${identity}`}><stop stopColor="white" stopOpacity="0" /><stop offset=".5" stopColor="white" stopOpacity=".3" /><stop offset="1" stopColor="white" stopOpacity="0" /></linearGradient>
      </defs>
      <path d={SHAPE_PATHS[resolvedShape]} fill="currentColor" />
      <g clipPath={`url(#bot-clip-${identity})`}><path className="bot-head-shine" d="M-40 0H-10L30 45H0Z" fill={`url(#bot-shine-${identity})`} /></g>
      <g transform={EYE_TRANSFORMS[resolvedShape]}>
        <path className="bot-eyes" d={EYE_PATH} fill="#172023" />
      </g>
    </svg>
  );
}

export interface AgentAvatarProps {
  agent: Agent | null | undefined;
  index?: number;
  size?: "small" | "medium" | "large";
  status?: AvatarStatus;
  statusLabel?: string;
}

/** Drop-in replacement for the incumbent AgentAvatar props. */
export function AgentAvatar({ agent, index = 0, size = "medium", status = "idle", statusLabel }: AgentAvatarProps): JSX.Element {
  const element = useRef<HTMLSpanElement>(null);
  const [motionVisible, setMotionVisible] = useState(true);
  const [imageFailed, setImageFailed] = useState(false);
  const moving = status === "working" || status === "typing" || status === "tool";
  useEffect(() => {
    setImageFailed(false);
  }, [agent?.id, agent?.avatar_url]);
  useEffect(() => {
    if (!moving) return;
    let inView = true;
    const update = () => setMotionVisible(inView && !document.hidden);
    const observer = typeof IntersectionObserver !== "undefined" ? new IntersectionObserver(([entry]) => { inView = entry.isIntersecting; update(); }) : null;
    if (element.current) observer?.observe(element.current);
    document.addEventListener("visibilitychange", update);
    update();
    return () => { observer?.disconnect(); document.removeEventListener("visibilitychange", update); };
  }, [moving]);
  const color = getAgentColor(agent, index);
  const shape = getAgentShape(agent, index);
  const style = {
    "--avatar-color": color,
    background: "transparent",
    boxShadow: "none",
  } as CSSProperties;

  return (
    <span
      ref={element}
      className={`agent-avatar agent-avatar-${size} agent-avatar-glyph ${status !== "idle" ? `has-status status-${status}` : ""}`}
      style={style}
      data-status={status}
      data-motion={motionVisible ? "running" : "paused"}
      aria-label={statusLabel}
      role={statusLabel ? "img" : undefined}
    >
      {agent?.avatar_url && !imageFailed ? <img src={agent.avatar_url} alt="" onError={() => setImageFailed(true)} /> : <BotGlyph shape={shape} color={color} size="100%" />}
      {status !== "idle" ? <span className="agent-avatar-status" aria-hidden="true"><i /><i /><i /></span> : null}
    </span>
  );
}

