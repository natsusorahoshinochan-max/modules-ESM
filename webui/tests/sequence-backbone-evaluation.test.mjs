import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as React from 'react';
const source = await readFile(new URL('../../modules/sequence_backbone_evaluation/ui.js', import.meta.url), 'utf8');
const { register } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
const { createRoot } = await import('react-dom/client');
after(() => dom.window.close());
const extensions = register({ React });
const positions = [{ chain: 'B', author_number: 42, insertion_code: '', tool_position: 1 }, { chain: 'B', author_number: 42, insertion_code: 'A', tool_position: 2 }];

test('editor inspects explicitly bound inputs and selects actual chain mapping and insertion-coded region', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container), calls = [], cancelled = [];
  let parameters = {};
  const data = { sequences: [{ object: 'private-seq', label: 'Research sequence', source_chain: 'S', sequence: 'WY' }], references: [{ object: 'private-reference', label: 'Arbitrary reference', positions }] };
  const host = { preview: async (...args) => { calls.push(args); return { id: 'preview', data, outputs: [] }; }, cancelPreview: async id => cancelled.push(id) };
  const context = { projectId: 'p', nodeId: 'n', parameters, inputs: { sequences: { packages: [{ id: 'sequence-package' }] }, reference: { packages: [{ id: 'reference-package' }] } }, host };
  function Harness() { const [p, setP] = React.useState({}); return React.createElement(extensions.editors[0].component, { parameters: p, onChange: value => { parameters = value; setP(value); }, readOnly: false, context }); }
  try {
    await React.act(async () => root.render(React.createElement(Harness)));
    await React.act(async () => container.querySelector('button').click());
    assert.deepEqual(calls, [['workbench.sequence_backbone.inspect', { sequences: ['sequence-package'], reference: ['reference-package'] }, {}]]);
    assert.deepEqual(cancelled, ['preview']);
    await React.act(async () => { const select = container.querySelector('[aria-label="Reference structure"]'); select.value = 'private-reference'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    await React.act(async () => { const select = container.querySelector('[aria-label="Sequence for reference chain B"]'); select.value = '0'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    assert.deepEqual(parameters.bindings, [{ reference_chain: 'B', object: 'private-seq', source_chain: 'S', positions: positions.map(({ tool_position, ...p }) => ({ ...p, sequence_index: tool_position })) }]);
    assert.match(container.textContent, /Research sequence · chain S/);
    assert.match(container.textContent, /B 42A/);
    assert.equal(container.textContent.includes('private-seq'), false);
    assert.equal(container.textContent.includes('private-reference'), false);
    await React.act(async () => container.querySelector('input[type="checkbox"]').click());
    assert.deepEqual(parameters.region, [{ chain: 'B', author_number: 42, insertion_code: '' }]);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});

test('viewer shows independent method, all mask values and source sequences without exposing IDs', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  const data = { objects: [{ id: 'private-seq', label: 'Research sequence', sequence: 'WY' }], evaluations: [{ origin: 'independent_sequence_backbone', object_ids: ['private-seq'], reference: { id: 'private-reference', label: 'Arbitrary reference' }, positions, method: 'ProteinMPNN score_only', actual_seed: 17, unit: 'negative log likelihood (natural logarithm)', region: null, samples: [{ score: 1.25, global_score: 2.75, region_nll: 2.5, chains: { B: 'WY' }, residue_nll: { B: [2., 3.] }, design_mask: { B: [1., 0.] }, coordinate_mask: { B: [1., 1.] }, region_mask: { B: [1., 1.] } }] }] };
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'pkg', entry: 'manifest.json' }, host: { readFile: async () => new Blob([JSON.stringify(data)]) } })));
    for (const text of ['1.25', '2.75', '2.5', 'WY', 'Arbitrary reference', 'ProteinMPNN score_only', '42A', 'Coordinate mask', 'Scoring mask', 'Region mask']) assert.ok(container.textContent.includes(text), text);
    assert.equal(container.textContent.includes('private-seq'), false);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});
