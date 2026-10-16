import { test, expect } from '@playwright/test'
const app = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5196'

test('ESMC viewer reads requested values, changes residue and reopens unchanged', async ({ page, request }) => {
  await request.patch(`${app}/api/v2/module-settings/esm3.represent_sequence.biohub_esmc_600m_2024_12`, { data: { values: { credential_handle: 'test-token' } } })
  const project = await (await request.post(`${app}/api/v2/projects`, { data: { name: 'ESMC values' } })).json()
  const base = `${app}/api/v2/projects/${project.id}`
  const input = await (await request.post(`${base}/inputs`, { data: { filename: 'seq.fasta', content_base64: Buffer.from('>seq\nAC\n').toString('base64') } })).json()
  const commit = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: project.id,
    nodes: [
      { node_id: 'source', node_type_id: 'protein_io.import_sequence', binding_id: 'protein_io.import_sequence.direct', node_parameters: { project_input_ref: input.project_input_ref }, binding_parameters: {} },
      { node_id: 'represent', node_type_id: 'esm3.represent_sequence', binding_id: 'esm3.represent_sequence.biohub_esmc_600m_2024_12', node_parameters: { outputs: 'both' }, binding_parameters: {} },
    ], edges: [{ source_node_id: 'source', source_port: 'sequence', target_node_id: 'represent', target_port: 'sequence' }],
  } } })
  expect(commit.status()).toBe(200)
  const start = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await commit.json()).workflow_commit_id, client_request_id: 'esmc-ui' } })
  const run = (await start.json()).run_id
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run}`)).json()).status).toBe('succeeded')
  const rawUrl = `${base}/runs/${run}/outputs/represent/representation/values/0`
  const original = await (await request.get(rawUrl)).text()
  await page.goto(`${app}/?project=${project.id}&run=${run}`)
  for (let opening = 0; opening < 2; opening++) {
    await page.getByRole('button', { name: '查看结果', exact: true }).click()
    await page.getByText('全部已发布类型值与附件', { exact: true }).click()
    await page.getByRole('button', { name: /represent \/ representation/ }).click()
    await page.getByRole('button', { name: '加载此值', exact: true }).click()
    const viewer = page.getByRole('region', { name: 'ESMC 数值' })
    await expect(viewer.getByRole('heading', { name: '逐位置 logits（非概率）' })).toBeVisible()
    await expect(viewer.getByRole('cell', { name: '1.25', exact: true })).toHaveCount(64)
    await viewer.getByLabel('序列位置').fill('2')
    await expect(viewer.getByRole('cell', { name: '-2.5', exact: true })).toHaveCount(64)
    expect(await (await request.get(rawUrl)).text()).toBe(original)
    if (opening === 0) await page.reload()
  }
})
