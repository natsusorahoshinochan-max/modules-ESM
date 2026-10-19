import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import * as React from 'react'

const source = await readFile(new URL('../../modules/folding/ui.js', import.meta.url), 'utf8')
const { register, parseSequence, runtime } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const { createRoot } = await import('react-dom/client')
const extensions = register({ React })
after(() => dom.window.close())

test('prediction input accepts a single sequence or FASTA and rejects unsupported input', () => {
  assert.deepEqual(runtime, { react: 19 })
  assert.deepEqual(parseSequence(' aCd\neF '), { sequence: 'ACDEF' })
  assert.deepEqual(parseSequence('>protein one\nACD\nEF'), { sequence: 'ACDEF', label: 'protein one' })
  assert.throws(() => parseSequence('>one\nACD\n>two\nEFG'), /batch import/)
  assert.throws(() => parseSequence('ACD*'), /standard amino acid/)
  assert.throws(() => parseSequence(''), /standard amino acid/)
})

test('public action uploads sequence bytes then creates a prediction node', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const calls = []
  const host = { readOnly: false,
    async createInput(input) { calls.push(['input', input]); return { id: 'sequence-package' } },
    async addNode(node) { calls.push(['node', node]); return 'prediction-node' },
  }
  try {
    await React.act(async () => root.render(React.createElement(extensions.actions[0].component, { host })))
    const textarea = container.querySelector('textarea')
    await React.act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(textarea, '>protein\nACDEF')
      textarea.dispatchEvent(new window.Event('input', { bubbles: true }))
    })
    await React.act(async () => container.querySelector('button').click())
    assert.equal(calls.length, 2)
    assert.equal(calls[0][1].format, 'workbench.sequence')
    const manifest = JSON.parse(await calls[0][1].files['manifest.json'].text())
    assert.equal(manifest.objects[0].sequence, 'ACDEF')
    assert.equal(manifest.objects[0].label, 'protein')
    assert.ok(manifest.objects[0].id)
    assert.deepEqual(calls[1][1], { type: 'workbench.predict', parameters: {}, inputs: { sequence: ['sequence-package'] }, tools: {}, tool_parameters: {} })
  } finally { await React.act(async () => root.unmount()); container.remove() }
})

test('public viewer reads actual structure and confidence from declared package files', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const files = {
    'manifest.json': JSON.stringify({ objects: [{ id: 'one', sequence: 'ACD', structure: { file: 'model.pdb', format: 'pdb' }, confidence: { plddt: { file: 'confidence.json', scale: '0-1' }, ptm: 0.8 } }] }),
    'model.pdb': 'ATOM actual structure bytes',
    'confidence.json': '{"plddt":[0.8,0.9,0.7]}',
  }
  const reads = []
  const host = { readFile: async (id, key) => { assert.equal(id, 'result'); reads.push(key); return new Blob([files[key]]) } }
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'result', entry: 'manifest.json', files: Object.keys(files) }, host })))
    assert.equal(container.querySelector('[aria-label="Package file contents"]').textContent, files['model.pdb'])
    assert.match(container.textContent, /0.9/)
    assert.ok(reads.includes('confidence.json'))
  } finally { await React.act(async () => root.unmount()); container.remove() }
})
