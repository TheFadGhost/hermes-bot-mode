import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/bot/",
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/bot/api": {
        target: "http://127.0.0.1:9120",
        changeOrigin: false,
      },
    },
  },
});

