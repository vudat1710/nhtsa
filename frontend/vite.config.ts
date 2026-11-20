import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API runs on :8000 (uvicorn); the UI calls /api/* and Vite forwards it.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
})
