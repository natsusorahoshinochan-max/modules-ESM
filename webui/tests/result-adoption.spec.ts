import { test, expect } from '@playwright/test'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5193'

test('adopting a historical result adds an unsaved source, which survives manual save and reopening', async ({ page, request }) => {
  const sourceResponse = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Adoption source' } })
  expect(sourceResponse.status()).toBe(201)
  const source = (await sourceResponse.json()).id
  const targetResponse = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Adoption target' } })
  expect(targetResponse.status()).toBe(201)
  const target = (await targetResponse.json()).id
  const uploaded = await request.post(`${appUrl}/api/v2/projects/${source}/inputs`, { data: { filename: 'sequences.fasta', content_base64: Buffer.from('>first\nACDE\n>second\nFGHI\n').toString('base64') } })
  expect(uploaded.status()).toBe(201)
  const committed = await request.post(`${appUrl}/api/v2/projects/${source}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: source,
    nodes: [{ node_id: 'import', node_type_id: 'protein_io.import_sequences', binding_id: 'protein_io.import_sequences.direct', node_parameters: { project_input_ref: (await uploaded.json()).project_input_ref }, binding_parameters: {} }], edges: [],
  } } })
  expect(committed.status()).toBe(200)
  const started = await request.post(`${appUrl}/api/v2/projects/${source}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: 'adoption-ui' } })
  expect(started.status()).toBe(202)
  const runId = (await started.json()).run_id
  await expect.poll(async () => (await (await request.get(`${appUrl}/api/v2/projects/${source}/runs/${runId}`)).json()).status).toBe('succeeded')
  const workspaceUrl = `${appUrl}/api/v2/projects/${target}/workspace`
  const savedBefore = await (await request.get(workspaceUrl)).json()
  await page.goto(`${appUrl}/?project=${target}`)
  await page.getByRole('button', { name: '采用历史结果', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '采用历史结果', exact: true })
  await dialog.getByLabel('来源项目').selectOption(source)
  await dialog.getByLabel('历史运行').selectOption(runId)
  await dialog.getByLabel('结果值').selectOption({ label: 'import / sequence_candidates · 值 1' })
  await dialog.getByRole('button', { name: '采用为输入', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByLabel('流程保存状态')).toContainText('未保存')
  expect(await (await request.get(workspaceUrl)).json()).toEqual(savedBefore)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.getByLabel('流程保存状态')).not.toContainText('未保存')
  const saved = await (await request.get(workspaceUrl)).json()
  expect(saved.draft.workflow.nodes).toHaveLength(1)
  expect(saved.draft.workflow.edges).toEqual([])
  expect(saved.draft.workflow.nodes[0].node_parameters.project_input_ref).toBeTruthy()
  await page.reload()
  await expect(page.locator('.react-flow__node')).toHaveCount(1)
  await expect(page.getByLabel('流程保存状态')).not.toContainText('未保存')
})
