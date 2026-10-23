import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'
import * as React from 'react'

const source = await readFile(new URL('../../modules/sequence_io/ui.js', import.meta.url), 'utf8')
const { register, parseSequence, runtime } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const { createRoot } = await import('react-dom/client')
const extensions = register({ React })
after(() => dom.window.close())

test('sequence input accepts a single sequence or FASTA and rejects unsupported input', () => {
  assert.deepEqual(runtime, { react: 19 })
  assert.deepEqual(parseSequence(' aCd\neF '), { sequence: 'ACDEF' })
  assert.deepEqual(parseSequence('>protein one\nACD\nEF'), { sequence: 'ACDEF', label: 'protein one' })
  assert.throws(() => parseSequence('>one\nACD\n>two\nEFG'), /batch import/)
  assert.throws(() => parseSequence('ACD*'), /standard amino acid/)
  assert.throws(() => parseSequence(''), /standard amino acid/)
})

test('public action imports sequences without selecting the next operation', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const calls = []
  const host = { readOnly: false,
    async createInput(input) { calls.push(['input', input]); return { id: 'sequence-package' } },
    async addNode() { assert.fail('Import must not choose the next operation') },
  }
  try {
    await React.act(async () => root.render(React.createElement(extensions.actions[0].component, { host })))
    const textarea = container.querySelector('textarea')
    await React.act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(textarea, '>protein\nACDEF')
      textarea.dispatchEvent(new window.Event('input', { bubbles: true }))
    })
    await React.act(async () => container.querySelector('button').click())
    assert.equal(calls.length, 1)
    assert.equal(calls[0][1].format, 'workbench.sequence')
    const manifest = JSON.parse(await calls[0][1].files['manifest.json'].text())
    assert.equal(manifest.objects[0].sequence, 'ACDEF')
    assert.equal(manifest.objects[0].label, 'protein')
    assert.ok(manifest.objects[0].id)
    assert.match(container.querySelector('[role=status]').textContent, /Imported sequences/)
    assert.deepEqual(extensions.viewers[0].formats, ['workbench.sequence'])
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

test('sequence file reading yields to later manual edits and keeps their source', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const inputs = []
  const host = { readOnly: false, async createInput(input) { inputs.push(input); return { id: 'edited' } }, async addNode() {} }
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  try {
    await React.act(async () => root.render(React.createElement(extensions.actions[0].component, { host })))
    const file = container.querySelector('input[type=file]')
    Object.defineProperty(file, 'files', { value: [{ name: 'old.fa', text: () => pending }] })
    await React.act(async () => file.dispatchEvent(new window.Event('change', { bubbles: true })))
    const textarea = container.querySelector('textarea')
    await React.act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(textarea, 'DEF')
      textarea.dispatchEvent(new window.Event('input', { bubbles: true }))
    })
    await React.act(async () => finish('>old\nACD'))
    await React.act(async () => container.querySelector('button').click())
    const actual = JSON.parse(await inputs[0].files['manifest.json'].text()).objects[0]
    assert.equal(actual.sequence, 'DEF')
    assert.equal(actual.source.text, 'DEF')
    assert.equal(actual.source.name, undefined)
  } finally { await React.act(async () => root.unmount()); container.remove() }
})

test('sequence file reads lose ownership when input mode or host changes', async t => {
  for (const change of ['batch', 'format', 'host']) await t.test(change, async () => {
    const container = document.createElement('div'); document.body.append(container)
    const root = createRoot(container)
    const host = { readOnly: false, async createInput() { throw new Error('No upload expected') }, async addNode() {} }
    let finish
    const pending = new Promise(resolve => { finish = resolve })
    try {
      await React.act(async () => root.render(React.createElement(React.StrictMode, null, React.createElement(extensions.actions[0].component, { host }))))
      const file = container.querySelector('input[type=file]')
      Object.defineProperty(file, 'files', { value: [{ name: 'old.fa', text: () => pending }] })
      await React.act(async () => file.dispatchEvent(new window.Event('change', { bubbles: true })))
      assert.equal(container.querySelector('button').disabled, true)
      assert.equal(container.querySelector('textarea').disabled, false)
      await React.act(async () => {
        if (change === 'batch') container.querySelector('[aria-label="Batch FASTA import"]').click()
        if (change === 'format') {
          const format = container.querySelector('select')
          format.value = 'json'; format.dispatchEvent(new window.Event('change', { bubbles: true }))
        }
        if (change === 'host') root.render(React.createElement(React.StrictMode, null, React.createElement(extensions.actions[0].component, { host: { ...host } })))
      })
      assert.equal(container.querySelector('button').disabled, false)
      await React.act(async () => finish('>old\nACD'))
      assert.equal(container.querySelector('textarea').value, '')
      assert.equal(container.querySelector('[role=alert]'), null)
    } finally { await React.act(async () => root.unmount()); container.remove() }
  })
})

test('latest sequence file owns pending status, errors and accepted source', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const inputs = []
  const host = { readOnly: false, async createInput(input) { inputs.push(input); return { id: 'file' } }, async addNode() {} }
  async function select(file) {
    const control = container.querySelector('input[type=file]')
    Object.defineProperty(control, 'files', { configurable: true, value: file ? [file] : [] })
    await React.act(async () => control.dispatchEvent(new window.Event('change', { bubbles: true })))
  }
  let rejectOld, finishNew, finishCancelled
  const old = new Promise((resolve, reject) => { rejectOld = reject })
  const newer = new Promise(resolve => { finishNew = resolve })
  const cancelled = new Promise(resolve => { finishCancelled = resolve })
  try {
    await React.act(async () => root.render(React.createElement(extensions.actions[0].component, { host })))
    await select({ name: 'old.fa', text: () => old })
    await select({ name: 'new.fa', text: () => newer })
    await React.act(async () => rejectOld(new Error('obsolete read failed')))
    assert.equal(container.querySelector('button').disabled, true)
    assert.equal(container.querySelector('[role=alert]'), null)
    await React.act(async () => finishNew('>new\nDEF'))
    assert.equal(container.querySelector('textarea').value, '>new\nDEF')
    assert.equal(container.querySelector('button').disabled, false)
    await select({ name: 'failed.fa', async text() { throw new Error('current read failed') } })
    assert.match(container.querySelector('[role=alert]').textContent, /current read failed/)
    assert.equal(container.querySelector('textarea').value, '>new\nDEF')
    await select({ name: 'cancelled.fa', text: () => cancelled })
    await select(null)
    assert.equal(container.querySelector('button').disabled, false)
    await React.act(async () => finishCancelled('>cancelled\nACD'))
    await React.act(async () => container.querySelector('button').click())
    const actual = JSON.parse(await inputs[0].files['manifest.json'].text()).objects[0]
    assert.equal(actual.sequence, 'DEF')
    assert.equal(actual.source.name, 'new.fa')
    assert.equal(actual.source.text, '>new\nDEF')
  } finally { await React.act(async () => root.unmount()); container.remove() }
})

test('sequence JSON import preserves label-only positions without assigning author numbers',async()=>{
 const {sequenceInput}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
 const object={id:'polymer',sequence:'AGC',positions:[
  {sequence_index:1,chain:'X',author_number:12,insertion_code:'',label_position:{chain:'A',position:1}},
  {sequence_index:2,label_position:{chain:'A',position:2}},
  {sequence_index:3},
 ]}
 const input=sequenceInput(JSON.stringify({objects:[object]}),{json:true})
 assert.deepEqual(JSON.parse(await input.files['manifest.json'].text()).objects,[object])
 assert.throws(()=>sequenceInput(JSON.stringify({objects:[{...object,positions:object.positions.map(row=>({...row,label_position:{chain:'A',position:1}}))}]}),{json:true}),/Repeated label/)
})
