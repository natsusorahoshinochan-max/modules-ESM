import { strToU8, zipSync } from 'fflate'
import { PublicV2Client, type CandidateReference, type CatalogSnapshot, type JsonObject, type PublishedOutput, type ResultCandidate, type ResultCandidateDetail, type ResultLocation, type RunProjection } from './protocol/client'

export type CandidateView = ResultCandidate & { source: ResultLocation; output: PublishedOutput; sequenceSource?: ResultLocation }
export type ScoreView = { subject: CandidateReference; metric: { contract_id: string }; method: { contract_id: string }; context: JsonObject; value: unknown; residue_axis: unknown; source_partition: string; source: ResultLocation }
export type ResultCollection = { source: ResultLocation; output: PublishedOutput; title: string; total: number; items: CandidateView[] }
export type AlignmentView = {
  subject: CandidateReference
  reference: CandidateReference
  transform: { maps_from_role: string; maps_to_role: string; row_vector_rotation: number[][]; translation: number[] }
  rmsd: number
  coverage: number
  method: { contract_id: string }
  source: ResultLocation
  output: PublishedOutput
}
export type ResultIndex = { sequences: Record<string, { residue_axis: { sequence: string }; source: ResultLocation }>; collections: ResultCollection[]; scores: ScoreView[]; alignments: AlignmentView[]; definitions: CatalogSnapshot['contracts'] }

export function referenceKey(reference: CandidateReference) {
  return JSON.stringify([reference.candidate_id, reference.data_type_id, reference.content_digest])
}
export function locationKey(source: ResultLocation) { return JSON.stringify([source.node_id, source.output_port, source.value_index]) }
export function observationContextSelector(context: JsonObject): JsonObject {
  if (context.kind !== 'pairwise') return context
  return { kind: 'pairwise', subject_role: (context.subject as { role: string }).role, reference_role: (context.reference as { role: string }).role, pairing_mode: context.pairing_mode, normalization: context.normalization }
}
export function observationKey(score: ScoreView) { return JSON.stringify([locationKey(score.source), score.source_partition, score.metric.contract_id, score.method.contract_id, observationContextSelector(score.context)]) }

export function scalarObservationChoices(scores: ScoreView[]) {
  const groups = new Map<string, { score: ScoreView; subjects: Set<string>; ambiguous: boolean }>()
  for (const score of scores) {
    if (typeof score.value !== 'number') continue
    const key = observationKey(score)
    const group = groups.get(key) ?? { score, subjects: new Set<string>(), ambiguous: false }
    const subject = referenceKey(score.subject)
    if (group.subjects.has(subject)) group.ambiguous = true
    group.subjects.add(subject)
    groups.set(key, group)
  }
  return [...groups].map(([key, { score, ambiguous }]) => ({ key, score, ambiguous }))
}

export function candidateViewKey(candidate: CandidateView) {
  return JSON.stringify([locationKey(candidate.source), referenceKey(candidate.reference)])
}

export function resolveParentReferences(candidate: CandidateView, collections: ResultCollection[]) {
  const all = collections.flatMap((collection) => collection.items)
  return candidate.parent_ids.map((candidate_id) => {
    const parents = all.filter((parent) => parent.reference.candidate_id === candidate_id)
    const references = [...new Map(parents.map((parent) => [referenceKey(parent.reference), parent.reference])).values()]
    return { candidate_id, status: references.length === 0 ? 'unresolved' : references.length === 1 ? 'resolved' : 'multiple_data_versions', references, sources: parents.map((parent) => ({ reference: parent.reference, source: parent.source, output: parent.output })) }
  })
}

/** The evidence contract maps row-vector subject coordinates into the reference frame. */
export function alignedCoordinate(coordinate: number[], transform: AlignmentView['transform']): number[] {
  return transform.translation.map((translation, axis) => coordinate.reduce((sum, value, index) => sum + value * transform.row_vector_rotation[index][axis], translation))
}

// Built-in Port values use tagged dataclasses; extension codecs publish their
// own plain objects. This removes wire wrappers, without deriving science.
export function publishedFields(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(publishedFields)
  if (value !== null && typeof value === 'object') {
    const object = value as Record<string, unknown>
    const fields = '$dataclass' in object ? object.fields as Record<string, unknown> : object
    return Object.fromEntries(Object.entries(fields).map(([key, item]) => [key, publishedFields(item)]))
  }
  return value
}

export function candidateWithSequence(candidate: CandidateView, sequences: ResultIndex['sequences']): CandidateView {
  const axis = sequences[referenceKey(candidate.reference)]
  return axis ? { ...candidate, sequence: axis.residue_axis.sequence, sequenceSource: axis.source } : candidate
}

const csv = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`

export async function candidateExportFiles(client: PublicV2Client, candidates: CandidateView[], index: ResultIndex, run: RunProjection, catalog: CatalogSnapshot, scienceStatus: 'current' | 'stale' | 'unknown') {
  const details = await Promise.all(candidates.map(async (candidate) => ({ candidate, detail: await client.resultCandidate(run.project_id, run.run_id, candidate.source, candidate.item_index) })))
  const files: Record<string, Uint8Array> = {}
  const selected = new Set(candidates.map((candidate) => referenceKey(candidate.reference)))
  const observations = index.scores.filter((score) => selected.has(referenceKey(score.subject)))
  const manifestItems = details.map(({ candidate, detail }, ordinal) => {
    const basename = `candidate-${String(ordinal + 1).padStart(4, '0')}`
    const structureFile = detail.pdb === null ? null : `structures/${basename}.pdb`
    if (structureFile) files[structureFile] = strToU8(detail.pdb!)
    return { reference: candidate.reference, parent_ids: candidate.parent_ids, parents: resolveParentReferences(candidate, index.collections), metadata: candidate.metadata, source: candidate.source, output: candidate.output, sequence_source: candidate.sequenceSource ?? candidate.source, has_sequence: candidate.sequence !== null, structure_file: structureFile }
  })
  files['candidates.fasta'] = strToU8(candidates.filter((candidate) => candidate.sequence !== null).map((candidate) => `>${candidate.reference.candidate_id}\n${candidate.sequence}`).join('\n') + '\n')
  files['scores.csv'] = strToU8([
    ['candidate_id', 'data_type_id', 'content_digest', 'metric', 'method', 'source_partition', 'context', 'value', 'unit', 'source'].map(csv).join(','),
    ...observations.map((score) => {
      const metric = catalog.contracts.find((contract) => contract.reference.contract_kind === 'metric' && contract.reference.contract_id === score.metric.contract_id)!.descriptor
      return [score.subject.candidate_id, score.subject.data_type_id, score.subject.content_digest, score.metric.contract_id, score.method.contract_id, score.source_partition, JSON.stringify(score.context), JSON.stringify(score.value), metric.unit, JSON.stringify(score.source)].map(csv).join(',')
    }),
  ].join('\n'))
  files['manifest.json'] = strToU8(JSON.stringify({ schema_namespace: 'protein-workbench-webui-export/v2', project_id: run.project_id, run_id: run.run_id, workflow_commit_id: run.workflow_commit_id, run_status: run.status, current_workflow_relation: scienceStatus, candidates: manifestItems, without_structure: manifestItems.filter((item) => item.structure_file === null).map((item) => item.reference), without_sequence_evidence: manifestItems.filter((item) => !item.has_sequence).map((item) => item.reference), observations, alignments: index.alignments.filter((alignment) => selected.has(referenceKey(alignment.subject)) || selected.has(referenceKey(alignment.reference))), scientific_definitions: catalog.contracts.filter((contract) => ['metric', 'method'].includes(contract.reference.contract_kind)) }, null, 2))
  return files
}

export async function exportCandidates(client: PublicV2Client, candidates: CandidateView[], index: ResultIndex, run: RunProjection, catalog: CatalogSnapshot, scienceStatus: 'current' | 'stale' | 'unknown') {
  const files = await candidateExportFiles(client, candidates, index, run, catalog, scienceStatus)
  const bytes = zipSync(files)
  const url = URL.createObjectURL(new Blob([bytes.buffer as ArrayBuffer], { type: 'application/zip' }))
  const link = document.createElement('a')
  link.href = url; link.download = `${run.run_id}-candidates.zip`; link.click()
  URL.revokeObjectURL(url)
}

export async function candidateDetail(client: PublicV2Client, run: RunProjection, candidate: CandidateView): Promise<ResultCandidateDetail> {
  const detail = await client.resultCandidate(run.project_id, run.run_id, candidate.source, candidate.item_index)
  return { ...detail, sequence: candidate.sequence }
}
