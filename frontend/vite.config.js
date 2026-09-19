import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend runs on :8000. Proxying /api keeps the frontend origin-clean and
// means no CORS surprises when a teammate opens it from a different host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
