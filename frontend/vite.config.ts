import { defineConfig } from 'vite'

// https://vite.dev/config/
//
// No @vitejs/plugin-react here on purpose. With Vite 8 (rolldown) that plugin
// emits `RefreshRuntime.getRefreshReg(...)` while the runtime Vite serves at
// /@react-refresh does not define it, so every component module throws
// "getRefreshReg is not a function" and the app renders blank.
//
// Vite 8 transforms .tsx natively using the `jsx: react-jsx` setting from
// tsconfig.app.json, so JSX, TypeScript and production builds all work without
// it. What we give up is React Fast Refresh: editing a component does a full
// page reload instead of preserving state. Worth revisiting if the plugin and
// the runtime line up in a later release.
export default defineConfig({})
