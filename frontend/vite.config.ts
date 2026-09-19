import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The backend runs on :8000. Proxying /api keeps the frontend origin-clean and
// means no CORS surprises when a teammate opens it from a different host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/outputs": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/assets": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
