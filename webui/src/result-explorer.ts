import { strToU8, zipSync } from 'fflate'
import type { ComputationParameters } from './result-parameters'
import type { CandidateReference, CatalogSnapshot, PublishedStructure, PublishedAlignment, PublishedObservation, PublishedOutput, ResultCandidate, ResultLocation, RunProjection } from './protocol/client'

export type CandidateView = ResultCandidate & { source: ResultLocation; output: PublishedOutput; sequenceSource?: ResultLocation }
export type ScoreView = PublishedObservation & { source: ResultLocation }
export type ResultCollection = { source: ResultLocation; output: PublishedOutput; title: string; total: number; items: CandidateView[] }
export type AlignmentView = PublishedAlignment & { source: ResultLocation; output: PublishedOutput }
export type ResultFacts = { sequences: Record<string, { sequence: string; source: ResultLocation }>; collections: ResultCollection[]; scores: ScoreView[]; alignments: AlignmentView[]; definitions: CatalogSnapshot['contracts'] }
export type ObservationGroup = { score: ScoreView; subjects: Map<string, ScoreView[]> }
export type ResultIndex = ResultFacts & {
  complete: boolean
  candidates: Map<string, CandidateView>
  references: Map<string, CandidateView[]>
  parentCandidates: Map<string, CandidateView[]>
  observations: Map<string, ObservationGroup>
  subjectScores: Map<string, ScoreView[]>
  subjectAlignments: Map<string, AlignmentView[]>
}
export type CandidateExportMaterial = { candidates: CandidateView[]; structures: Map<string, PublishedStructure | null>; index: ResultIndex; run: RunProjection; computationParameters: ComputationParameters }

export function referenceKey(reference: CandidateReference) {
  return JSON.stringify([reference.candidate_id, reference.data_type_id, reference.content_digest])
}
export function locationKey(source: ResultLocation) { return JSON.stringify([source.node_id, source.output_port, source.value_index]) }
export function observationKey(score: ScoreView) { return JSON.stringify([locationKey(score.source), score.source_partition, score.metric.contract_id, score.method.contract_id, score.context_profile]) }
export function candidateViewKey(candidate: CandidateView) { return JSON.stringify([locationKey(candidate.source), candidate.item_index]) }

/** All scientific associations for one immutable reading snapshot. */
export function buildResultIndex(facts: ResultFacts, allSourcesKnown = true): ResultIndex {
  const candidates = new Map<string, CandidateView>()
  const references = new Map<string, CandidateView[]>()
  const parentCandidates = new Map<string, CandidateView[]>()
  const observations = new Map<string, ObservationGroup>()
  const subjectScores = new Map<string, ScoreView[]>()
  const subjectAlignments = new Map<string, AlignmentView[]>()
  const collections = facts.collections.map(collection => ({ ...collection, items: collection.items.map(candidate => {
    const sequence = facts.sequences[referenceKey(candidate.reference)]
    const item = sequence ? { ...candidate, sequence: sequence.sequence, sequenceSource: sequence.source } : candidate
    candidates.set(candidateViewKey(item), item)
    const key = referenceKey(item.reference)
    references.set(key, [...(references.get(key) ?? []), item])
    parentCandidates.set(item.reference.candidate_id, [...(parentCandidates.get(item.reference.candidate_id) ?? []), item])
    return item
  }) }))
  for (const score of facts.scores) {
    const key = observationKey(score)
    const subject = referenceKey(score.subject)
    const group = observations.get(key) ?? { score, subjects: new Map<string, ScoreView[]>() }
    group.subjects.set(subject, [...(group.subjects.get(subject) ?? []), score])
    observations.set(key, group)
    subjectScores.set(subject, [...(subjectScores.get(subject) ?? []), score])
  }
  for (const alignment of facts.alignments) for (const key of new Set([referenceKey(alignment.subject), referenceKey(alignment.reference)])) {
    subjectAlignments.set(key, [...(subjectAlignments.get(key) ?? []), alignment])
  }
  return { ...facts, collections, complete: allSourcesKnown && collections.every(collection => collection.items.length === collection.total), candidates, references, parentCandidates, observations, subjectScores, subjectAlignments }
}

export function scalarObservationChoices(index: ResultIndex) {
  return [...index.observations].flatMap(([key, group]) => {
    const score = [...group.subjects.values()].flat().find(score => typeof score.value === 'number')
    return score ? [{ key, score, ambiguous: [...group.subjects.values()].some(scores => scores.length !== 1) }] : []
  })
}

export function uniqueScalarObservation(scores: readonly ScoreView[] | undefined): number | undefined {
  return scores?.length === 1 && typeof scores[0].value === 'number' ? scores[0].value : undefined
}

export function resolveParentReferences(candidate: CandidateView, index: ResultIndex) {
  return candidate.parent_ids.map(candidate_id => {
    const parents = index.parentCandidates.get(candidate_id) ?? []
    const references = [...new Map(parents.map(parent => [referenceKey(parent.reference), parent.reference])).values()]
    return { candidate_id, status: !index.complete ? 'incomplete' : references.length === 0 ? 'unresolved' : references.length === 1 ? 'resolved' : 'multiple_data_versions', references, sources: parents.map(parent => ({ reference: parent.reference, source: parent.source, output: parent.output })) }
  })
}

/** The evidence contract maps row-vector subject coordinates into the reference frame. */
export function alignedCoordinate(coordinate: number[], transform: AlignmentView['transform']): number[] {
  return transform.translation.map((translation, axis) => coordinate.reduce((sum, value, index) => sum + value * transform.row_vector_rotation[index][axis], translation))
}

const csv = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`

/** Formatting cannot fetch or combine another snapshot's scientific facts. */
export function candidateExportFiles({ candidates, structures, index, run, computationParameters }: CandidateExportMaterial, scienceStatus: 'current' | 'stale' | 'unknown') {
  const files: Record<string, Uint8Array> = {}
  const selected = new Set(candidates.map(candidate => referenceKey(candidate.reference)))
  const observations = [...selected].flatMap(key => index.subjectScores.get(key) ?? []).map(score => {
    const { context_profile, ...observation } = score
    void context_profile
    return observation
  })
  const alignments = [...new Set([...selected].flatMap(key => index.subjectAlignments.get(key) ?? []))]
  const manifestItems = candidates.map((candidate, ordinal) => {
    const basename = `candidate-${String(ordinal + 1).padStart(4, '0')}`
    const structure = structures.get(candidateViewKey(candidate))!
    const structureFile = structure === null ? null : `structures/${basename}.${structure.format === 'pdb' ? 'pdb' : 'cif'}`
    if (structureFile) files[structureFile] = strToU8(structure!.text)
    return { reference: candidate.reference, parent_ids: candidate.parent_ids, parents: resolveParentReferences(candidate, index), metadata: candidate.metadata, source: candidate.source, output: candidate.output, sequence_source: candidate.sequenceSource ?? candidate.source, has_sequence: candidate.sequence !== null, structure_file: structureFile }
  })
  files['candidates.fasta'] = strToU8(candidates.filter(candidate => candidate.sequence !== null).map(candidate => `>${candidate.reference.candidate_id}\n${candidate.sequence}`).join('\n') + '\n')
  files['scores.csv'] = strToU8([
    ['candidate_id', 'data_type_id', 'content_digest', 'metric', 'method', 'source_partition', 'context', 'value', 'unit', 'source'].map(csv).join(','),
    ...observations.map(score => {
      const metric = index.definitions.find(contract => contract.reference.contract_kind === 'metric' && contract.reference.contract_id === score.metric.contract_id)!.descriptor
      return [score.subject.candidate_id, score.subject.data_type_id, score.subject.content_digest, score.metric.contract_id, score.method.contract_id, score.source_partition, JSON.stringify(score.context), JSON.stringify(score.value), metric.unit, JSON.stringify(score.source)].map(csv).join(',')
    }),
  ].join('\n'))
  files['computation-parameters.json'] = strToU8(JSON.stringify({
    description: 'Saved computation settings. Match manifest candidate, sequence, observation and alignment source locations to outputs, then parameter_record_ids to records. Records identify original producer Runs, including cache replays. Node and Binding parameters are saved Workflow values; admitted_parameters contains the separately saved compiled values, or null when unavailable. No current defaults or Environment Configuration are added. Workflows preserve saved input connections, selectors and objectives; they do not imply every node executed.',
    project_id: run.project_id, run_id: run.run_id, workflow_commit_id: run.workflow_commit_id,
    ...computationParameters,
  }, null, 2))
  files['manifest.json'] = strToU8(JSON.stringify({ schema_namespace: 'protein-workbench-webui-export/v2', project_id: run.project_id, run_id: run.run_id, workflow_commit_id: run.workflow_commit_id, run_status: run.status, current_workflow_relation: scienceStatus, computation_parameters_file: 'computation-parameters.json', candidates: manifestItems, without_structure: manifestItems.filter(item => item.structure_file === null).map(item => item.reference), without_sequence_evidence: manifestItems.filter(item => !item.has_sequence).map(item => item.reference), observations, alignments, scientific_definitions: index.definitions.filter(contract => ['metric', 'method'].includes(contract.reference.contract_kind)) }, null, 2))
  return files
}

export function exportCandidates(material: CandidateExportMaterial, scienceStatus: 'current' | 'stale' | 'unknown') {
  const bytes = zipSync(candidateExportFiles(material, scienceStatus))
  const url = URL.createObjectURL(new Blob([bytes.buffer as ArrayBuffer], { type: 'application/zip' }))
  const link = document.createElement('a')
  link.href = url; link.download = `${material.run.run_id}-candidates.zip`; link.click()
  URL.revokeObjectURL(url)
}
