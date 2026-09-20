import react from "@vitejs/plugin-react";
// vitest's defineConfig, not vite's: the `test` block below is not part of
// vite's own config type, so importing from "vite" fails `tsc -b` and takes
// `npm run build` down with it.
import { defineConfig } from "vitest/config";

// The backend runs on :8000. Proxying /api keeps the frontend origin-clean and
// means no CORS surprises when a teammate opens it from a different host.
export default defineConfig({
  plugins: [react()],
  // testing-library and jsdom are already in devDependencies; this is what makes
  // component tests actually run alongside the existing pure-logic ones.
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/outputs": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/assets": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
