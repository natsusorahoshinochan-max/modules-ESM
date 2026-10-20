/** Real App and registered external sample; only HTTP transport is isolated. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { registerHooks } from 'node:module';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import * as React from 'react';

const repo = fileURLToPath(new URL('../../', import.meta.url));

test('external parameter drafts protect unsaved edits and corrected objects reach save, copy and run', { timeout: 15000 }, async () => {
  const directory = await mkdtemp(join(repo, 'webui/.notes-draft-'));
  const originalFetch = globalThis.fetch;
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
  const confirms = []; window.confirm = message => { confirms.push(message); return true; };
  const sample = await readFile(join(repo, 'examples/external_module/src/workbench_notes/ui.js'), 'utf8');
  const hooks = registerHooks({ resolve(specifier, context, next) {
    if (specifier === '/api/modules/notes/ui.js') return { url: 'data:text/javascript;base64,' + Buffer.from(sample).toString('base64'), shortCircuit: true };
    return next(specifier, context);
  } });
  const tutorial = { id: 'tutorial', name: 'Teaching example', tutorial: true, flow: { nodes: [], edges: [] }, layout: {} };
  const projects = new Map([['p', { id: 'p', name: 'External notes', flow: { nodes: [{ id: 'note', type: 'example.uppercase', parameters: { label: 'accepted' }, inputs: {} }], edges: [] }, layout: {} }]]);
  const saves = [], copies = [], starts = []; let polls = 0; let running = false;
  globalThis.fetch = async (url, options = {}) => {
    const path = String(url); let value;
    if (path === '/api/catalog') value = {
      nodes: [{ id: 'example.uppercase', name: 'Uppercase note', module_id: 'example.notes', inputs: {}, outputs: {}, parameters: {} }],
      modules: [{ id: 'example.notes', name: 'External notes', enabled: true, settings: {}, settings_schema: {}, installation_id: 'installed-notes', ui_url: '/api/modules/notes/ui.js' }],
    };
    else if (path === '/api/tutorial' || path === '/api/projects/tutorial') value = tutorial;
    else if (path === '/api/projects') value = [...projects.values()];
    else if (path.endsWith('/packages')) value = [];
    else if (path.endsWith('/runs')) {
      const id = path.split('/')[3];
      if (options.method === 'POST') { starts.push(structuredClone(projects.get(id).flow)); running = true; }
      else polls++;
      const run = { id: 'run1', status: 'running', diagnostics: [], nodes: {} };
      value = options.method === 'POST' ? run : running ? [run] : [];
    } else if (path.endsWith('/copies')) {
      const body = JSON.parse(options.body); copies.push(body);
      value = { ...body, id: 'copy', name: 'Notes copy' }; projects.set('copy', value);
    } else if (projects.has(path.split('/')[3])) {
      const id = path.split('/')[3];
      if (options.method === 'PUT') { const body = JSON.parse(options.body); saves.push(body); projects.set(id, { ...projects.get(id), ...body }); }
      value = projects.get(id);
    } else throw Error('Unexpected HTTP request ' + path);
    return Response.json(structuredClone(value));
  };
  let root;
  try {
    const output = join(directory, 'App.mjs');
    await build({ entryPoints: [join(repo, 'webui/src/App.tsx')], bundle: true, packages: 'external', platform: 'node', format: 'esm', jsx: 'automatic', outfile: output });
    const { default: App } = await import(pathToFileURL(output));
    const { createRoot } = await import('react-dom/client');
    const container = document.createElement('div'); document.body.append(container); root = createRoot(container);
    const button = text => [...container.querySelectorAll('button')].find(item => item.textContent === text);
    const field = () => container.querySelector('.node textarea');
    async function settle(predicate) {
      for (let i = 0; i < 150; i++) { await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); }); if (predicate()) return; }
      assert.fail(container.textContent);
    }
    async function click(text) { await React.act(async () => button(text).click()); }
    async function edit(value) { await React.act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(field(), value);
      field().dispatchEvent(new window.Event('input', { bubbles: true }));
    }); }
    await React.act(async () => root.render(React.createElement(App)));
    await settle(() => button('External notes')); await click('External notes'); await settle(field);
    await edit('{');
    assert.equal(field().checkValidity(), false, 'invalid input blocks saving before blur');
    assert.match(container.querySelector('.toolbar h2').textContent, /unsaved/);
    const exit = new window.Event('beforeunload', { cancelable: true }); window.dispatchEvent(exit);
    assert.equal(exit.defaultPrevented, true);
    await click('Save project'); await click('Copy project'); await click('Save and run');
    assert.ok(confirms.includes('Save changes and run?'));
    assert.equal(saves.length, 0); assert.equal(copies.length, 0); assert.equal(starts.length, 0);
    assert.deepEqual(projects.get('p').flow.nodes[0].parameters, { label: 'accepted' });
    for (const invalid of ['null', '[]', '"text"', '1', 'true']) {
      await edit(invalid); assert.equal(field().checkValidity(), false);
    }
    const beforePoll = polls; await settle(() => polls > beforePoll);
    assert.equal(field().value, 'true'); assert.equal(field().checkValidity(), false);
    // A queued accepted-value echo must preserve a newer local invalid keystroke.
    await React.act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(field(), '{"label":"intermediate"}');
      field().dispatchEvent(new window.Event('input', { bubbles: true }));
      setter.call(field(), '{"label":');
      field().dispatchEvent(new window.Event('input', { bubbles: true }));
    });
    assert.equal(field().value, '{"label":'); assert.equal(field().checkValidity(), false);
    const corrected = '{ "label": "corrected" }'; await edit(corrected);
    assert.equal(field().checkValidity(), true); assert.equal(field().value, corrected);
    await click('Save project'); assert.deepEqual(saves.at(-1).flow.nodes[0].parameters, { label: 'corrected' });
    await edit('{"label":"copied"}'); await click('Copy project'); await settle(() => container.querySelector('.toolbar h2').textContent === 'Notes copy');
    assert.deepEqual(copies.at(-1).flow.nodes[0].parameters, { label: 'copied' });
    await edit('{'); await click('External notes'); await settle(() => container.querySelector('.toolbar h2').textContent === 'External notes');
    assert.equal(field().checkValidity(), true); assert.deepEqual(JSON.parse(field().value), { label: 'corrected' });
    await edit('{"label":"run-new"}'); await click('Save and run'); await settle(() => starts.length === 1);
    assert.deepEqual(starts[0].nodes[0].parameters, { label: 'run-new' });
    assert.deepEqual(saves.at(-1).flow.nodes[0].parameters, { label: 'run-new' });
    assert.equal(field().disabled, true);
    await edit('{"label":"forbidden"}'); assert.deepEqual(projects.get('p').flow.nodes[0].parameters, { label: 'run-new' });
    console.log('Actual external editor: invalid dirty/unload/save/copy/run protection, shape rejection, poll preservation, correction/no-blur persistence, owner reset and readOnly verified');
  } finally {
    if (root) await React.act(async () => root.unmount());
    globalThis.fetch = originalFetch; hooks.deregister(); dom.window.close();
    await rm(directory, { recursive: true, force: true });
  }
});
