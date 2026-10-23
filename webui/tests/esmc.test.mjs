import test from 'node:test';
import assert from 'node:assert/strict';
import { decodePage, register } from '../../modules/esmc/ui.js';

test('binary numeric viewer reads actual float16 values and leaves unnamed columns unnamed', () => {
  const data = new Uint16Array([0x3c00, 0xc000, 0x3800]);
  assert.deepEqual(decodePage(data.buffer, 'float16'), [1, -2, 0.5]);
  const react = { createElement() {} };
  const extension = register({ React: react });
  assert.equal(extension.viewers[0].formats[0], 'workbench.esmc');
  assert.equal(extension.editors[0].node, 'workbench.represent');
});

import { JSDOM } from 'jsdom';
import * as React from 'react';

test('viewer displays actual numeric page, source insertion codes and unnamed logits', async () => {
  const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { url: 'http://localhost' });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
  const { createRoot } = await import('react-dom/client');
  const root = createRoot(document.getElementById('root'));
  const columns = [{ index: 0, name: '<cls>' }, ...Array.from({ length: 33 }, (_, index) => ({ index: index + 1 }))];
  const descriptor = { dtype: 'float32', shape: [3, 34], pages: [{ file: 'page0.bin', start: 0, rows: 1 }, { file: 'page1.bin', start: 1, rows: 1 }, { file: 'page2.bin', start: 2, rows: 1 }], columns, semantics: 'raw logits; not probabilities' };
  const manifest = { tool: { id: 'workbench.esmc.biohub', parameters: { model: 'esmc-6b-2024-12' } }, objects: [{ input: { id: 'original', positions: [{ sequence_index: 1, chain: 'B', author_number: 12, insertion_code: 'A', label_position: { chain: 'X', position: 3 } }, { sequence_index: 2, label_position: { chain: 'X', position: 4 } }] }, tokens: [{ index: 0, id: 0, name: '<cls>' }, { index: 1, id: 5, name: 'A', sequence_index: 1 }, { index: 2, id: 6, name: 'G', sequence_index: 2 }], logits: descriptor }] };
  const reads = [];
  const host = { readFile: async (id, key) => { reads.push(key); return key === 'manifest.json' ? new Blob([JSON.stringify(manifest)]) : new Blob([new Float32Array(Array.from({ length: 34 }, (_, index) => (key === 'page0.bin' ? -17.25 : -29.5) + index))]); } };
  const Viewer = register({ React }).viewers[0].component;
  try {
    await React.act(async () => root.render(React.createElement(Viewer, { package: { id: 'result', entry: 'manifest.json' }, host })));
    assert.match(document.body.textContent, /-17.25/);
    assert.deepEqual(reads, ['manifest.json', 'page0.bin']);
    await React.act(async () => { const select = [...document.querySelectorAll('label')].find(label => label.textContent.startsWith('Columns')).querySelector('select'); select.value = '32'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    assert.deepEqual([...document.querySelectorAll('thead th')].map(cell => cell.textContent), ['Token / source position', '32', '33']);
    await React.act(async () => { const select = [...document.querySelectorAll('label')].find(label => label.textContent.startsWith('Page')).querySelector('select'); select.value = '1'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    assert.match(document.body.textContent, /author B:12A; label X:3/);
    assert.match(document.body.textContent, /2.5/);
    assert.deepEqual(reads, ['manifest.json', 'page0.bin', 'page1.bin']);
    await React.act(async () => { const select = [...document.querySelectorAll('label')].find(label => label.textContent.startsWith('Page')).querySelector('select'); select.value = '2'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    assert.match(document.querySelector('tbody th').textContent, /residue 2; label X:4/);
    assert.doesNotMatch(document.querySelector('tbody th').textContent, /author|undefined/);
  } finally { await React.act(async () => root.unmount()); dom.window.close(); }
});
