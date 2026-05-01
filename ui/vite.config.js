import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const flaskPort = process.env.FLASK_PORT || 5000
const backend = `http://localhost:${flaskPort}`

export default defineConfig({
  plugins: [react()],
  appType: 'spa',
  server: {
    host: '0.0.0.0',
    allowedHosts: ['trainer'],
    proxy: {
      '/api': backend,
      '/preview': backend,
      '/scene_preview': backend,
      // Regex so `/clip/<id>` proxies to Flask but `/clips`, `/clips/<id>`
      // (the SPA route) stay with Vite.
      '^/clip/[0-9]': backend,
      '/clip_item_preview': backend,
      '/bucket_clip': backend,
      '/bucket_waveform': backend,
      '/waveform': backend,
      '/output_image': backend,
      '/output_thumb': backend,
    },
  },
  build: {
    outDir: 'dist',
  },
})
