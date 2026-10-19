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
