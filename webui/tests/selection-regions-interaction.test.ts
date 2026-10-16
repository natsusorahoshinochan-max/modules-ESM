import assert from 'node:assert/strict'
import { createServer, type ServerResponse } from 'node:http'
import test from 'node:test'
import { build } from 'esbuild'
import { chromium } from 'playwright'

test('historical regions remain readable and selecting either exact fact preserves its original node and result payload', { timeout: 30_000 }, async () => {
  const subject = { candidate_id: 'subject', data_type_id: 'protein.structure', content_digest: 'sha256:subject' }
  const reference = { candidate_id: 'reference', data_type_id: 'protein.structure', content_digest: 'sha256:reference' }
  const profile = { kind: 'pairwise', subject_role: 'subject', reference_role: 'reference', pairing_mode: 'explicit_relation', normalization: 'reference-axis-residue-count' }
  const contexts = ['one', 'two'].map(id => ({ kind: 'pairwise', subject: { role: 'subject', candidate: subject }, reference: { role: 'reference', candidate: reference }, pairing_mode: 'explicit_relation', normalization: 'reference-axis-residue-count', evidence_content_digest: `sha256:${id}`, subject_axis_content_digest: 'sha256:subject-axis', reference_axis_content_digest: 'sha256:reference-axis' }))
  const scores = contexts.map((context, index) => ({ subject, context, context_profile: profile, metric: { contract_kind: 'metric', contract_id: 'similarity' }, method: { contract_kind: 'method', contract_id: 'alignment' }, source_partition: 'raw', residue_axis: null, value: index ? 0.9 : 0.1 }))
  const evidence = contexts.map((context, index) => ({ subject, reference, subject_axis_content_digest: context.subject_axis_content_digest, reference_axis_content_digest: context.reference_axis_content_digest, subject_region: [index ? 'A:8' : 'A:1'], reference_region: [index ? 'B:12' : 'B:5'], method: { contract_kind: 'method', contract_id: 'alignment' }, transform: { maps_from_role: 'subject', maps_to_role: 'reference', row_vector_rotation: [[1, 0, 0], [0, 1, 0], [0, 0, 1]], translation: [0, 0, 0] }, rmsd: 0, coverage: 1 }))
  const original = JSON.stringify({ scores, evidence })
  const code = await build({
    stdin: { resolveDir: process.cwd(), loader: 'tsx', contents: `
      import { useState } from 'react'
      import { createRoot } from 'react-dom/client'
      import { register } from '../modules/selection/ui/entry'
      import { ResultObservationEditor } from '../modules/protein_io/ui/ResultFilter'
      import { candidateResults } from '../modules/protein_io/ui/candidate-results'
      import { resultSelection } from '../modules/protein_io/ui/result-filter'
      import { createSelectionDraft, newObservation, saveSelectionDraft } from '../modules/selection/ui/selection-authoring'
      import { PublishedResults } from './src/published-results'
      import { PublicV2Client } from './src/protocol/client'
      const client = new PublicV2Client()
      const published = new PublishedResults(client)
      const reading = candidateResults(published, client)
      published.openRun({ project_id: 'study', run_id: 'run' })
      await published.refresh()
      await reading.refresh()
      const index = reading.getSnapshot().index
      const profile = ${JSON.stringify(profile)}
      const subject = ${JSON.stringify(subject)}
      const selection = { ...newObservation(), scoreInput: 'score-slot', scoreSource: { node_id: 'source', output_port: 'scores' }, metricId: 'similarity', methodId: 'alignment', partition: 'raw', context: profile, exactContexts: [] }
      const workflow = saveSelectionDraft({ schema_version: '2.1.0', workflow_id: 'study', nodes: [{ node_id: 'source', node_type_id: 'source', binding_id: 'source.direct', node_parameters: {}, binding_parameters: {} }], edges: [] }, 'rank', { ...createSelectionDraft('top_k'), observations: [selection], direction: 'ascending', k: 1 })
      const catalog = { availability: [], contracts: [{ reference: { contract_kind: 'node_type', contract_id: 'source' }, descriptor: { title: 'Scores', inputs: [], outputs: [{ name: 'scores', port_type: { contract_kind: 'port_type', contract_id: 'score.collection' }, multiplicity: 'one' }] } }] }
      const NodeEditor = register().SelectionEditor
      function View() {
        const [node, setNode] = useState()
        const [draft, setDraft] = useState({ ...selection, scoreInput: JSON.stringify(['source', 'scores', 0]) })
        const [applied, setApplied] = useState()
        return <><section aria-label="节点"><NodeEditor catalog={catalog} workflow={workflow} nodeId="rank" results={published} client={client} onCancel={() => {}} onApply={async next => setNode(next.nodes.find(node => node.node_id === 'rank').node_parameters.selection)} /><output aria-label="节点参数">{JSON.stringify(node)}</output></section>
          <section aria-label="结果"><ResultObservationEditor value={draft} observations={index.scores} alignments={index.alignments} candidates={[subject]} catalog={catalog} onChange={setDraft} /><button onClick={() => setApplied(resultSelection(draft))}>应用查看</button><output aria-label="查看参数">{JSON.stringify(applied)}</output></section></>
      }
      createRoot(document.getElementById('root')).render(<View />)
    ` },
    bundle: true, format: 'esm', platform: 'browser', jsx: 'automatic', write: false,
    loader: { '.css': 'empty' }, nodePaths: [process.cwd() + '/node_modules'],
  })
  const requests: Array<{ url: string; body: Record<string, unknown> }> = []
  const reply = (response: ServerResponse, body: unknown) => { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(body)) }
  const output = (node_id: string, output_port: string, port_type: string, value_count: number) => ({ node_id, output_port, port_type: { contract_kind: 'port_type', contract_id: port_type }, value_count, content_digest: 'sha256:whole-port', result_identity: 'sha256:result', producer_provenance: {}, materialization: { run_id: 'run', resolution: 'executed' }, value_manifest_reference: 'manifest' })
  const server = createServer(async (request, response) => {
    const url = request.url!
    if (url === '/view.js') { response.writeHead(200, { 'Content-Type': 'text/javascript' }); response.end(code.outputFiles![0].text); return }
    if (!url.startsWith('/api/')) { response.writeHead(200, { 'Content-Type': 'text/html' }); response.end('<div id="root"></div><script type="module" src="/view.js"></script>'); return }
    let text = ''
    for await (const chunk of request) text += chunk
    const body = text ? JSON.parse(text) : {}
    requests.push({ url, body })
    if (url.endsWith('/results:value')) return reply(response, body.node_id === 'source'
      ? { kind: 'scores', value_content_digest: 'sha256:scores', value: { entries: scores } }
      : { kind: 'alignment', value_content_digest: contexts[body.value_index].evidence_content_digest, value: evidence[body.value_index] })
    if (url.includes('/authoring-actions/selection.observation_options')) return reply(response, { options: [] })
    if (url.includes('/commits/')) return reply(response, { scientific_definitions: [] })
    if (url.endsWith('/runs/run')) return reply(response, { project_id: 'study', run_id: 'run', workflow_commit_id: 'commit', status: 'succeeded', node_dispositions: [], artifact_index: [], outputs: [output('source', 'scores', 'score.collection', 1), output('alignment', 'evidence', 'structure_comparison.alignment_evidence', 2)] })
    response.writeHead(404); response.end(url)
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage()
    await page.goto(`http://127.0.0.1:${(server.address() as { port: number }).port}`)
    for (const region of ['节点', '结果']) {
      const panel = page.getByRole('region', { name: region, exact: true })
      const select = panel.getByLabel('候选 subject 的评价上下文')
      await select.waitFor()
      const options = await select.locator('option').allTextContents()
      assert.ok(options.some(text => text.includes('候选区域 A:1') && text.includes('参考区域 B:5')))
      assert.ok(options.some(text => text.includes('候选区域 A:8') && text.includes('参考区域 B:12')))
      for (const index of [0, 1]) {
        await select.selectOption({ label: options.find(text => text.includes(index ? '候选区域 A:8' : '候选区域 A:1'))! })
        await panel.getByRole('button', { name: region === '节点' ? '应用到流程' : '应用查看', exact: true }).click()
        const parameters = JSON.parse((await page.getByLabel(region === '节点' ? '节点参数' : '查看参数').textContent())!)
        assert.deepEqual(parameters.exact_contexts, [{ subject, context: contexts[index], residue_axis: null }])
        assert.equal(Object.hasOwn(parameters.exact_contexts[0].context, 'subject_region'), false)
      }
    }
    assert.equal(JSON.stringify({ scores, evidence }), original)
    const action = requests.find(request => request.url.includes('/authoring-actions/selection.observation_options'))!
    assert.deepEqual(Object.keys((action.body.parameters as { workflow: object }).workflow).sort(), ['edges', 'nodes'])
    assert.equal(requests.some(request => request.url.includes('workflow:observation-options')), false)
    assert.equal(requests.some(request => request.url.includes('/results:action') || request.url.endsWith('/workspace')), false)
  } finally {
    await browser.close()
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
})
