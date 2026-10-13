import { expect, test } from '@playwright/test'
import { strFromU8 } from 'fflate'
import { type CandidateReference, type RunProjection } from '../src/protocol/client'
import { buildResultIndex, resolveParentReferences, alignedCoordinate, candidateExportFiles, candidateViewKey, observationKey, scalarObservationChoices, uniqueScalarObservation, type CandidateView, type ResultFacts, type ScoreView } from '../src/result-explorer'
import { resultFilterOutcome } from '../src/result-filter'
import { encodePredicate, type Predicate } from '../src/selection-authoring'

const reference = (id: string, digest = 'a'): CandidateReference => ({ candidate_id: id, data_type_id: 'protein.sequence', content_digest: `sha256:${digest.repeat(64)}` })
const candidate = (id: string, parents: string[] = []): CandidateView => ({ item_index: 0, reference: reference(id), parent_ids: parents, metadata: {}, sequence: 'ACD', has_structure: false, source: { node_id: id, output_port: 'candidates', value_index: 0 }, output: { node_id: id, output_port: 'candidates', port_type: { contract_kind: 'port_type', contract_id: 'candidate.collection' }, content_digest: `sha256:${'b'.repeat(64)}`, result_identity: 'result', value_count: 1, producer_provenance: {} } })
const score = (id: string, value: number, metric: string): ScoreView => ({ subject: reference(id), value, metric: { contract_kind: 'metric', contract_id: metric }, method: { contract_kind: 'method', contract_id: 'method' }, context: { kind: 'intrinsic' }, context_profile: { kind: 'intrinsic' }, residue_axis: null, source_partition: 'partition', source: { node_id: 'scores', output_port: 'scores', value_index: 0 } })
const indexFor = (scores: ScoreView[]) => buildResultIndex({ scores, collections: [], alignments: [], definitions: [], sequences: {} })
const run: RunProjection = { project_id: 'project', run_id: 'run', workflow_commit_id: 'commit', status: 'succeeded', ledger_cursor: 'cursor', scope: { mode: 'full', selected_node_ids: [], execution_node_ids: ['child'], forced_node_ids: [], reused_node_ids: [], out_of_scope_node_ids: [], out_of_scope_selection_ids: [] }, node_dispositions: [], outputs: [], artifact_index: [] }

test('temporary grouped filter and saved expression omit empty display groups consistently', () => {
  const values = [score('a', 0.2, 'quality'), score('b', 0.9, 'quality')]
  const comparison: Predicate = { kind: 'comparison', selectorId: observationKey(values[0]), operator: '>', threshold: 0.5 }
  const predicate: Predicate = { kind: 'group', operator: 'or', children: [comparison, { kind: 'group', operator: 'and', children: [] }] }
  expect(resultFilterOutcome(predicate, reference('a'), indexFor(values).observations)).toBe(false)
  expect(resultFilterOutcome(predicate, reference('b'), indexFor(values).observations)).toBe(true)
  expect(encodePredicate(predicate, [comparison.selectorId])).toEqual([{ selector_index: 0, operator: '>', threshold: 0.5 }])
  const stale = reference('b', 'f')
  expect(resultFilterOutcome(predicate, stale, indexFor(values).observations)).toBe(null)
})

test('grouping changes the display subset and missing observations cannot disappear behind OR', () => {
  const values = [score('a', 0.9, 'quality'), score('a', 0.7, 'cost')]
  const quality: Predicate = { kind: 'comparison', selectorId: observationKey(values[0]), operator: '>', threshold: 0.8 }
  const cost: Predicate = { kind: 'comparison', selectorId: observationKey(values[1]), operator: '<', threshold: 0.3 }
  expect(resultFilterOutcome({ kind: 'group', operator: 'and', children: [quality, cost] }, reference('a'), indexFor(values).observations)).toBe(false)
  expect(resultFilterOutcome({ kind: 'group', operator: 'or', children: [quality, cost] }, reference('a'), indexFor(values).observations)).toBe(true)
  expect(resultFilterOutcome({ kind: 'group', operator: 'or', children: [quality, cost] }, reference('a'), indexFor(values.slice(0, 1)).observations)).toBe(null)
})

test('pairwise scalar choices group exact contexts without treating subject identity as a different metric', () => {
  const values = ['a', 'b'].map((id) => ({ ...score(id, 0.5, 'tm'), context_profile: { kind: 'pairwise', subject_role: 'subject', reference_role: 'reference', pairing_mode: 'fixed_reference', normalization: 'reference-axis' }, context: { kind: 'pairwise', subject: { role: 'subject', candidate: reference(id) }, reference: { role: 'reference', candidate: reference('parent') }, pairing_mode: 'fixed_reference', normalization: 'reference-axis' } }))
  expect(scalarObservationChoices(indexFor(values))).toHaveLength(1)
  expect(scalarObservationChoices(indexFor([...values, { ...values[0], value: 0.8 }]))[0].ambiguous).toBe(true)
})

test('alignment display uses directed row-vector rotation instead of its transpose', () => {
  expect(alignedCoordinate([1, 0, 0], { maps_from_role: 'subject', maps_to_role: 'reference', row_vector_rotation: [[0, 1, 0], [-1, 0, 0], [0, 0, 1]], translation: [3, 4, 5] })).toEqual([3, 5, 5])
})

test('sequence-only ZIP export retains exact parents even when only a child is selected', async () => {
  const parent = candidate('parent')
  const child = candidate('child', ['parent', 'unpublished-parent'])
  const facts: ResultFacts = { collections: [parent, child].map((item) => ({ source: item.source, output: item.output, title: item.reference.candidate_id, total: 1, items: [item] })), scores: [], alignments: [], definitions: [], sequences: {} }
  const index = buildResultIndex(facts)
  const files = candidateExportFiles({ candidates: [child], structures: new Map([[candidateViewKey(child), null]]), index, run }, 'stale')
  expect(Object.keys(files).sort()).toEqual(['candidates.fasta', 'manifest.json', 'scores.csv'])
  expect(strFromU8(files['candidates.fasta'])).toBe('>child\nACD\n')
  const manifest = JSON.parse(strFromU8(files['manifest.json']))
  expect(manifest.current_workflow_relation).toBe('stale')
  expect(manifest.candidates[0].parents[0]).toMatchObject({ status: 'resolved', references: [parent.reference], sources: [{ reference: parent.reference, source: parent.source }] })
  expect(manifest.candidates[0].parents[1]).toMatchObject({ status: 'unresolved', references: [] })
  expect(manifest.without_structure).toEqual([child.reference])
  expect(candidateViewKey(child)).toBe(candidateViewKey({ ...child, sequence: 'ACDE', sequenceSource: { node_id: 'axis', output_port: 'axis', value_index: 0 } }))
})

test('partial parent associations remain incomplete even when one matching data version is loaded', () => {
  const parent = candidate('parent')
  const child = candidate('child', ['parent', 'unknown'])
  const index = buildResultIndex({ collections: [{ source: child.source, output: child.output, title: 'partial', total: 3, items: [parent, child] }], scores: [], alignments: [], sequences: {}, definitions: [] })
  expect(resolveParentReferences(child, index)).toMatchObject([{ status: 'incomplete', references: [parent.reference] }, { status: 'incomplete', references: [] }])
})

test('complete export preserves full Context, residue axis, alignment evidence and Commit definitions without reading profile', () => {
  const child = candidate('child')
  const observation = { ...score('child', 0.5, 'quality'), context: { kind: 'pairwise', subject: { candidate: child.reference, role: 'subject' }, reference: { candidate: reference('parent'), role: 'reference' }, normalization_length: 57, evidence_digest: 'exact-evidence' }, residue_axis: { residue_ids: ['A:1'], values: [0.5] } }
  const alignment = { subject: child.reference, reference: reference('parent'), transform: { maps_from_role: 'subject', maps_to_role: 'reference', row_vector_rotation: [[1, 0, 0], [0, 1, 0], [0, 0, 1]], translation: [0, 0, 0] }, rmsd: 0, coverage: 1, method: { contract_kind: 'method', contract_id: 'alignment-method' }, source: child.source, output: child.output, correspondence: [{ subject: 'A:1', reference: 'B:4' }], segment_map: ['complete'], axis_digests: { subject: 'exact' }, policy: { name: 'original' } }
  const definitions = [{ reference: observation.metric, descriptor: { unit: 'dimensionless', meaning: 'Commit definition' } }]
  const index = buildResultIndex({ collections: [{ source: child.source, output: child.output, title: 'child', total: 1, items: [child] }], scores: [observation], alignments: [alignment], sequences: {}, definitions })
  const files = candidateExportFiles({ candidates: [child], structures: new Map([[candidateViewKey(child), null]]), index, run }, 'current')
  const manifest = JSON.parse(strFromU8(files['manifest.json']))
  expect(manifest.observations[0].context).toEqual(observation.context)
  expect(manifest.observations[0].residue_axis).toEqual(observation.residue_axis)
  expect(manifest.observations[0]).not.toHaveProperty('context_profile')
  expect(manifest.alignments).toEqual([alignment])
  expect(manifest.scientific_definitions).toEqual(definitions)
})


test('nullable scalar groups retain numeric choices and masks remain missing for sorting and filtering', () => {
  const masked = { ...score('a', 0, 'quality'), value: null }
  const numeric = score('b', 2, 'quality')
  const index = indexFor([masked, numeric])
  expect(scalarObservationChoices(index)).toMatchObject([{ score: numeric, ambiguous: false }])
  expect(uniqueScalarObservation([masked])).toBeUndefined()
  expect(uniqueScalarObservation([numeric])).toBe(2)
  expect(uniqueScalarObservation([{ ...numeric, value: 0 }])).toBe(0)
  const ambiguous = indexFor([masked, { ...numeric, subject: masked.subject }])
  expect(scalarObservationChoices(ambiguous)[0].ambiguous).toBe(true)
  expect(uniqueScalarObservation([masked, { ...numeric, subject: masked.subject }])).toBeUndefined()
})
