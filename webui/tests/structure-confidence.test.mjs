import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as React from 'react';
const source = await readFile(new URL('../../modules/structure_confidence/ui.js', import.meta.url), 'utf8');
const { register } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
const { createRoot } = await import('react-dom/client');
after(() => dom.window.close());
const extensions = register({ React });

test('prepared confidence viewer selects actual discontinuous residues and binds the unchanged object', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container), calls = [];
  const positions = [{ chain: 'Z', author_number: 12, insertion_code: 'A' }, { chain: 'Z', author_number: 18, insertion_code: '' }, { chain: 'Z', author_number: 19, insertion_code: '' }];
  const manifest = { objects: [{ id: 'original', label: 'Research structure', structure: { file: 'original.pdb', format: 'pdb' } }], confidence_positions: { original: 'positions.json' } };
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'prepared', entry: 'manifest.json', format: 'workbench.confidence_input' }, host: { readOnly: false, readFile: async (id, key) => new Blob([JSON.stringify(key === 'positions.json' ? positions : manifest)]), addNode: async node => calls.push(node) } })));
    const checks = container.querySelectorAll('input[type="checkbox"]');
    assert.equal(checks.length, 3);
    await React.act(async () => { checks[0].click(); checks[2].click(); });
    const button = [...container.querySelectorAll('button')].find(b => b.textContent === 'Add independent confidence evaluation');
    await React.act(async () => button.click());
    assert.deepEqual(calls[0].parameters, { object: 'original', region: [positions[0], positions[2]] });
    assert.deepEqual(calls[0].inputs, { structures: ['prepared'] });
    assert.equal(container.querySelector('textarea'), null);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});

test('confidence viewer reads stored per-position scores and displays method scale and attribution', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  const position = { chain: 'Z', author_number: 12, insertion_code: 'A' };
  const manifest = { objects: [{ id: 'original', label: 'Research structure', structure: { file: 'original.pdb', format: 'pdb' }, confidence: { plddt: { file: 'source-confidence.json' } } }], evaluations: [{ object_id: 'original', origin: 'independent_existing_geometry', reference: null, region: [position], method: 'Given geometry latent + head', values: { mean_plddt: { value: .75, meaning: 'Selected residue mean' } }, per_position: { file: 'scores.json', unit: 'fraction (0–1)' } }] };
  const reads = [];
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'saved', entry: 'manifest.json' }, host: { readOnly: true, readFile: async (id, key) => { reads.push([id, key]); return new Blob([JSON.stringify(key === 'scores.json' ? { positions: [position], plddt: [.75] } : manifest)]); } } })));
    assert.match(container.textContent, /Given geometry latent \+ head/);
    assert.match(container.textContent, /fraction \(0–1\)/);
    assert.match(container.textContent, /Research structure/);
    assert.match(container.textContent, /0.75/);
    assert.match(container.textContent, /source-confidence.json/);
    assert.deepEqual(reads, [['saved', 'manifest.json'], ['saved', 'scores.json']]);
    assert.ok([...container.querySelectorAll('button')].every(button => button.disabled));
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});

test('confidence result chooses explicit structure format export without recomputing', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container), calls = [];
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'evaluation', entry: 'manifest.json', format: 'workbench.structure_confidence' }, host: { readOnly: false, readFile: async () => new Blob([JSON.stringify({ objects: [{ id: 'original', label: 'Existing structure', structure: { file: 'original.pdb', format: 'pdb' } }] })]), addNode: async node => calls.push(node) } })));
    const select = container.querySelector('[aria-label="Confidence structure export format"]');
    await React.act(async () => { select.value = 'pdb'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    await React.act(async () => [...container.querySelectorAll('button')].find(button => button.textContent === 'Add structure format export').click());
    assert.deepEqual(calls, [{ type: 'workbench.export_structure', inputs: { structures: ['evaluation'] }, parameters: { object: 'original', format: 'pdb' } }]);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});
