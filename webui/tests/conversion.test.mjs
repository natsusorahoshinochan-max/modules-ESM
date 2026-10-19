import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { execFileSync } from 'node:child_process'
import { JSDOM } from 'jsdom'
import * as React from 'react'

// Exercise the same served public ES module the browser loads.
const source = execFileSync(process.env.WORKBENCH_PYTHON || 'python3', ['-c', `
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
with tempfile.TemporaryDirectory() as directory:
    with TestClient(create_application(data_root=Path(directory))) as client:
        record = next(item for item in client.get('/api/modules').json() if item['id'] == 'workbench.structure_conversion')
        response = client.get(record['ui_url'])
        response.raise_for_status()
        print(response.text, end='')
`], { cwd: new URL('../../', import.meta.url), encoding: 'utf8' })
const { register } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const { createRoot } = await import('react-dom/client')
const extensions = register({ React })
after(() => dom.window.close())

test('explicit conversion action uploads reference and inserts converter and C-only consumer', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const calls = []
  const host = { readOnly: false,
    async createInput(input) { calls.push(input); return { id: 'reference-package' } },
    async addNode(node) { calls.push(node); return calls.length === 2 ? 'converter' : 'comparison' },
    async connect(edge) { calls.push(edge) },
  }
  try {
    await React.act(async () => root.render(React.createElement(extensions.actions[0].component, { host })))
    const input = container.querySelector('input[type=file]')
    const original = new Blob(['original reference']); Object.defineProperty(original, 'name', { value: 'reference.pdb' })
    Object.defineProperty(input, 'files', { value: [original] })
    await React.act(async () => input.dispatchEvent(new window.Event('change', { bubbles: true })))
    await React.act(async () => container.querySelector('button').click())
    assert.equal(calls[0].format, 'workbench.reference')
    assert.equal(calls[0].files['structure.pdb'], original)
    assert.equal(calls[1].type, 'workbench.prediction_to_structure')
    assert.equal(calls[2].type, 'workbench.compare_structure')
    assert.deepEqual(calls[2].inputs, { reference: ['reference-package'] })
    assert.deepEqual(calls[3], { source: 'converter', source_port: 'structure', target: 'comparison', target_port: 'subject' })
    assert.match(container.textContent, /Connect a prediction/)
  } finally { await React.act(async () => root.unmount()); container.remove() }
})
