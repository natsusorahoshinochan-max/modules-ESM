import { expect, test } from '@playwright/test'
import { strFromU8, unzipSync } from 'fflate'
const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5304'
const ensemble = 'HEADER    HISTORICAL EXPORT\nMODEL        1\nATOM      1  CA  ALA A  12A      1.000   2.000   3.000  1.00 80.00           C  \nENDMDL\nMODEL        2\nATOM      1  CA  GLY B  23       8.000   9.000  10.000  1.00 70.00           C  \nENDMDL\nEND\n'

test('main results ZIP converts the selected historical structure and records its original parameters', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Historical export formats' } })
  expect(created.status()).toBe(201)
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const upload = await request.post(`${base}/inputs`, { data: { filename: 'ensemble.pdb', content_base64: Buffer.from(ensemble).toString('base64') } })
  expect(upload.status()).toBe(201)
  const { project_input_ref } = await upload.json()
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [{ node_id: 'input', node_type_id: 'protein_io.import_structure', binding_id: 'protein_io.import_structure.direct', node_parameters: { project_input_ref, model_index: 1 }, binding_parameters: {} }], edges: [] }
  const commit = await request.post(`${base}/workflow:commit`, { data: { workflow } })
  expect(commit.status()).toBe(200)
  const { workflow_commit_id } = await commit.json()
  const started = await request.post(`${base}/runs`, { data: { workflow_commit_id, client_request_id: 'historical-export' } })
  expect(started.status()).toBe(202)
  const { run_id } = await started.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
  const rawUrl = `${base}/runs/${run_id}/outputs/input/structure_candidates/values/0`
  const original = await (await request.get(rawUrl)).text()
  workflow.nodes[0].node_parameters.model_index = 2
  expect((await request.put(`${base}/workspace`, { data: { workflow } })).status()).toBe(200)
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  await page.getByRole('checkbox').first().check()
  for (const format of ['pdb', 'mmcif']) {
    await page.getByLabel('结构导出格式', { exact: true }).selectOption(format)
    const downloading = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出所选 · ZIP', exact: true }).click()
    const download = await downloading
    const stream = await download.createReadStream()
    const chunks: Buffer[] = []
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk))
    const files = unzipSync(Buffer.concat(chunks))
    const manifest = JSON.parse(strFromU8(files['manifest.json']))
    expect(manifest.run_id).toBe(run_id)
    expect(manifest.candidates).toHaveLength(1)
    const filename = manifest.candidates[0].structure_file
    expect(filename).toBe(`structures/candidate-0001.${format === 'pdb' ? 'pdb' : 'cif'}`)
    const content = strFromU8(files[filename])
    expect(content).toContain('ALA')
    expect(content).not.toContain('GLY')
    // Read the actual ZIP file through the public declared-format import boundary.
    const reuploaded = await request.post(`${base}/inputs`, { data: { filename, content_base64: Buffer.from(files[filename]).toString('base64') } })
    expect(reuploaded.status()).toBe(201)
    const ref = (await reuploaded.json()).project_input_ref
    const inspected = await request.post(`${base}/authoring-actions/protein_io.inspect_input`, { data: { parameters: { project_input_ref: ref, format } } })
    expect(inspected.status()).toBe(200)
    expect((await inspected.json()).models).toEqual([{ model_index: 1, model_id: '1', chain_ids: ['A'] }])
    const parameters = JSON.parse(strFromU8(files['computation-parameters.json']))
    expect(parameters.workflow_commit_id).toBe(workflow_commit_id)
    expect(parameters.records).toHaveLength(1)
    expect(parameters.records[0]).toMatchObject({ project_id: id, run_id, node_id: 'input', node_type_id: 'protein_io.import_structure', node_parameters: { project_input_ref, model_index: 1 }, binding_parameters: {} })
    expect(parameters.outputs).toContainEqual(expect.objectContaining({ source: manifest.candidates[0].source, status: 'recorded', parameter_record_ids: [parameters.records[0].record_id] }))
  }
  expect((await (await request.get(`${base}/workspace`)).json()).draft.workflow.nodes[0].node_parameters.model_index).toBe(2)
  expect(await (await request.get(rawUrl)).text()).toBe(original)
})

test('mixed ZIP selection associates a cache replay and a new output with their own producer parameters', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Mixed cached export' } })
  expect(created.status()).toBe(201)
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const refs: string[] = []
  for (const [name, sequence] of [['first', 'ACDE'], ['second', 'GGGG']]) {
    const uploaded = await request.post(`${base}/inputs`, { data: { filename: `${name}.fasta`, content_base64: Buffer.from(`>${name}\n${sequence}\n`).toString('base64') } })
    expect(uploaded.status()).toBe(201)
    refs.push((await uploaded.json()).project_input_ref)
  }
  const imported = (name: string, ref: string) => ({ node_id: name, node_type_id: 'protein_io.import_sequences', binding_id: 'protein_io.import_sequences.direct', node_parameters: { project_input_ref: ref }, binding_parameters: {} })
  const take = (name: string) => ({ node_id: name, node_type_id: 'collection_ops.take_candidates', binding_id: 'collection_ops.take_candidates.direct', node_parameters: { k: 1 }, binding_parameters: {} })
  const run = async (replay: boolean) => {
    const takeId = replay ? 'replayed-prefix' : 'original-prefix'
    const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [imported('first-source', refs[0]), take(takeId), ...(replay ? [imported('second-source', refs[1])] : [])], edges: [{ source_node_id: 'first-source', source_port: 'sequence_candidates', target_node_id: takeId, target_port: 'candidates' }] }
    const committed = await request.post(`${base}/workflow:commit`, { data: { workflow } })
    expect(committed.status()).toBe(200)
    const started = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: takeId } })
    expect(started.status()).toBe(202)
    const { run_id } = await started.json()
    await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
    return (await request.get(`${base}/runs/${run_id}`)).json()
  }
  const original = await run(false)
  const mixed = await run(true)
  const cached = mixed.outputs.find((output: { node_id: string }) => output.node_id === 'replayed-prefix')
  expect(cached.materialization.resolution).toBe('cache_replayed')
  expect(cached.producer_provenance.producer_run_id).toBe(original.run_id)
  await page.goto(`${appUrl}/?project=${id}&run=${mixed.run_id}`)
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  for (const name of ['Take an ordered Candidate prefix', 'second-source']) {
    await page.getByRole('navigation', { name: '结果阶段' }).getByRole('button', { name: new RegExp(name) }).click()
    await page.getByRole('region', { name: '候选列表', exact: true }).getByRole('checkbox').check()
  }
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出所选 · ZIP', exact: true }).click()
  const stream = await (await downloading).createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk))
  const files = unzipSync(Buffer.concat(chunks))
  const manifest = JSON.parse(strFromU8(files['manifest.json']))
  const parameters = JSON.parse(strFromU8(files['computation-parameters.json']))
  expect(manifest.candidates.map((candidate: { source: { node_id: string } }) => candidate.source.node_id)).toEqual(['replayed-prefix', 'second-source'])
  expect(strFromU8(files['candidates.fasta'])).toContain('\nACDE\n')
  expect(strFromU8(files['candidates.fasta'])).toContain('\nGGGG\n')
  for (const [exportedNode, producerRun, producerNode, expectedParameters] of [
    ['replayed-prefix', original.run_id, 'original-prefix', { k: 1 }],
    ['second-source', mixed.run_id, 'second-source', { project_input_ref: refs[1] }],
  ] as const) {
    const output = parameters.outputs.find((entry: { source: { node_id: string } }) => entry.source.node_id === exportedNode)
    expect(output).toMatchObject({ producer_run_id: producerRun, status: 'recorded' })
    expect(output.parameter_record_ids).toHaveLength(1)
    const record = parameters.records.find((entry: { record_id: string }) => entry.record_id === output.parameter_record_ids[0])
    expect(record).toMatchObject({ project_id: id, run_id: producerRun, node_id: producerNode, node_parameters: expectedParameters, binding_parameters: {} })
  }
  expect(parameters.records.some((entry: { node_id: string }) => entry.node_id === 'replayed-prefix')).toBe(false)
})

test('export node attachment download includes original file and recorded parameters', async ({ page, request }) => {
  const { id } = await (await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Attachment ZIP' } })).json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const { project_input_ref } = await (await request.post(`${base}/inputs`, { data: { filename: 'source.pdb', content_base64: Buffer.from(ensemble).toString('base64') } })).json()
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [
    { node_id: 'input', node_type_id: 'protein_io.import_structure', binding_id: 'protein_io.import_structure.direct', node_parameters: { project_input_ref, model_index: 2 }, binding_parameters: {} },
    { node_id: 'export', node_type_id: 'protein_io.export_structure', binding_id: 'protein_io.export_structure.direct', node_parameters: {} as { format?: string }, binding_parameters: {} },
  ], edges: [{ source_node_id: 'input', source_port: 'structure', target_node_id: 'export', target_port: 'structure' }] }
  workflow.nodes.push({ ...workflow.nodes[1], node_id: 'same-run-replay' })
  workflow.edges.push({ ...workflow.edges[0], target_node_id: 'same-run-replay' })
  const { workflow_commit_id } = await (await request.post(`${base}/workflow:commit`, { data: { workflow } })).json()
  let { run_id } = await (await request.post(`${base}/runs`, { data: { workflow_commit_id, client_request_id: 'attachment' } })).json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
  const originalRunId = run_id
  const firstRun = await (await request.get(`${base}/runs/${run_id}`)).json()
  expect(firstRun.node_dispositions).toContainEqual(expect.objectContaining({ node_id: 'same-run-replay', resolution: 'cache_replayed' }))
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  await page.getByText('全部已发布类型值与附件', { exact: true }).click()
  const sameRunDownload = page.waitForEvent('download')
  await page.getByRole('region', { name: '已发布附件', exact: true }).getByRole('button', { name: / · ZIP$/ }).last().click()
  const sameRunStream = await (await sameRunDownload).createReadStream()
  const sameRunChunks: Buffer[] = []
  for await (const chunk of sameRunStream!) sameRunChunks.push(Buffer.from(chunk))
  const sameRunParameters = JSON.parse(strFromU8(unzipSync(Buffer.concat(sameRunChunks))['computation-parameters.json']))
  expect(sameRunParameters.artifacts.every((artifact: { status: string }) => artifact.status === 'recorded')).toBe(true)
  expect(sameRunParameters.records.some((record: { node_id: string }) => record.node_id === 'same-run-replay')).toBe(false)
  workflow.nodes[1].node_id = 'replayed-export'
  workflow.nodes[1].node_parameters.format = 'pdb'
  workflow.edges[0].target_node_id = 'replayed-export'
  const replayCommit = await (await request.post(`${base}/workflow:commit`, { data: { workflow } })).json()
  run_id = (await (await request.post(`${base}/runs`, { data: { workflow_commit_id: replayCommit.workflow_commit_id, client_request_id: 'replay-attachment' } })).json()).run_id
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
  const run = await (await request.get(`${base}/runs/${run_id}`)).json()
  expect(run.node_dispositions).toContainEqual(expect.objectContaining({ node_id: 'replayed-export', resolution: 'cache_replayed' }))
  const artifact = run.artifact_index[0]
  const original = await (await request.get(`${base}/runs/${run_id}/artifacts/${artifact.artifact_reference}`)).text()
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  await page.getByText('全部已发布类型值与附件', { exact: true }).click()
  const downloading = page.waitForEvent('download')
  await page.getByRole('region', { name: '已发布附件', exact: true }).getByRole('button', { name: `${artifact.filename} · ZIP`, exact: true }).first().click()
  const stream = await (await downloading).createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk))
  const files = unzipSync(Buffer.concat(chunks))
  expect(strFromU8(files[artifact.filename])).toBe(original)
  const parameters = JSON.parse(strFromU8(files['computation-parameters.json']))
  expect(parameters.records).toContainEqual(expect.objectContaining({ node_id: 'input', node_parameters: { project_input_ref, model_index: 2 } }))
  expect(parameters.records).toContainEqual(expect.objectContaining({ node_id: 'export', run_id: originalRunId, node_parameters: {}, admitted_parameters: { node_parameters: { format: 'pdb' }, binding_parameters: {} } }))
  expect(parameters.records.some((record: { node_id: string }) => record.node_id === 'replayed-export')).toBe(false)
  expect(parameters.artifacts).toContainEqual(expect.objectContaining({ artifact_reference: artifact.artifact_reference, producer_run_id: originalRunId, status: 'recorded' }))
})

test('a retired attachment download cannot publish after switching A to B to A', async ({ page }) => {
  await page.goto(appUrl)
  const outcome = await page.evaluate(async () => {
    const moduleUrl = '/src/published-results.ts'
    const { PublishedResults } = await import(moduleUrl)
    let commits = 0
    const client = {
      runEvents: () => ({ close() {} }),
      runProjection: async (project_id: string, run_id: string) => ({ project_id, run_id, status: 'succeeded', node_dispositions: [], outputs: [], artifact_index: [], workflow_commit_id: 'commit' }),
      artifactUrl: () => '/delayed-artifact',
      workflowCommit: async () => { commits++; throw new Error('Retired attachment must not read a Commit') },
    }
    const results = new PublishedResults(client)
    results.openRun({ project_id: 'project', run_id: 'A' }); await results.refresh()
    const originalFetch = window.fetch
    let release!: (response: Response) => void
    window.fetch = () => new Promise<Response>(resolve => { release = resolve })
    try {
      const pending = results.exportArtifact({ artifact_reference: 'artifact', filename: 'result.txt' })
      results.openRun({ project_id: 'project', run_id: 'B' }); await results.refresh()
      results.openRun({ project_id: 'project', run_id: 'A' }); await results.refresh()
      release(new Response('old bytes'))
      return { retired: await pending === undefined, commits }
    } finally { window.fetch = originalFetch; results.openRun(undefined) }
  })
  expect(outcome).toEqual({ retired: true, commits: 0 })
})
