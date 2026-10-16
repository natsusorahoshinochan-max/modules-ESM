import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SelectionEditor } from '../../modules/selection/ui/SelectionEditor'
import { createSelectionDraft, newObservation, readSelectionDraft, saveSelectionDraft } from '../../modules/selection/ui/selection-authoring'
import { copyWorkflowFragment, pasteWorkflowFragment } from '../src/workflow-fragments'
import { connectWorkflowPorts, deleteWorkflowElements, reconnectWorkflowPorts } from '../src/workflow-connections'
import type { CatalogSnapshot, Workflow } from '../src/protocol/client'

const catalog: CatalogSnapshot = { availability: [], contracts: [
  { reference: { contract_kind: 'binding', contract_id: 'selection.filter.direct' }, descriptor: {} },
  { reference: { contract_kind: 'binding', contract_id: 'source.direct' }, descriptor: {} },
  { reference: { contract_kind: 'node_type', contract_id: 'source' }, descriptor: { title: '输入', inputs: [], outputs: [{ name: 'scores', port_type: { contract_id: 'score.collection' }, multiplicity: 'one' }] } },
  { reference: { contract_kind: 'node_type', contract_id: 'selection.filter' }, descriptor: { title: '条件筛选', inputs: [{ name: 'scores', port_type: { contract_id: 'score.collection' }, multiplicity: 'many' }, { name: 'relations', port_type: { contract_id: 'candidate.relation' }, multiplicity: 'many' }], outputs: [] } },
] }

function workflow(): Workflow {
  return { schema_version: '2.1.0', workflow_id: 'project', nodes: [
    { node_id: 'input', node_type_id: 'source', binding_id: 'source.direct', node_parameters: {}, binding_parameters: {} },
  ], edges: [], observation_selectors: [], selection_objectives: [] }
}

test('a condition owns its evaluation and threshold after saving and reopening', () => {
  const draft = createSelectionDraft('filter', { node_id: 'input', output_port: 'candidates' })
  draft.condition = { kind: 'comparison', selection: { ...newObservation(), scoreInput: 'energy-input', scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'energy', methodId: 'measurement', partition: 'measured' }, operator: '<', threshold: -2 }
  const saved = saveSelectionDraft(workflow(), 'filter', draft)
  assert.deepEqual(saved.nodes[1].node_parameters, { condition: { kind: 'comparison', selection: { score_input: 'energy-input', metric_id: 'energy', method_id: 'measurement', source_partition: 'measured', context: { kind: 'intrinsic' } }, operator: '<', threshold: -2 } })
  assert.deepEqual(saved.observation_selectors, [])
  assert.deepEqual(saved.selection_objectives, [])
  const reopened = readSelectionDraft(JSON.parse(JSON.stringify(saved)), 'filter')
  assert.equal(reopened.condition?.kind, 'comparison')
  if (reopened.condition?.kind !== 'comparison') throw new Error('Expected a comparison')
  assert.equal(reopened.condition.selection.metricId, 'energy')
  assert.deepEqual(reopened.condition.selection.scoreSource, { node_id: 'input', output_port: 'scores' })
  assert.equal(reopened.condition.threshold, -2)
})

test('each nested comparison offers its own actual evaluation context and raw threshold', () => {
  const subject = { candidate_id: 'A', data_type_id: 'protein.structure', content_digest: 'sha256:subject' }
  const reference = { candidate_id: 'Ref-a', data_type_id: 'protein.structure', content_digest: 'sha256:reference' }
  const context = { kind: 'pairwise', subject: { role: 'subject', candidate: subject }, reference: { role: 'reference', candidate: reference }, pairing_mode: 'explicit_relation', normalization: 'reference_length', subject_region: ['A:8', 'A:10'], reference_region: ['B:3', 'B:5'] }
  const profile = { kind: 'pairwise', subject_role: 'subject', reference_role: 'reference', pairing_mode: 'explicit_relation', normalization: 'reference_length' }
  const draft = createSelectionDraft('filter')
  draft.condition = { kind: 'group', operator: 'and', children: [
    { kind: 'comparison', selection: { ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'similarity', methodId: 'alignment', partition: 'regions', context: profile, exactContexts: [{ subject, context, residue_axis: null }] }, operator: '>=', threshold: 0.7 },
    { kind: 'group', operator: 'or', children: [{ kind: 'comparison', selection: { ...newObservation(), metricId: 'energy', methodId: 'measurement', partition: 'measured' }, operator: '<', threshold: -2 }] },
  ] }
  const saved = saveSelectionDraft(workflow(), 'filter', draft)
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saved, nodeId: 'filter', onChange: () => {}, scoreObservations: [{ subject, metric: { contract_kind: 'metric', contract_id: 'similarity' }, method: { contract_kind: 'method', contract_id: 'alignment' }, source_partition: 'regions', context_profile: profile, context, residue_axis: null, value: 0.7, source: { node_id: 'input', output_port: 'scores', value_index: 0 } }] }))
  assert.equal(view.match(/aria-label="阈值（Metric 原单位）"/g)?.length, 2)
  assert.equal(view.match(/aria-label="评价上下文选择方式"/g)?.length, 2)
  assert.match(view, /参考 Ref-a/)
  assert.match(view, /候选区域 A:8、A:10/)
  assert.match(view, /全部所选评价/)
  assert.match(view, /未选择的其他评价/)
  assert.doesNotMatch(view, /比较使用的观察条件|范围外观察值|Utility Transform（输出 0–1）/)
})

test('a copied nested condition keeps its inputs and can be edited independently', () => {
  const draft = createSelectionDraft('filter', { node_id: 'input', output_port: 'candidates' })
  draft.condition = { kind: 'group', operator: 'or', children: [
    { kind: 'comparison', selection: { ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'energy', methodId: 'measurement', partition: 'measured' }, operator: '<', threshold: -2 },
    { kind: 'group', operator: 'and', children: [{ kind: 'comparison', selection: { ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'confidence', methodId: 'prediction', partition: 'predicted' }, operator: '>=', threshold: 80 }] },
  ] }
  const saved = saveSelectionDraft(workflow(), 'filter', draft)
  const fragment = copyWorkflowFragment(saved, new Set(['input', 'filter']))
  let nextId = 0
  const copied = pasteWorkflowFragment(saved, fragment, { x: 0, y: 0 }, () => `copy-${nextId++}`).workflow
  const copyDraft = readSelectionDraft(copied, 'copy-1')
  if (copyDraft.condition?.kind !== 'group') throw new Error('Expected a condition group')
  const first = copyDraft.condition.children[0]
  if (first.kind !== 'comparison') throw new Error('Expected a comparison')
  assert.deepEqual(first.selection.scoreSource, { node_id: 'copy-0', output_port: 'scores' })
  copyDraft.condition.children[0] = { ...first, threshold: -4 }
  const edited = saveSelectionDraft(copied, 'copy-1', copyDraft)
  assert.deepEqual(edited.nodes.find((node) => node.node_id === 'filter')?.node_parameters, saved.nodes[1].node_parameters)
  const reopened = readSelectionDraft(JSON.parse(JSON.stringify(edited)), 'copy-1')
  if (reopened.condition?.kind !== 'group') throw new Error('Expected a condition group')
  assert.equal((reopened.condition.children[0] as { threshold: number }).threshold, -4)
  assert.equal(reopened.condition.children[1].kind, 'group')
})

test('removing or reconnecting a required score source never redirects a saved condition', () => {
  const draft = createSelectionDraft('filter')
  draft.condition = { kind: 'comparison', selection: { ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'energy', methodId: 'measurement', partition: 'measured' }, operator: '<', threshold: -2 }
  const saved = saveSelectionDraft(workflow(), 'filter', draft)
  saved.nodes.push({ ...saved.nodes[0], node_id: 'other' })
  const original = saved.edges[0]
  const reconnected = reconnectWorkflowPorts(saved, catalog, original, { nodeId: 'other', portName: 'scores', direction: 'output' }, { nodeId: 'filter', portName: 'scores', direction: 'input' })
  const removed = deleteWorkflowElements(saved, { nodeIds: new Set(), edges: [original] }).workflow
  const connected = connectWorkflowPorts(removed, catalog, { nodeId: 'other', portName: 'scores', direction: 'output' }, { nodeId: 'filter', portName: 'scores', direction: 'input' })
  for (const changed of [removed, reconnected, connected]) {
    const reopened = readSelectionDraft(changed, 'filter')
    if (reopened.condition?.kind !== 'comparison') throw new Error('Expected a comparison')
    assert.equal(reopened.condition.selection.scoreSource, undefined)
    assert.equal(reopened.condition.selection.metricId, 'energy')
    assert.equal(reopened.condition.selection.scoreInput, original.target_slot)
    const savedAgain = saveSelectionDraft(changed, 'filter', reopened)
    assert.deepEqual(savedAgain.nodes[1].node_parameters, saved.nodes[1].node_parameters)
  }
})

test('unfinished conditions remain editable and removing a comparison removes its input', () => {
  for (const condition of [undefined, { kind: 'group', operator: 'and' }, { kind: 'group', operator: 'and', children: [] }, { kind: 'comparison', selection: {}, operator: '>=' }]) {
    const saved = workflow()
    saved.nodes.push({ node_id: 'filter', node_type_id: 'selection.filter', binding_id: 'selection.filter.direct', node_parameters: condition ? { condition } : {}, binding_parameters: {} })
    saved.edges.push({ source_node_id: 'input', source_port: 'scores', target_node_id: 'filter', target_port: 'scores', target_slot: 'unselected-input' })
    const reopened = readSelectionDraft(saved, 'filter')
    if (reopened.condition?.kind === 'comparison') {
      assert.equal(reopened.condition.selection.scoreSource, undefined)
      assert.equal(reopened.condition.threshold, undefined)
    }
    assert.doesNotThrow(() => renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saveSelectionDraft(saved, 'filter', reopened), nodeId: 'filter', onChange: () => {} })))
  }
  const draft = createSelectionDraft('filter')
  draft.condition = { kind: 'group', operator: 'and', children: [
    { kind: 'comparison', selection: { ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'energy', methodId: 'measurement', partition: 'measured' }, operator: '<', threshold: -2 },
  ] }
  const saved = saveSelectionDraft(workflow(), 'filter', draft)
  const edited = readSelectionDraft(saved, 'filter')
  edited.condition = { kind: 'group', operator: 'and', children: [] }
  const removed = saveSelectionDraft(saved, 'filter', edited)
  assert.deepEqual(removed.nodes[1].node_parameters, { condition: { kind: 'group', operator: 'and', children: [] } })
  assert.deepEqual(removed.edges, [])
})

test('switching to condition filtering discards abandoned evaluation dependencies', () => {
  const saved = workflow()
  saved.nodes.push({ node_id: 'chosen', node_type_id: 'selection.top_k', binding_id: 'selection.top_k.direct',
    node_parameters: { selection: { score_input: 'old-scores', relation_input: 'old-relations' }, direction: 'descending', k: 1 }, binding_parameters: {} })
  saved.edges.push(
    { source_node_id: 'unneeded-score', source_port: 'scores', target_node_id: 'chosen', target_port: 'scores', target_slot: 'old-scores' },
    { source_node_id: 'unneeded-relation', source_port: 'relations', target_node_id: 'chosen', target_port: 'relations', target_slot: 'old-relations' },
  )
  const draft = createSelectionDraft('filter', { node_id: 'input', output_port: 'candidates' })
  draft.condition = { kind: 'comparison', selection: { ...newObservation(), scoreInput: 'chosen-scores', scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'energy', methodId: 'measurement', partition: 'raw' }, operator: '<', threshold: 0 }
  const changed = saveSelectionDraft(saved, 'chosen', draft)
  assert.deepEqual(changed.edges.map((edge) => [edge.source_node_id, edge.target_port]), [['input', 'candidates'], ['input', 'scores']])
})
