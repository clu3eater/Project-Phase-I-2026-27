import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The console is served from the same origin as the API in production, so the
// dev server proxies /api and /ws rather than the front end knowing a host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
