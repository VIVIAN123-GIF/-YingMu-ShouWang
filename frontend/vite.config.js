import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const elementResolver = ElementPlusResolver({ importStyle: process.env.VITEST ? false : 'css' })

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxyTarget = env.VITE_DEV_API_PROXY_TARGET || 'http://127.0.0.1:8000'
  return {
  base: env.VITE_BASE_PATH || '/',
  // Public/Pages builds are intentionally media-free: selected human video is
  // available only in the local restricted demonstration package.
  publicDir: mode === 'pages' ? false : 'public',
  plugins: [
    vue(),
    AutoImport({ resolvers: [elementResolver], dts: false }),
    Components({ resolvers: [elementResolver], dts: false }),
  ],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': apiProxyTarget,
      '/media/session': apiProxyTarget,
      '/media/live': apiProxyTarget,
      '/media/assets': apiProxyTarget,
    },
  },
  build: {
    chunkSizeWarningLimit: 600,
  },
  test: {
    include: ['src/tests/**/*.spec.js'],
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/tests/setup.js'],
  },
  }
})
