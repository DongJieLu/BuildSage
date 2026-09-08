import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期：Vite dev server 在 5173，通过 proxy 把 /api 转发到 FastAPI(8000)，实现同源、免 CORS。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
