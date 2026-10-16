import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const testDataRoot = mkdtempSync(join(tmpdir(), 'protein-workbench-module-ui-'))
export default defineConfig({
  tsconfig: './tsconfig.test.json',
  testDir: './tests/module-ui',
  globalSetup: './tests/support/journey-environment.ts',
  metadata: { backendDataRoot: testDataRoot }, retries: 0,
  outputDir: 'test-results/module-ui',
  reporter: [['line'], ['junit', { outputFile: 'test-results/module-ui.xml' }]],
  timeout: 60_000, workers: 1,
  use: { baseURL: 'http://127.0.0.1:5184', screenshot: 'only-on-failure', trace: 'retain-on-failure', viewport: { width: 1600, height: 1000 } },
  webServer: [
    { command: `PYTHONPATH=.. PROTEIN_WORKBENCH_DATA_ROOT=${testDataRoot} ../.venv/bin/python -m uvicorn tests.fixtures.module_ui.application:create_application --factory --host 127.0.0.1 --port 8184`, port: 8184, reuseExistingServer: false, timeout: 60_000 },
    { command: 'PROTEIN_WORKBENCH_BACKEND_URL=http://127.0.0.1:8184 npm run dev -- --host 127.0.0.1 --port 5184 --strictPort', port: 5184, reuseExistingServer: false, timeout: 60_000 },
  ],
})
