import { defineConfig } from '@playwright/test'

const baseURL = process.env.PROTEIN_WORKBENCH_REAL_UI_URL
if (!baseURL) throw new Error('Set PROTEIN_WORKBENCH_REAL_UI_URL to the supervised built WebUI service.')

export default defineConfig({
  tsconfig: './tsconfig.test.json',
  testDir: './real-tests',
  timeout: 30 * 60_000,
  expect: { timeout: 20_000 },
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [['line'], ['html', { outputFolder: 'real-playwright-report', open: 'never' }], ['junit', { outputFile: 'real-test-results/junit.xml' }]],
  outputDir: 'real-test-results',
  use: { baseURL, actionTimeout: 20_000, navigationTimeout: 30_000, viewport: { width: 1600, height: 1000 }, trace: 'on', screenshot: 'only-on-failure' },
})
