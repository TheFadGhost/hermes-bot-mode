import { useEffect, useRef, useState, type CSSProperties, type ReactElement, type RefObject } from "react";
import { useReducedMotion } from "../lib/motion";
import "./ImageGeneration.css";

export type ImageGenerationState = {
  status: "generating" | "complete" | "error" | "cancelled";
  src?: string;
  alt?: string;
  message?: string;
  prompt?: string;
  aspectRatio?: string;
};

type ImageOrientation = "square" | "portrait" | "landscape";

type ImageAspect = {
  orientation: ImageOrientation;
  ratio: string;
  value: number;
  width: number;
  label: "Square" | "Portrait" | "Landscape";
};

const DEFAULT_ASPECT: ImageAspect = {
  orientation: "square",
  ratio: "1 / 1",
  value: 1,
  width: 205,
  label: "Square",
};

const CANCELLED_MESSAGE = "Stopped waiting for the image. The provider may still finish this request.";

function aspectFromValue(value?: string): ImageAspect {
  const normalized = value?.trim().toLowerCase() ?? "";
  if (!normalized) return DEFAULT_ASPECT;

  const named = normalized.replace(/[\s_-]+/g, "");
  if (named === "square" || named === "sq" || named === "1:1" || named === "1/1") return DEFAULT_ASPECT;

  const parts = normalized.match(/^(\d+(?:\.\d+)?)\s*[:/x×]\s*(\d+(?:\.\d+)?)$/);
  if (!parts) {
    if (named === "portrait" || named === "vertical") {
      return { orientation: "portrait", ratio: "2 / 3", value: 2 / 3, width: 166, label: "Portrait" };
    }
    if (named === "landscape" || named === "horizontal") {
      return { orientation: "landscape", ratio: "3 / 2", value: 3 / 2, width: 256, label: "Landscape" };
    }
    return DEFAULT_ASPECT;
  }

  const width = Number(parts[1]);
  const height = Number(parts[2]);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return DEFAULT_ASPECT;

  const valueRatio = width / height;
  if (Math.abs(valueRatio - 1) < 0.03) return DEFAULT_ASPECT;

  if (valueRatio < 1) {
    // Keep the supplied ratio while keeping the reference portrait height close to 250px.
    const displayWidth = Math.min(166, 250 * valueRatio);
    return {
      orientation: "portrait",
      ratio: `${width} / ${height}`,
      value: valueRatio,
      width: displayWidth,
      label: "Portrait",
    };
  }

  return {
    orientation: "landscape",
    ratio: `${width} / ${height}`,
    value: valueRatio,
    width: 256,
    label: "Landscape",
  };
}

function aspectStyle(aspect: ImageAspect): CSSProperties {
  return {
    "--generation-ratio": aspect.ratio,
    "--generation-width": `${aspect.width}px`,
  } as CSSProperties;
}

function useSpotlight(surfaceRef: RefObject<HTMLDivElement | null>, enabled: boolean): boolean {
  const reducedMotion = useReducedMotion();
  const [offscreen, setOffscreen] = useState(false);
  const [documentVisible, setDocumentVisible] = useState(() => typeof document === "undefined" || !document.hidden);

  useEffect(() => {
    const updateVisibility = () => setDocumentVisible(!document.hidden);
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    const target = surfaceRef.current;
    if (!enabled || !target || !("IntersectionObserver" in window)) {
      setOffscreen(false);
      return;
    }

    const observer = new IntersectionObserver(([entry]) => {
      setOffscreen(!entry.isIntersecting);
    }, { threshold: 0.01 });
    observer.observe(target);
    return () => observer.disconnect();
  }, [enabled, surfaceRef]);

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!enabled || !surface || reducedMotion || offscreen || !documentVisible) return;

    let frame = 0;
    const startedAt = performance.now();
    const cycleDuration = 7600;
    const updateSpotlight = (time: number) => {
      const phase = (time - startedAt) / cycleDuration;
      const angle = phase * Math.PI * 2;
      const x = 50 + Math.sin(angle * 1.08) * 26 + Math.sin(angle * 0.57 + 0.8) * 8;
      const y = 48 + Math.cos(angle * 0.94 + 0.6) * 23 + Math.sin(angle * 1.47) * 7;
      surface.style.setProperty("--spot-x", `${Math.max(12, Math.min(88, x))}%`);
      surface.style.setProperty("--spot-y", `${Math.max(12, Math.min(88, y))}%`);
      frame = window.requestAnimationFrame(updateSpotlight);
    };

    updateSpotlight(startedAt);
    return () => window.cancelAnimationFrame(frame);
  }, [documentVisible, enabled, offscreen, reducedMotion, surfaceRef]);

  return reducedMotion;
}

function DownloadIcon(): ReactElement {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M12 3.5v11" />
      <path d="m7.8 10.8 4.2 4.2 4.2-4.2" />
      <path d="M5 19.5h14" />
    </svg>
  );
}

function AlertIcon(): ReactElement {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M12 3.7 21 20.3H3L12 3.7Z" />
      <path d="M12 9v5" />
      <path d="M12 17.4h.01" />
    </svg>
  );
}

function quotedPrompt(prompt?: string): string | null {
  const trimmed = prompt?.trim();
  return trimmed ? `“${trimmed}”` : null;
}

function GenerationCaption({ heading, detail, prompt }: { heading: string; detail?: string; prompt?: string }): ReactElement {
  const promptText = quotedPrompt(prompt);
  return (
    <figcaption className="image-generation-caption">
      <strong>{heading}</strong>
      {promptText ? <span className="image-generation-prompt" title={promptText}>{promptText}</span> : detail ? <span className="image-generation-detail">{detail}</span> : null}
    </figcaption>
  );
}

function StatusCard({ state, previewError = false }: { state: ImageGenerationState; previewError?: boolean }): ReactElement {
  const cancelled = state.status === "cancelled";
  const heading = cancelled ? "Image generation stopped" : "Image generation failed";
  const detail = cancelled ? CANCELLED_MESSAGE : previewError ? "The saved image could not be loaded." : state.message ?? "The image request did not finish.";

  return (
    <div className={`image-generation-card image-generation-state ${cancelled ? "image-generation-cancelled" : "image-generation-error"}`} role={cancelled ? "status" : "alert"} aria-label={heading}>
      <span className="image-generation-state-icon"><AlertIcon /></span>
      <div className="image-generation-state-copy">
        <strong>{heading}</strong>
        <span>{detail}</span>
      </div>
    </div>
  );
}

export function ImageGenerationCard({ state }: { state: ImageGenerationState }): ReactElement {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const reducedMotion = useSpotlight(surfaceRef, state.status === "generating");
  const aspect = aspectFromValue(state.aspectRatio);
  const style = aspectStyle(aspect);
  const [previewError, setPreviewError] = useState(false);

  useEffect(() => {
    setPreviewError(false);
  }, [state.src, state.status]);

  if (state.status === "complete" && state.src && !previewError) {
    return (
      <figure className="image-generation-card image-generation-result" style={style}>
        <div className="image-generation-surface image-generation-complete-surface" data-orientation={aspect.orientation}>
          <img
            className="image-generation-image"
            src={state.src}
            alt={state.alt ?? "Generated image"}
            loading="lazy"
            onError={() => setPreviewError(true)}
          />
          <a className="image-generation-download" href={state.src} download aria-label="Download generated image" title="Download generated image">
            <DownloadIcon />
          </a>
        </div>
        <GenerationCaption heading="Generated image" prompt={state.prompt} />
      </figure>
    );
  }

  if (state.status === "error" || state.status === "cancelled" || previewError || (state.status === "complete" && !state.src)) {
    return <StatusCard state={state.status === "complete" ? { ...state, status: "error" } : state} previewError={previewError || (state.status === "complete" && !state.src)} />;
  }

  return (
    <figure className="image-generation-card image-generation-pending" style={style} role="status" aria-label="Generating image">
      <div ref={surfaceRef} className="image-generation-surface" data-orientation={aspect.orientation} data-motion={reducedMotion ? "static" : "dynamic"}>
        <div className="image-generation-spotlight-glow" aria-hidden="true" />
        <div className="image-generation-spotlight-grid" aria-hidden="true" />
        <span className="image-generation-aspect-badge">{aspect.label}</span>
      </div>
      <GenerationCaption heading="Generating image" detail={state.message ?? "Preparing a visual result…"} prompt={state.prompt} />
    </figure>
  );
}

export default ImageGenerationCard;

