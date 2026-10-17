import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In local dev, proxy /api to the FastAPI backend (uvicorn on :8080).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8080", changeOrigin: true },
      "/healthz": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
});
