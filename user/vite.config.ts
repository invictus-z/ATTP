import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import pkg from './package.json'

export default defineConfig({
  base: './',
  plugins: [vue()],
  define: {
    // 构建期注入版本号，侧栏等处直接用，避免硬编码漂移
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
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
