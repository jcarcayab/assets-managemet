import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// In dev, Vite serves the UI and proxies API/admin calls to Django so cookies stay same-origin.
const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [
    react(),
    // Installable app ("Add to Home Screen" / "Install app"). The service worker only caches the app shell
    // (JS, CSS, fonts, icons) so it opens instantly; financial data always comes from the API, never a cache.
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['apple-touch-icon.png'],
      manifest: {
        name: 'Patrimonio',
        short_name: 'Patrimonio',
        description: 'Patrimonio neto, inversiones y deudas',
        lang: 'es',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        background_color: '#f6f7f9',
        theme_color: '#0f766e',
        icons: [
          { src: '/pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,woff2,png,svg}'],
        // Client-side routes open from the cached shell; the server's own paths always hit the network.
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/admin\//, /^\/static\//],
        cleanupOutdatedCaches: true,
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
      },
    }),
  ],
  server: {
    proxy: {
      '/api': backend,
      '/admin': backend,
      '/static': backend,
    },
  },
})
