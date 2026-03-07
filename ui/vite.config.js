import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:5000',
      '/preview': 'http://localhost:5000',
      '/scene_preview': 'http://localhost:5000',
      '/clip': 'http://localhost:5000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
