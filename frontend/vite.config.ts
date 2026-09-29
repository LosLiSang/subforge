import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(import.meta.dirname, '../subforge/ui/dist'),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/covers': 'http://127.0.0.1:8765',
      '/tracks': 'http://127.0.0.1:8765',
      '/picker': 'http://127.0.0.1:8765',
      '/library': 'http://127.0.0.1:8765',
      '/items': 'http://127.0.0.1:8765',
      '/tasks': 'http://127.0.0.1:8765',
      '/settings': 'http://127.0.0.1:8765',
      '/profiles': 'http://127.0.0.1:8765',
      '/audio-models': 'http://127.0.0.1:8765',
      '/creators': 'http://127.0.0.1:8765',
    },
  },
})
