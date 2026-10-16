import { rmSync } from 'node:fs'
import type { FullConfig } from '@playwright/test'

// Only the disposable backend root belongs to this run. Playwright traces and
// reports have a separate lifecycle and remain available after failures.
export default async function journeyEnvironment(config: FullConfig) {
  const root = config.metadata.backendDataRoot
  if (typeof root !== 'string' || !root) throw new Error('Journey backend data root is missing')
  return async () => { rmSync(root, { recursive: true, force: true }) }
}
