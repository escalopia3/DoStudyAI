import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '')
  return {
    envDir: '..',
    plugins: [vue()],
    server: {
      proxy: {
        '/api/v2': { target: env.VITE_V2_PROXY_TARGET || 'http://127.0.0.1:8092', changeOrigin: true }
      }
    }
  }
})
