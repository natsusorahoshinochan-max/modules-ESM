import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  resolve: { dedupe: ['react', 'react-dom'] },
  publicDir: '../examples/v2/structures',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: loadEnv(mode, '.', 'PROTEIN_WORKBENCH_').PROTEIN_WORKBENCH_BACKEND_URL ?? 'http://127.0.0.1:8000',
        ws: true,
      },
    },
  },
}))
