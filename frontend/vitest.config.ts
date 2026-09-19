import { mergeConfig } from "vite";
import { defineConfig } from "vitest/config";

import viteConfig from "./vite.config";

// Extends the app's own Vite config rather than replacing it, so the React
// plugin the existing JSX tests rely on stays in place.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./test/setup.ts"],
      include: [
        "src/**/__tests__/**/*.{test,spec}.{js,jsx,ts,tsx}",
        "src/**/*.{test,spec}.{js,jsx,ts,tsx}",
        "test/**/*.{test,spec}.{ts,tsx}",
      ],
    },
  }),
);
