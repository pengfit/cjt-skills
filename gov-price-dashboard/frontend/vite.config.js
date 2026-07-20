import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,  // 2026-07-20 19:21 修: 监听所有接口 (含 IPv4 127.0.0.1); 默认只监听 localhost (IPv6 ::1) 让 127.0.0.1 连不上
    port: 5300,
    allowedHosts: true,  // 2026-07-20 19:21 修: 白名单全开 (配合 host: true)
    proxy: {
      '/api': {
        target: 'http://localhost:5200',
        changeOrigin: true,
      },
    },
  },
})
