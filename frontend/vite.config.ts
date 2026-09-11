import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  if (command === 'serve' && mode === 'development' && !env.VITE_DEV_API_TARGET) throw new Error('请在环境文件中配置 VITE_DEV_API_TARGET')
  return {
    plugins: [react()],
    server: env.VITE_DEV_API_TARGET ? { proxy: { '/api': { target: env.VITE_DEV_API_TARGET, changeOrigin: true, ws: true } } } : undefined,
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('/node_modules/zrender/')) return 'chart-renderer'
            if (id.includes('/node_modules/echarts/')) return 'chart-core'
            if (/\/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react-runtime'
          },
        },
      },
    },
  }
})
