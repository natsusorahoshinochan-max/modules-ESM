import { type CandidateReference, type JsonObject, type PublicV2Client, type PublishedOutput, type ResultCandidate, type ResultLocation, type RunProjection, type RunDiagnostic, type RunEventEnvelope } from './protocol/client'
import { candidateWithSequence, locationKey, publishedFields, referenceKey, type AlignmentView, type ResultIndex, type ScoreView } from './result-explorer'

export type RunReference = Pick<RunProjection, 'project_id' | 'run_id'>
export type ResultSnapshot = {
  readonly connection?: 'connecting' | 'connected' | 'disconnected'
  readonly currentNodeId?: string
  readonly diagnostics: Record<string, RunDiagnostic>
  readonly run?: RunProjection
  readonly index: ResultIndex
  readonly phase: 'idle' | 'loading' | 'ready' | 'error'
  readonly error?: unknown
}
export type CandidateRequest = { source: ResultLocation; count: number | 'all' } | { all: true }

type Collection = { source: ResultLocation; output: PublishedOutput; total?: number; items: ResultCandidate[]; pending?: Promise<void> }
type Session = {
  socket?: WebSocket
  cursor?: string
  connection: ResultSnapshot['connection']
  currentNodeId?: string
  attempts: Record<string, string>
  diagnostics: Record<string, RunDiagnostic>
  reference: RunReference
  run?: RunProjection
  revision: number
  refresh?: Promise<void>
  definitions?: ResultIndex['definitions']
  definitionsPending?: Promise<void>
  collections: Map<string, Collection>
  scores: Map<string, ScoreView[]>
  alignments: Map<string, AlignmentView>
  axes: Map<string, ResultIndex['sequences']>
  loaded: Set<string>
  pending: Map<string, Promise<void>>
}

const emptyIndex = (): ResultIndex => ({ collections: [], scores: [], alignments: [], sequences: {}, definitions: [] })

/** Owns one actual result Run, including every consumer's candidate read progress. */
export class PublishedResults {
  private session?: Session
  private snapshot: ResultSnapshot = { index: emptyIndex(), phase: 'idle', diagnostics: {} }
  private listeners = new Set<() => void>()

  constructor(private readonly client: PublicV2Client) {}

  getSnapshot = (): ResultSnapshot => this.snapshot
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  openRun(reference: RunReference | undefined, eventCursor?: string): void {
    if (reference && this.session?.reference.project_id === reference.project_id && this.session.reference.run_id === reference.run_id) {
      void this.refresh()
      return
    }
    this.session?.socket?.close()
    this.session = reference ? {
      reference, cursor: eventCursor, connection: 'connecting', attempts: {}, diagnostics: {}, revision: 0, collections: new Map(), scores: new Map(), alignments: new Map(), axes: new Map(), loaded: new Set(), pending: new Map(),
    } : undefined
    this.snapshot = { index: emptyIndex(), phase: reference ? 'loading' : 'idle', diagnostics: {} }
    this.notify()
    if (reference) { this.reconnect(); void this.refresh() }
  }

  reconnect(): void {
    const session = this.session
    if (!session) return
    session.socket?.close()
    const { project_id, run_id } = session.reference
    const socket = session.socket = this.client.runEvents(project_id, run_id, session.cursor)
    session.connection = 'connecting'
    let replaying = true
    let terminalSeen = false
    const current = () => this.session === session && session.socket === socket
    socket.onopen = () => { if (current()) { session.connection = 'connected'; this.publish(session) } }
    socket.onclose = socket.onerror = () => { if (current() && !terminalSeen) { session.connection = 'disconnected'; this.publish(session) } }
    socket.onmessage = (message) => {
      if (!current()) return
      const { cursor, event } = JSON.parse(message.data as string) as RunEventEnvelope
      session.cursor = cursor
      if (event.type === 'node_attempt_started') {
        session.attempts[event.node_attempt_id] = event.node_id
        session.currentNodeId = event.node_id
      }
      if (event.type === 'node_attempt_terminal') {
        const nodeId = session.attempts[event.node_attempt_id]
        if (event.error) session.diagnostics = { ...session.diagnostics, [nodeId]: event.error }
        if (session.currentNodeId === nodeId) session.currentNodeId = undefined
      }
      if (event.type === 'node_disposition' && session.currentNodeId === event.disposition.node_id) session.currentNodeId = undefined
      if (event.type === 'run_terminal') { terminalSeen = true; session.currentNodeId = undefined }
      if (event.type === 'replay_complete') replaying = false
      this.publish(session)
      if (!replaying && ['run_started', 'node_disposition', 'replay_complete', 'run_terminal'].includes(event.type)) void this.refresh()
    }
    this.publish(session)
  }

  refresh(): Promise<void> {
    const session = this.session
    if (!session) return Promise.resolve()
    const revision = ++session.revision
    this.publish(session, 'loading')
    const task = (async () => {
      try {
        const run = await this.client.runProjection(session.reference.project_id, session.reference.run_id)
        if (this.session !== session || revision !== session.revision) return
        session.run = run
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

  async ensureCandidates(request: CandidateRequest): Promise<ResultSnapshot | undefined> {
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

  private notify(): void { for (const listener of this.listeners) listener() }

  private publish(session: Session, phase = this.snapshot.phase, error = this.snapshot.error): void {
    if (this.session !== session) return
    const sources = session.run?.outputs.flatMap((output) => Array.from({ length: output.value_count }, (_, value_index) => locationKey({ node_id: output.node_id, output_port: output.output_port, value_index }))) ?? []
    const sequences: ResultIndex['sequences'] = Object.assign({}, ...sources.map((key) => session.axes.get(key)))
    this.snapshot = {
      connection: session.connection, diagnostics: session.diagnostics,
      currentNodeId: session.run && ['admitted', 'running'].includes(session.run.status) && !session.run.node_dispositions.some((item) => item.node_id === session.currentNodeId) ? session.currentNodeId : undefined,
      run: session.run, phase, error: phase === 'error' ? error : undefined,
      index: {
        sequences, definitions: session.definitions ?? [],
        collections: [...session.collections.values()].filter((collection) => collection.total !== undefined).map(({ source, output, total, items }) => ({
          source, output, total: total!, title: `${source.node_id} / ${source.output_port}${output.value_count > 1 ? ` [${source.value_index}]` : ''}`,
          items: items.map((item) => candidateWithSequence({ ...item, source, output }, sequences)),
        })),
        scores: sources.flatMap((key) => session.scores.get(key) ?? []), alignments: sources.flatMap((key) => { const alignment = session.alignments.get(key); return alignment ? [alignment] : [] }),
      },
    }
    this.notify()
  }

  private async readOutputs(session: Session): Promise<void> {
    const run = session.run!
    if (!session.definitions) {
      session.definitionsPending ??= this.client.workflowCommit(run.project_id, run.workflow_commit_id).then((commit) => {
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
    const { project_id, run_id } = session.reference
    const task = this.client.typedValue(project_id, run_id, source.node_id, source.output_port, source.value_index).then((payload) => {
      if (this.session !== session) return
      if (type === 'score.collection') {
        const collection = publishedFields(payload.value) as { entries: Omit<ScoreView, 'source'>[] }
        session.scores.set(key, collection.entries.map((entry) => ({ ...entry, source })))
      } else if (type === 'structure_transform.candidate_resolved_residue_axis_associations') {
        const value = payload.value as { entries: Array<{ subject: CandidateReference; residue_axis: { sequence: string } }> }
        session.axes.set(key, Object.fromEntries(value.entries.map((entry) => [referenceKey(entry.subject), { ...entry, source }])))
      } else {
        session.alignments.set(key, { ...payload.value as Omit<AlignmentView, 'source' | 'output'>, source, output })
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
    const task = this.client.resultCollection(project_id, run_id, collection.source, collection.items.length).then((page) => {
      if (this.session !== session) return
      collection.items.push(...page.items)
      collection.total = page.total
      this.publish(session)
    }).finally(() => { collection.pending = undefined })
    collection.pending = task
    return task
  }
}
