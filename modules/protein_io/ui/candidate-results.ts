import { strToU8 } from 'fflate'
import type { ComponentReading, StructuralComponent } from './StructureComponents'
import type { PublishedResults } from '../../../webui/src/published-results'
import { type PublishedStructure, type PublishedResultValue, type PublishedScientificValue, type JsonObject, type PublicV2Client, type PublishedOutput, type ResultCandidate, type ResultCollectionPage, type ResultLocation, type RunProjection } from '../../../webui/src/protocol/client'
import { buildResultIndex, candidateViewKey, locationKey, referenceKey, type CandidateExportMaterial, type AlignmentView, type ResultIndex, type ScoreView } from './result-explorer'
import type { WorkflowCommitSnapshot } from '../../../webui/src/project-workspace'
import { readComputationParameters } from '../../../webui/src/result-parameters'

export type RunReference = Pick<RunProjection, 'project_id' | 'run_id'>
export type CandidateSnapshot = {
  readonly run?: RunProjection
  readonly index: ResultIndex
  readonly phase: 'idle' | 'loading' | 'ready' | 'error'
  readonly error?: unknown
}
export type CandidateRequest = { source: ResultLocation; count: number | 'all' } | { all: true }

type Collection = { source: ResultLocation; output: PublishedOutput; total?: number; items: ResultCandidate[]; pending?: Promise<void> }
type Session = {
  reference: RunReference
  run?: RunProjection
  revision: number
  refresh?: Promise<void>
  definitions?: ResultIndex['definitions']
  commit?: WorkflowCommitSnapshot
  definitionsPending?: Promise<void>
  collections: Map<string, Collection>
  scores: Map<string, ScoreView[]>
  alignments: Map<string, AlignmentView>
  axes: Map<string, ResultIndex['sequences']>
  loaded: Set<string>
  pending: Map<string, Promise<void>>
  values: Map<string, Promise<PublishedResultValue>>
  structures: Map<string, Promise<PublishedStructure>>
}

const emptyIndex = (): ResultIndex => buildResultIndex({ collections: [], scores: [], alignments: [], sequences: {}, definitions: [] }, false)

/** Owns one actual result Run, including every consumer's candidate read progress. */
export class CandidateResults {
  private session?: Session
  private snapshot: CandidateSnapshot = { index: emptyIndex(), phase: 'idle' }
  private listeners = new Set<() => void>()

  constructor(private readonly client: PublicV2Client, private readonly published: PublishedResults) {
    published.subscribe(() => this.sync())
    this.sync()
  }

  private sync(): void {
    const run = this.published.getSnapshot().run
    if (run === this.session?.run) return
    if (!run) {
      this.session = undefined
      this.snapshot = { index: emptyIndex(), phase: 'idle' }
      this.notify()
      return
    }
    if (this.session?.reference.project_id !== run.project_id || this.session?.reference.run_id !== run.run_id) {
      this.session = {
        reference: run, revision: 0,
        collections: new Map(), scores: new Map(), alignments: new Map(), axes: new Map(),
        loaded: new Set(), pending: new Map(), values: new Map(), structures: new Map(),
      }
    }
    this.session.run = run
    void this.refresh()
  }

  getSnapshot = (): CandidateSnapshot => this.snapshot
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  refresh(): Promise<void> {
    const session = this.session
    if (!session) return Promise.resolve()
    const revision = ++session.revision
    this.publish(session, 'loading')
    const task = (async () => {
      try {
        this.publish(session)
        await this.readOutputs(session)
        if (revision === session.revision) this.publish(session, 'ready')
      } catch (error) {
        if (revision === session.revision) this.publish(session, 'error', error)
      }
    })()
    session.refresh = task
    return task
  }

  async ensureCandidates(request: CandidateRequest): Promise<CandidateSnapshot | undefined> {
    const session = this.session
    if (!session) return undefined
    try {
      for (;;) {
        const refresh = session.refresh
        await refresh
        if (this.session !== session) return undefined
        if (refresh !== session.refresh) continue
        if (this.snapshot.phase === 'error') throw this.snapshot.error
        if (!session.run) return undefined
        await this.readOutputs(session)
        const collections = 'all' in request ? [...session.collections.values()] : [session.collections.get(locationKey(request.source))!]
        await Promise.all(collections.map(async (collection) => {
          const count = 'all' in request ? 'all' : request.count
          while (this.session === session && collection.items.length < (count === 'all' ? collection.total! : Math.min(count, collection.total!))) {
            await this.readPage(session, collection)
          }
        }))
        if (this.session !== session) return undefined
        if (refresh !== session.refresh) continue
        this.publish(session, 'ready')
        return this.snapshot
      }
    } catch (error) {
      if (this.session !== session) return undefined
      throw error
    }
  }

  /** Apply Selection's read-only view to a complete, immutable collection. */
  async temporaryView(source: ResultLocation, parameters: JsonObject): Promise<number[] | undefined> {
    const session = this.session
    if (!session) return undefined
    // This explicit operation also retries a previously failed initial read.
    await this.refresh()
    if (this.session !== session) return undefined
    const snapshot = await this.ensureCandidates({ source, count: 'all' })
    if (!snapshot?.run || this.session !== session) return undefined
    const scores = snapshot.run.outputs.filter(output => output.port_type.contract_id === 'score.collection').flatMap(output =>
      Array.from({ length: output.value_count }, (_, value_index) => {
        const location = { node_id: output.node_id, output_port: output.output_port, value_index }
        return { ...location, slot: locationKey(location) }
      }))
    try {
      const value = await this.client.resultAction<{ candidate_indices: number[] }>(session.reference.project_id, session.reference.run_id,
        { candidates: [{ ...source, slot: 'collection' }], scores }, 'selection.view', parameters)
      return this.session === session ? value.candidate_indices : undefined
    } catch (error) { if (this.session === session) throw error }
  }

  async structure(key: string, exportFormat?: PublishedStructure['format']): Promise<PublishedStructure | null | undefined> {
    const session = this.session
    if (!session) return undefined
    const candidate = this.snapshot.index.candidates.get(key)!
    if (!candidate.has_structure) return null
    const contentKey = JSON.stringify([locationKey(candidate.source), candidate.item_index, exportFormat ?? null])
    let pending = session.structures.get(contentKey)
    if (!pending) {
      pending = (exportFormat
        ? this.client.resultAction<PublishedStructure>(session.reference.project_id, session.reference.run_id, { candidates: [{ ...candidate.source, slot: 'collection' }] }, 'protein_io.export_structure', { item_index: candidate.item_index, format: exportFormat })
        : this.client.resultAction<PublishedStructure>(session.reference.project_id, session.reference.run_id, { candidates: [{ ...candidate.source, slot: 'collection' }] }, 'protein_io.candidate_structure', { item_index: candidate.item_index }))
        .catch(error => { session.structures.delete(contentKey); throw error })
      session.structures.set(contentKey, pending)
    }
    try {
      const structure = await pending
      return this.session === session ? structure : undefined
    } catch (error) { if (this.session === session) throw error }
  }

  componentSelectionKey(key: string): string {
    return JSON.stringify([this.session?.reference.project_id, this.session?.reference.run_id, key])
  }

  async components(key: string): Promise<ComponentReading | undefined> {
    const session = this.session
    if (!session) return undefined
    const candidate = this.snapshot.index.candidates.get(key)!
    const reading = await this.client.resultAction<ComponentReading>(session.reference.project_id, session.reference.run_id, { candidates: [{ ...candidate.source, slot: 'collection' }] }, 'protein_io.structure_components', { item_index: candidate.item_index })
    return this.session === session ? reading : undefined
  }

  async exportComponents(key: string, components: StructuralComponent[], format: PublishedStructure['format']): Promise<Uint8Array | undefined> {
    const session = this.session
    if (!session) return undefined
    const candidate = this.snapshot.index.candidates.get(key)!
    const indices = components.map(component => component.component_index)
    const value = await this.client.resultAction<PublishedStructure>(session.reference.project_id, session.reference.run_id, { candidates: [{ ...candidate.source, slot: 'collection' }] }, 'protein_io.export_structure_components', { item_index: candidate.item_index, component_indices: indices, format })
    if (this.session !== session) return undefined
    const bundle = await this.published.exportBundle({ [`components.${format === 'pdb' ? 'pdb' : 'cif'}`]: strToU8(value.text) }, { source: candidate.source, candidate: candidate.reference, component_indices: indices, components, format, operation: 'protein_io.export_structure_components' })
    return this.session === session ? bundle : undefined
  }

  async prepareExport(keys: readonly string[], format: PublishedStructure['format']): Promise<CandidateExportMaterial | undefined> {
    const selected = [...keys]
    const session = this.session
    if (!session) return undefined
    const snapshot = await this.ensureCandidates({ all: true })
    if (!snapshot?.run || this.session !== session) return undefined
    const candidates = selected.map(key => snapshot.index.candidates.get(key)!)
    const content = await Promise.all(candidates.map(async candidate => {
      const key = candidateViewKey(candidate)
      const original = await this.structure(key)
      return !original || original.format === format ? original : this.structure(key, format)
    }))
    if (this.session !== session) return undefined
    const computationParameters = await readComputationParameters(this.client, snapshot.run, session.commit!)
    if (this.session !== session) return undefined
    return { candidates, structures: new Map(candidates.map((candidate, index) => [candidateViewKey(candidate), content[index]!])), index: snapshot.index, run: snapshot.run, computationParameters }
  }

  private readValue(session: Session, source: ResultLocation): Promise<PublishedResultValue> {
    const key = locationKey(source)
    let pending = session.values.get(key)
    if (!pending) {
      pending = this.client.resultValue(session.reference.project_id, session.reference.run_id, source)
        .catch(error => { session.values.delete(key); throw error })
      session.values.set(key, pending)
    }
    return pending
  }

  private notify(): void { for (const listener of this.listeners) listener() }

  private publish(session: Session, phase = this.snapshot.phase, error = this.snapshot.error): void {
    if (this.session !== session) return
    const sources = session.run?.outputs.flatMap((output) => Array.from({ length: output.value_count }, (_, value_index) => locationKey({ node_id: output.node_id, output_port: output.output_port, value_index }))) ?? []
    const sequences: ResultIndex['sequences'] = Object.assign({}, ...sources.map((key) => session.axes.get(key)))
    const candidateSources = session.run?.outputs.filter(output => output.port_type.contract_id === 'candidate.collection').reduce((count, output) => count + output.value_count, 0)
    const allSourcesKnown = candidateSources !== undefined && candidateSources === session.collections.size && [...session.collections.values()].every(collection => collection.total !== undefined)
    this.snapshot = {
      run: session.run, phase, error: phase === 'error' ? error : undefined,
      index: buildResultIndex({
        sequences, definitions: session.definitions ?? [],
        collections: [...session.collections.values()].filter((collection) => collection.total !== undefined).map(({ source, output, total, items }) => ({
          source, output, total: total!, title: `${source.node_id} / ${source.output_port}${output.value_count > 1 ? ` [${source.value_index}]` : ''}`,
          items: items.map((item) => ({ ...item, source, output })),
        })),
        scores: sources.flatMap((key) => session.scores.get(key) ?? []), alignments: sources.flatMap((key) => { const alignment = session.alignments.get(key); return alignment ? [alignment] : [] }),
      }, allSourcesKnown),
    }
    this.notify()
  }

  private async readOutputs(session: Session): Promise<void> {
    const run = session.run!
    if (!session.definitions) {
      session.definitionsPending ??= this.client.workflowCommit(run.project_id, run.workflow_commit_id).then((commit) => {
        session.commit = commit
        session.definitions = commit.scientific_definitions.map((definition) => ({ reference: { contract_kind: definition.contract_kind as string, contract_id: definition.contract_id as string }, descriptor: definition.descriptor as JsonObject }))
      }).finally(() => { session.definitionsPending = undefined })
      await session.definitionsPending
    }
    if (this.session !== session) return
    await Promise.all(run.outputs.flatMap((output) => Array.from({ length: output.value_count }, (_, value_index) => this.readOutput(session, output, { node_id: output.node_id, output_port: output.output_port, value_index }))))
    this.publish(session)
  }

  private readOutput(session: Session, output: PublishedOutput, source: ResultLocation): Promise<void> {
    const key = locationKey(source)
    const type = output.port_type.contract_id
    if (type === 'candidate.collection') {
      let collection = session.collections.get(key)
      if (!collection) {
        collection = { source, output, items: [] }
        session.collections.set(key, collection)
      }
      return collection.total === undefined ? this.readPage(session, collection) : Promise.resolve()
    }
    if (!['score.collection', 'structure_transform.candidate_resolved_residue_axis_associations', 'structure_comparison.alignment_evidence'].includes(type) || session.loaded.has(key)) return Promise.resolve()
    const existing = session.pending.get(key)
    if (existing) return existing
    const task = this.readValue(session, source).then((reading) => {
      const payload = reading as PublishedScientificValue
      if (this.session !== session) return
      if (payload.kind === 'scores') {
        session.scores.set(key, payload.value.entries.map(entry => ({ ...entry, source })))
      } else if (payload.kind === 'candidate_sequences') {
        session.axes.set(key, Object.fromEntries(payload.value.entries.map(entry => [referenceKey(entry.subject), { sequence: entry.sequence, source }])))
      } else if (payload.kind === 'alignment') {
        session.alignments.set(key, { ...payload.value, value_content_digest: reading.value_content_digest, source, output })
      }
      session.loaded.add(key)
      this.publish(session)
    }).finally(() => { session.pending.delete(key) })
    session.pending.set(key, task)
    return task
  }

  private readPage(session: Session, collection: Collection): Promise<void> {
    if (collection.pending) return collection.pending
    const { project_id, run_id } = session.reference
    const task = this.client.resultAction<ResultCollectionPage>(project_id, run_id, { candidates: [{ ...collection.source, slot: 'collection' }] }, 'protein_io.candidate_page', { offset: collection.items.length, limit: 100 }).then((page) => {
      if (this.session !== session) return
      collection.items.push(...page.items)
      collection.total = page.total
      this.publish(session)
    }).finally(() => { collection.pending = undefined })
    collection.pending = task
    return task
  }
}

const cacheKey = Symbol.for('protein-workbench.protein_io.result-sessions')
const cacheHost = globalThis as unknown as Record<symbol, WeakMap<PublishedResults, CandidateResults>>
const sessions = cacheHost[cacheKey] ??= new WeakMap<PublishedResults, CandidateResults>()
export function candidateResults(published: PublishedResults, client: PublicV2Client): CandidateResults {
  let result = sessions.get(published)
  if (!result) { result = new CandidateResults(client, published); sessions.set(published, result) }
  return result
}
