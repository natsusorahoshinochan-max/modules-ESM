import { expect, test } from '@playwright/test'
import type { Workflow } from '../../src/protocol/client'
import { createSelectionDraft, decodePredicate, encodePredicate, readSelectionDraft, saveSelectionDraft, type ObservationDraft, type Predicate } from '../../src/selection-authoring'
import { effectiveWeightPercentages } from '../../src/selection-observations'

function workflow(): Workflow { return { schema_version: '2.1.0', workflow_id: 'work', nodes: [], edges: [], observation_selectors: [], selection_objectives: [] } }
const source = { node_id: 'source', output_port: 'candidates' }
function observation(id: string, scoreNode: string): ObservationDraft { return { id, scoreSource: { node_id: scoreNode, output_port: 'scores' }, metricId: 'quality', methodId: 'measured-quality', partition: 'default', context: { kind: 'intrinsic' }, transformId: 'quality-to-unit', transformParameters: { lower: 0, upper: 1 }, weight: 1 } }

test('grouped filter save and reload preserve AND/OR, exact scientific scope and source edge de-duplication', () => {
  const predicate: Predicate = { kind: 'group', operator: 'or', children: [
    { kind: 'group', operator: 'and', children: [{ kind: 'comparison', selectorId: 'a', operator: '>', threshold: 0.8 }, { kind: 'comparison', selectorId: 'b', operator: '<=', threshold: 2 }] },
    { kind: 'comparison', selectorId: 'a', operator: '==', threshold: 0.5 },
  ] }
  const original = workflow()
  const updated = saveSelectionDraft(original, 'select', { ...createSelectionDraft('filter', source), observations: [observation('a', 'scorer'), observation('b', 'scorer')], predicate })
  expect(original.nodes).toHaveLength(0)
  expect(updated.edges).toHaveLength(2)
  expect(updated.observation_selectors).toHaveLength(2)
  expect(updated.selection_objectives).toHaveLength(0)
  const reopened = readSelectionDraft(updated, 'select')
  expect(reopened.predicate).toEqual(predicate)
  expect(reopened.observations.map((item) => item.scoreSource)).toEqual([{ node_id: 'scorer', output_port: 'scores' }, { node_id: 'scorer', output_port: 'scores' }])
  expect(updated.observation_selectors[0]).toMatchObject({ candidate_input: source, metric: { contract_kind: 'metric', contract_id: 'quality' }, method: { contract_kind: 'method', contract_id: 'measured-quality' }, context_selector: { kind: 'intrinsic' }, match_cardinality: 'exactly_one', missing_policy: 'error' })
})

test('switching to manual removes former score dependencies and retains complete chosen data references', () => {
  const ranked = saveSelectionDraft(workflow(), 'select', { ...createSelectionDraft('weighted_rank', source), observations: [observation('a', 'score-a'), observation('b', 'score-b')] })
  const selectedCandidates = [{ candidate_id: 'candidate', data_type_id: 'protein.sequence', content_digest: `sha256:${'1'.repeat(64)}` }]
  const manual = saveSelectionDraft(ranked, 'select', { ...createSelectionDraft('manual', source), selectedCandidates })
  expect(manual.selection_objectives).toEqual([])
  expect(manual.observation_selectors).toEqual([])
  expect(manual.edges).toEqual([{ source_node_id: 'source', source_port: 'candidates', target_node_id: 'select', target_port: 'candidates' }])
  expect(manual.nodes[0]).toMatchObject({ node_type_id: 'selection.manual', node_parameters: { selected_candidates: selectedCandidates } })
  expect(readSelectionDraft(manual, 'select').selectedCandidates).toEqual(selectedCandidates)
})

test('one condition has the same meaning with or without a singleton display group', () => {
  const condition: Predicate = { kind: 'comparison', selectorId: 'a', operator: '>=', threshold: 0.4 }
  const expression = encodePredicate({ kind: 'group', operator: 'and', children: [condition] }, ['a'])
  expect(expression).toEqual([{ selector_index: 0, operator: '>=', threshold: 0.4 }])
  expect(decodePredicate(expression, ['a'])).toEqual(condition)
})

test('an unfinished filter reopens as an editable empty group', () => {
  expect(decodePredicate([], [])).toEqual({ kind: 'group', operator: 'and', children: [] })
})

test('declared weights produce effective percentages without silently assigning missing or zero totals', () => {
  expect(effectiveWeightPercentages([observation('a', 'scorer'), observation('b', 'scorer')])).toEqual([50, 50])
  expect(effectiveWeightPercentages([{ ...observation('a', 'scorer'), weight: 3 }, observation('b', 'scorer')])).toEqual([75, 25])
  expect(effectiveWeightPercentages([{ ...observation('a', 'scorer'), weight: 0 }, observation('b', 'scorer')])).toEqual([undefined, undefined])
  expect(effectiveWeightPercentages([{ ...observation('a', 'scorer'), weight: undefined }, observation('b', 'scorer')])).toEqual([undefined, undefined])
  expect(effectiveWeightPercentages([{ ...observation('a', 'scorer'), weight: 0 }])).toEqual([undefined])
})
