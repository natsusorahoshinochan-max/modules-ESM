import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SelectionEditor } from '../../modules/selection/ui/SelectionEditor'
import { createSelectionDraft, newObservation, readSelectionDraft, saveSelectionDraft } from '../../modules/selection/ui/selection-authoring'
import type { CatalogSnapshot, Workflow } from '../src/protocol/client'

const transform = (id: string, method = 'trials', context = { kind: 'intrinsic' }) => ({
  reference: { contract_kind: 'utility_transform', contract_id: id }, descriptor: {
    title: '成功试验比例（原始尺度）', meaning: '1 表示本组试验全部成功。',
    applicability: '仅用于相同试验定义的 intrinsic 成功比例。', limitations: ['不同试验设计不能视为已经校准。'],
    compatible_input_contract: { metric: { contract_id: 'success_fraction' }, method: { contract_id: method }, context_profile: context }, parameters: {},
  },
})
const catalog: CatalogSnapshot = { protocol_digest: 'test', catalog_digest: 'test', availability: [], contracts: [
  transform('success.native'), transform('wrong.method', 'other'), transform('wrong.context', 'trials', { kind: 'calibration' }),
] }
const workflow: Workflow = { schema_version: '2.1.0', workflow_id: 'study', nodes: [], edges: [], observation_selectors: [], selection_objectives: [] }

test('the public weighted editor presents module meaning and exact applicable choices after reopen', () => {
  const draft = createSelectionDraft('weighted_rank')
  draft.observations = [{ ...newObservation(), metricId: 'success_fraction', methodId: 'trials', partition: 'measured', transformId: 'success.native', weight: 1 }]
  const saved = saveSelectionDraft(workflow, 'rank', draft)
  const reopened = readSelectionDraft(JSON.parse(JSON.stringify(saved)), 'rank')
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saved, nodeId: 'rank', onChange: () => {} }))
  assert.equal(reopened.observations[0].transformId, 'success.native')
  assert.match(view, /aria-label="加权评分方式"/)
  assert.match(view, /1 表示本组试验全部成功/)
  assert.match(view, /不同试验设计不能视为已经校准/)
  assert.match(view, /仅用于相同试验定义/)
  assert.doesNotMatch(view, /wrong.method|wrong.context/)
  assert.doesNotMatch(view, /Utility Transform（输出 0–1）/)
})

test('weighted choices belong to the node and retain the exact evaluation without endpoint parameters', () => {
  const draft = createSelectionDraft('weighted_rank', { node_id: 'population', output_port: 'candidates' })
  draft.observations = [{ ...newObservation(), scoreSource: { node_id: 'trials', output_port: 'scores' }, metricId: 'success_fraction', methodId: 'trials', partition: 'measured', transformId: 'success.native', weight: 2 }]
  const saved = saveSelectionDraft(workflow, 'rank', draft)
  assert.deepEqual(saved.selection_objectives, [])
  const objective = (saved.nodes[0].node_parameters.objectives as Array<Record<string, unknown>>)[0]
  assert.equal(objective.transform_id, 'success.native')
  assert.equal('transform_parameters' in objective, false)
  const reopened = readSelectionDraft(JSON.parse(JSON.stringify(saved)), 'rank')
  assert.equal(reopened.observations[0].transformId, 'success.native')
  assert.equal(reopened.observations[0].weight, 2)
  assert.deepEqual(reopened.observations[0].scoreSource, { node_id: 'trials', output_port: 'scores' })
})

test('an evaluation without a module scoring choice explains weighted unavailability', () => {
  const draft = createSelectionDraft('weighted_rank')
  draft.observations = [{ ...newObservation(), metricId: 'unconverted', methodId: 'trials', partition: 'measured', transformId: 'removed.choice' }]
  const saved = saveSelectionDraft(workflow, 'rank', draft)
  const reopened = readSelectionDraft(JSON.parse(JSON.stringify(saved)), 'rank')
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saved, nodeId: 'rank', onChange: () => {} }))
  assert.equal(reopened.observations[0].transformId, 'removed.choice')
  assert.match(view, /当前评价没有适用评分方式，加权不可用/)
  assert.match(view, /原值筛选、排序和 Pareto 仍可使用/)
  assert.match(view, /已保存评分方式当前不适用/)
})

test('the editor only offers scoring modes that the module supplies ready to use', () => {
  const draft = createSelectionDraft('weighted_rank')
  draft.observations = [{ ...newObservation(), metricId: 'success_fraction', methodId: 'trials', partition: 'measured' }]
  const incomplete = transform('requires.formula')
  const descriptor = { ...incomplete.descriptor, title: '需要项目用户填写转换端点', parameters: { endpoint: { required: true, value_contract: { type: 'number' } } } }
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog: { ...catalog, contracts: [{ ...incomplete, descriptor }] }, workflow: saveSelectionDraft(workflow, 'rank', draft), nodeId: 'rank', onChange: () => {} }))
  assert.match(view, /当前评价没有适用评分方式，加权不可用/)
  assert.doesNotMatch(view, /需要项目用户填写转换端点/)
})

test('the editor accepts a zero relative weight as an inactive term', () => {
  const draft = createSelectionDraft('weighted_rank')
  draft.observations = [2, 0].map((weight) => ({ ...newObservation(), metricId: 'success_fraction', methodId: 'trials', partition: 'measured', transformId: 'success.native', weight }))
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saveSelectionDraft(workflow, 'rank', draft), nodeId: 'rank', onChange: () => {} }))
  assert.match(view, /aria-label="相对权重（非负）"/)
  assert.match(view, /aria-label="观察条件 2 的有效权重">有效权重：0%/)
})

test('an inactive term does not claim that an otherwise configured weighted choice is unavailable', () => {
  const draft = createSelectionDraft('weighted_rank')
  draft.observations = [
    { ...newObservation(), metricId: 'success_fraction', methodId: 'trials', partition: 'measured', transformId: 'success.native', weight: 1 },
    { ...newObservation(), metricId: 'no_scoring_mode', methodId: 'other', partition: 'unused', weight: 0 },
  ]
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saveSelectionDraft(workflow, 'rank', draft), nodeId: 'rank', onChange: () => {} }))
  assert.match(view, /此项权重为 0，不参与计算，无需评分方式/)
  assert.doesNotMatch(view, /当前评价没有适用评分方式，加权不可用/)
})

test('switching to weighted choices replaces the previous operation score dependencies', () => {
  const raw = createSelectionDraft('sort')
  raw.direction = 'ascending'
  raw.observations = [{ ...newObservation(), scoreSource: { node_id: 'previous', output_port: 'scores' }, metricId: 'energy', methodId: 'old', partition: 'old' }]
  const previous = saveSelectionDraft(workflow, 'rank', raw)
  const weighted = createSelectionDraft('weighted_rank')
  weighted.observations = [{ ...newObservation(), scoreSource: { node_id: 'trials', output_port: 'scores' }, metricId: 'success_fraction', methodId: 'trials', partition: 'measured', transformId: 'success.native', weight: 1 }]
  const changed = saveSelectionDraft(previous, 'rank', weighted)
  assert.deepEqual(changed.edges.map((edge) => edge.source_node_id), ['trials'])
})

test('each weighted evaluation can retain and display its actual reference and regions', () => {
  const subject = { candidate_id: 'subject', data_type_id: 'protein.structure', content_digest: 'sha256:subject' }
  const reference = { candidate_id: 'reference', data_type_id: 'protein.structure', content_digest: 'sha256:reference' }
  const profile = { kind: 'pairwise', subject_role: 'subject', reference_role: 'reference', pairing_mode: 'explicit_relation', normalization: 'reference-axis-residue-count' }
  const context = { kind: 'pairwise', subject: { role: 'subject', candidate: subject }, reference: { role: 'reference', candidate: reference }, pairing_mode: 'explicit_relation', normalization: 'reference-axis-residue-count', subject_region: ['A:2', 'A:5'], reference_region: ['B:8', 'B:11'] }
  const draft = createSelectionDraft('weighted_rank')
  draft.observations = [{ ...newObservation(), scoreSource: { node_id: 'trials', output_port: 'scores' }, metricId: 'similarity', methodId: 'alignment', partition: 'regions', context: profile, exactContexts: [{ subject, context }] }]
  const saved = saveSelectionDraft(workflow, 'rank', draft)
  const reopened = readSelectionDraft(JSON.parse(JSON.stringify(saved)), 'rank')
  assert.deepEqual(reopened.observations[0].exactContexts, [{ subject, context }])
  const view = renderToStaticMarkup(createElement(SelectionEditor, { catalog, workflow: saved, nodeId: 'rank', onChange: () => {}, scoreObservations: [{ subject, metric: { contract_kind: 'metric', contract_id: 'similarity' }, method: { contract_kind: 'method', contract_id: 'alignment' }, source_partition: 'regions', context_profile: profile, context, residue_axis: null, value: 0.7, source: { node_id: 'trials', output_port: 'scores', value_index: 0 } }] }))
  assert.match(view, /aria-label="评价上下文选择方式"/)
  assert.match(view, /候选区域 A:2、A:5/)
  assert.match(view, /参考区域 B:8、B:11/)
})
