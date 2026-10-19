import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as React from 'react';
const source = await readFile(new URL('../../modules/solubility/ui.js', import.meta.url), 'utf8');
const { register } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
const { createRoot } = await import('react-dom/client');
after(() => dom.window.close());
const extensions = register({ React });

test('solubility node explains complete-sequence tool parameters and restrictions', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  try {
    const editor = extensions.editors.find(item => item.node === 'workbench.evaluate_solubility');
    assert.ok(editor);
    await React.act(async () => root.render(React.createElement(editor.component, { parameters: {}, onChange() {}, readOnly: false })));
    assert.match(container.textContent, /20 residues/);
    assert.match(container.textContent, /21 residues/);
    assert.match(container.textContent, /membrane_exclude/);
    assert.match(container.textContent, /threads/);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});

test('viewer renders actual object method numbers units and meanings', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  const manifest = { objects: [{ id: 'original', label: 'Research protein', sequence: 'ACD', source: { name: 'research.fa' } }],
    evaluations: [{ object_id: 'original', method: 'Protein-Sol October 2017 sequence prediction', values: { percent_solubility: { value: 113.241, unit: 'percent', meaning: 'Niwa cell-free expression percentage scale' }, isoelectric_point: { value: 7.13, unit: 'pH', meaning: 'Calculated isoelectric point' } } }],
    tool: { id: 'workbench.protein_sol', parameters: { membrane_exclude: false }, context: { population_scaled_solubility: .446 } } };
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'result', entry: 'manifest.json' }, host: { readFile: async (id, key) => { assert.equal(id, 'result'); assert.equal(key, 'manifest.json'); return new Blob([JSON.stringify(manifest)]); } } })));
    assert.match(container.textContent, /Research protein/);
    assert.match(container.textContent, /113.241/);
    assert.match(container.textContent, /percent/);
    assert.match(container.textContent, /pH/);
    assert.match(container.textContent, /research.fa/);
    assert.match(container.textContent, /Niwa cell-free expression/);
    assert.equal(container.querySelectorAll('tbody tr').length, 2);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});

test('viewer reports an unresolved evaluation object instead of displaying an invented label', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  try {
    const malformed = { objects: [{ id: 'actual', sequence: 'ACD' }], evaluations: [{ object_id: 'absent', method: 'Tool', values: { score: { value: .4, unit: 'fraction', meaning: 'Known scale' } } }], tool: { id: 'actual-tool', parameters: {}, context: {} } };
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'invalid', entry: 'manifest.json' }, host: { readFile: async () => new Blob([JSON.stringify(malformed)]) } })));
    assert.match(container.querySelector('[role="alert"]')?.textContent || '', /object/);
    assert.equal(container.querySelector('table'), null);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});
