import { test, expect } from '@playwright/test'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5191'

test('continue uses the selected failed Run inputs without saving the edited workspace', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Continue original batch' } })
  expect(created.status()).toBe(201)
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const uploaded = await request.post(`${base}/inputs`, { data: { filename: 'one.fasta', content_base64: Buffer.from('>one\nA\n').toString('base64') } })
  expect(uploaded.status()).toBe(201)
  const { project_input_ref } = await uploaded.json()
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [
    { node_id: 'input', node_type_id: 'protein_io.import_sequences', binding_id: 'protein_io.import_sequences.direct', node_parameters: { project_input_ref }, binding_parameters: {} },
    { node_id: 'fold', node_type_id: 'folding.fold', binding_id: 'folding.fold.esmfold2_remote', node_parameters: { num_samples: 3 }, binding_parameters: {} },
  ], edges: [{ source_node_id: 'input', source_port: 'sequence_candidates', target_node_id: 'fold', target_port: 'sequence_candidates' }] }
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow } })
  expect(committed.status()).toBe(200)
  const { workflow_commit_id } = await committed.json()
  const started = await request.post(`${base}/runs`, { data: { workflow_commit_id, client_request_id: crypto.randomUUID() } })
  expect(started.status()).toBe(202)
  const { run_id } = await started.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('failed')
  const savedBefore = await (await request.get(`${base}/workspace`)).json()
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  await expect(page.getByRole('button', { name: '继续批次：fold', exact: true })).toBeVisible()
  // A canvas edit remains in memory; continuing the source Run must not save it.
  const node = page.locator('.react-flow__node[data-id="fold"]')
  const box = await node.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + 25)
  await page.mouse.down()
  await page.mouse.move(box!.x + box!.width / 2 + 90, box!.y + 75, { steps: 8 })
  await page.mouse.up()
  await expect(page.getByLabel('布局保存状态')).toContainText('未保存')
  let saves = 0
  page.on('request', req => { if (req.method() === 'PUT' && req.url().endsWith('/workspace')) saves++ })
  const derivedResponse = page.waitForResponse(response => response.url().endsWith('/runs:derive') && response.request().method() === 'POST')
  await expect(page.getByText('继续这次运行的原输入和参数；当前画布修改不会保存或用于续算。', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '继续批次：fold', exact: true }).click()
  const response = await derivedResponse
  expect(response.status()).toBe(202)
  expect(response.request().postDataJSON()).toMatchObject({ source_run_id: run_id, policy: 'continue_batch', node_ids: ['fold'] })
  const receipt = await response.json()
  expect(receipt.workflow_commit_id).toBe(workflow_commit_id)
  await expect.poll(async () => (await (await request.get(`${base}/runs/${receipt.run_id}`)).json()).status).toBe('succeeded')
  await expect(page.getByRole('button', { name: '继续批次：fold', exact: true })).toHaveCount(0)
  expect(saves).toBe(0)
  expect(await (await request.get(`${base}/workspace`)).json()).toEqual(savedBefore)
})
