import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// 生产：nginx 挂 /admin/（docs/18 §6 T2、§7 T5），产物资源路径必须带 /admin/ 前缀。
// dev：本机 5173 起 dev server，/api 反代到本机 backend（127.0.0.1:8041）；
//      生产同域 nginx Basic 自动携带，前端零凭据逻辑（MUST NOT：无 JWT/RBAC）。
export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8041',
    },
  },
})
