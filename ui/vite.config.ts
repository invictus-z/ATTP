import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8001',
        ws: true,
      },
    },
  },
  build: {
    outDir: '../src/attp_channel/web_app/static',
    emptyOutDir: true,
  },
})