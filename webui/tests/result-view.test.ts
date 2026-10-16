import assert from 'node:assert/strict'
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import test from 'node:test'
import { CandidateResults } from '../../modules/protein_io/ui/candidate-results'
import { PublishedResults } from '../src/published-results'
import { PublicV2Client, type JsonObject, type PublishedOutput, type ResultLocation } from '../src/protocol/client'
import type { ObservationDraft } from '../../modules/selection/ui/selection-authoring'
import type { ScoreView } from '../../modules/protein_io/ui/result-explorer'

const source = { node_id: 'input', output_port: 'candidates', value_index: 0 }
const scoreSource = { node_id: 'scores', output_port: 'scores', value_index: 0 }
const output = (node_id: string, output_port: string, type: string): PublishedOutput => ({ node_id, output_port, port_type: { contract_kind: 'port_type', contract_id: type }, value_count: 1, content_digest: 'sha256:output', result_identity: 'sha256:result', producer_provenance: {}, materialization: { run_id: 'A', resolution: 'executed' }, value_manifest_reference: 'manifest' })
const candidate = (item_index: number) => ({ item_index, reference: { candidate_id: `candidate-${item_index}`, data_type_id: 'protein.sequence', content_digest: `sha256:${item_index}` }, parent_ids: [], metadata: {}, sequence: 'AAA', has_structure: false })
const reply = (response: ServerResponse, value: unknown, status = 200) => { response.writeHead(status, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(value)) }

type ActionRequest = { inputs: Record<string, Array<ResultLocation & { slot: string }>> } & (
  | { action_id: 'protein_io.candidate_page'; parameters: { offset: number; limit: number } }
  | { action_id: 'selection.view'; parameters: JsonObject }
)

async function fixture(action: (runId: string, body: ActionRequest, response: ServerResponse) => void) {
  const requests: Array<{ runId: string; body: ActionRequest }> = []
  const server = createServer(async (request: IncomingMessage, response: ServerResponse) => {
    const path = request.url!
    const runId = path.match(/\/runs\/([^/:]+)/)?.[1] ?? 'A'
    if (path.endsWith('results:action')) {
      let text = ''
      for await (const chunk of request) text += chunk
      const body = JSON.parse(text) as ActionRequest
      requests.push({ runId, body })
      action(runId, body, response)
    } else if (path.endsWith('results:value')) reply(response, { kind: 'scores', value: { entries: [] } })
    else if (path.includes('/commits/')) reply(response, { scientific_definitions: [] })
    else reply(response, { project_id: 'project', run_id: runId, workflow_commit_id: 'commit', status: 'succeeded', outputs: [output('input', 'candidates', 'candidate.collection'), output('scores', 'scores', 'score.collection')] })
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address() as { port: number }
  const client = new PublicV2Client(`http://127.0.0.1:${address.port}`)
  // Events are an external transport; this test exercises immutable HTTP reads.
  const originalSocket = globalThis.WebSocket
  globalThis.WebSocket = class { close() {} } as unknown as typeof WebSocket
  const published = new PublishedResults(client)
  const results = new CandidateResults(client, published)
  async function open(runId: string) {
    published.openRun({ project_id: 'project', run_id: runId })
    await published.refresh()
    await results.refresh()
  }
  return { requests, results, open, async close() { published.openRun(undefined); globalThis.WebSocket = originalSocket; await new Promise<void>(resolve => server.close(() => resolve())) } }
}

test('temporary result viewing stops on an incomplete read and an explicit retry uses the full collection', async () => {
  let failed = false
  const reading = await fixture((_runId, body, response) => {
    if (body.action_id === 'selection.view') return reply(response, { candidate_indices: [150, 0] })
    const offset = body.parameters.offset
    if (offset === 100 && !failed) { failed = true; return reply(response, { message: 'page unavailable' }, 503) }
    reply(response, { total: 151, items: Array.from({ length: offset === 0 ? 100 : 51 }, (_, index) => candidate(offset + index)) })
  })
  try {
    await reading.open('A')
    await assert.rejects(reading.results.temporaryView(source, {}), { message: 'page unavailable' })
    assert.equal(reading.requests.some(({ body }) => body.action_id === 'selection.view'), false)
    assert.deepEqual(await reading.results.temporaryView(source, {}), [150, 0])
    assert.equal(reading.results.getSnapshot().index.collections[0].items.length, 151)
    const request = reading.requests.find(({ body }) => body.action_id === 'selection.view')!.body
    assert.deepEqual(request.inputs, { candidates: [{ ...source, slot: 'collection' }], scores: [{ ...scoreSource, slot: JSON.stringify(['scores', 'scores', 0]) }] })
  } finally { await reading.close() }
})

test('late temporary-view results cannot be applied after A → B → A', async () => {
  let finish: (() => void) | undefined
  let started: (() => void) | undefined
  const actionStarted = new Promise<void>(resolve => { started = resolve })
  const reading = await fixture((_runId, body, response) => {
    if (body.action_id === 'selection.view') { finish = () => reply(response, { candidate_indices: [0] }); started!(); return }
    reply(response, { total: 1, items: [candidate(0)] })
  })
  try {
    await reading.open('A')
    const pending = reading.results.temporaryView(source, {})
    await actionStarted
    await reading.open('B')
    await reading.open('A')
    finish!()
    assert.equal(await pending, undefined)
    assert.equal(reading.results.getSnapshot().run?.run_id, 'A')
  } finally { await reading.close() }
})

test('a failed temporary-view action rejects and an explicit retry can apply', async () => {
  let failed = false
  const reading = await fixture((_runId, body, response) => {
    if (body.action_id === 'selection.view') {
      if (!failed) { failed = true; return reply(response, { message: 'required score missing' }, 422) }
      return reply(response, { candidate_indices: [0] })
    }
    reply(response, { total: 1, items: [candidate(0)] })
  })
  try {
    await reading.open('A')
    await assert.rejects(reading.results.temporaryView(source, {}), { message: 'required score missing' })
    assert.deepEqual(await reading.results.temporaryView(source, {}), [0])
  } finally { await reading.close() }
})

test('the result panel lets users choose actual reference regions when a score group is ambiguous', async () => {
  const { createElement } = await import('react')
  const { renderToStaticMarkup } = await import('react-dom/server')
  const { ResultFilter } = await import('../../modules/protein_io/ui/ResultFilter')
  const subject = candidate(0).reference
  const reference = { candidate_id: 'reference-B', data_type_id: 'protein.structure', content_digest: 'sha256:reference' }
  const profile = { kind: 'pairwise', subject_role: 'subject', reference_role: 'reference', pairing_mode: 'explicit_relation', normalization: 'reference_length' }
  const context = { kind: 'pairwise', subject: { role: 'subject', candidate: subject }, reference: { role: 'reference', candidate: reference }, pairing_mode: 'explicit_relation', normalization: 'reference_length', subject_region: ['A:8', 'A:10'], reference_region: ['B:3'] }
  const score: ScoreView = { subject, metric: { contract_kind: 'metric', contract_id: 'similarity' }, method: { contract_kind: 'method', contract_id: 'alignment' }, source_partition: 'regions', context_profile: profile, context, residue_axis: null, value: 0.7, source: scoreSource }
  const selected: ObservationDraft = { id: 'test', scoreInput: JSON.stringify(['scores', 'scores', 0]), scoreSource, metricId: 'similarity', methodId: 'alignment', partition: 'regions', context: profile, transformId: '', transformParameters: {}, exactContexts: [{ subject, context, residue_axis: null }] }
  const view = renderToStaticMarkup(createElement(ResultFilter, { value: { kind: 'comparison', selectorId: 'similarity', selection: selected, operator: '>=', threshold: 0.5 }, choices: [{ key: 'similarity', score, label: 'Similarity', ambiguous: true }], observations: [score, { ...score, context: { ...context, subject_region: ['A:12'] } }], candidates: [subject], catalog: { contracts: [], availability: [] }, onChange: () => {} }))
  assert.match(view, /逐候选选择已有结果的确切上下文/)
  assert.match(view, /参考 reference-B/)
  assert.match(view, /候选区域 A:8、A:10/)
  assert.doesNotMatch(view, /使用明确的候选关系输入/)
  assert.doesNotMatch(view, /个候选缺少唯一匹配观察值或条件未填写，当前未显示/)
})
