import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = process.env.VITE_API_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": api, "/health": api } },
  build: { chunkSizeWarningLimit: 2500 },
});
