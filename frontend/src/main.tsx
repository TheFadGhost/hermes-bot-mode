import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyMotionPreference, readMotionPreference } from "./lib/motion";
import "./styles.css";

const root = document.getElementById("root");

if (!root) throw new Error("Hermes could not find its app root");

applyMotionPreference(readMotionPreference());

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/bot/sw.js", { scope: "/bot/" });
  });
}

