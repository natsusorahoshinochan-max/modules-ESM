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

test('explicit batch FASTA import creates ordered sequence objects without concatenation', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const inputs = []
  const host = { readOnly: false, async createInput(input) { inputs.push(input); return { id: 'batch' } }, async addNode() {} }
  try {
    await React.act(async () => root.render(React.createElement(extensions.actions[0].component, { host })))
    const batch = container.querySelector('[aria-label="Batch FASTA import"]')
    assert.ok(batch)
    await React.act(async () => batch.click())
    const textarea = container.querySelector('textarea')
    await React.act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(textarea, '>first\nACD\n>second\nEFG')
      textarea.dispatchEvent(new window.Event('input', { bubbles: true }))
    })
    await React.act(async () => container.querySelector('button').click())
    assert.equal(inputs.length, 1)
    const document = JSON.parse(await inputs[0].files['manifest.json'].text())
    assert.deepEqual(document.objects.map(({ sequence, label }) => ({ sequence, label })), [{ sequence: 'ACD', label: 'first' }, { sequence: 'EFG', label: 'second' }])
    assert.notEqual(document.objects[0].id, document.objects[1].id)
  } finally { await React.act(async () => root.unmount()); container.remove() }
})

test('sequence imports preserve explicit correspondence and FASTA source without guessing a chain', async () => {
  const { sequenceInput } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
  assert.equal(typeof sequenceInput, 'function')
  const input = sequenceInput('>chain Q residue 77\r\nACD\r\n', { name: 'research.fa' })
  const value = JSON.parse(await input.files['manifest.json'].text()).objects[0]
  assert.deepEqual(value.positions, [{ sequence_index: 1 }, { sequence_index: 2 }, { sequence_index: 3 }])
  assert.deepEqual(value.source, { name: 'research.fa', record: 'chain Q residue 77', text: '>chain Q residue 77\r\nACD\r\n' })
  const mapped = { id: 'original', sequence: 'ACD', source: { name: 'selection.json' }, positions: [
    { sequence_index: 1, chain: 'Q', author_number: 12, insertion_code: '' },
    { sequence_index: 2, chain: 'Q', author_number: 12, insertion_code: 'B' },
    { sequence_index: 3, chain: 'Q', author_number: 22, insertion_code: '' },
  ] }
  const structured = sequenceInput(JSON.stringify({ objects: [mapped] }), { json: true })
  assert.deepEqual(JSON.parse(await structured.files['manifest.json'].text()), { objects: [mapped] })
  assert.throws(() => sequenceInput(JSON.stringify({ objects: [{ ...mapped, positions: mapped.positions.slice(1) }] }), { json: true }), /every sequence residue/)
})

test('related result action requires each explicit file binding and preserves values and original bytes', async () => {
  const action = extensions.actions.find(action => action.id === 'workbench.prediction.import')
  assert.ok(action, 'Related prediction result import action')
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const inputs = []
  const manifest = JSON.stringify({ objects: [{ id: 'existing', sequence: 'ACD', structure: { file: 'nested/model.cif', format: 'mmcif' }, confidence: { plddt: { file: 'values.json', scale: '0-1' }, ptm: 0.74 } }], tool: { id: 'actual.tool', parameters: { seed: 42 } } }, null, 2)
  const original = new Blob(['data_original\n# original structure bytes'])
  const confidence = new Blob(['{"plddt":[0.25,0.75,1.0]}'])
  const host = { readOnly: false, async createInput(input) { inputs.push(input); return { id: 'imported' } } }
  async function select(label, file) {
    const input = container.querySelector(`[aria-label="${label}"]`)
    assert.ok(input, label)
    Object.defineProperty(input, 'files', { configurable: true, value: [file] })
    await React.act(async () => input.dispatchEvent(new window.Event('change', { bubbles: true })))
  }
  try {
    await React.act(async () => root.render(React.createElement(action.component, { host })))
    await select('Prediction result manifest', new Blob([manifest]))
    await React.act(async () => container.querySelector('button').click())
    assert.equal(inputs.length, 0)
    assert.match(container.querySelector('[role=alert]').textContent, /nested\/model.cif/)
    await select('File for nested/model.cif', original)
    await select('File for values.json', confidence)
    await React.act(async () => container.querySelector('button').click())
    assert.equal(inputs.length, 1)
    assert.equal(await inputs[0].files['manifest.json'].text(), manifest)
    assert.equal(inputs[0].files['nested/model.cif'], original)
    assert.equal(inputs[0].files['values.json'], confidence)
    assert.match(container.querySelector('[role=status]').textContent, /Imported/)
  } finally { await React.act(async () => root.unmount()); container.remove() }
})

test('public result action bytes survive HTTP receipt, reopen, independent calculation and ZIP export', async () => {
  const { execFileSync } = await import('node:child_process')
  const action = extensions.actions.find(action => action.id === 'workbench.prediction.import')
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const mapped = { id: 'source-sequence', sequence: 'AAAAA', source: { name: 'real research input' }, positions: [12, 12, 14, 16, 20].map((number, index) => ({ sequence_index: index + 1, chain: 'X', author_number: number, insertion_code: index === 1 ? 'A' : '' })) }
  const manifest = JSON.stringify({ objects: [{ id: 'existing-prediction', input: mapped, sequence: 'AAAAA', structure: { file: 'nested/model.pdb', format: 'pdb' }, confidence: { plddt: { file: 'values.json', scale: '0-1' }, ptm: 0.74 } }], tool: { id: 'external.actual-tool', parameters: { seed: 42, temperature: 0.5 } } }, null, 2)
  const original = new Blob([await readFile(new URL('../../modules/structure_comparison/sample/subject.pdb', import.meta.url))])
  const confidence = new Blob(['{"plddt":[0.25,0.75,1.0,0.5,0.625]}'])
  let observed
  const host = { readOnly: false, async createInput(input) {
    const files = Object.fromEntries(await Promise.all(Object.entries(input.files).map(async ([key, blob]) => [key, Buffer.from(await blob.arrayBuffer()).toString('base64')])))
    observed = JSON.parse(execFileSync(process.env.WORKBENCH_PYTHON || 'python3', ['-m', 'tests.sequence_io_http'], { cwd: new URL('../../', import.meta.url), input: JSON.stringify({ ...input, files }), encoding: 'utf8' }))
    return observed.package
  } }
  async function select(label, blob) {
    const input = container.querySelector(`[aria-label="${label}"]`)
    Object.defineProperty(input, 'files', { value: [blob] })
    await React.act(async () => input.dispatchEvent(new window.Event('change', { bubbles: true })))
  }
  try {
    await React.act(async () => root.render(React.createElement(action.component, { host })))
    await select('Prediction result manifest', new Blob([manifest]))
    await select('File for nested/model.pdb', original)
    await select('File for values.json', confidence)
    await React.act(async () => container.querySelector('button').click())
    assert.ok(observed, container.textContent)
    assert.equal(observed.index.format, 'workbench.prediction')
    assert.equal(Buffer.from(observed.files['manifest.json'], 'base64').toString(), manifest)
    assert.equal(Buffer.from(observed.files['nested/model.pdb'], 'base64').toString(), await original.text())
    assert.equal(Buffer.from(observed.files['values.json'], 'base64').toString(), await confidence.text())
    assert.deepEqual(observed.comparison.subject.generation.input, mapped)
    assert.deepEqual(observed.converted.generation.input, mapped)
    assert.deepEqual(observed.comparison.subject.generation.tool, { id: 'external.actual-tool', parameters: { seed: 42, temperature: 0.5 } })
    assert.deepEqual(observed.comparison.alignment.subject_positions[1], { chain: 'X', author_number: 12, insertion_code: 'A' })
    assert.ok(Math.abs(observed.comparison.metrics.tm_subject.value - 1) < 1e-6)
  } finally { await React.act(async () => root.unmount()); container.remove() }
})

test('result import rejects missing required metadata and incomplete confidence without repairing values', async () => {
  const { predictionInput } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
  const document = { objects: [{ id: 'actual', sequence: 'ACD', structure: { file: 'model', format: 'pdb' }, confidence: { plddt: { file: 'confidence', scale: '0-1' } } }], tool: { id: 'actual.tool', parameters: {} } }
  const files = { model: new Blob(['PDB bytes']), confidence: new Blob(['{"plddt":[0.5,0.75]}']) }
  await assert.rejects(predictionInput(JSON.stringify(document), files), /one finite 0-1 value per sequence residue/)
  await assert.rejects(predictionInput(JSON.stringify({ ...document, tool: { id: 'unknown-parameters' } }), files), /existing parameters/)
  await assert.rejects(predictionInput(JSON.stringify({ ...document, objects: [{ ...document.objects[0], input: null }] }), files), /sequence object/)
})

test('prediction import rejects a contradictory supplied input sequence instead of relabeling it', async () => {
  const { predictionInput } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
  const manifest = { objects: [{ id: 'prediction', sequence: 'ACD', input: { id: 'input', sequence: 'AAA' }, structure: { file: 'model', format: 'pdb' } }], tool: { id: 'tool', parameters: {} } }
  await assert.rejects(predictionInput(JSON.stringify(manifest), { model: new Blob(['structure']) }), /input sequence.*prediction sequence/)
})
