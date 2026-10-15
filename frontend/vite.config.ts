import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, Vite serves the UI and proxies API/admin calls to Django so cookies stay same-origin.
const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': backend,
      '/admin': backend,
      '/static': backend,
    },
  },
})
