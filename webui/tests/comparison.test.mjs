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
        record = next(item for item in client.get('/api/modules').json() if item['id'] == 'workbench.structure_comparison')
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

test('reference action uploads the single original mmCIF then adds the actual comparison node', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const calls = []
  const host = { readOnly: false,
    async createInput(input) { calls.push(input); return { id: 'reference-package' } },
    async addNode(node) { calls.push(node); return 'compare-node' },
  }
  try {
    await React.act(async () => root.render(React.createElement(extensions.actions[0].component, { host })))
    const input = container.querySelector('input[type=file]')
    const original = new Blob(['data_independent\n# actual structure bytes']); Object.defineProperty(original, 'name', { value: 'reference.cif' })
    Object.defineProperty(input, 'files', { value: [original] })
    await React.act(async () => input.dispatchEvent(new window.Event('change', { bubbles: true })))
    await React.act(async () => container.querySelector('button').click())
    assert.equal(calls[0].format, 'workbench.reference')
    assert.equal(calls[0].files['structure.cif'], original)
    const manifest = JSON.parse(await calls[0].files['manifest.json'].text())
    assert.equal(manifest.objects[0].structure.format, 'mmcif')
    assert.ok(manifest.objects[0].id)
    assert.equal(calls[1].type, 'workbench.compare')
    assert.deepEqual(calls[1].inputs, { reference: ['reference-package'] })
    assert.match(container.textContent, /subject/)
  } finally { await React.act(async () => root.unmount()); container.remove() }
})


test('comparison viewer reopens a real saved overlay and exposes all components with interactive rotation', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const reads = []
  const files = Object.fromEntries(await Promise.all(['manifest.json', 'overlay.json'].map(async key => [key, await readFile(new URL(`../../modules/structure_comparison/sample/${key}`, import.meta.url))])))
  const host = { readFile: async (id, key) => {
    assert.equal(id, 'saved-comparison'); reads.push(key)
    return new Blob([files[key]])
  } }
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'saved-comparison', entry: 'manifest.json' }, host })))
    assert.ok(reads.includes('overlay.json'))
    assert.equal(container.querySelectorAll('svg circle').length, 12)
    assert.match(container.textContent, /subject length: 5/)
    assert.match(container.textContent, /reference length: 5/)
    const initial = container.querySelector('circle').getAttribute('cx')
    const yaw = container.querySelector('[aria-label="Rotate around vertical axis"]')
    await React.act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(yaw, '90')
      yaw.dispatchEvent(new window.Event('input', { bubbles: true }))
    })
    assert.notEqual(container.querySelector('circle').getAttribute('cx'), initial)
    await React.act(async () => container.querySelector('circle[data-residue="HOH"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true })))
    assert.match(container.querySelector('[aria-label="Selected atom"]').textContent, /HOH/)
    const subject = container.querySelector('[aria-label="Show subject"]')
    await React.act(async () => subject.click())
    assert.equal(container.querySelectorAll('svg circle').length, 6)
  } finally { await React.act(async () => root.unmount()); container.remove() }
})


test('rotation keeps every atom inside the selectable overlay viewport', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const manifest = await readFile(new URL('../../modules/structure_comparison/sample/manifest.json', import.meta.url))
  const atoms = [{ position: [0.5, 0.5, -0.5], component: 'other', residue_name: 'ZN' }, { position: [-0.5, -0.5, 0.5], component: 'other', residue_name: 'HOH' }]
  const host = { readFile: async (_id, key) => new Blob([key === 'manifest.json' ? manifest : JSON.stringify({ subject: atoms, reference: atoms })]) }
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'diagonal-overlay', entry: 'manifest.json' }, host })))
    for (const label of ['Rotate around vertical axis', 'Tilt around horizontal axis']) {
      const input = container.querySelector(`[aria-label="${label}"]`)
      await React.act(async () => {
        Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, '45')
        input.dispatchEvent(new window.Event('input', { bubbles: true }))
      })
    }
    assert.equal(container.querySelectorAll('circle').length, 4)
    for (const atom of container.querySelectorAll('circle')) {
      assert.ok(Number(atom.getAttribute('cy')) >= 5 && Number(atom.getAttribute('cy')) <= 435)
      assert.ok(Number(atom.getAttribute('cx')) >= 5 && Number(atom.getAttribute('cx')) <= 595)
    }
  } finally { await React.act(async () => root.unmount()); container.remove() }
})


test('comparison editor selects a chain and discontinuous author positions without JSON or internal IDs', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const changes = []
  let parameters = {}
  const Editor = extensions.editors?.find(editor => editor.node === 'workbench.compare')?.component
  assert.ok(Editor, 'the actual comparison node has its own selection editor')
  function render() { root.render(React.createElement(Editor, { parameters, readOnly: false, onChange(next) { parameters = next; changes.push(next); render() } })) }
  async function edit(label, value) {
    const element = container.querySelector(`[aria-label="${label}"]`)
    await React.act(async () => {
      const prototype = element.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value)
      element.dispatchEvent(new window.Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
    })
  }
  try {
    await React.act(async () => render())
    await edit('Subject scope', 'positions')
    await edit('Subject chain', 'X')
    await edit('Subject residues', '12A, 16, 20')
    await React.act(async () => container.querySelector('[aria-label="Apply Subject region"]').click())
    assert.deepEqual(parameters.subject_selection, { positions: [
      { chain: 'X', author_number: 12, insertion_code: 'A' },
      { chain: 'X', author_number: 16, insertion_code: '' },
      { chain: 'X', author_number: 20, insertion_code: '' },
    ] })
    await edit('Reference scope', 'chain')
    await edit('Reference chain', 'R')
    await React.act(async () => container.querySelector('[aria-label="Apply Reference region"]').click())
    assert.deepEqual(parameters.reference_selection, { chains: ['R'] })
    assert.ok(!container.querySelector('textarea'))
    assert.match(container.textContent, /complete original structures/)
    await edit('Subject residues', '12A, missing, 20')
    const count = changes.length
    await React.act(async () => container.querySelector('[aria-label="Apply Subject region"]').click())
    assert.equal(changes.length, count)
    assert.match(container.querySelector('[role=alert]').textContent, /actual residue/)
  } finally { await React.act(async () => root.unmount()); container.remove() }
})
