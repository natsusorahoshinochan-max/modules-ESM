import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const testDataRoot = mkdtempSync(join(tmpdir(), 'protein-workbench-webui-playwright-'))

export default defineConfig({
  tsconfig: './tsconfig.test.json',
  testDir: './tests/journeys',
  globalSetup: './tests/support/journey-environment.ts',
  metadata: { backendDataRoot: testDataRoot },
  retries: 0,
  outputDir: 'test-results/journeys',
  reporter: [['line'], ['junit', { outputFile: 'test-results/journeys.xml' }]],
  timeout: 60_000,
  workers: 4,
  use: {
    baseURL: 'http://127.0.0.1:5179',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    viewport: { width: 1600, height: 1000 },
  },
  webServer: [
    {
      command: `PYTHONPATH=.. PROTEIN_WORKBENCH_DATA_ROOT=${testDataRoot} ../.venv/bin/python -m uvicorn protein_workbench_public.bootstrap:create_application --factory --host 127.0.0.1 --port 8180`,
      port: 8180,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'PROTEIN_WORKBENCH_BACKEND_URL=http://127.0.0.1:8180 npm run dev -- --host 127.0.0.1 --port 5179 --strictPort',
      port: 5179,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
