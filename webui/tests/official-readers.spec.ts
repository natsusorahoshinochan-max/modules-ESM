import { test, expect } from '@playwright/test'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5199'

test('an imported sequence opens through its module viewer after reopening the project', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Sequence reading' } })
  expect(created.status()).toBe(201)
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const uploaded = await request.post(`${base}/inputs`, { data: { filename: 'sequence.fasta', content_base64: Buffer.from('>example\nACDEFG\n').toString('base64') } })
  expect(uploaded.status()).toBe(201)
  const { project_input_ref } = await uploaded.json()
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [{ node_id: 'import', node_type_id: 'protein_io.import_sequence', binding_id: 'protein_io.import_sequence.direct', node_parameters: { project_input_ref }, binding_parameters: {} }], edges: [],
  } } })
  expect(committed.status()).toBe(200)
  const receipt = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: 'sequence-reading' } })
  expect(receipt.status()).toBe(202)
  const { run_id } = await receipt.json()
  const runUrl = `${base}/runs/${run_id}`
  await expect.poll(async () => (await (await request.get(runUrl)).json()).status).toBe('succeeded')
  const rawUrl = `${runUrl}/outputs/import/sequence/values/0`
  const original = await (await request.get(rawUrl)).text()
  for (let opened = 0; opened < 2; opened++) {
    await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
    await page.getByRole('button', { name: '查看结果', exact: true }).click()
    await page.getByText('全部已发布类型值与附件', { exact: true }).click()
    await page.getByRole('button', { name: 'import / sequence protein.sequence · 1 个值', exact: true }).click()
    await page.getByRole('button', { name: '加载此值', exact: true }).click()
    await expect(page.getByLabel('结果查看器')).toHaveValue('protein_io.sequence')
    await expect(page.getByLabel('已发布序列')).toContainText('ACDEFG')
    await expect(page.getByLabel('已发布序列')).toContainText('6 个序列位置')
  }
  expect(await (await request.get(rawUrl)).text()).toBe(original)
})

test('a published Prompt retains masks, absent tracks and residue paging in its module viewer after reopen', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Prompt reading' } })
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [{ node_id: 'prompt', node_type_id: 'prompt_authoring.author', binding_id: 'prompt_authoring.author.direct', node_parameters: { document: { chains: [{ chain_id: 'A', length: 101 }] } }, binding_parameters: {} }], edges: [],
  } } })
  expect(committed.status()).toBe(200)
  const receipt = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: 'prompt-reading' } })
  expect(receipt.status()).toBe(202)
  const { run_id } = await receipt.json()
  const runUrl = `${base}/runs/${run_id}`
  await expect.poll(async () => (await (await request.get(runUrl)).json()).status).toBe('succeeded')
  for (let opened = 0; opened < 2; opened++) {
    await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
    await page.getByRole('button', { name: '查看结果', exact: true }).click()
    await page.getByText('全部已发布类型值与附件', { exact: true }).click()
    await page.getByRole('button', { name: /prompt \/ protein_prompt/ }).click()
    await page.getByRole('button', { name: '加载此值', exact: true }).click()
    await expect(page.getByLabel('结果查看器')).toHaveValue('prompt_authoring.prompt')
    const prompt = page.getByLabel('已发布 Prompt')
    await expect(prompt.getByRole('row')).toHaveCount(101)
    await expect(prompt.getByRole('row').nth(1)).toContainText('Mask')
    await expect(prompt.getByRole('row').nth(1)).toContainText('未提供整条轨道')
    await prompt.getByRole('button', { name: '下一页' }).click()
    await expect(prompt.getByRole('row')).toHaveCount(2)
    await expect(prompt.getByRole('row').nth(1)).toContainText('A:101')
    await expect(prompt).toContainText('没有功能注释。')
  }
})
