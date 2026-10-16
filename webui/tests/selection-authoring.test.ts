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
  { reference: { contract_kind: 'binding', contract_id: 'selection.top_k.direct' }, descriptor: {} },
  { reference: { contract_kind: 'binding', contract_id: 'source.direct' }, descriptor: {} },
  { reference: { contract_kind: 'node_type', contract_id: 'source' }, descriptor: { title: '输入', inputs: [], outputs: [{ name: 'scores', port_type: { contract_id: 'score.collection' }, multiplicity: 'one' }] } },
  { reference: { contract_kind: 'node_type', contract_id: 'selection.top_k' }, descriptor: { title: 'Top-k', inputs: [{ name: 'scores', port_type: { contract_id: 'score.collection' }, multiplicity: 'many' }], outputs: [] } },
] }
function workflow(): Workflow {
  return { schema_version: '2.1.0', workflow_id: 'project', nodes: [
    { node_id: 'input', node_type_id: 'source', binding_id: 'source.direct', node_parameters: {}, binding_parameters: {} },
  ], edges: [], observation_selectors: [], selection_objectives: [] }
}

test('node-owned raw top-k settings reopen and copied nodes can be edited independently', () => {
  const draft = createSelectionDraft('top_k', { node_id: 'input', output_port: 'candidates' })
  draft.direction = 'ascending'
  draft.k = 3
  draft.observations = [{ ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'energy', methodId: 'measurement', partition: 'measured' }]
  const saved = saveSelectionDraft(workflow(), 'rank', draft)
  const reopened = readSelectionDraft(JSON.parse(JSON.stringify(saved)), 'rank')
  assert.equal(reopened.direction, 'ascending')
  assert.equal(reopened.k, 3)
  assert.equal(reopened.observations[0].metricId, 'energy')
  assert.deepEqual(saved.selection_objectives, [])
  assert.deepEqual(saved.observation_selectors, [])
  const fragment = copyWorkflowFragment(saved, new Set(['input', 'rank']))
  let nextId = 0
  const copied = pasteWorkflowFragment(saved, fragment, { x: 0, y: 0 }, () => `copy-${nextId++}`).workflow
  const copyDraft = readSelectionDraft(copied, 'copy-1')
  const edited = saveSelectionDraft(copied, 'copy-1', { ...copyDraft, direction: 'descending', k: 1 })
  assert.equal(readSelectionDraft(edited, 'rank').direction, 'ascending')
  assert.equal(readSelectionDraft(edited, 'rank').k, 3)
  assert.equal(readSelectionDraft(edited, 'copy-1').direction, 'descending')
  assert.equal(readSelectionDraft(edited, 'copy-1').k, 1)
})

test('deleting or reconnecting a score input leaves the saved evaluation unresolved', () => {
  const draft = createSelectionDraft('top_k')
  draft.direction = 'ascending'
  draft.k = 2
  draft.observations = [{ ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'energy', methodId: 'measurement', partition: 'measured' }]
  const saved = saveSelectionDraft(workflow(), 'rank', draft)
  saved.nodes.push({ ...saved.nodes[0], node_id: 'other' })
  const original = saved.edges[0]
  const reconnected = reconnectWorkflowPorts(saved, catalog, original, { nodeId: 'other', portName: 'scores', direction: 'output' }, { nodeId: 'rank', portName: 'scores', direction: 'input' })
  assert.ok(reconnected.edges[0].target_slot)
  assert.notEqual(reconnected.edges[0].target_slot, original.target_slot)
  assert.equal(readSelectionDraft(reconnected, 'rank').observations[0].scoreSource, undefined)
  const removed = deleteWorkflowElements(saved, { nodeIds: new Set(), edges: [original] }).workflow
  const connected = connectWorkflowPorts(removed, catalog, { nodeId: 'other', portName: 'scores', direction: 'output' }, { nodeId: 'rank', portName: 'scores', direction: 'input' })
  assert.ok(connected.edges[0].target_slot)
  assert.notEqual(connected.edges[0].target_slot, original.target_slot)
  assert.equal(readSelectionDraft(connected, 'rank').observations[0].scoreSource, undefined)
})

test('the raw top-k editor offers value direction without requiring a utility transform', () => {
  const draft = createSelectionDraft('top_k')
  draft.direction = 'ascending'
  draft.observations = [{ ...newObservation(), metricId: 'energy', methodId: 'measurement', partition: 'measured' }]
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saveSelectionDraft(workflow(), 'rank', draft), nodeId: 'rank', onChange: () => {} }))
  assert.match(view, /aria-label="原值排序方向"/)
  assert.match(view, /同分保持输入顺序/)
  assert.doesNotMatch(view, /Utility Transform（输出 0–1）/)
  assert.doesNotMatch(view, /aria-label="范围外观察值"/)
})

test('saved-result evaluations can be selected by their actual reference and context', () => {
  const subject = { candidate_id: 'A', data_type_id: 'protein.structure', content_digest: 'sha256:subject' }
  const reference = { candidate_id: 'Ref-a', data_type_id: 'protein.structure', content_digest: 'sha256:reference' }
  const context = { kind: 'pairwise', subject: { role: 'subject', candidate: subject }, reference: { role: 'reference', candidate: reference }, pairing_mode: 'explicit_relation', normalization: 'reference_length', sequence_correspondence: [[1, 'A:8'], [2, 'A:10']] }
  const profile = { kind: 'pairwise', subject_role: 'subject', reference_role: 'reference', pairing_mode: 'explicit_relation', normalization: 'reference_length' }
  const draft = createSelectionDraft('top_k')
  draft.observations = [{ ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'similarity', methodId: 'alignment', partition: 'regions', context: profile, exactContexts: [{ subject, context, residue_axis: null }] }]
  const saved = saveSelectionDraft(workflow(), 'rank', draft)
  const reopened = readSelectionDraft(JSON.parse(JSON.stringify(saved)), 'rank')
  assert.deepEqual(reopened.observations[0].exactContexts, [{ subject, context, residue_axis: null }])
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saved, nodeId: 'rank', onChange: () => {}, scoreObservations: [{ subject, metric: { contract_kind: 'metric', contract_id: 'similarity' }, method: { contract_kind: 'method', contract_id: 'alignment' }, source_partition: 'regions', context_profile: profile, context, residue_axis: null, value: 0.7, source: { node_id: 'input', output_port: 'scores', value_index: 0 } }] }))
  assert.match(view, /aria-label="评价上下文选择方式"/)
  assert.match(view, /aria-label="候选 A 的评价上下文"/)
  assert.match(view, /参考 Ref-a/)
  assert.match(view, /A:8/)
})

test('an unfinished saved evaluation reopens for editing without choosing a connected score source', () => {
  const saved = workflow()
  saved.nodes.push({ node_id: 'rank', node_type_id: 'selection.top_k', binding_id: 'selection.top_k.direct', node_parameters: { selection: {} }, binding_parameters: {} })
  saved.edges.push({ source_node_id: 'input', source_port: 'scores', target_node_id: 'rank', target_port: 'scores', target_slot: 'other-score' })
  const reopened = readSelectionDraft(saved, 'rank')
  assert.equal(reopened.observations[0].scoreSource, undefined)
  assert.doesNotThrow(() => renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saved, nodeId: 'rank', onChange: () => {} })))
})

test('choosing an already connected source gives it one stable input association', () => {
  const saved = workflow()
  saved.nodes.push({ node_id: 'rank', node_type_id: 'selection.top_k', binding_id: 'selection.top_k.direct', node_parameters: {}, binding_parameters: {} })
  saved.edges.push({ source_node_id: 'input', source_port: 'scores', target_node_id: 'rank', target_port: 'scores' })
  const draft = readSelectionDraft(saved, 'rank')
  draft.observations = [{ ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'energy', methodId: 'measurement', partition: 'measured' }]
  const edited = saveSelectionDraft(saved, 'rank', draft)
  assert.equal(edited.edges.length, 1)
  assert.ok(edited.edges[0].target_slot)
  assert.deepEqual(readSelectionDraft(edited, 'rank').observations[0].scoreSource, { node_id: 'input', output_port: 'scores' })
})

test('same-length pairwise regions have readable labels from the exact recorded alignment', () => {
  const subject = { candidate_id: 'A', data_type_id: 'protein.structure', content_digest: 'sha256:subject' }
  const reference = { candidate_id: 'Ref-a', data_type_id: 'protein.structure', content_digest: 'sha256:reference' }
  const profile = { kind: 'pairwise', subject_role: 'subject', reference_role: 'reference', pairing_mode: 'explicit_relation', normalization: 'reference-axis-residue-count' }
  const context = { kind: 'pairwise', subject: { role: 'subject', candidate: subject }, reference: { role: 'reference', candidate: reference }, pairing_mode: 'explicit_relation', normalization: 'reference-axis-residue-count', aligned_atom_count: 2 }
  const first = { ...context, evidence_content_digest: 'sha256:region-one', subject_region: ['A:1', 'A:3'], reference_region: ['B:5', 'B:7'] }
  const second = { ...context, evidence_content_digest: 'sha256:region-two', subject_region: ['A:8', 'A:10'], reference_region: ['B:12', 'B:14'] }
  const draft = createSelectionDraft('top_k')
  draft.observations = [{ ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'similarity', methodId: 'alignment', partition: 'regions', context: profile, exactContexts: [{ subject, context: first, residue_axis: { layout: { residue_ids: ['A:1', 'A:3'] } } }] }]
  const score = { subject, metric: { contract_kind: 'metric', contract_id: 'similarity' }, method: { contract_kind: 'method', contract_id: 'alignment' }, source_partition: 'regions', context_profile: profile, value: 0.7, source: { node_id: 'input', output_port: 'scores', value_index: 0 } }
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saveSelectionDraft(workflow(), 'rank', draft), nodeId: 'rank', onChange: () => {}, scoreObservations: [{ ...score, context: first, residue_axis: { layout: { residue_ids: ['A:1', 'A:3'] } } }, { ...score, context: second, residue_axis: null }] }))
  assert.match(view, /候选区域 A:1、A:3/)
  assert.match(view, /参考区域 B:12、B:14/)
  assert.match(view, /残基轴 A:1、A:3/)
})

test('the editor offers many-valued evaluations and relations only to compatible inputs', () => {
  const multiple = { reference: { contract_kind: 'node_type', contract_id: 'batch_source' }, descriptor: { title: '批量评价', inputs: [], outputs: [
    { name: 'scores', port_type: { contract_id: 'score.collection' }, multiplicity: 'many' },
    { name: 'relations', port_type: { contract_id: 'candidate.relation' }, multiplicity: 'many' },
    { name: 'candidates', port_type: { contract_id: 'candidate.collection' }, multiplicity: 'many' },
  ] } }
  const inputs = (multiplicity: string) => [
    { name: 'scores', port_type: { contract_id: 'score.collection' }, multiplicity },
    { name: 'relations', port_type: { contract_id: 'candidate.relation' }, multiplicity },
    { name: 'candidates', port_type: { contract_id: 'candidate.collection' }, multiplicity: 'one' },
  ]
  const draft = createSelectionDraft('top_k')
  draft.observations = [{ ...newObservation(), context: { kind: 'pairwise' }, relationInput: 'pending-relation' }]
  const saved = saveSelectionDraft(workflow(), 'rank', draft)
  saved.nodes.push({ node_id: 'batch', node_type_id: 'batch_source', binding_id: 'batch_source.direct', node_parameters: {}, binding_parameters: {} })
  const render = (multiplicity: string) => renderToStaticMarkup(createElement(SelectionEditor, { catalog: { ...catalog, contracts: [...catalog.contracts.filter((entry) => entry.reference.contract_id !== 'selection.top_k'), multiple, { reference: { contract_kind: 'node_type', contract_id: 'selection.top_k' }, descriptor: { title: 'Top-k', inputs: inputs(multiplicity), outputs: [] } }] }, workflow: saved, nodeId: 'rank', onChange: () => {} }))
  const many = render('many')
  assert.match(many, />批量评价 · batch \/ scores<\/option>/)
  assert.match(many, />批量评价 · batch \/ relations<\/option>/)
  assert.doesNotMatch(many, />批量评价 · batch \/ candidates<\/option>/)
  const one = render('one')
  assert.doesNotMatch(one, />批量评价 · batch \/ scores<\/option>/)
  assert.doesNotMatch(one, />批量评价 · batch \/ relations<\/option>/)
})

test('Pareto stores independent raw directions per evaluation and reopens without global objectives', () => {
  const draft = createSelectionDraft('pareto', { node_id: 'input', output_port: 'candidates' })
  draft.observations = [
    { ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'yield', methodId: 'measurement', partition: 'measured', direction: 'descending' },
    { ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'cost', methodId: 'measurement', partition: 'measured', direction: 'ascending' },
  ]
  const saved = saveSelectionDraft(workflow(), 'frontier', draft)
  const reopened = readSelectionDraft(JSON.parse(JSON.stringify(saved)), 'frontier')
  assert.deepEqual(reopened.observations.map((entry) => [entry.metricId, entry.direction]), [['yield', 'descending'], ['cost', 'ascending']])
  assert.deepEqual(saved.selection_objectives, [])
  assert.deepEqual(saved.observation_selectors, [])
  assert.equal(saved.edges.filter((edge) => edge.target_port === 'scores').length, 1)
  const parameters = saved.nodes.at(-1)!.node_parameters
  assert.equal(JSON.stringify(parameters).includes('weight'), false)
  assert.equal(JSON.stringify(parameters).includes('transform'), false)
})

test('Pareto evaluations sharing one input remain independently editable after reopening', () => {
  const draft = createSelectionDraft('pareto')
  draft.observations = ['yield', 'cost'].map((metricId) => ({ ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId, methodId: 'measurement', partition: 'measured', direction: 'descending' }))
  const saved = saveSelectionDraft(workflow(), 'frontier', draft)
  const reopened = readSelectionDraft(saved, 'frontier')
  const selectedId = reopened.observations[1].id
  reopened.observations = reopened.observations.map((entry) => entry.id === selectedId ? { ...entry, direction: 'ascending' } : entry)
  const edited = readSelectionDraft(saveSelectionDraft(saved, 'frontier', reopened), 'frontier')
  assert.deepEqual(edited.observations.map((entry) => entry.direction), ['descending', 'ascending'])
})

test('the Pareto editor exposes one raw better-value direction and exact context per objective', () => {
  const draft = createSelectionDraft('pareto')
  draft.observations = ['yield', 'cost'].map((metricId) => ({ ...newObservation(), metricId, methodId: 'measurement', partition: 'measured', direction: 'ascending' }))
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saveSelectionDraft(workflow(), 'frontier', draft), nodeId: 'frontier', onChange: () => {} }))
  assert.equal((view.match(/aria-label="指标优劣方向"/g) ?? []).length, 2)
  assert.equal((view.match(/aria-label="评价上下文选择方式"/g) ?? []).length, 2)
  assert.match(view, /较小值更优/)
  assert.match(view, /较大值更优/)
  assert.match(view, /保持输入顺序/)
  assert.doesNotMatch(view, /Utility Transform（输出 0–1）/)
  assert.doesNotMatch(view, /声明权重/)
  assert.doesNotMatch(view, /aria-label="原值排序方向"/)
})

test('switching Pareto to a single raw metric drops discarded score dependencies', () => {
  const input = workflow()
  input.nodes.push({ ...input.nodes[0], node_id: 'cost-input' }, { ...input.nodes[0], node_id: 'unused' })
  const draft = createSelectionDraft('pareto')
  draft.observations = [
    { ...newObservation(), scoreSource: { node_id: 'input', output_port: 'scores' }, metricId: 'yield', methodId: 'measurement', partition: 'measured', direction: 'descending' },
    { ...newObservation(), scoreSource: { node_id: 'cost-input', output_port: 'scores' }, metricId: 'cost', methodId: 'measurement', partition: 'measured', direction: 'ascending' },
  ]
  const saved = saveSelectionDraft(input, 'frontier', draft)
  saved.edges.push({ source_node_id: 'unused', source_port: 'scores', target_node_id: 'frontier', target_port: 'scores', target_slot: 'spare-score' })
  const reopened = readSelectionDraft(saved, 'frontier')
  const sorted = saveSelectionDraft(saved, 'frontier', { ...reopened, operation: 'sort', direction: 'descending' })
  assert.deepEqual(sorted.edges.filter((edge) => edge.target_node_id === 'frontier' && edge.target_port === 'scores').map((edge) => edge.source_node_id), ['input'])
})
