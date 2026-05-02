import { defineConfig } from 'vite'

export default defineConfig({
  base: './',
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
    outDir: 'dist',
    emptyOutDir: true,
  },
})