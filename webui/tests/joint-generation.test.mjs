import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import * as React from 'react';
const source = await readFile(new URL('../../modules/joint_generation/ui.js', import.meta.url), 'utf8');
const { register } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
const { createRoot } = await import('react-dom/client');
after(() => dom.window.close());
const extensions = register({ React });

test('joint viewer exposes accepted sequence and pending structure, then real structure and native metrics', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  const pending = { id: 'sequence', sequence: 'AB|CD', positions: [{ sequence_index: 1, edit_position: 'edit-fixed', structure_position: { position: { chain: 'Z', author_number: 42, insertion_code: 'A' } } }], generation: { tracks: { sequence: 'A____' } }, native: { file: 'sequence-values' }, tool: { actual_seed: 0 } };
  const manifest = { batch: { completed: 0, sequence_completed: 1, total: 2, status: 'failed' }, objects: [], pending_sequence: pending };
  const files = { manifest, 'sequence-values': { tracks: { sequence: 'AB|CD' }, metrics: { ptm: .6 } }, 'structure-values': { tracks: { sequence: 'AB|CD', coordinates: [[[1, 2, 3], [null, null, null]]] }, metrics: { plddt: [.3, .4], ptm: .8 } } };
  const read = [];
  const host = { readFile: async (id, key) => { read.push([id, key]); return new Blob([JSON.stringify(files[key])]); } };
  try {
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'partial', entry: 'manifest' }, host })));
    assert.match(container.textContent, /0\/2 completed; failed/);
    assert.match(container.textContent, /sequence accepted; structure pending/);
    assert.match(container.textContent, /AB\|CD/);
    assert.match(container.textContent, /insertion_code/);
    assert.match(container.textContent, /0.6/);
    manifest.objects = [{ ...pending, id: 'complete', native: { file: 'structure-values' }, sequence_stage: pending }];
    manifest.pending_sequence = null;
    manifest.batch = { completed: 1, sequence_completed: 1, total: 2, status: 'failed' };
    await React.act(async () => root.render(React.createElement(extensions.viewers[0].component, { package: { id: 'completed', entry: 'manifest' }, host })));
    assert.match(container.textContent, /1\/2 completed; failed/);
    assert.match(container.textContent, /0.8/);
    assert.equal(container.querySelectorAll('svg circle').length, 1);
    assert.deepEqual(read, [['partial', 'manifest'], ['partial', 'sequence-values'], ['completed', 'manifest'], ['completed', 'structure-values']]);
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});

test('joint controls retain invalid local JSON across unrelated accepted parameter updates', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  const accepted = [], drafts = [];
  let parameters = { samples: 1, conditions: {}, structure_parameters: {} };
  const render = async () => React.act(async () => root.render(React.createElement(extensions.editors[0].component, { parameters, onChange: value => { accepted.push(value); parameters = value; }, onDraftChange: () => drafts.push(true), readOnly: false })));
  try {
    await render();
    const control = container.querySelectorAll('textarea')[1];
    const set = Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, 'value').set;
    await React.act(async () => { set.call(control, '{'); control.dispatchEvent(new dom.window.Event('input', { bubbles: true })); });
    assert.equal(control.checkValidity(), false);
    assert.equal(drafts.length, 1);
    assert.equal(accepted.length, 0);
    parameters = { ...parameters, samples: 2 };
    await render();
    assert.equal(control.value, '{');
    await React.act(async () => { set.call(control, '{"temperature":0.2}'); control.dispatchEvent(new dom.window.Event('input', { bubbles: true })); });
    assert.equal(control.checkValidity(), true);
    assert.deepEqual(accepted[0], { samples: 2, conditions: {}, structure_parameters: { temperature: .2 } });
  } finally { await React.act(async () => root.unmount()); container.remove(); }
});
