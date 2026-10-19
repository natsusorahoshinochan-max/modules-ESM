import assert from 'node:assert/strict'
import { after, afterEach, beforeEach, test } from 'node:test'
import { mkdtemp, rm } from 'node:fs/promises'
import { registerHooks } from 'node:module'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { build } from 'esbuild'
import { JSDOM } from 'jsdom'
import { act, createElement } from 'react'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
window.confirm = () => true
const { createRoot } = await import('react-dom/client')
const directory = await mkdtemp(join(process.cwd(), '.app-tests-'))
const output = join(directory, 'App.mjs')
await build({ entryPoints: ['src/App.tsx'], bundle: true, packages: 'external', platform: 'node', format: 'esm', jsx: 'automatic', outfile: output })
const { default: App } = await import(pathToFileURL(output).href)
const hooks = registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === '/api/modules/test.actions/ui.js') return { url: new URL('./module-actions.mjs', import.meta.url).href, shortCircuit: true }
    return nextResolve(specifier, context)
  },
})
const originalFetch = globalThis.fetch
let root, container, records, pendingSave, packages, uploadGate, savedFlows, runRequests, projectGate, runGate
const clone = value => structuredClone(value)
const node = (id, type = 'test.one') => ({ id, type, parameters: {}, inputs: {} })
function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
const declaration = (id, cardinality = 'one') => ({ id, module_id: 'test.actions', name: id, inputs: { input: { accepts: ['test.format'], cardinality: 'one', required: false } }, outputs: { output: { format: 'test.format', cardinality } }, parameters: {} })

beforeEach(async () => {
  records = [
    { id: 'a', name: 'Project A', flow: { nodes: [], edges: [] }, layout: {} },
    { id: 'b', name: 'Project B', flow: { nodes: [], edges: [] }, layout: {} },
  ]
  pendingSave = null; uploadGate = null; savedFlows = []; runRequests = []; projectGate = null; runGate = null
  packages = { a: [], b: [{ id: 'b-package', project_id: 'b', format: 'other', entry: 'data', files: ['data'] }] }
  globalThis.fetch = async (url, options = {}) => {
    const path = String(url)
    let result
    if (path === '/api/catalog') result = { nodes: [declaration('test.one'), declaration('test.many', 'many')], modules: [{ id: 'test.actions', name: 'Test module', entry_point: 'test:module', enabled: true, settings: {}, settings_schema: {}, ui: 'fixture.js' }] }
    else if (path === '/api/projects') result = records
    else {
      const [, id, suffix = ''] = path.match(/^\/api\/projects\/([^/]+)(.*)$/) ?? []
      const record = records.find(item => item.id === id)
      assert.ok(record, `Unexpected request ${path}`)
      if (!suffix && options.method === 'PUT') {
        result = { ...record, ...JSON.parse(options.body) }
        savedFlows.push(clone(result))
        if (pendingSave) await pendingSave.promise
        records = records.map(item => item.id === id ? clone(result) : item)
      } else if (!suffix) { if (id === 'b' && projectGate) await projectGate.promise; result = record }
      else if (suffix === '/packages') result = packages[id]
      else if (suffix === '/runs') {
        if (options.method === 'POST') { runRequests.push(id); if (runGate) await runGate.promise; result = { id: 'run', status: 'succeeded', nodes: {}, diagnostics: [] } }
        else result = []
      }
      else if (suffix === '/uploads') result = { upload_id: 'upload' }
      else if (suffix.startsWith('/uploads/upload/files')) { if (uploadGate) await uploadGate.promise; result = { key: 'data' } }
      else if (suffix === '/uploads/upload/commit') {
        result = { id: 'a-input', project_id: id, format: 'test.format', entry: 'data', files: ['data'] }
        packages[id].push(result)
      } else assert.fail(`Unexpected request ${path}`)
    }
    return Response.json(clone(result))
  }
  container = document.createElement('div'); document.body.append(container)
  root = createRoot(container)
  await act(async () => root.render(createElement(App)))
  await click('Project A')
})
afterEach(async () => { await act(async () => root.unmount()); container.remove(); globalThis.fetch = originalFetch })
after(async () => { hooks.deregister(); dom.window.close(); await rm(directory, { recursive: true, force: true }) })
function button(text) {
  const element = [...container.querySelectorAll('button')].find(item => item.textContent === text)
  assert.ok(element, `Missing button ${text}`)
  return element
}
async function click(text) { await act(async () => button(text).click()) }
async function addNode(type = 'test.one') {
  const select = container.querySelector('label > select')
  assert.ok(select)
  await act(async () => { select.value = type; select.dispatchEvent(new window.Event('change', { bubbles: true })) })
}
const title = () => container.querySelector('.toolbar h2').textContent
const nodeCount = () => container.querySelectorAll('.canvas article').length

test('a delayed save preserves edits made after its submitted snapshot', async () => {
  await addNode()
  pendingSave = deferred()
  await click('Save project')
  await addNode()
  await act(async () => pendingSave.resolve())
  assert.equal(nodeCount(), 2)
  assert.equal(title(), 'Project A · unsaved')
  assert.equal(savedFlows[0].flow.nodes.length, 1)
})

test('a delayed save cannot replace a project opened while it was pending', async () => {
  await addNode()
  pendingSave = deferred()
  await click('Save project')
  await click('Project B')
  await act(async () => pendingSave.resolve())
  assert.equal(title(), 'Project B')
  assert.equal(nodeCount(), 0)
  assert.equal(container.querySelector('[role=status]'), null)
})

test('an author action can await two node additions then connect their declared ports', async () => {
  await click('Add connected pair')
  assert.equal(container.querySelector('[data-testid=action-result]').textContent, 'Completed')
  assert.equal(nodeCount(), 2)
  await click('Save project')
  const flow = savedFlows[0].flow
  assert.deepEqual(flow.edges, [{ source: flow.nodes[0].id, source_port: 'output', target: flow.nodes[1].id, target_port: 'input' }])
})

test('an upload started in one project cannot update another project or add its node there', async () => {
  uploadGate = deferred()
  await click('Upload and add node')
  await click('Project B')
  await act(async () => uploadGate.resolve())
  assert.equal(title(), 'Project B')
  assert.equal(nodeCount(), 0)
  const options = [...container.querySelector('[aria-label="Data package"]').options].map(option => option.value)
  assert.deepEqual(options, ['', 'b-package'])
  assert.match(container.querySelector('[data-testid=action-result]').textContent, /project changed/i)
  await click('Project A')
  assert.equal(nodeCount(), 0)
})


test('a many output cannot be connected to a one input of the same format', async () => {
  await addNode('test.many')
  await addNode()
  async function select(label, value) {
    const element = container.querySelector(`[aria-label="${label}"]`)
    await act(async () => { element.value = value; element.dispatchEvent(new window.Event('change', { bubbles: true })) })
  }
  const nodes = [...container.querySelectorAll('.canvas article small')].map(element => element.textContent.split(' · ')[1])
  await select('Source node', nodes[0]); await select('Source port', 'output')
  await select('Target node', nodes[1]); await select('Target port', 'input')
  await click('Connect')
  assert.match(container.querySelector('[role=alert]')?.textContent ?? '', /cardinality/i)
  await click('Save project')
  assert.deepEqual(savedFlows[0].flow.edges, [])
})


test('an old author action cannot add a node after leaving and reopening its project', async () => {
  await click('Prepare delayed node')
  await click('Project B')
  await click('Project A')
  await click('Finish delayed node')
  assert.equal(title(), 'Project A')
  assert.equal(nodeCount(), 0)
  assert.match(container.querySelector('[data-testid=action-result]').textContent, /project changed/i)
})

test('an upload cannot resume authoring after leaving and reopening its project', async () => {
  uploadGate = deferred()
  await click('Upload and add node')
  await click('Project B')
  await click('Project A')
  await act(async () => uploadGate.resolve())
  assert.equal(title(), 'Project A')
  assert.equal(nodeCount(), 0)
  assert.deepEqual([...container.querySelector('[aria-label="Data package"]').options].map(option => option.value), [''])
  assert.match(container.querySelector('[data-testid=action-result]').textContent, /project changed/i)
})

test('save and run stops when editing supersedes the saved snapshot', async () => {
  await addNode()
  pendingSave = deferred()
  await click('Save and run')
  await addNode()
  await act(async () => pendingSave.resolve())
  assert.equal(nodeCount(), 2)
  assert.equal(title(), 'Project A · unsaved')
  assert.deepEqual(runRequests, [])
  assert.match(container.querySelector('[role=alert]').textContent, /changed while saving/i)
})

test('save and run stops when the user opens another project before save completes', async () => {
  await addNode()
  pendingSave = deferred()
  await click('Save and run')
  await click('Project B')
  await act(async () => pendingSave.resolve())
  assert.equal(title(), 'Project B')
  assert.deepEqual(runRequests, [])
  assert.deepEqual([...container.querySelector('[aria-label="Data package"]').options].map(option => option.value), ['', 'b-package'])
})


test('starting a run keeps a pending project-open response from replacing the running project', async () => {
  projectGate = deferred(); runGate = deferred()
  await click('Project B')
  await click('Run')
  await act(async () => projectGate.resolve())
  assert.equal(title(), 'Project A')
  await act(async () => runGate.resolve())
  assert.deepEqual(runRequests, ['a'])
  assert.equal(title(), 'Project A')
})

test('a pending save prevents overlapping saves while later edits remain possible', async () => {
  await addNode()
  pendingSave = deferred()
  await click('Save project')
  await addNode()
  assert.equal(button('Save project').disabled, true)
  assert.equal(button('Save and run').disabled, true)
  await click('Save project')
  assert.equal(savedFlows.length, 1)
  await act(async () => pendingSave.resolve())
  assert.equal(button('Save project').disabled, false)
  await click('Save project')
  assert.equal(savedFlows[1].flow.nodes.length, 2)
  assert.equal(title(), 'Project A')
})

test('canvas edits preserve other flow and layout fields in the saved project', async () => {
  records[0].flow = { nodes: [node('positioned')], edges: [], annotation: { title: 'Keep this note' } }
  records[0].layout = { positioned: { x: 20, y: 57, color: 'blue' } }
  await click('Project A')
  const position = container.querySelector('input[type=range]')
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(position, '120')
    position.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
  await click('Remove node')
  await click('Save project')
  assert.deepEqual(savedFlows[0].flow, { nodes: [], edges: [], annotation: { title: 'Keep this note' } })
  assert.deepEqual(savedFlows[0].layout.positioned, { x: 120, y: 57, color: 'blue' })
})
