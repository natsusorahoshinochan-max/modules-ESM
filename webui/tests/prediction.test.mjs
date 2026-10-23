import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import * as React from 'react'

const source = await readFile(new URL('../../modules/folding/ui.js', import.meta.url), 'utf8')
const { register } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const { createRoot } = await import('react-dom/client')
const extensions = register({ React })
after(() => dom.window.close())

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

test('prediction viewer adds an explicit selected-format export preserving the existing result package', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container), calls = []
  const pkg = { id: 'existing-prediction', entry: 'manifest.json', files: ['manifest.json', 'structure.pdb'] }
  const host = { readOnly: false, async readFile(id,key) { return new Blob([key === 'manifest.json' ? JSON.stringify({objects:[{id:'actual-object',structure:{file:'structure.pdb',format:'pdb'}}],tool:{id:'actual-tool',parameters:{seed:0}}}) : 'actual structure']) }, async addNode(node) { calls.push(node) } }
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: pkg, host })))
    await React.act(async () => { await new Promise(resolve => setTimeout(resolve,20)) })
    const button = [...container.querySelectorAll('button')].find(b => b.textContent.includes('export node'))
    assert.ok(button, 'prediction result offers selected-format export')
    await React.act(async () => button.click())
    assert.deepEqual(calls[0], {type:'workbench.export_structure',inputs:{structures:['existing-prediction']},parameters:{object:'actual-object',format:'mmcif'}})
  } finally { await React.act(async () => root.unmount()); container.remove() }
})

test('prediction result import accepts its explicit source label correspondence',async()=>{
 const {predictionInput}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
 const input={id:'source',sequence:'AGC',positions:[{sequence_index:1,chain:'X',author_number:12,insertion_code:''},{sequence_index:2,label_position:{chain:'A',position:2}},{sequence_index:3}]}
 const manifest={objects:[{id:'prediction',sequence:'AGC',input,structure:{file:'model.cif',format:'mmcif'}}],tool:{id:'actual.predictor',parameters:{}}}
 const received=await predictionInput(JSON.stringify(manifest),{'model.cif':new Blob(['data_structure\n'])})
 assert.deepEqual(JSON.parse(await received.files['manifest.json'].text()),manifest)
})
