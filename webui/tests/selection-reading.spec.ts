import { test, expect } from '@playwright/test'
const app = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5217'

for (const failedOffset of [0, 100]) test(`Selection blocks failed candidate page at ${failedOffset} and recovers on explicit retry`, async ({ page, request }) => {
  const { id } = await (await request.post(`${app}/api/v2/projects`, { data: { name: 'Selection read recovery' } })).json()
  const base = `${app}/api/v2/projects/${id}`
  const fasta = Array.from({ length: 101 }, (_, i) => `>sequence-${i + 1}\nACDEFG\n`).join('')
  const uploaded = await request.post(`${base}/inputs`, { data: { filename: 'sequences.fasta', content_base64: Buffer.from(fasta).toString('base64') } })
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [
    { node_id: 'import', node_type_id: 'protein_io.import_sequences', binding_id: 'protein_io.import_sequences.direct', node_parameters: { project_input_ref: (await uploaded.json()).project_input_ref }, binding_parameters: {} },
    { node_id: 'select', node_type_id: 'selection.manual', binding_id: 'selection.manual.direct', node_parameters: { selected_candidates: [] }, binding_parameters: {} },
  ], edges: [{ source_node_id: 'import', source_port: 'sequence_candidates', target_node_id: 'select', target_port: 'candidates' }] }
  expect((await request.put(`${base}/workspace`, { data: { workflow, ui_state: {}, expected_draft_revision: 0, expected_workspace_revision: 0 } })).status()).toBe(200)
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow } })
  expect(committed.status(), await committed.text()).toBe(200)
  const receipt = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: 'selection-recovery' } })
  const { run_id } = await receipt.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
  let failPage = true
  await page.route('**/results:action', async route => {
    const body = route.request().postDataJSON()
    if (failPage && body.action_id === 'protein_io.candidate_page' && body.parameters.offset === failedOffset) await route.abort('failed')
    else await route.continue()
  })
  await page.goto(`${app}/?project=${id}&run=${run_id}`)
  await page.getByRole('button', { name: '编辑筛选与排序', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('alert')).toContainText('候选读取失败')
  await expect(dialog.getByLabel('流程筛选编辑器')).toHaveCount(0)
  failPage = false
  await dialog.getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(dialog.getByRole('checkbox')).toHaveCount(101)
  await dialog.getByRole('checkbox').last().check()
  await dialog.getByRole('button', { name: '应用到流程', exact: true }).click()
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect.poll(async () => (await (await request.get(`${base}/workspace`)).json()).draft.workflow.nodes[1].node_parameters.selected_candidates.length).toBe(1)
})
