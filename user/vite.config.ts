import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  base: './',
  plugins: [vue()],
  resolve: {
    alias: {
      '@attp/core': path.resolve(__dirname, '../typescript/attp/core'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
