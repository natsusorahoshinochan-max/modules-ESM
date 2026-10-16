import { defineConfig } from '@playwright/test'

// Pure owners and transformations run in Node; no browser or server is started.
export default defineConfig({
  tsconfig: './tsconfig.test.json',
  testDir: './tests/logic',
  timeout: 15_000,
  workers: 4,
  retries: 0,
  outputDir: 'test-results/logic',
  reporter: [['line'], ['junit', { outputFile: 'test-results/logic.xml' }]],
})
