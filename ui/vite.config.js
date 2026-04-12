import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  appType: 'spa',
  server: {
    host: '0.0.0.0',
    allowedHosts: ['trainer'],
    proxy: {
      '/api': 'http://localhost:5000',
      '/preview': 'http://localhost:5000',
      '/scene_preview': 'http://localhost:5000',
      '/clip': 'http://localhost:5000',
      '/bucket_clip': 'http://localhost:5000',
      '/bucket_waveform': 'http://localhost:5000',
      '/waveform': 'http://localhost:5000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
