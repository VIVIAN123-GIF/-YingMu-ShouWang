import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const elementResolver = ElementPlusResolver({ importStyle: process.env.VITEST ? false : 'css' })

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
  base: env.VITE_BASE_PATH || '/',
  plugins: [
    vue(),
    AutoImport({ resolvers: [elementResolver], dts: false }),
    Components({ resolvers: [elementResolver], dts: false }),
  ],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/media': 'http://127.0.0.1:8000',
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
