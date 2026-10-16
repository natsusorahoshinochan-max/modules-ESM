import { type CanonicalTypedValue, type PublishedResultValue, type PublicV2Client, type ResultLocation, type RunProjection, type RunDiagnostic, type RunEventEnvelope } from './protocol/client'
const locationKey = (source: ResultLocation) => JSON.stringify([source.node_id, source.output_port, source.value_index])

export type RunReference = Pick<RunProjection, 'project_id' | 'run_id'>
export type ResultSnapshot = {
  readonly connection?: 'connecting' | 'connected' | 'disconnected'
  readonly currentNodeId?: string
  readonly diagnostics: Record<string, RunDiagnostic>
  readonly run?: RunProjection
  readonly phase: 'idle' | 'loading' | 'ready' | 'error'
  readonly error?: unknown
}
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
  values: Map<string, Promise<PublishedResultValue>>
  rawValues: Map<string, Promise<CanonicalTypedValue>>
}

/** Owns one actual result Run, including immutable reads shared by module viewers. */
export class PublishedResults {
  private session?: Session
  private snapshot: ResultSnapshot = { phase: 'idle', diagnostics: {} }
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
      reference, cursor: eventCursor, connection: 'connecting', attempts: {}, diagnostics: {}, revision: 0, values: new Map(), rawValues: new Map(),
    } : undefined
    this.snapshot = { phase: reference ? 'loading' : 'idle', diagnostics: {} }
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
        if (revision === session.revision) this.publish(session, 'ready')
      } catch (error) {
        if (revision === session.revision) this.publish(session, 'error', error)
      }
    })()
    session.refresh = task
    return task
  }

  value(source: ResultLocation): Promise<PublishedResultValue | undefined> {
    return this.session ? this.sessionValue(this.session, source) : Promise.resolve(undefined)
  }

  /** A long authoring read keeps the Run it compared, even before its HTTP read starts. */
  captureReading() {
    const session = this.session
    if (!session?.run) return undefined
    return { run: session.run, value: (source: ResultLocation) => this.sessionValue(session, source) }
  }

  private async sessionValue(session: Session, source: ResultLocation): Promise<PublishedResultValue | undefined> {
    if (this.session !== session) return undefined
    try {
      const value = await this.readValue(session, source)
      return this.session === session ? value : undefined
    } catch (error) { if (this.session === session) throw error }
  }

  async rawValue(source: ResultLocation): Promise<CanonicalTypedValue | undefined> {
    const session = this.session
    if (!session) return undefined
    const key = locationKey(source)
    let pending = session.rawValues.get(key)
    if (!pending) {
      const { project_id, run_id } = session.reference
      pending = this.client.typedValue(project_id, run_id, source.node_id, source.output_port, source.value_index)
        .catch(error => { session.rawValues.delete(key); throw error })
      session.rawValues.set(key, pending)
    }
    try {
      const value = await pending
      return this.session === session ? value : undefined
    } catch (error) { if (this.session === session) throw error }
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
    this.snapshot = {
      connection: session.connection, diagnostics: session.diagnostics,
      currentNodeId: session.run && ['admitted', 'running'].includes(session.run.status) && !session.run.node_dispositions.some((item) => item.node_id === session.currentNodeId) ? session.currentNodeId : undefined,
      run: session.run, phase, error: phase === 'error' ? error : undefined,
    }
    this.notify()
  }

}
