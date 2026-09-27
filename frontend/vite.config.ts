import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: false,   // 由 scripts/prebuild.mjs 负责归档旧产物（避免触发 safe-delete 拦截）
    chunkSizeWarningLimit: 1600,
    // 关闭 preload polyfill：其内部 fetch(file://) 在 render-smoke 的 node 环境直接崩溃；
    // 本地单机 + 现代浏览器原生支持 modulepreload，无兼容损失。
    modulePreload: { polyfill: false },
  },
})
