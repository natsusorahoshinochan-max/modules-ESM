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
    if (specifier === '/api/modules/test.broken/ui.js') return { url: new URL('./module-broken-viewer.mjs', import.meta.url).href, shortCircuit: true }
    if (specifier === '/api/modules/test.viewers/ui.js') return { url: new URL('./module-viewers.mjs', import.meta.url).href, shortCircuit: true }
    if (specifier === '/api/modules/test.actions/ui.js') return { url: new URL('./module-actions.mjs', import.meta.url).href, shortCircuit: true }
    return nextResolve(specifier, context)
  },
})
const originalFetch = globalThis.fetch
let root, container, records, pendingSave, packages, uploadGate, savedFlows, runRequests, projectGate, runGate, adoptionGate, deleteGate, adoptionFailure, discardedDraftInputs
const clone = value => structuredClone(value)
const node = (id, type = 'test.one') => ({ id, type, parameters: {}, inputs: {} })
function deferred() {
  let resolve, reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const declaration = (id, cardinality = 'one') => ({ id, module_id: 'test.actions', name: id, inputs: { input: { accepts: ['test.format'], cardinality: 'one', required: false } }, outputs: { output: { format: 'test.format', cardinality } }, parameters: {} })

beforeEach(async () => {
  records = [
    { id: 'a', name: 'Project A', flow: { nodes: [], edges: [] }, layout: {} },
    { id: 'b', name: 'Project B', flow: { nodes: [], edges: [] }, layout: {} },
  ]
  window.confirm = () => true
  discardedDraftInputs = [];
  adoptionGate = null; deleteGate = null; adoptionFailure = null
  pendingSave = null; uploadGate = null; savedFlows = []; runRequests = []; projectGate = null; runGate = null
  packages = { tutorial: [], a: [], b: [{ id: 'b-package', project_id: 'b', format: 'other', entry: 'data', files: ['data'] }] }
  globalThis.fetch = async (url, options = {}) => {
    const path = String(url)
    let result
    if (path.startsWith('/api/draft-inputs/')) { discardedDraftInputs.push(path.split('/').at(-1)); result = {} }
    else if (path === '/api/catalog') result = { nodes: [declaration('test.one'), declaration('test.many', 'many')], modules: [{ id: 'test.actions', name: 'Test module', entry_point: 'test:module', enabled: true, settings: {}, settings_schema: {}, ui: 'fixture.js' }] }
    else if (path === '/api/tutorial') result = { id: 'tutorial', tutorial: true, name: 'Teaching example', flow: { nodes: [node('teaching')], edges: [] }, layout: {} }
    else if (path === '/api/projects' && options.method === 'POST') { result = { id: 'new', name: JSON.parse(options.body).name, flow: { nodes: [], edges: [] }, layout: {} }; records.push(result); packages.new = [] }
    else if (path === '/api/projects') result = records
    else {
      const [, id, suffix = ''] = path.match(/^\/api\/projects\/([^/]+)(.*)$/) ?? []
      const record = id === 'tutorial' ? { id: 'tutorial', tutorial: true, name: 'Teaching example', flow: { nodes: [node('teaching')], edges: [] }, layout: {} } : records.find(item => item.id === id)
      assert.ok(record, `Unexpected request ${path}`)
      if (suffix === '/copies') {
        if (pendingSave) await pendingSave.promise
        const body = JSON.parse(options.body)
        result = { id: 'copied', name: body.name, flow: body.flow ?? clone(record.flow), layout: body.layout ?? clone(record.layout) }
        records.push(clone(result)); packages.copied = []
      } else if (suffix === '/adoptions') {
        if (adoptionGate) await adoptionGate.promise
        if (adoptionFailure) return Response.json({ detail: adoptionFailure }, { status: 409 })
        const source = Object.values(packages).flat().find(item => item.id === JSON.parse(options.body).package_id)
        assert.ok(source)
        result = { ...source, id: 'adopted-package', project_id: id }; packages[id].push(result)
      } else if (!suffix && options.method === 'DELETE') {
        if (deleteGate) await deleteGate.promise
        records = records.filter(item => item.id !== id); delete packages[id]; result = { deleted: id }
      } else if (!suffix && options.method === 'PUT') {
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
        if (id !== 'tutorial') packages[id].push(result)
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


test('tool slots filter compatible implementations and save independent tool parameters', async () => {
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    if (String(url) === '/api/modules') return Response.json({})
    if (String(url) === '/api/catalog') return Response.json({
      modules: [],
      nodes: [{ ...declaration('test.one'), tools: { predictor: { id: 'test.predict', name: 'Structure predictor' } } }],
      tools: [
        { id: 'tool.local', name: 'Local predictor', module_id: 'test.tools', slot: 'test.predict', parameters: { seed: { default: 42 } }, capabilities: { protein_only: true } },
        { id: 'tool.remote', name: 'Remote predictor', module_id: 'test.tools', slot: 'test.predict', parameters: {}, capabilities: {} },
        { id: 'tool.other', name: 'Unrelated tool', module_id: 'test.tools', slot: 'test.other', parameters: {}, capabilities: {} },
      ],
    })
    return previousFetch(url, options)
  }
  await click('Register module')
  await addNode()
  const select = container.querySelector('.node fieldset select')
  assert.deepEqual([...select.options].map(option => option.value), ['', 'tool.local', 'tool.remote'])
  await act(async () => { select.value = 'tool.local'; select.dispatchEvent(new window.Event('change', { bubbles: true })) })
  assert.match(container.querySelector('.node fieldset').textContent, /protein_only/)
  assert.match(container.querySelector('.node fieldset').textContent, /42/)
  const parameters = container.querySelector('.node fieldset textarea')
  await act(async () => {
    parameters.value = '{"seed":7}'
    parameters.dispatchEvent(new window.FocusEvent('focusout', { bubbles: true }))
  })
  await click('Save project')
  assert.deepEqual(savedFlows[0].flow.nodes[0].tools, { predictor: 'tool.local' })
  assert.deepEqual(savedFlows[0].flow.nodes[0].tool_parameters, { predictor: { seed: 7 } })
  await act(async () => { select.value = 'tool.remote'; select.dispatchEvent(new window.Event('change', { bubbles: true })) })
  await click('Save project')
  assert.deepEqual(savedFlows[1].flow.nodes[0].tool_parameters, { predictor: {} })
})

async function choose(label, value) {
  const element = container.querySelector(`[aria-label="${label}"]`)
  assert.ok(element, `Missing selector ${label}`)
  await act(async () => { element.value = value; element.dispatchEvent(new window.Event('change', { bubbles: true })) })
}

test('a generic package can be adopted into a chosen project and downloaded as ZIP without a viewer', async () => {
  await click('Project B')
  await choose('Data package', 'b-package')
  assert.match(container.querySelector('.package').textContent, /Format: other · Entry: data/)
  assert.equal(container.querySelector('.package a[download]').getAttribute('href'), '/api/packages/b-package/export.zip')
  await choose('Adoption target', 'a')
  await click('Adopt package')
  await click('Project A')
  await choose('Data package', 'adopted-package')
  assert.match(container.querySelector('.package').textContent, /Format: other · Entry: data/)
  assert.equal(packages.a[0].project_id, 'a')
  assert.equal(packages.b[0].id, 'b-package')
})

test('deleting a dirty project requires explicit discard confirmation and clears its editor and packages', async () => {
  await addNode()
  const confirmations = []
  window.confirm = message => { confirmations.push(message); return false }
  await click('Delete project')
  assert.equal(title(), 'Project A · unsaved')
  assert.equal(nodeCount(), 1)
  assert.equal(records.length, 2)
  assert.match(confirmations[0], /delete.*Project A/i)
  assert.match(confirmations[0], /unsaved/i)
  window.confirm = () => true
  await click('Delete project')
  assert.equal(title(), 'Open or create a project')
  assert.equal(nodeCount(), 0)
  assert.equal(container.querySelector('[aria-label="Data package"]'), null)
  assert.deepEqual(records.map(item => item.id), ['b'])
  assert.equal([...container.querySelectorAll('button')].some(item => item.textContent === 'Project A'), false)
  await click('Project B')
  assert.equal(nodeCount(), 0)
})

test('a late adoption completion cannot replace the packages or notice of a newly opened project', async () => {
  await click('Project B')
  await choose('Data package', 'b-package')
  await choose('Adoption target', 'a')
  adoptionGate = deferred()
  await click('Adopt package')
  await click('Project A')
  await act(async () => adoptionGate.resolve())
  assert.equal(title(), 'Project A')
  assert.deepEqual([...container.querySelector('[aria-label="Data package"]').options].map(option => option.value), [''])
  assert.equal(container.querySelector('[role=status]'), null)
  await click('Project A')
  assert.deepEqual([...container.querySelector('[aria-label="Data package"]').options].map(option => option.value), ['', 'adopted-package'])
})

test('adoption errors are shown in their originating project and ignored after leaving and reopening it', async () => {
  await click('Project B')
  await choose('Data package', 'b-package')
  await choose('Adoption target', 'a')
  adoptionFailure = 'Target project is running'
  await click('Adopt package')
  assert.match(container.querySelector('[role=alert]').textContent, /Target project is running/)
  adoptionGate = deferred()
  await click('Adopt package')
  await click('Project A')
  await click('Project B')
  await act(async () => adoptionGate.resolve())
  assert.equal(container.querySelector('[role=alert]'), null)
  assert.deepEqual(packages.a, [])
})

test('a pending deletion locks its editor and cannot clear the next project when it completes', async () => {
  await addNode()
  deleteGate = deferred()
  await click('Delete project')
  assert.equal(button('Remove node').disabled, true)
  assert.equal(button('Save project').disabled, true)
  await click('Project B')
  await act(async () => deleteGate.resolve())
  assert.equal(title(), 'Project B')
  assert.equal(nodeCount(), 0)
  assert.deepEqual([...container.querySelector('[aria-label="Data package"]').options].map(option => option.value), ['', 'b-package'])
  assert.equal(container.querySelector('[role=status]'), null)
})

test('a failed deletion preserves the dirty editor and reports the reason', async () => {
  await addNode()
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => options?.method === 'DELETE'
    ? Response.json({ detail: 'Project is running' }, { status: 409 }) : previousFetch(url, options)
  await click('Delete project')
  assert.equal(title(), 'Project A · unsaved')
  assert.equal(nodeCount(), 1)
  assert.match(container.querySelector('[role=alert]').textContent, /Project is running/)
  assert.equal(button('Save project').disabled, false)
  assert.equal(records.length, 2)
})

test('backend running state keeps editing locked through polling and cancellation', async () => {
  let status = 'running'
  let cancellations = 0
  const history = () => [{ id: 'background', status, nodes: { node: { status: status === 'running' ? 'running' : 'cancelled', outputs: {}, diagnostics: [] } }, diagnostics: [] }]
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => {
    if (String(url) === '/api/projects/a/runs') return Response.json(options.method === 'POST' ? history()[0] : history())
    if (String(url) === '/api/runs/background/cancel') { cancellations++; status = 'cancelled'; return Response.json(history()[0]) }
    return previousFetch(url, options)
  }
  await click('Run')
  assert.equal(button('Save project').disabled, true)
  assert.equal(button('Run').disabled, true)
  await click('Cancel run')
  assert.equal(cancellations, 1)
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)) })
  assert.equal(button('Save project').disabled, false)
  assert.match(container.textContent, /cancelled/)
})

test('opening a project with an existing backend run restores the edit lock', async () => {
  let status = 'running'
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => String(url) === '/api/projects/a/runs'
    ? Response.json([{ id: 'existing', status, nodes: {}, diagnostics: [] }])
    : previousFetch(url, options)
  await click('Project A')
  assert.equal(button('Save project').disabled, true)
  assert.equal(button('Run').disabled, true)
  assert.ok(button('Cancel run'))
  status = 'succeeded'
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)) })
  assert.equal(button('Save project').disabled, false)
})

test('module deployment fields save credentials and locations independently of node parameters', async () => {
  let settings = {}, received
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    if (String(url) === '/api/modules') return Response.json({})
    if (String(url) === '/api/modules/environment/settings') {
      received = JSON.parse(options.body).settings; settings = received
      return Response.json({})
    }
    if (String(url) === '/api/catalog') return Response.json({ nodes: [declaration('test.one')], modules: [{ id: 'environment', name: 'Environment', entry_point: 'environment:module', enabled: true, ui: null, settings, settings_schema: {
      credential: { type: 'string', title: 'Service credential', secret: true },
      model: 'Existing model location', service: 'Service URL', program: 'Program location',
    } }] })
    return previousFetch(url, options)
  }
  await click('Register module')
  for (const [name, value] of Object.entries({ credential: 'chosen-token', model: '/model', service: 'http://localhost', program: '/program' })) {
    const input = container.querySelector(`[aria-label="Environment: ${name}"]`)
    assert.ok(input, `Missing deployment field ${name}`)
    if (name === 'credential') assert.equal(input.type, 'password')
    await act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, value)
      input.dispatchEvent(new window.Event('input', { bubbles: true }))
    })
  }
  await click('Save settings')
  assert.deepEqual(received, { credential: 'chosen-token', model: '/model', service: 'http://localhost', program: '/program' })
  await addNode()
  await click('Save project')
  assert.deepEqual(savedFlows[0].flow.nodes[0].parameters, {})
})

test('a chosen wheel is uploaded with its entry and module controls refresh the canvas without editing its draft', async () => {
  const previousFetch = globalThis.fetch
  let enabled = true, installed = true, uploaded, receivedEntry
  const module = { id: 'test.actions', name: 'Test module', entry_point: 'test:module', enabled: true, settings: {}, settings_schema: {}, ui: 'fixture.js' }
  globalThis.fetch = async (url, options) => {
    const path = String(url)
    if (path.startsWith('/api/module-packages?')) {
      uploaded = options.body; receivedEntry = new URL(path, 'http://localhost').searchParams.get('entry_point'); installed = true; enabled = true
      return Response.json(module)
    }
    if (path === '/api/modules/test.actions/enabled') { enabled = JSON.parse(options.body).enabled; return Response.json(module) }
    if (path === '/api/modules/test.actions' && options.method === 'DELETE') { installed = false; return Response.json({}) }
    if (path.startsWith('/api/draft-inputs/')) { discardedDraftInputs.push(path.split('/').at(-1)); result = {} }
    else if (path === '/api/catalog') return Response.json({ nodes: installed && enabled ? [declaration('test.one')] : [], modules: installed ? [{ ...module, enabled }] : [] })
    return previousFetch(url, options)
  }
  await addNode()
  await click('Disable')
  assert.match(container.querySelector('.canvas').textContent, /Missing module: test.one/)
  assert.match(container.querySelector('.canvas').textContent, /Cannot run/)
  assert.equal(nodeCount(), 1)
  await click('Enable')
  assert.doesNotMatch(container.querySelector('.canvas').textContent, /Missing module/)
  await click('Uninstall')
  assert.equal(nodeCount(), 1)
  const input = container.querySelector('input[type=file]')
  const file = new window.File(['selected wheel bytes'], 'external-0.1-py3-none-any.whl')
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await act(async () => input.dispatchEvent(new window.Event('change', { bubbles: true })))
  await click('Install package')
  assert.equal(uploaded, file)
  assert.equal(receivedEntry, 'workbench_notes:module')
  assert.doesNotMatch(container.querySelector('.canvas').textContent, /Missing module/)
  await click('Save project')
  assert.equal(savedFlows[0].flow.nodes.length, 1)
})

test('multiple viewers use a stable ID default and switching leaves packages and computation unchanged', async () => {
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    if (String(url) === '/api/modules') return Response.json({})
    if (String(url) === '/api/catalog') return Response.json({ nodes: [], modules: [{ id: 'test.viewers', name: 'Viewers', enabled: true, ui: 'fixture.js', settings: {}, settings_schema: {} }] })
    return previousFetch(url, options)
  }
  await click('Register module')
  await click('Project B')
  const original = clone(packages.b)
  await choose('Data package', 'b-package')
  const select = [...container.querySelectorAll('label')].find(label => label.textContent.startsWith('Viewer')).querySelector('select')
  assert.deepEqual([...select.options].map(option => option.value), ['a.basic', 'z.detail'])
  assert.equal(select.value, 'a.basic')
  assert.equal(container.querySelector('[data-testid=viewer]').textContent, 'Basic b-package')
  await act(async () => { select.value = 'z.detail'; select.dispatchEvent(new window.Event('change', { bubbles: true })) })
  assert.equal(container.querySelector('[data-testid=viewer]').textContent, 'Detailed b-package')
  assert.deepEqual(packages.b, original)
  assert.deepEqual(runRequests, [])
  assert.equal(title(), 'Project B')
  await click('Project A'); await click('Project B'); await choose('Data package', 'b-package')
  assert.equal(container.querySelector('[data-testid=viewer]').textContent, 'Basic b-package')
})

test('disabling a failed viewer restores the stable available default', async () => {
  const previousFetch = globalThis.fetch
  let brokenEnabled = true
  globalThis.fetch = async (url, options) => {
    if (String(url) === '/api/modules') return Response.json({})
    if (String(url) === '/api/catalog') return Response.json({ nodes: [], modules: [
      { id: 'test.viewers', name: 'Viewers', enabled: true, ui: 'fixture.js', settings: {}, settings_schema: {} },
      { id: 'test.broken', name: 'Broken viewer', enabled: brokenEnabled, ui: 'fixture.js', settings: {}, settings_schema: {} },
    ] })
    return previousFetch(url, options)
  }
  await click('Register module'); await click('Project B'); await choose('Data package', 'b-package')
  const select = [...container.querySelectorAll('label')].find(label => label.textContent.startsWith('Viewer')).querySelector('select')
  const originalError = console.error
  console.error = () => {}
  try {
    await act(async () => { select.value = 'z.broken'; select.dispatchEvent(new window.Event('change', { bubbles: true })) })
  } finally { console.error = originalError }
  assert.match(container.querySelector('.package [role=alert]').textContent, /Viewer unavailable/)
  brokenEnabled = false
  await click('Register module')
  assert.equal(container.querySelector('[data-testid=viewer]')?.textContent, 'Basic b-package')
  assert.deepEqual(runRequests, [])
})

test('a failed save from a previous project cannot show an error in the current editor', async () => {
  await addNode()
  pendingSave = deferred()
  await click('Save project')
  await click('Project B')
  await act(async () => pendingSave.reject(new Error('Old save failed')))
  assert.equal(title(), 'Project B')
  assert.equal(container.querySelector('[role=alert]')?.textContent, undefined)
})

test('typing parameter JSON immediately marks the draft unsaved and saving commits the focused editor', async () => {
  await addNode()
  await click('Save project')
  const parameters = container.querySelector('.canvas textarea')
  await act(async () => {
    parameters.focus()
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(parameters, '{"region":[12,17]}')
    parameters.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
  assert.equal(title(), 'Project A · unsaved')
  assert.equal(savedFlows.length, 1)
  await click('Save project')
  assert.deepEqual(savedFlows[1].flow.nodes[0].parameters, { region: [12, 17] })
  assert.equal(title(), 'Project A')
})


test('creating another project asks once to discard the unchanged unsaved draft', async () => {
  await addNode()
  const prompts = []
  window.confirm = message => { prompts.push(message); return prompts.length === 1 }
  await click('Create project')
  assert.equal(title(), 'Research project')
  assert.equal(prompts.length, 1)
  assert.match(prompts[0], /discard unsaved/i)
  assert.equal(savedFlows.length, 0)
})

test('opening another project cannot silently discard edits made while its response was pending', async () => {
  projectGate = deferred()
  await click('Project B')
  await addNode()
  const prompts = []
  window.confirm = message => { prompts.push(message); return false }
  await act(async () => projectGate.resolve())
  assert.equal(title(), 'Project A · unsaved')
  assert.equal(nodeCount(), 1)
  assert.equal(prompts.length, 1)
  assert.equal(savedFlows.length, 0)
})

test('a pending save cannot clear an unblurred parameter draft entered after its snapshot', async () => {
  await addNode()
  pendingSave = deferred()
  await click('Save project')
  const parameters = container.querySelector('.canvas textarea')
  await act(async () => {
    parameters.focus()
    parameters.value = '{"seed":9}'
    parameters.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
  await act(async () => pendingSave.resolve())
  assert.equal(title(), 'Project A · unsaved')
  assert.equal(parameters.value, '{"seed":9}')
  assert.deepEqual(savedFlows[0].flow.nodes[0].parameters, {})
})

test('canceling save and run leaves edits in memory and never starts or saves', async () => {
  await addNode()
  const prompts = []
  window.confirm = message => { prompts.push(message); return false }
  await click('Save and run')
  assert.match(prompts[0], /save.*run/i)
  assert.equal(title(), 'Project A · unsaved')
  assert.equal(savedFlows.length, 0)
  assert.deepEqual(runRequests, [])
})

test('a failed save and run preserves the draft and never starts a run', async () => {
  await addNode()
  pendingSave = deferred()
  await click('Save and run')
  await act(async () => pendingSave.reject(new Error('Project commit refused')))
  assert.match(container.querySelector('[role=alert]')?.textContent ?? '', /Project commit refused/)
  assert.equal(container.querySelector('[role=status]')?.textContent, undefined)
  assert.equal(title(), 'Project A · unsaved')
  assert.deepEqual(runRequests, [])
  pendingSave = null
  await click('Save and run')
  assert.equal(title(), 'Project A')
  assert.deepEqual(runRequests, ['a'])
})

test('invalid parameter text stays unsaved and cannot save or start its previous valid parameters', async () => {
  await addNode()
  const parameters = container.querySelector('.canvas textarea')
  await act(async () => {
    parameters.focus(); parameters.value = '{unfinished'
    parameters.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
  await click('Save and run')
  assert.equal(title(), 'Project A · unsaved')
  assert.equal(parameters.value, '{unfinished')
  assert.match(container.querySelector('[role=alert]')?.textContent ?? '', /valid parameter JSON/)
  assert.equal(savedFlows.length, 0)
  assert.deepEqual(runRequests, [])
})

test('leaving a dirty project offers discard or cancel without saving', async () => {
  await addNode()
  const prompts = []
  window.confirm = message => { prompts.push(message); return false }
  await click('Project B')
  assert.equal(title(), 'Project A · unsaved')
  assert.match(prompts[0], /discard unsaved/i)
  assert.doesNotMatch(prompts[0], /save.*(?:exit|leave)/i)
  window.confirm = () => true
  await click('Project B')
  await click('Project A')
  assert.equal(nodeCount(), 0)
  assert.equal(savedFlows.length, 0)
})

test('beforeunload is prevented only while a project draft is unsaved', async () => {
  const unload = () => {
    const event = new window.Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
  }
  assert.equal(unload(), false)
  await addNode()
  assert.equal(unload(), true)
  await click('Save project')
  assert.equal(unload(), false)
  await addNode()
  window.confirm = () => true
  await click('Project B')
  assert.equal(unload(), false)
})

test('discarding invalid JSON and reopening the same project restores its saved parameter editor', async () => {
  await addNode()
  await click('Save project')
  const parameters = container.querySelector('.canvas textarea')
  await act(async () => {
    parameters.focus(); parameters.value = '{unfinished'
    parameters.dispatchEvent(new window.Event('input', { bubbles: true }))
    parameters.blur()
  })
  assert.equal(title(), 'Project A · unsaved')
  window.confirm = () => true
  await click('Project A')
  assert.equal(title(), 'Project A')
  const reopened = container.querySelector('.canvas textarea')
  assert.equal(reopened.value, '{}')
  assert.equal(reopened.validity.valid, true)
  await click('Save project')
  assert.equal(container.querySelector('[role=alert]')?.textContent, undefined)
  assert.deepEqual(savedFlows[1].flow.nodes[0].parameters, {})
})


test('teaching edits stay in memory until first manual save creates a user project', async () => {
  await click('Teaching example')
  assert.equal(title(), 'Teaching example')
  await addNode()
  assert.equal(title(), 'Teaching example · unsaved')
  assert.equal(records.length, 2)
  await click('Save project')
  assert.equal(title(), 'Research project')
  assert.equal(nodeCount(), 2)
  assert.equal(records.find(item => item.id === 'copied').flow.nodes.length, 2)
  await click('Teaching example')
  assert.equal(nodeCount(), 1)
})

test('failed teaching first save preserves its draft and never reports completion', async () => {
  await click('Teaching example')
  await addNode()
  pendingSave = deferred()
  await click('Save project')
  await act(async () => pendingSave.reject(new Error('commit refused')))
  assert.equal(title(), 'Teaching example · unsaved')
  assert.equal(nodeCount(), 2)
  assert.match(container.querySelector('[role=alert]').textContent, /commit refused/)
  assert.equal(container.querySelector('[role=status]'), null)
  assert.equal(records.length, 2)
})


test('an untouched teaching example saves a user project before starting its run', async () => {
  await click('Teaching example')
  assert.equal(title(), 'Teaching example')
  await click('Save and run')
  assert.deepEqual(runRequests, ['copied'])
  assert.equal(title(), 'Research project')
})

test('copy opens a new unrun project with the current flow and layout draft', async () => {
  await addNode()
  await click('Copy project')
  assert.equal(title(), 'Research project')
  assert.equal(nodeCount(), 1)
  assert.equal(records.find(item => item.id === 'a').flow.nodes.length, 0)
  assert.deepEqual(runRequests, [])
})


test('teaching file edits remain available in the draft and are released when discarded', async () => {
  await click('Teaching example')
  await click('Upload and add node')
  assert.equal(title(), 'Teaching example · unsaved')
  assert.equal(nodeCount(), 2)
  assert.equal(records.length, 2)
  assert.deepEqual(discardedDraftInputs, [])
  await click('Project A')
  assert.deepEqual(discardedDraftInputs, ['a-input'])
})

test('leaving the page releases teaching draft inputs after native leave confirmation', async () => {
  await click('Teaching example')
  await click('Upload and add node')
  await act(async () => window.dispatchEvent(new window.Event('pagehide')))
  assert.deepEqual(discardedDraftInputs, ['a-input'])
})


test('a copy failure after switching projects cannot overwrite the current editor notice', async () => {
  await addNode()
  pendingSave = deferred()
  await click('Copy project')
  await click('Project B')
  await act(async () => pendingSave.reject(new Error('copy commit refused')))
  assert.equal(title(), 'Project B')
  assert.equal(Boolean(container.querySelector('[role=alert]')), false)
})


test('application startup opens the editable teaching example by default', async () => {
  await act(async () => root.unmount())
  root = createRoot(container)
  await act(async () => root.render(createElement(App)))
  assert.equal(title(), 'Teaching example')
  assert.equal(nodeCount(), 1)
  await addNode()
  assert.equal(title(), 'Teaching example · unsaved')
  assert.equal(records.length, 2)
})

test('a poll begun before start cannot unlock the accepted running project', async () => {
  const previousFetch = globalThis.fetch
  const stalePoll = deferred()
  let pollingStarted = false, backendRunning = false
  const runRecord = { id: 'new-run', status: 'running', nodes: {}, diagnostics: [] }
  globalThis.fetch = async (url, options = {}) => {
    if (String(url) === '/api/projects/a/runs') {
      if (options.method === 'POST') { backendRunning = true; return Response.json(runRecord) }
      const snapshot = backendRunning ? [runRecord] : []
      pollingStarted = true
      await stalePoll.promise
      return Response.json(snapshot)
    }
    return previousFetch(url, options)
  }
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)) })
  assert.equal(pollingStarted, true)
  await click('Run')
  assert.equal(button('Save project').disabled, true)
  assert.equal(backendRunning, true)
  await act(async () => stalePoll.resolve())
  assert.equal(button('Save project').disabled, true, 'old empty history must not unlock a project whose start was accepted')
})

test('a poll package response begun before cancel cannot overwrite the cancellation view', async () => {
  const previousFetch = globalThis.fetch
  const oldPackages = deferred()
  let packageRequested = false
  let status = 'running'
  const history = () => [{ id: 'background', status, nodes: {}, diagnostics: [] }]
  globalThis.fetch = async (url, options = {}) => {
    if (String(url) === '/api/projects/a/runs') return Response.json(options.method === 'POST' ? history()[0] : history())
    if (String(url) === '/api/projects/a/packages' && !packageRequested) {
      packageRequested = true
      await oldPackages.promise
      return Response.json([{ id: 'stale-package', format: 'other', entry: 'data', files: ['data'] }])
    }
    if (String(url) === '/api/runs/background/cancel') return Response.json(history()[0])
    return previousFetch(url, options)
  }
  await click('Run')
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)) })
  assert.equal(packageRequested, true)
  await click('Cancel run')
  await act(async () => oldPackages.resolve())
  assert.match(container.querySelector('[role=status]').textContent, /Cancellation requested/)
  assert.equal(button('Save project').disabled, true)
  assert.equal([...container.querySelector('[aria-label="Data package"]').options].some(option => option.value === 'stale-package'), false)
  status = 'cancelled'
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)) })
  assert.equal(button('Save project').disabled, false)
})

test('lost start response keeps the project locked until a current poll observes the backend', async () => {
  const previousFetch = globalThis.fetch
  const stalePoll = deferred()
  let backendRunning = false
  const runRecord = { id: 'accepted-with-lost-response', status: 'running', nodes: {}, diagnostics: [] }
  globalThis.fetch = async (url, options = {}) => {
    if (String(url) === '/api/projects/a/runs') {
      if (options.method === 'POST') { backendRunning = true; throw new Error('start response lost') }
      const snapshot = backendRunning ? [runRecord] : []
      if (!backendRunning) await stalePoll.promise
      return Response.json(snapshot)
    }
    return previousFetch(url, options)
  }
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)) })
  await click('Run')
  assert.match(container.querySelector('[role=alert]').textContent, /response lost/)
  assert.equal(button('Save project').disabled, true)
  await act(async () => stalePoll.resolve())
  assert.equal(button('Save project').disabled, true)
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)) })
  assert.equal(button('Save project').disabled, true)
  assert.match(container.textContent, /accepted-with-lost-response/)
})

test('a rejected poll from before start cannot replace the current run with an error', async () => {
  const previousFetch = globalThis.fetch
  const oldPoll = deferred()
  globalThis.fetch = async (url, options = {}) => {
    if (String(url) === '/api/projects/a/runs') {
      if (options.method === 'POST') return Response.json({ id: 'accepted', status: 'running', nodes: {}, diagnostics: [] })
      await oldPoll.promise
      throw new Error('obsolete poll failed')
    }
    return previousFetch(url, options)
  }
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)) })
  await click('Run')
  await act(async () => oldPoll.resolve())
  assert.equal(container.querySelector('[role=alert]'), null)
  assert.equal(button('Save project').disabled, true)
})
