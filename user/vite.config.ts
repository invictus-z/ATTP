import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  base: './',
  plugins: [vue()],
  resolve: {
    alias: {
      '@attp/core': path.resolve(__dirname, '../typescript/attp/core'),
      // SDK 源码在 ../typescript/（项目根之外），vite 从该位置解析 @noble 子路径会失败；
      // 显式指回 user/node_modules，主入口与 .js 子路径均能命中
      '@noble/curves': path.resolve(__dirname, 'node_modules/@noble/curves'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      // SDK 的 PEM 加载函数（loadPrivateKeyPem / importPublicPem）走 node:crypto，
      // 仅 Electron 主进程 / Node 侧调用，渲染进程不触发；显式 external 避免
      // vite 的 "externalized for browser compatibility" 警告
      external: [/^node:/],
    },
  },
})
