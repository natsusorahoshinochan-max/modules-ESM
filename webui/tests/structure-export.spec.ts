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
    const inspected = await request.post(`${base}/inputs/${ref}:inspect`, { data: { format } })
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
