import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const repositoryRoot = fileURLToPath(new URL('../', import.meta.url))

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    viewport: { width: 1600, height: 1000 },
  },
  webServer: [
    {
      command: `PYTHONPATH=.. PROTEIN_WORKBENCH_DATA_ROOT=${repositoryRoot}.scratch/webui-playwright ../.venv/bin/python -m uvicorn protein_workbench_public.bootstrap:create_application --factory --host 127.0.0.1 --port 8000`,
      port: 8000,
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      port: 5173,
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
