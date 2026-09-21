import { expect, test } from '@playwright/test'
import { strFromU8 } from 'fflate'
import { PublishedResults } from '../src/published-results'
import { PublicV2Client, type PublishedOutput, type ResultCandidate, type ResultCollectionPage, type ResultLocation, type RunProjection, type RunEvent } from '../src/protocol/client'
import { candidateExportFiles } from '../src/result-explorer'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const source: ResultLocation = { node_id: 'batch', output_port: 'candidates', value_index: 0 }
const output: PublishedOutput = { ...source, port_type: { contract_kind: 'port_type', contract_id: 'candidate.collection' }, content_digest: `sha256:${'a'.repeat(64)}`, result_identity: 'batch-result', value_count: 1, producer_provenance: {} }
const axisOutput: PublishedOutput = { ...output, node_id: 'axis', output_port: 'associations', port_type: { contract_kind: 'port_type', contract_id: 'structure_transform.candidate_resolved_residue_axis_associations' }, result_identity: 'axis-result' }
function projection(runId = 'A', outputs = [output]): RunProjection {
  return { project_id: 'project', run_id: runId, workflow_commit_id: 'commit', status: 'succeeded', ledger_cursor: '1', scope: { mode: 'full', selected_node_ids: [], execution_node_ids: ['batch'], forced_node_ids: [], reused_node_ids: [], out_of_scope_node_ids: [], out_of_scope_selection_ids: [] }, node_dispositions: [], outputs, artifact_index: [] }
}
function item(index: number): ResultCandidate {
  return { item_index: index, reference: { candidate_id: `candidate-${index}`, data_type_id: 'protein.sequence', content_digest: `sha256:${index.toString(16).padStart(64, '0')}` }, parent_ids: index === 0 ? ['candidate-100'] : [], metadata: {}, sequence: null, has_structure: false }
}
function collectionPage(offset: number, total = 250): ResultCollectionPage {
  return { collection_id: 'collection', item_type: 'protein.sequence', total, offset, items: Array.from({ length: Math.min(100, total - offset) }, (_, index) => item(offset + index)) }
}
class EventSocket {
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((message: { data: string }) => void) | null = null
  closed = false
  close() { this.closed = true }
  event(event: RunEvent, cursor = 'received') { this.onmessage?.({ data: JSON.stringify({ cursor, event }) }) }
}
// Concrete client substitutions return the existing protocol's conforming values.
class ResultsClient extends PublicV2Client {
  offsets: number[] = []
  sockets: EventSocket[] = []
  cursors: Array<string | undefined> = []
  override runEvents(_projectId: string, _runId: string, cursor?: string) {
    const socket = new EventSocket()
    this.sockets.push(socket)
    this.cursors.push(cursor)
    return socket as unknown as WebSocket
  }
  projectionFor = async (runId: string) => projection(runId)
  pageFor = async (offset: number) => collectionPage(offset)
  override runProjection(_projectId: string, runId: string) { return this.projectionFor(runId) }
  override async workflowCommit() {
    return { project_id: 'project', workflow_commit_id: 'commit', source_draft_revision: 1, workflow: { schema_version: '2.1.0', workflow_id: 'workflow', nodes: [], edges: [], observation_selectors: [], selection_objectives: [] }, scientific_definitions: [], scientific_identity: {} }
  }
  override resultCollection(_projectId: string, _runId: string, _source: ResultLocation, offset = 0) {
    this.offsets.push(offset)
    return this.pageFor(offset)
  }
  override async typedValue() { return { port_type_id: axisOutput.port_type.contract_id, value: { entries: [{ subject: item(0).reference, residue_axis: { sequence: 'ACDE' } }] } } }
  override async resultCandidate(_projectId: string, _runId: string, _source: ResultLocation, itemIndex: number) { return { ...item(itemIndex), pdb: null } }
}
async function ready(reader: PublishedResults) {
  if (reader.getSnapshot().phase === 'ready') return
  await new Promise<void>((resolve, reject) => {
    const unsubscribe = reader.subscribe(() => {
      const snapshot = reader.getSnapshot()
      if (snapshot.phase === 'ready' || snapshot.phase === 'error') {
        unsubscribe()
        if (snapshot.phase === 'error') reject(snapshot.error)
        else resolve()
      }
    })
  })
}
async function open(reader: PublishedResults, runId = 'A') {
  reader.openRun({ project_id: 'project', run_id: runId })
  await ready(reader)
}

test('an empty published Run finishes loading', async () => {
  const client = new ResultsClient()
  client.projectionFor = async () => projection('A', [])
  const reader = new PublishedResults(client)
  await open(reader)
  expect(reader.getSnapshot()).toMatchObject({ phase: 'ready', run: { run_id: 'A' }, index: { collections: [] } })
  expect(client.offsets).toEqual([])
})

for (const outcome of ['success', 'failure'] as const) {
  test(`A to B to A retires old Selection paging ${outcome}`, async () => {
    const client = new ResultsClient()
    const reader = new PublishedResults(client)
    await open(reader)
    const held = deferred<ResultCollectionPage>()
    const requested = deferred<void>()
    client.pageFor = offset => { if (offset === 100) { requested.resolve(); return held.promise } return Promise.resolve(collectionPage(offset)) }
    const selection = reader.ensureCandidates({ all: true })
    await requested.promise
    await open(reader, 'B')
    await open(reader, 'A')
    if (outcome === 'success') held.resolve(collectionPage(100))
    else held.reject(new Error('retired page failed'))
    expect(await selection).toBeUndefined()
    expect(reader.getSnapshot().run?.run_id).toBe('A')
    expect(reader.getSnapshot().index.collections[0].items).toHaveLength(100)
    expect(reader.getSnapshot().error).toBeUndefined()
    expect(reader.getSnapshot().phase).toBe('ready')
  })
}

test('concurrent consumers share each page and continue to their requested counts', async () => {
  const client = new ResultsClient()
  const reader = new PublishedResults(client)
  await open(reader)
  const held = deferred<ResultCollectionPage>()
  const requested = deferred<void>()
  client.pageFor = offset => { if (offset === 100) { requested.resolve(); return held.promise } return Promise.resolve(collectionPage(offset)) }
  const partial = reader.ensureCandidates({ source, count: 150 })
  const complete = reader.ensureCandidates({ all: true })
  await requested.promise
  held.resolve(collectionPage(100))
  const [partialSnapshot, completeSnapshot] = await Promise.all([partial, complete])
  expect(partialSnapshot!.index.collections[0].items.length).toBeGreaterThanOrEqual(150)
  expect(completeSnapshot!.index.collections[0].items).toHaveLength(250)
  expect(client.offsets).toEqual([0, 100, 200])
})

test('failed paging retains successful pages and explicit retry resumes at the failed offset', async () => {
  const client = new ResultsClient()
  const reader = new PublishedResults(client)
  await open(reader)
  client.pageFor = async offset => { if (offset === 200) throw new Error('page unavailable'); return collectionPage(offset) }
  await expect(reader.ensureCandidates({ all: true })).rejects.toThrow('page unavailable')
  expect(reader.getSnapshot().index.collections[0].items).toHaveLength(200)
  client.pageFor = async offset => collectionPage(offset)
  const snapshot = await reader.ensureCandidates({ all: true })
  expect(snapshot!.index.collections[0].items).toHaveLength(250)
  expect(client.offsets).toEqual([0, 100, 200, 200])
})

test('latest same-Run refresh wins without discarding loaded pages or rereading immutable outputs', async () => {
  const client = new ResultsClient()
  const reader = new PublishedResults(client)
  await open(reader)
  await reader.ensureCandidates({ source, count: 150 })
  const old = deferred<RunProjection>()
  client.projectionFor = () => old.promise
  const oldRefresh = reader.refresh()
  client.projectionFor = async () => ({ ...projection('A', [output, axisOutput]), ledger_cursor: '3' })
  await reader.refresh()
  old.resolve({ ...projection(), ledger_cursor: '2' })
  await oldRefresh
  expect(reader.getSnapshot().run?.ledger_cursor).toBe('3')
  expect(reader.getSnapshot().index.collections[0].items).toHaveLength(200)
  expect(reader.getSnapshot().index.collections[0].items[0].sequence).toBe('ACDE')
  expect(client.offsets).toEqual([0, 100])
})

test('refresh during paging enriches the returned snapshot and export resolves parents on later pages', async () => {
  const client = new ResultsClient()
  const reader = new PublishedResults(client)
  await open(reader)
  const held = deferred<ResultCollectionPage>()
  const requested = deferred<void>()
  client.pageFor = offset => { if (offset === 100) { requested.resolve(); return held.promise } return Promise.resolve(collectionPage(offset)) }
  const completion = reader.ensureCandidates({ all: true })
  await requested.promise
  client.projectionFor = async () => projection('A', [output, axisOutput])
  await reader.refresh()
  held.resolve(collectionPage(100))
  const snapshot = (await completion)!
  expect(snapshot.index.collections[0].items).toHaveLength(250)
  const candidate = snapshot.index.collections[0].items[0]
  expect(candidate.sequence).toBe('ACDE')
  const files = await candidateExportFiles(client, [candidate], snapshot.index, snapshot.run!, { contracts: snapshot.index.definitions, availability: [] }, 'current')
  expect(strFromU8(files['candidates.fasta'])).toBe('>candidate-0\nACDE\n')
  const manifest = JSON.parse(strFromU8(files['manifest.json']))
  expect(manifest.candidates[0].parents[0]).toMatchObject({ status: 'resolved', references: [item(100).reference] })
  expect(manifest.candidates[0].sequence_source).toEqual({ node_id: 'axis', output_port: 'associations', value_index: 0 })
  expect(client.offsets).toEqual([0, 100, 200])
})

test('an older refresh error cannot replace newer ready state and reopening preserves the page', async () => {
  const client = new ResultsClient()
  const reader = new PublishedResults(client)
  await open(reader)
  const old = deferred<RunProjection>()
  client.projectionFor = () => old.promise
  const oldRefresh = reader.refresh()
  client.projectionFor = async () => ({ ...projection(), ledger_cursor: '4' })
  reader.openRun({ project_id: 'project', run_id: 'A' })
  await ready(reader)
  old.reject(new Error('obsolete projection failed'))
  await oldRefresh
  expect(reader.getSnapshot()).toMatchObject({ phase: 'ready', run: { ledger_cursor: '4' } })
  expect(reader.getSnapshot().error).toBeUndefined()
  expect(client.offsets).toEqual([0])
})

test('complete paging includes a collection published during the operation', async () => {
  const held = deferred<ResultCollectionPage>()
  const requested = deferred<void>()
  const addedOutput = { ...output, node_id: 'later', result_identity: 'later-result' }
  class GrowingClient extends ResultsClient {
    requests: Array<[string, number]> = []
    override resultCollection(_projectId: string, _runId: string, location: ResultLocation, offset = 0) {
      this.requests.push([location.node_id, offset])
      if (location.node_id === 'batch' && offset === 100) { requested.resolve(); return held.promise }
      return Promise.resolve(collectionPage(offset, 150))
    }
  }
  const client = new GrowingClient()
  const reader = new PublishedResults(client)
  await open(reader)
  const completion = reader.ensureCandidates({ all: true })
  await requested.promise
  client.projectionFor = async () => projection('A', [output, addedOutput])
  await reader.refresh()
  held.resolve(collectionPage(100, 150))
  const snapshot = (await completion)!
  expect(snapshot.index.collections.map(entry => [entry.source.node_id, entry.items.length])).toEqual([['batch', 150], ['later', 150]])
  expect(client.requests).toEqual([['batch', 0], ['batch', 100], ['later', 0], ['later', 100]])
})


test('events retain activity and diagnostics while REST alone publishes completion', async () => {
  const client = new ResultsClient()
  const reader = new PublishedResults(client)
  client.projectionFor = async () => ({ ...projection(), status: 'running' })
  reader.openRun({ project_id: 'project', run_id: 'A' }, 'receipt')
  await ready(reader)
  const socket = client.sockets[0]
  socket.onopen?.()
  socket.event({ type: 'replay_complete' })
  await ready(reader)
  const held = deferred<RunProjection>()
  client.projectionFor = () => held.promise
  socket.event({ type: 'node_attempt_started', node_id: 'batch', node_attempt_id: 'attempt' })
  expect(reader.getSnapshot().currentNodeId).toBe('batch')
  const error = { code: 'operation_failed', message: 'located failure', retryable: false, correlation_id: 'operation', details: {} }
  socket.event({ type: 'node_attempt_terminal', node_attempt_id: 'attempt', status: 'failed', error })
  socket.event({ type: 'node_disposition', disposition: { node_id: 'batch', outcome: 'failed', terminal_sequence: 7, blocked_by: [] } })
  socket.event({ type: 'run_terminal', status: 'failed' })
  socket.onclose?.()
  expect(reader.getSnapshot()).toMatchObject({ run: { status: 'running', node_dispositions: [] }, connection: 'connected', diagnostics: { batch: error } })
  expect(reader.getSnapshot().currentNodeId).toBeUndefined()
  held.resolve({ ...projection(), status: 'failed', node_dispositions: [{ node_id: 'batch', outcome: 'failed', terminal_sequence: 7, blocked_by: [] }] })
  await ready(reader)
  expect(reader.getSnapshot().run?.status).toBe('failed')
  expect(client.cursors).toEqual(['receipt'])
})

test('replay refreshes once and received cursor survives reconnect independently of the REST cursor', async () => {
  const client = new ResultsClient()
  let reads = 0
  client.projectionFor = async () => { reads += 1; return { ...projection(), ledger_cursor: '99', node_dispositions: [{ node_id: 'batch', outcome: 'succeeded', terminal_sequence: 9, blocked_by: [], resolution: 'cache_replayed' }] } }
  const reader = new PublishedResults(client)
  await open(reader)
  const socket = client.sockets[0]
  socket.event({ type: 'node_attempt_started', node_id: 'batch', node_attempt_id: 'old-attempt' }, '2')
  expect(reader.getSnapshot().currentNodeId).toBeUndefined()
  socket.event({ type: 'node_disposition', disposition: { node_id: 'batch', outcome: 'succeeded', terminal_sequence: 9, blocked_by: [], resolution: 'cache_replayed' } }, '9')
  socket.event({ type: 'run_terminal', status: 'succeeded' }, '10')
  expect(reads).toBe(1)
  socket.event({ type: 'replay_complete' }, '10')
  await ready(reader)
  expect(reads).toBe(2)
  reader.reconnect()
  expect(client.cursors).toEqual([undefined, '10'])
  expect(socket.closed).toBe(true)
  socket.onerror?.()
  expect(reader.getSnapshot().connection).toBe('connecting')
  client.sockets[1].onerror?.()
  expect(reader.getSnapshot().connection).toBe('disconnected')
})

test('retired HTTP and socket responses cannot update A after A to B to A', async () => {
  const client = new ResultsClient()
  const held = deferred<RunProjection>()
  client.projectionFor = () => held.promise
  const reader = new PublishedResults(client)
  reader.openRun({ project_id: 'project', run_id: 'A' })
  const socket = client.sockets[0]
  client.projectionFor = async runId => projection(runId)
  await open(reader, 'B')
  await open(reader, 'A')
  expect(socket.closed).toBe(true)
  socket.event({ type: 'node_attempt_started', node_id: 'retired', node_attempt_id: 'attempt' })
  socket.event({ type: 'node_attempt_terminal', node_attempt_id: 'attempt', status: 'failed', error: { code: 'old', message: 'retired', retryable: false, correlation_id: 'old', details: {} } })
  held.resolve({ ...projection(), status: 'failed' })
  await held.promise
  expect(reader.getSnapshot()).toMatchObject({ phase: 'ready', run: { status: 'succeeded' }, diagnostics: {} })
  reader.openRun(undefined)
  expect(client.sockets[2].closed).toBe(true)
  expect(reader.getSnapshot()).toMatchObject({ phase: 'idle', diagnostics: {} })
})

test('failed final projection retains published results and can be retried without reopening the stream', async () => {
  const client = new ResultsClient()
  client.projectionFor = async () => ({ ...projection(), status: 'running' })
  const reader = new PublishedResults(client)
  await open(reader)
  const socket = client.sockets[0]
  socket.onopen?.()
  socket.event({ type: 'replay_complete' })
  await ready(reader)
  client.projectionFor = async () => { throw new Error('final read failed') }
  socket.event({ type: 'run_terminal', status: 'succeeded' })
  socket.onclose?.()
  await expect(ready(reader)).rejects.toThrow('final read failed')
  expect(reader.getSnapshot()).toMatchObject({ phase: 'error', connection: 'connected', run: { status: 'running' } })
  expect(reader.getSnapshot().index.collections[0].items).toHaveLength(100)
  client.projectionFor = async () => projection()
  await reader.refresh()
  expect(reader.getSnapshot().run?.status).toBe('succeeded')
  expect(client.sockets).toHaveLength(1)
})
