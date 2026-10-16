import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { strFromU8, unzipSync } from 'fflate'
import type { ProjectMetadata, RunProjection, Workflow } from '../../src/protocol/client'

for (const sourceRecord of ['original', 'cached', 'missing'] as const) test(`downloaded ${sourceRecord} results retain recorded parameters after the workspace changes`, async ({ page, request }) => {
  const project = await (await request.post('/api/v2/projects', { data: { name: `Export parameters ${crypto.randomUUID()}` } })).json() as ProjectMetadata
  const base = `/api/v2/projects/${project.id}`
  const input = await (await request.post(`${base}/inputs`, { data: { filename: 'original.fasta', content_base64: Buffer.from('>one\nACD\n>two\nEFG\n').toString('base64') } })).json()
  const workflow: Workflow = {
    schema_version: '2.1.0', workflow_id: project.id,
    nodes: [
      { node_id: 'source', node_type_id: 'protein_io.import_sequences', binding_id: 'protein_io.import_sequences.direct', node_parameters: { project_input_ref: input.project_input_ref }, binding_parameters: {} },
      { node_id: 'take', node_type_id: 'collection_ops.take_candidates', binding_id: 'collection_ops.take_candidates.direct', node_parameters: { k: 1 }, binding_parameters: {} },
    ],
    edges: [{ source_node_id: 'source', source_port: 'sequence_candidates', target_node_id: 'take', target_port: 'candidates' }], observation_selectors: [], selection_objectives: [],
  }
  const committed = await (await request.post(`${base}/workflow:commit`, { data: { workflow } })).json()
  const started = await (await request.post(`${base}/runs`, { data: { workflow_commit_id: committed.workflow_commit_id, client_request_id: crypto.randomUUID() } })).json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${started.run_id}`)).json() as RunProjection).status).toBe('succeeded')
  let displayedRunId: string = started.run_id
  if (sourceRecord !== 'original') {
    const replay = await (await request.post(`${base}/runs`, { data: { workflow_commit_id: committed.workflow_commit_id, client_request_id: crypto.randomUUID() } })).json()
    displayedRunId = replay.run_id
    await expect.poll(async () => (await (await request.get(`${base}/runs/${displayedRunId}`)).json() as RunProjection).status).toBe('succeeded')
    const projection = await (await request.get(`${base}/runs/${displayedRunId}`)).json() as RunProjection
    expect(projection.node_dispositions).toContainEqual(expect.objectContaining({ node_id: 'take', resolution: 'cache_replayed' }))
  }
  if (sourceRecord === 'missing') await page.route(`**${base}/runs/${started.run_id}`, route => route.fulfill({ status: 404, json: { schema_namespace: 'protein-workbench-public/v2', error: { code: 'run_not_found', message: 'Run record unavailable', details: { resource_kind: 'run', resource_id: started.run_id } } } }))
  workflow.nodes[1].node_parameters = { k: 2 }
  expect((await request.put(`${base}/workspace`, { data: { workflow, ui_state: {} } })).status()).toBe(200)
  await page.goto('/')
  await page.getByRole('button', { name: '项目', exact: true }).click()
  const projects = page.getByRole('dialog', { name: '项目与版本' })
  await projects.getByRole('button').filter({ has: page.getByText(project.name, { exact: true }) }).click()
  await projects.getByRole('button', { name: '打开项目', exact: true }).click()
  await page.getByRole('button', { name: /^Results/ }).click()
  await page.getByTestId('result-source-["source","sequence_candidates",0]').click()
  await page.locator('.result-table input[type=checkbox]').last().check()
  await page.getByTestId('result-source-["take","candidates",0]').click()
  await page.locator('.result-table input[type=checkbox]').first().check()
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出所选 · ZIP' }).click()
  const files = unzipSync(await readFile((await (await downloading).path())!))
  expect(files).toHaveProperty('computation-parameters.json')
  const parameters = JSON.parse(strFromU8(files['computation-parameters.json']))
  const manifest = JSON.parse(strFromU8(files['manifest.json']))
  expect(manifest.run_id).toBe(displayedRunId)
  expect(manifest.candidates).toHaveLength(2)
  expect(manifest.computation_parameters_file).toBe('computation-parameters.json')
  if (sourceRecord === 'missing') {
    expect(parameters.records).toEqual([])
    expect(parameters.workflows).toEqual([])
    expect(parameters.outputs).toEqual(expect.arrayContaining(manifest.candidates.map((candidate: { source: unknown }) => expect.objectContaining({ source: candidate.source, status: 'unavailable', producer_run_id: started.run_id, parameter_record_ids: [] }))))
    return
  }
  expect(parameters.records).toContainEqual(expect.objectContaining({
    project_id: project.id, run_id: started.run_id, workflow_commit_id: committed.workflow_commit_id,
    node_id: 'take', node_type_id: 'collection_ops.take_candidates', binding_id: 'collection_ops.take_candidates.direct', node_parameters: { k: 1 }, binding_parameters: {},
    admitted_parameters: { node_parameters: { k: 1 }, binding_parameters: {} },
  }))
  expect(parameters.records).toContainEqual(expect.objectContaining({ node_id: 'source', node_parameters: { project_input_ref: input.project_input_ref }, binding_parameters: {} }))
  expect(parameters.outputs).toContainEqual(expect.objectContaining({
    source: manifest.candidates[0].source, status: 'recorded', producer_run_id: started.run_id,
  }))
})
