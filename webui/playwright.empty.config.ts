import { defineConfig } from '@playwright/test'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const testDataRoot = mkdtempSync(join(tmpdir(), 'protein-workbench-empty-'))
writeFileSync(join(testDataRoot, 'modules.json'), JSON.stringify({ packages: [] }))

export default defineConfig({
  testDir: './tests/empty-carrier',
  globalSetup: './tests/support/journey-environment.ts',
  metadata: { backendDataRoot: testDataRoot },
  retries: 0,
  outputDir: 'test-results/empty-carrier',
  reporter: [['line'], ['junit', { outputFile: 'test-results/empty-carrier.xml' }]],
  timeout: 60_000,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:5182', screenshot: 'only-on-failure', trace: 'retain-on-failure', viewport: { width: 1600, height: 1000 } },
  webServer: [
    {
      command: `PYTHONPATH=.. PROTEIN_WORKBENCH_DATA_ROOT=${testDataRoot} ../.venv/bin/python -m uvicorn protein_workbench_public.bootstrap:create_application --factory --host 127.0.0.1 --port 8182`,
      port: 8182, reuseExistingServer: false, timeout: 60_000,
    },
    {
      command: 'PROTEIN_WORKBENCH_BACKEND_URL=http://127.0.0.1:8182 npm run dev -- --host 127.0.0.1 --port 5182 --strictPort',
      port: 5182, reuseExistingServer: false, timeout: 60_000,
    },
  ],
})
