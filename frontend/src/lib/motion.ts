import { useEffect, useState } from "react";
import type { MotionPreference } from "./types";

export const MOTION_STORAGE_KEY = "hermes-motion";
export const MOTION_CHANGE_EVENT = "hermes-motion-change";

export function isMotionPreference(value: unknown): value is MotionPreference {
  return value === "system" || value === "on" || value === "off";
}

export function readMotionPreference(): MotionPreference {
  try {
    const value = window.localStorage.getItem(MOTION_STORAGE_KEY);
    return isMotionPreference(value) ? value : "system";
  } catch {
    return "system";
  }
}

export function applyMotionPreference(preference: MotionPreference): void {
  document.documentElement.dataset.motion = preference;
  try {
    window.localStorage.setItem(MOTION_STORAGE_KEY, preference);
  } catch {
    // Storage is optional; the preference still applies for this session.
  }
  window.dispatchEvent(new CustomEvent<MotionPreference>(MOTION_CHANGE_EVENT, { detail: preference }));
}

export function prefersReducedMotion(): boolean {
  const preference = document.documentElement.dataset.motion;
  if (preference === "on") return false;
  if (preference === "off") return true;
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(prefersReducedMotion());
    const onPreferenceChange = () => update();
    update();
    mediaQuery.addEventListener("change", update);
    window.addEventListener(MOTION_CHANGE_EVENT, onPreferenceChange);
    return () => {
      mediaQuery.removeEventListener("change", update);
      window.removeEventListener(MOTION_CHANGE_EVENT, onPreferenceChange);
    };
  }, []);

  return reduced;
}


