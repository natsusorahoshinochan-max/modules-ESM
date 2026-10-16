import { defineConfig } from '@playwright/test'

// Controlled hosts exercise component contracts; they do not provide an app backend.
export default defineConfig({
  tsconfig: './tsconfig.test.json',
  testDir: './tests/components',
  timeout: 60_000,
  workers: 4,
  retries: 0,
  outputDir: 'test-results/components',
  reporter: [['line'], ['junit', { outputFile: 'test-results/components.xml' }]],
  use: {
    baseURL: 'http://127.0.0.1:5181',
    screenshot: 'only-on-failure', trace: 'retain-on-failure',
    viewport: { width: 1600, height: 1000 },
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5181 --strictPort',
    port: 5181, reuseExistingServer: false, timeout: 60_000,
  },
})
