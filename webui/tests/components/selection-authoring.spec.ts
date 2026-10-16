import { expect, test } from '@playwright/test'
import type { CatalogSnapshot, JsonObject, Workflow } from '../../src/protocol/client'
import { createSelectionDraft, saveSelectionDraft, type ObservationDraft } from '../../src/selection-authoring'
import { chooseObservation } from '../../src/selection-observations'

function workflow(): Workflow { return { schema_version: '2.1.0', workflow_id: 'work', nodes: [], edges: [], observation_selectors: [], selection_objectives: [] } }
const source = { node_id: 'source', output_port: 'candidates' }
function observation(id: string, scoreNode: string): ObservationDraft { return { id, scoreSource: { node_id: scoreNode, output_port: 'scores' }, metricId: 'quality', methodId: 'measured-quality', partition: 'default', context: { kind: 'intrinsic' }, transformId: 'quality-to-unit', transformParameters: { lower: 0, upper: 1 }, weight: 1 } }

const intrinsic = { kind: 'intrinsic' }
function contract(kind: string, id: string, descriptor: JsonObject): CatalogSnapshot['contracts'][number] {
  return { reference: { contract_kind: kind, contract_id: id }, descriptor }
}
function produced(metric = 'quality', context: JsonObject = intrinsic, extra: JsonObject = {}): JsonObject {
  return {
    output_port: 'scores', output_partition: 'declared-partition', metric: { contract_kind: 'metric', contract_id: metric }, context_profile: context,
    subject_grain: 'candidate', source_role: 'subject', guaranteed_multiplicity: 'one', subject_direction: 'input', subject_port: 'candidates',
    reference_direction: null, reference_port: null, pairing_direction: null, pairing_port: null, method_direction: null, method_port: null, ...extra,
  }
}
function binding(id: string, method: string, observations: JsonObject[] = [], propagation: JsonObject | null = null): CatalogSnapshot['contracts'][number] {
  return contract('binding', id, { method: { contract_kind: 'method', contract_id: method }, produced_observations: observations, observation_propagation: propagation })
}
function scientificCatalog(): CatalogSnapshot {
  return { availability: [], contracts: [
    contract('node_type', 'source', { title: '候选来源', outputs: [{ name: 'candidates', port_type: { contract_kind: 'port_type', contract_id: 'candidate.collection' }, multiplicity: 'one' }] }),
    contract('node_type', 'scorer', { title: '评分', outputs: [{ name: 'scores', port_type: { contract_kind: 'port_type', contract_id: 'score.collection' }, multiplicity: 'one' }] }),
    contract('node_type', 'selection.weighted_rank', { title: '加权排序', outputs: [{ name: 'candidates', port_type: { contract_kind: 'port_type', contract_id: 'candidate.collection' }, multiplicity: 'one' }] }),
    contract('metric', 'quality', { title: '质量', value_shape: 'scalar', unit: 'fraction', direction: 'maximize', description: '声明的质量', canonical_range: { minimum: 0, maximum: 1 }, aggregation_semantics: { kind: 'none' } }),
    contract('metric', 'per-residue-quality', { title: '逐残基质量', value_shape: 'vector' }),
    contract('method', 'scoring-method', { title: '评分方法' }),
    contract('method', 'unrelated-method', { title: '不相关方法' }),
    contract('method', 'fold-one', { title: '折叠方法 1' }),
    contract('method', 'fold-two', { title: '折叠方法 2' }),
    binding('source-binding', 'unrelated-method'),
    binding('scorer-binding', 'scoring-method', [produced()]),
    binding('fold-binding-one', 'fold-one'),
    binding('fold-binding-two', 'fold-two'),
    binding('confidence-binding', 'unrelated-method', [produced('quality', intrinsic, { method_direction: 'input', method_port: 'confidence_facts' })]),
    binding('merge-binding', 'unrelated-method', [], { mode: 'union', input_ports: ['scores'], output_port: 'scores', filter: null }),
  ] }
}
function scoredWorkflow(): Workflow {
  return { ...workflow(), nodes: [
    { node_id: 'source', node_type_id: 'source', binding_id: 'source-binding', node_parameters: {}, binding_parameters: {} },
    { node_id: 'scorer', node_type_id: 'scorer', binding_id: 'scorer-binding', node_parameters: {}, binding_parameters: {} },
  ], edges: [{ source_node_id: 'source', source_port: 'candidates', target_node_id: 'scorer', target_port: 'candidates' }] }
}

test('editor presents complete scientific choices and effective weights without free-form identity controls', async ({ page }) => {
  const catalog = scientificCatalog()
  const original = scoredWorkflow()
  const choice = { key: '', label: '', partition: 'declared-partition', metricId: 'quality', methodId: 'scoring-method', context: intrinsic }
  const updated = saveSelectionDraft(original, 'select', { ...createSelectionDraft('weighted_rank', source), observations: [chooseObservation(observation('a', 'scorer'), choice), chooseObservation({ ...observation('b', 'scorer'), weight: 3 }, choice)] })
  await page.route('**/workflow:observation-options', route => route.fulfill({ json: { options: [{ source: { node_id: 'scorer', output_port: 'scores' }, partition: choice.partition, metric_id: choice.metricId, method_id: choice.methodId, context: choice.context }] } }))
  await page.goto('/tests/support/selection-editor.html')
  await expect(page.locator('html')).toHaveAttribute('data-fixture-ready', 'true')
  await page.evaluate((detail) => window.dispatchEvent(new CustomEvent('render-selection-fixture', { detail })), { workflow: updated, catalog, nodeId: 'select' })
  await expect(page.getByLabel('科学观察', { exact: true })).toHaveCount(2)
  await expect(page.getByText('有效权重：25%', { exact: true })).toBeVisible()
  await expect(page.getByText('有效权重：75%', { exact: true })).toBeVisible()
  await expect(page.getByLabel('分数分区', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Context normalization', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Method', { exact: true })).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('不相关方法')
})

