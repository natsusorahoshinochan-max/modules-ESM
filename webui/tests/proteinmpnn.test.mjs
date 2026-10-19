import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as React from 'react';
const source = await readFile(new URL('../../modules/proteinmpnn/ui.js', import.meta.url), 'utf8');
const { register } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
const { createRoot } = await import('react-dom/client');
after(() => dom.window.close());
const extensions = register({ React });

test('design viewer distinguishes score masks and shows actual values and insertion mapping', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  const manifest = { batch: { completed: 1, total: 2, status: 'failed' }, objects: [{ id: 'sample', chains: { B: 'AC' }, positions: [{ chain: 'B', author_number: 42, insertion_code: 'A', tool_position: 2 }], design: { score: 1.25, global_score: 2.75 }, tool: { actual_seed: 17 } }] };
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'result', entry: 'design.json' }, host: { readFile: async () => new Blob([JSON.stringify(manifest)]) } })));
    assert.match(container.textContent, /1\/2 backbones · failed/);
    assert.match(container.textContent, /1.25/);
    assert.match(container.textContent, /2.75/);
    assert.match(container.textContent, /global NLL averages coordinate mask over all chains/);
    assert.match(container.textContent, /insertion_code/);
    assert.match(container.textContent, /42/);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});

test('viewer shows actual chains and explicitly adds a chain conversion for the viewed package', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container), nodes = [];
  const manifest = { objects: [{ id: 'private-sample-id', chains: { B: 'AC', A: 'D' }, positions: [], design: { score: 1., global_score: 2. }, tool: { actual_seed: 17 } }] };
  const host = { readOnly: false, readFile: async () => new Blob([JSON.stringify(manifest)]), async addNode(node) { nodes.push(node); return 'private-node-id'; } };
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'viewed-design', entry: 'design.json' }, host })));
    assert.equal(container.querySelector('[aria-label="Chain B sequence"]').textContent, 'AC');
    assert.equal(container.querySelector('[aria-label="Chain A sequence"]').textContent, 'D');
    assert.equal(container.textContent.includes('private-sample-id'), false);
    assert.equal(container.querySelector('button').disabled, true);
    await React.act(async () => {
      const select = container.querySelector('[aria-label="Sequence chain"]');
      select.value = 'B'; select.dispatchEvent(new window.Event('change', { bubbles: true }));
    });
    await React.act(async () => container.querySelector('button').click());
    assert.deepEqual(nodes, [{ type: 'workbench.proteinmpnn_chain_sequence', parameters: { chain: 'B' }, inputs: { design: ['viewed-design'] } }]);
    assert.equal(container.textContent.includes('private-node-id'), false);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});
