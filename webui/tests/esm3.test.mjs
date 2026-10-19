import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as React from 'react';
const source = await readFile(new URL('../../modules/esm3/ui.js', import.meta.url), 'utf8');
const { register } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
const { createRoot } = await import('react-dom/client');
after(() => dom.window.close());
const extensions = register({ React });

test('generation viewer reads partial native result files and shows actual conditions and values', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  const manifest = { batch: { completed: 1, total: 3, status: 'failed' }, objects: [{ id: 'object', sequence: 'AB|CD', positions: [{ sequence_index: 1, source: { position: { chain: 'Z', author_number: 42, insertion_code: 'A' } } }], generation: { tracks: { sequence: 'A____' } }, native: { file: 'native-values' }, tool: { actual_seed: 17 } }] };
  const files = { manifest, 'native-values': { tracks: { sequence: 'AB|CD' }, metrics: { plddt: [.3, .4], ptm: .6 } } };
  const read = [];
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'result', entry: 'manifest' }, host: { readFile: async (id, key) => { read.push([id, key]); return new Blob([JSON.stringify(files[key])]); } } })));
    assert.match(container.textContent, /1\/3 completed; failed/);
    assert.match(container.textContent, /AB\|CD/);
    assert.match(container.textContent, /insertion_code/);
    assert.match(container.textContent, /0.6/);
    assert.match(container.textContent, /A____/);
    assert.deepEqual(read, [['result', 'manifest'], ['result', 'native-values']]);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});
