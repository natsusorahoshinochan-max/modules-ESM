import { expect, test } from '@playwright/test'
const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5297'
const mixed = 'HEADER    MIXED STRUCTURE\nATOM      1  CA  ALA A  12A      1.000   2.000   3.000  1.00 80.00           C  \nHETATM    2  C1  LIG B 201       4.000   2.000   3.000  1.00 20.00           C  \nHETATM    3  O1  LIG B 201       5.000   2.000   3.000  1.00 20.00           O  \nHETATM    4 ZN    ZN C 301       8.000   2.000   3.000  1.00 20.00          ZN  \nHETATM    5  O   HOH D 401      11.000   2.000   3.000  1.00 20.00           O  \nATOM      6  P    DA E 501      14.000   2.000   3.000  1.00 20.00           P  \nEND\n'

test('mixed components can each be viewed, selected and exported while the original remains intact', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Mixed components' } })
  const { id } = await created.json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const upload = await request.post(`${base}/inputs`, { data: { filename: 'mixed.pdb', content_base64: Buffer.from(mixed).toString('base64') } })
  const { project_input_ref } = await upload.json()
  const commit = await request.post(`${base}/workflow:commit`, { data: { workflow: { schema_version: '2.1.0', workflow_id: id, nodes: [{ node_id: 'input', node_type_id: 'protein_io.import_structure', binding_id: 'protein_io.import_structure.direct', node_parameters: { project_input_ref }, binding_parameters: {} }], edges: [] } } })
  expect(commit.status()).toBe(200)
  const { workflow_commit_id } = await commit.json()
  const started = await request.post(`${base}/runs`, { data: { workflow_commit_id, client_request_id: 'components' } })
  const { run_id } = await started.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json()).status).toBe('succeeded')
  const rawUrl = `${base}/runs/${run_id}/outputs/input/structure_candidates/values/0`
  const original = await (await request.get(rawUrl)).text()
  await page.goto(`${appUrl}/?project=${id}&run=${run_id}`)
  await page.getByRole('button', { name: /^Results/ }).click()
  await page.getByRole('region', { name: '候选列表', exact: true }).getByRole('button', { name: /^candidate-/ }).first().click()
  await expect(page.getByLabel('结构组分视口')).toBeVisible()
  await expect(page.getByRole('status', { name: '结构组分显示' })).toHaveText('显示 6 个原子 · 已选 0 个原子')
  for (const name of ['LIG B:201', 'ZN C:301', 'HOH D:401', 'DA E:501']) {
    await page.getByRole('checkbox', { name: `选择组分 ${name}`, exact: true }).check()
  }
  await expect(page.getByRole('status', { name: '结构组分显示' })).toHaveText('显示 6 个原子 · 已选 5 个原子')
  await page.getByLabel('结构组分视口').screenshot({ path: '/tmp/workbench-components-viewport.png' })
  for (const format of ['pdb', 'mmcif']) {
    await page.getByLabel('组分导出格式', { exact: true }).selectOption(format)
    const downloaded = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出所选组分', exact: true }).click()
    const download = await downloaded
    expect(download.suggestedFilename()).toBe(`components.${format === 'pdb' ? 'pdb' : 'cif'}`)
    const stream = await download.createReadStream()
    const buffers: Buffer[] = []
    for await (const chunk of stream!) buffers.push(Buffer.from(chunk))
    const body = Buffer.concat(buffers).toString()
    for (const residue of ['LIG', 'ZN', 'HOH', 'DA']) expect(body).toContain(residue)
    expect(body).not.toContain('ALA')
  }
  await page.reload()
  await page.getByRole('button', { name: /^Results/ }).click()
  await page.getByRole('region', { name: '候选列表', exact: true }).getByRole('button', { name: /^candidate-/ }).first().click()
  await expect(page.getByRole('checkbox', { name: '选择组分 HOH D:401', exact: true })).toBeChecked()
  expect(await (await request.get(rawUrl)).text()).toBe(original)
})
