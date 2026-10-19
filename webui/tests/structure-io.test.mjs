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
        record = next(item for item in client.get('/api/modules').json() if item['id'] == 'workbench.structure_io')
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

test('single-file import passes the actual model selection and preserves original file bytes', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container), calls = []
  const host = { readOnly: false, async createInput(input) { calls.push(input); return { id: 'raw' } }, async addNode(node) { calls.push(node) } }
  try {
    await React.act(async () => root.render(React.createElement(extensions.actions[0].component, { host })))
    const input = container.querySelector('input[type=file]')
    assert.equal(input.multiple, false)
    const original = new Blob(['MODEL        9\n']); Object.defineProperty(original, 'name', { value: 'actual.pdb' })
    Object.defineProperty(input, 'files', { value: [original] })
    await React.act(async () => input.dispatchEvent(new window.Event('change', { bubbles: true })))
    await React.act(async () => container.querySelector('button').click())
    assert.equal(calls[0].files.original, original)
    assert.deepEqual(calls[1].parameters, { models: 'all' })
    assert.equal(calls[1].type, 'workbench.import_structure')
  } finally { await React.act(async () => root.unmount()); container.remove() }
})

test('viewer selects actual components and adds export, extraction and coordinate nodes', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container), calls = []
  const files = { 'manifest.json': JSON.stringify({objects:[{id:'actual',label:'Original model 9',atoms:'atoms.json'}]}),
    'atoms.json': JSON.stringify([
      {index:0,model:9,chain:'X',author_number:12,insertion_code:'A',residue_name:'ALA',atom_name:'CA',altloc:'',position:[1,2,3]},
      {index:1,model:9,chain:'M',author_number:-2,insertion_code:'',residue_name:'ZN',atom_name:'ZN',altloc:'',position:[7,8,9]},
      {index:2,model:9,chain:'W',author_number:3,insertion_code:'',residue_name:'HOH',atom_name:'O',altloc:'',position:[10,11,12]},
      {index:3,model:9,chain:'N',author_number:40,insertion_code:'',residue_name:'DA',atom_name:'P',altloc:'',position:[13,14,15]},
      {index:4,model:9,chain:'L',author_number:91,insertion_code:'',residue_name:'LIG',atom_name:'C1',altloc:'',position:[4,5,6]},
    ]) }
  const host = { readOnly:false, async readFile(id,key) { assert.equal(id,'saved'); return new Blob([files[key]]) }, async addNode(node) { calls.push(node) } }
  try {
    await React.act(async () => { root.render(React.createElement(extensions.viewers[0].component, { package:{id:'saved',entry:'manifest.json'},host })); })
    await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 20)) })
    assert.equal(container.querySelectorAll('circle').length, 5)
    const metal = [...container.querySelectorAll('circle')].find(c => c.getAttribute('aria-label').includes('ZN'))
    await React.act(async () => metal.dispatchEvent(new window.KeyboardEvent('keydown', {key:'Enter',bubbles:true})))
    assert.match(container.textContent,/1 selected/)
    await React.act(async () => [...container.querySelectorAll('button')].find(b => b.textContent.includes('export node')).click())
    assert.deepEqual(calls[0], {type:'workbench.export_structure',inputs:{structures:['saved']},parameters:{object:'actual',format:'mmcif',atoms:[1]}})
    assert.match(metal.getAttribute('aria-label'), /9: M -2 ZN ZN/)
    const extract = [...container.querySelectorAll('button')].find(b => b.textContent === 'Add extraction node')
    assert.ok(extract, 'Viewer provides explicit extraction')
    await React.act(async () => extract.click())
    assert.deepEqual(calls[1], {type:'workbench.extract_structure',inputs:{structures:['saved']},parameters:{object:'actual',format:'mmcif',selection:{atoms:[1]}}})
    const transform = [...container.querySelectorAll('button')].find(b => b.textContent === 'Add coordinate transform node')
    assert.ok(transform, 'Viewer provides coordinate operation')
    await React.act(async () => {
      const matrix = container.querySelector('[aria-label="Coordinate rotation matrix"]')
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(matrix, '[[0,-1,0],[1,0,0],[0,0,1]]')
      matrix.dispatchEvent(new window.Event('input', {bubbles:true}))
      const translation = container.querySelector('[aria-label="Coordinate translation"]')
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(translation, '[10,20,30]')
      translation.dispatchEvent(new window.Event('input', {bubbles:true}))
    })
    await React.act(async () => transform.click())
    assert.deepEqual(calls[2], {type:'workbench.transform_structure',inputs:{structures:['saved']},parameters:{object:'actual',format:'mmcif',selection:{atoms:[1]},rotation:[[0,-1,0],[1,0,0],[0,0,1]],translation:[10,20,30]}})
    assert.match(container.textContent, /7, 8, 9 Å/)

  } finally { await React.act(async () => root.unmount()); container.remove() }
})
