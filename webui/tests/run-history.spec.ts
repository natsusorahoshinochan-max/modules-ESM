import { test, expect } from '@playwright/test'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5215'

test('the run history list opens an older result and keeps that selection after refresh', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Two saved runs' } })
  expect(created.status()).toBe(201)
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const runs: string[] = []
  for (const sequence of ['ACDE', 'WYYY']) {
    const uploaded = await request.post(`${base}/inputs`, { data: {
      filename: `${sequence}.fasta`, content_base64: Buffer.from(`>sequence\n${sequence}\n`).toString('base64'),
    } })
    expect(uploaded.status()).toBe(201)
    const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: {
      schema_version: '2.1.0', workflow_id: id,
      nodes: [{ node_id: 'import', node_type_id: 'protein_io.import_sequence',
        binding_id: 'protein_io.import_sequence.direct', binding_parameters: {},
        node_parameters: { project_input_ref: (await uploaded.json()).project_input_ref } }], edges: [],
    } } })
    expect(committed.status()).toBe(200)
    const started = await request.post(`${base}/runs`, { data: {
      workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: `history-${sequence}`,
    } })
    expect(started.status()).toBe(202)
    const { run_id } = await started.json()
    runs.push(run_id)
    await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
  }
  const savedWorkspace = await (await request.get(`${base}/workspace`)).json()
  // Enter the project normally; selecting the older Run must use the visible list.
  await page.goto(`${appUrl}/?project=${id}`)
  await page.getByRole('button', { name: '运行历史', exact: true }).click()
  const history = page.getByRole('dialog', { name: '项目运行历史', exact: true })
  const older = history.getByRole('listitem').filter({ has: page.getByText(runs[0], { exact: true }) })
  const latest = history.getByRole('listitem').filter({ has: page.getByText(runs[1], { exact: true }) })
  await expect(older).toContainText('succeeded · 有保留结果')
  await expect(latest).toContainText('succeeded · 有保留结果')
  await expect(latest.getByRole('button', { name: '打开运行' })).toHaveAttribute('aria-current', 'true')
  await older.getByRole('button', { name: '打开运行' }).click()
  await expect(older.getByRole('button', { name: '打开运行' })).toHaveAttribute('aria-current', 'true')
  await expect(latest.getByRole('button', { name: '打开运行' })).not.toHaveAttribute('aria-current', 'true')
  await expect(history.getByLabel('选中运行状态')).toContainText(runs[0])
  await expect(history.getByLabel('选中运行状态')).toContainText('import · succeeded')
  await history.getByRole('button', { name: '关闭', exact: true }).click()
  for (let opening = 0; opening < 2; opening++) {
    if (opening) {
      await page.reload()
      await page.getByRole('button', { name: '运行历史', exact: true }).click()
      await expect(older.getByRole('button', { name: '打开运行' })).toHaveAttribute('aria-current', 'true')
      await expect(history.getByLabel('选中运行状态')).toContainText(runs[0])
      await history.getByRole('button', { name: '关闭', exact: true }).click()
    }
    await page.getByRole('button', { name: '查看结果', exact: true }).click()
    await page.getByText('全部已发布类型值与附件', { exact: true }).click()
    await page.getByRole('button', { name: 'import / sequence protein.sequence · 1 个值', exact: true }).click()
    await page.getByRole('button', { name: '加载此值', exact: true }).click()
    await expect(page.getByLabel('已发布序列')).toContainText('ACDE')
    await expect(page.getByLabel('已发布序列')).not.toContainText('WYYY')
  }
  expect(await (await request.get(`${base}/workspace`)).json()).toEqual(savedWorkspace)
})
