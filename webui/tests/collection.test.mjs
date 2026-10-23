import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { readFile } from 'node:fs/promises';
import * as React from 'react';
import { JSDOM } from 'jsdom';

const source = await readFile(new URL('../../modules/collection/ui.js', import.meta.url), 'utf8');
const { register } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
const { createRoot } = await import('react-dom/client');
after(() => dom.window.close());

test('collection viewer creates explicit standalone conversions and split', async () => {
  const extension = register({ React }), Viewer = extension.viewers[0].component;
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
  const nodes = [], pkg = { id: 'private-package', entry: 'manifest.json' };
  const host = { readOnly: false, readFile: async () => new Blob([JSON.stringify({ items: [{ object: { id: 'private-object', label: 'Selected candidate' } }] })]),
    addNode: async node => nodes.push(node) };
  await React.act(async () => root.render(React.createElement(Viewer, { package: pkg, host })));
  for (const label of ['Split into object packages', 'Extract selected structures', 'Extract selected sequences']) {
    await React.act(async () => [...container.querySelectorAll('button')].find(button => button.textContent === label).click());
  }
  assert.deepEqual(nodes.map(node => node.type), ['workbench.collection.split', 'workbench.collection.extract_structures', 'workbench.collection.extract_sequences']);
  assert.ok(nodes.every(node => node.inputs.collection[0] === pkg.id));
  assert.ok(!container.textContent.includes('private-object'));
  await React.act(async () => root.render(React.createElement(Viewer, { package: pkg, host: { ...host, readOnly: true } })));
  assert.ok([...container.querySelectorAll('button')].every(button => button.disabled));
  await React.act(async () => root.unmount()); container.remove();
});

test('selection editor preserves explicit pick order without exposing identities', async () => {
  const Editor = register({ React }).editors[0].component;
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
  const context = { inputs: { collection: { packages: [{ id: 'package', entry: 'manifest.json' }] } },
    host: { readFile: async () => new Blob([JSON.stringify({ items: [{ object: { id: 'secret-a', label: 'A' } }, { object: { id: 'secret-b', label: 'B' } }] })]) } };
  let parameters = { items: [] };
  const render = () => root.render(React.createElement(Editor, { context, parameters, readOnly: false, onChange: value => { parameters = value; render(); } }));
  await React.act(async () => render());
  await React.act(async () => container.querySelectorAll('input')[1].click());
  await React.act(async () => container.querySelectorAll('input')[0].click());
  assert.deepEqual(parameters.items, [1, 0]);
  assert.equal(container.querySelector('ol').textContent, 'BA');
  assert.ok(!container.textContent.includes('secret-'));
  await React.act(async () => root.unmount()); container.remove();
});
