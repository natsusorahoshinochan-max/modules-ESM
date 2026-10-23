/** Actual App EditorContext -> public HTTP Interaction -> saved module parameters. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { registerHooks } from 'node:module';
import { createServer } from 'node:net';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import * as React from 'react';

const repo = fileURLToPath(new URL('../../', import.meta.url));
const originalFetch = globalThis.fetch;
const pdb = `ATOM      1  N   ALA Z  12A      1.000   2.000   3.000  1.00 11.00           N
ATOM      2  CA  ALA Z  12A      2.000   3.000   4.000  1.00 12.00           C
ATOM      3  C   ALA Z  12A      3.000   4.000   5.000  1.00 13.00           C
ATOM      4  O   ALA Z  12A      4.000   5.000   6.000  1.00 14.00           O
END
`;

test('actual editor selects explicit objects and saves full chain mapping through public interaction', { timeout: 60000 }, async () => {
  const dataRoot = await mkdtemp(join(tmpdir(), 'mpnn166-handoff-'));
  const buildRoot = await mkdtemp(join(repo, 'webui/.mpnn166-handoff-'));
  const portProbe = createServer(); await new Promise(resolve => portProbe.listen(0, '127.0.0.1', resolve));
  const port = portProbe.address().port; await new Promise(resolve => portProbe.close(resolve));
  const backend = spawn(process.env.WORKBENCH_PYTHON || 'python3', ['-u', '-c', 'from pathlib import Path; import sys,uvicorn; from protein_workbench_public.bootstrap import create_application; uvicorn.run(create_application(data_root=Path(sys.argv[1])),host="127.0.0.1",port=int(sys.argv[2]),log_level="error")', dataRoot, String(port)], { cwd: repo, stdio: ['ignore', 'pipe', 'pipe'] });
  let diagnostics = ''; backend.stderr.on('data', value => { diagnostics += value.toString(); });
  const base = `http://127.0.0.1:${port}`;
  const json = async (path, options = {}) => { const response = await originalFetch(base + path, options); assert.ok(response.ok, await response.clone().text()); return response.json(); };
  const post = (path, body) => json(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  let root, dom, hooks;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 600; attempt++) {
      try { await json('/api/projects'); ready = true; break; } catch { if (backend.exitCode !== null) break; await new Promise(resolve => setTimeout(resolve, 50)); }
    }
    assert.ok(ready, diagnostics);
    const project = await post('/api/projects', { name: '166 actual editor handoff' });
    async function upload(format, files) {
      const upload = await post(`/api/projects/${project.id}/uploads`, {});
      const path = `/api/projects/${project.id}/uploads/${upload.upload_id}`;
      for (const [key, content] of Object.entries(files)) {
        const response = await originalFetch(base + path + '/files?key=' + encodeURIComponent(key), { method: 'PUT', body: content });
        assert.ok(response.ok, await response.text());
      }
      return post(path + '/commit', { format, entry: 'manifest.json', files: Object.fromEntries(Object.keys(files).map(key => [key, key])) });
    }
    const sequence = await upload('workbench.sequence', { 'manifest.json': JSON.stringify({ objects: [{ id: 'private-sequence', label: 'Explicit imported W', sequence: 'W' }] }) });
    const reference = await upload('workbench.structure_set', { 'manifest.json': JSON.stringify({ objects: [{ id: 'private-reference', label: 'Explicit reference Z', structure: { file: 'original.pdb', format: 'pdb' } }] }), 'original.pdb': pdb });
    await json(`/api/projects/${project.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ flow: { nodes: [{ id: 'evaluation', type: 'workbench.evaluate_sequence_backbone', inputs: { sequences: [sequence.id], reference: [reference.id] }, parameters: {}, tools: { mpnn: 'workbench.proteinmpnn.local' } }], edges: [] }, layout: {} }) });
    const catalog = await json('/api/catalog');
    const uiFiles = new Map(await Promise.all(catalog.modules.filter(module => module.ui_url).map(async module => {
      const response = await originalFetch(base + module.ui_url); assert.ok(response.ok);
      return [module.ui_url.split('?')[0], `data:text/javascript;base64,${Buffer.from(await response.text()).toString('base64')}`];
    })));
    hooks = registerHooks({ resolve(specifier, context, nextResolve) { const path = specifier.split('?')[0]; if (uiFiles.has(path)) return { url: uiFiles.get(path), shortCircuit: true }; return nextResolve(specifier, context); } });
    dom = new JSDOM('<!doctype html><html><body></body></html>', { url: base });
    Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
    window.confirm = () => true;
    const interactionRequests = [];
    globalThis.fetch = (url, options) => { if (String(url).endsWith('/interactions') && options?.method === 'POST') interactionRequests.push(JSON.parse(options.body)); return originalFetch(new URL(String(url), base), options); };
    const output = join(buildRoot, 'App.mjs');
    await build({ entryPoints: [join(repo, 'webui/src/App.tsx')], bundle: true, packages: 'external', platform: 'node', format: 'esm', jsx: 'automatic', outfile: output });
    const { default: App } = await import(pathToFileURL(output));
    const { createRoot } = await import('react-dom/client');
    const container = document.createElement('div'); document.body.append(container); root = createRoot(container);
    async function settle(predicate) { for (let i = 0; i < 100; i++) { await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 15)); }); if (predicate()) return; } assert.fail(container.textContent); }
    const button = text => [...container.querySelectorAll('button')].find(item => item.textContent === text);
    await React.act(async () => root.render(React.createElement(App)));
    await settle(() => !!button('166 actual editor handoff'));
    await React.act(async () => button('166 actual editor handoff').click());
    await settle(() => !!button('Inspect sequence and reference inputs'));
    assert.equal(button('Inspect sequence and reference inputs').disabled, false);
    await React.act(async () => button('Inspect sequence and reference inputs').click());
    await settle(() => !!container.querySelector('[aria-label="Reference structure"]'));
    assert.deepEqual(interactionRequests, [{ interaction: 'workbench.sequence_backbone.inspect', inputs: { sequences: [sequence.id], reference: [reference.id] }, parameters: {} }]);
    async function choose(label, value) { await React.act(async () => { const select = container.querySelector(`[aria-label="${label}"]`); select.value = value; select.dispatchEvent(new window.Event('change', { bubbles: true })); }); }
    await choose('Reference structure', 'private-reference');
    await choose('Sequence for reference chain Z', '0');
    await React.act(async () => container.querySelector('.canvas input[type="checkbox"]').click());
    assert.match(container.querySelector('.toolbar').textContent, /unsaved/);
    const unsaved = await json(`/api/projects/${project.id}`); assert.deepEqual(unsaved.flow.nodes[0].parameters, {});
    await React.act(async () => button('Save project').click());
    await settle(() => !container.querySelector('.toolbar').textContent.includes('unsaved'));
    const saved = await json(`/api/projects/${project.id}`);
    assert.deepEqual(saved.flow.nodes[0].parameters, { reference: 'private-reference', bindings: [{ reference_chain: 'Z', object: 'private-sequence', positions: [{ chain: 'Z', author_number: 12, insertion_code: 'A', sequence_index: 1 }] }], region: [{ chain: 'Z', author_number: 12, insertion_code: 'A' }] });
    assert.deepEqual(saved.flow.nodes[0].inputs, { sequences: [sequence.id], reference: [reference.id] });
    assert.deepEqual(await json(`/api/projects/${project.id}/runs`), []);
    assert.equal((await json(`/api/projects/${project.id}/packages`)).length, 2);
  } finally {
    if (root) await React.act(async () => root.unmount());
    globalThis.fetch = originalFetch;
    hooks?.deregister(); dom?.window.close();
    backend.kill('SIGTERM');
    if (backend.exitCode === null) await new Promise(resolve => backend.once('exit', resolve));
    await rm(dataRoot, { recursive: true, force: true }); await rm(buildRoot, { recursive: true, force: true });
  }
});
