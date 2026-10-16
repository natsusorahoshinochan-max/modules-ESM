import { test, expect } from '@playwright/test'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5188'

test('an external value opens in its default viewer, switches without changing the saved value, and reopens', async ({ page, request }) => {
  const projectResponse = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Temperature readings' } })
  expect(projectResponse.status()).toBe(201)
  const { id } = await projectResponse.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const commitResponse = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [{ node_id: 'observe', node_type_id: 'reader_demo.observe', binding_id: 'reader_demo.observe.direct', node_parameters: {}, binding_parameters: {} }], edges: [],
  } } })
  expect(commitResponse.status()).toBe(200)
  const commit = await commitResponse.json()
  const started = await request.post(`${base}/runs`, { data: { workflow_commit_id: commit.workflow_commit_id, client_request_id: 'temperature-ui' } })
  expect(started.status()).toBe(202)
  const { run_id } = await started.json()
  const runUrl = `${base}/runs/${run_id}`
  await expect.poll(async () => (await (await request.get(runUrl)).json()).status).toBe('succeeded')
  const rawUrl = `${runUrl}/outputs/observe/observation/values/0`
  const original = await (await request.get(rawUrl)).text()
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  await expect(page.getByLabel('结果面板')).toHaveValue('reader_demo.run')
  await expect(page.getByText('Saved run temperature: 23.5 °C', { exact: true })).toBeVisible()
  await page.getByLabel('结果面板').selectOption('reader_demo.unavailable')
  await expect(page.getByRole('alert')).toContainText('未导出组件 Unavailable')
  await page.getByLabel('结果面板').selectOption('reader_demo.run')
  await expect(page.getByText('Saved run temperature: 23.5 °C', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByText('全部已发布类型值与附件', { exact: true }).click()
  await page.getByRole('button', { name: /observe \/ observation/ }).click()
  await page.getByRole('button', { name: '加载此值', exact: true }).click()
  await expect(page.getByText('23.5 °C', { exact: true })).toBeVisible()
  await page.getByLabel('结果查看器').selectOption('reader_demo.fahrenheit')
  await expect(page.getByText('74.3 °F', { exact: true })).toBeVisible()
  await page.getByText('查看原始已发布值', { exact: true }).click()
  await expect(page.getByText('"temperature": 23.5', { exact: false })).toBeVisible()
  expect(await (await request.get(rawUrl)).text()).toBe(original)
  await page.reload()
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  await page.getByText('全部已发布类型值与附件', { exact: true }).click()
  await page.getByRole('button', { name: /observe \/ observation/ }).click()
  await page.getByRole('button', { name: '加载此值', exact: true }).click()
  await expect(page.getByText('23.5 °C', { exact: true })).toBeVisible()
})

test('a saved structure uses registered 3D and text viewers without rewriting the structure', async ({ page, request }) => {
  const pdb = 'ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N  \nATOM      2  CA  GLY A   1       1.000   0.000   0.000  1.00 20.00           C  \nATOM      3  C   GLY A   1       2.000   0.000   0.000  1.00 20.00           C  \nEND\n'
  const response = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Structure readers' } })
  expect(response.status()).toBe(201)
  const { id } = await response.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const uploaded = await request.post(`${base}/inputs`, { data: { filename: 'glycine.pdb', content_base64: Buffer.from(pdb).toString('base64') } })
  expect(uploaded.status()).toBe(201)
  const { project_input_ref } = await uploaded.json()
  const commit = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [{ node_id: 'import', node_type_id: 'protein_io.import_structure', binding_id: 'protein_io.import_structure.direct', node_parameters: { project_input_ref }, binding_parameters: {} }], edges: [],
  } } })
  expect(commit.status()).toBe(200)
  const started = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await commit.json()).workflow_commit_id, client_request_id: 'structure-ui' } })
  expect(started.status()).toBe(202)
  const { run_id } = await started.json()
  const runUrl = `${base}/runs/${run_id}`
  await expect.poll(async () => (await (await request.get(runUrl)).json()).status).toBe('succeeded')
  const rawUrl = `${runUrl}/outputs/import/structure/values/0`
  const original = await (await request.get(rawUrl)).text()
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  await page.getByText('全部已发布类型值与附件', { exact: true }).click()
  await page.getByRole('button', { name: 'import / structure protein.structure · 1 个值', exact: true }).click()
  await page.getByRole('button', { name: '加载此值', exact: true }).click()
  await expect(page.getByLabel('结果查看器')).toHaveValue('protein_io.structure.3d')
  await expect(page.getByLabel('已发布结构', { exact: true }).getByLabel('三维结构视口')).toBeVisible()
  await page.getByLabel('结果查看器').selectOption('protein_io.structure.text')
  await expect(page.getByLabel('已发布结构原文')).toHaveText(pdb.trim())
  await page.getByText('查看原始已发布值', { exact: true }).click()
  await expect(page.locator('.published-raw pre')).toContainText('GLY A')
  expect(await (await request.get(rawUrl)).text()).toBe(original)
  const reading = await request.post(`${runUrl}/results:value`, { data: { node_id: 'import', output_port: 'structure', value_index: 0 } })
  expect((await reading.json()).value).toEqual({ text: pdb, format: 'pdb' })
})

test('an external reader kind does not select a protein presentation', async ({ page, request }) => {
  const project = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'External reading names' } })
  expect(project.status()).toBe(201)
  const { id } = await project.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [{ node_id: 'observe', node_type_id: 'reader_demo.observe', binding_id: 'reader_demo.observe.direct', node_parameters: {}, binding_parameters: {} }], edges: [],
  } } })
  expect(committed.status()).toBe(200)
  const receipt = await request.post(`${base}/runs`, { data: { workflow_commit_id: (await committed.json()).workflow_commit_id, client_request_id: 'external-reading' } })
  expect(receipt.status()).toBe(202)
  const { run_id } = await receipt.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  await page.getByText('全部已发布类型值与附件', { exact: true }).click()
  await page.getByRole('button', { name: /observe \/ note/ }).click()
  await page.getByRole('button', { name: '加载此值', exact: true }).click()
  await page.getByText('查看已发布科学事实', { exact: true }).click()
  await expect(page.getByText('"message": "room temperature"', { exact: false })).toBeVisible()
})

test('a canvas output link opens an external typed value without rewriting it', async ({ page, request }) => {
  const projectResponse = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Temperature readings' } })
  expect(projectResponse.status()).toBe(201)
  const { id } = await projectResponse.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const commitResponse = await request.post(`${base}/workflow:commit`, { data: { workflow: {
    schema_version: '2.1.0', workflow_id: id,
    nodes: [{ node_id: 'observe', node_type_id: 'reader_demo.observe', binding_id: 'reader_demo.observe.direct', node_parameters: {}, binding_parameters: {} }], edges: [],
  } } })
  expect(commitResponse.status()).toBe(200)
  const commit = await commitResponse.json()
  const started = await request.post(`${base}/runs`, { data: { workflow_commit_id: commit.workflow_commit_id, client_request_id: 'temperature-ui' } })
  expect(started.status()).toBe(202)
  const { run_id } = await started.json()
  const runUrl = `${base}/runs/${run_id}`
  await expect.poll(async () => (await (await request.get(runUrl)).json()).status).toBe('succeeded')
  const rawUrl = `${runUrl}/outputs/observe/observation/values/0`
  const original = await (await request.get(rawUrl)).text()
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  const node = page.locator('.react-flow__node[data-id="observe"]')
  await node.getByText('查看输出', { exact: false }).click()
  await node.getByRole('button', { name: 'observe observation · 值 1' }).click()
  const detail = page.getByRole('region', { name: '输出详情', exact: true })
  await expect(detail.getByRole('heading', { name: 'observe / observation' })).toBeVisible()
  await expect(detail.getByLabel('输出值索引')).toHaveValue('0')
  await detail.getByRole('button', { name: '加载此值', exact: true }).click()
  await expect(detail.getByText('23.5 °C', { exact: true })).toBeVisible()
  await page.reload()
  await node.getByText('查看输出', { exact: false }).click()
  await node.getByRole('button', { name: 'observe observation · 值 1' }).click()
  await expect(detail.getByRole('heading', { name: 'observe / observation' })).toBeVisible()
  expect(await (await request.get(rawUrl)).text()).toBe(original)
})
