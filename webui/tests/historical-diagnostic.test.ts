import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { PublishedResults } from '../src/published-results'
import { PublicV2Client } from '../src/protocol/client'
import { RunDiagnostics } from '../src/RunDiagnostics'

test('a failed historical Run shows its recorded run-level reason without inventing a node', async () => {
  const diagnostic = { code: 'selection_failed', message: 'Recorded required score was absent', retryable: false, correlation_id: 'recorded-error', details: { reason: 'One required score was absent' } }
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ project_id: 'research', run_id: 'historical', workflow_commit_id: 'recorded', status: 'failed', node_dispositions: [], outputs: [], artifact_index: [], diagnostic }))
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const socket = globalThis.WebSocket
  globalThis.WebSocket = class { close() {} } as unknown as typeof WebSocket
  const port = (server.address() as { port: number }).port
  const results = new PublishedResults(new PublicV2Client(`http://127.0.0.1:${port}`))
  try {
    results.openRun({ project_id: 'research', run_id: 'historical' })
    await results.refresh()
    const snapshot = results.getSnapshot()
    assert.deepEqual(snapshot.runDiagnostic, diagnostic)
    assert.deepEqual(snapshot.diagnostics, {})
    const displayed = renderToStaticMarkup(createElement(RunDiagnostics, { errors: snapshot.diagnostics, runDiagnostic: snapshot.runDiagnostic, onFocus: () => assert.fail('No node owns this diagnostic') }))
    assert.match(displayed, /Recorded required score was absent/)
    assert.match(displayed, /One required score was absent/)
    assert.doesNotMatch(displayed, /定位节点/)
    results.openRun(undefined)
    assert.equal(results.getSnapshot().runDiagnostic, undefined)
  } finally {
    results.openRun(undefined)
    globalThis.WebSocket = socket
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
})
