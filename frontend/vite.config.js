import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 서버에서도 프로덕션(Nginx)과 동일하게 /api 경로를 백엔드로 프록시한다.
    // 덕분에 프론트엔드 코드는 환경에 상관없이 상대경로 '/api' 하나만 쓰면 되고,
    // 브라우저 입장에서는 항상 동일 출처(same-origin)라 CORS 자체가 발생하지 않는다.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
