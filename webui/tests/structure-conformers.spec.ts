import { expect, test } from '@playwright/test'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5206'
const ensemble = 'MODEL        7\nATOM      1  CA  ALA A  12A      1.000   2.000   3.000  1.00 80.00           C  \nENDMDL\nMODEL       19\nATOM      1  CA  GLY B  23       8.000   9.000  10.000  1.00 70.00           C  \nENDMDL\nEND\n'

test('one uploaded structure splits selected conformers into a saved and reopened candidate source', async ({ page, request }) => {
  const response = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Structure conformers' } })
  expect(response.status()).toBe(201)
  const { id } = await response.json()
  await page.goto(`${appUrl}/?project=${id}`)
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  await page.getByRole('button', { name: 'PDB / mmCIF Candidates' }).click()
  const upload = page.getByLabel('来源文件', { exact: true })
  await expect(upload).not.toHaveAttribute('multiple')
  await upload.setInputFiles({ name: 'ensemble.pdb', mimeType: 'chemical/x-pdb', buffer: Buffer.from(ensemble) })
  await page.getByRole('button', { name: '上传并检查输入', exact: true }).click()
  await expect(page.getByLabel('选择构象 7', { exact: true })).toBeVisible()
  await page.getByLabel('选择构象 7', { exact: true }).check()
  await page.getByLabel('选择构象 19', { exact: true }).check()
  await page.getByRole('button', { name: '确认导入独立 Candidates', exact: true }).click()
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  const base = `${appUrl}/api/v2/projects/${id}`
  await expect.poll(async () => (await (await request.get(`${base}/workspace`)).json()).draft.workflow.nodes.length).toBe(1)
  const saved = await (await request.get(`${base}/workspace`)).json()
  expect(saved.draft.workflow.nodes[0]).toMatchObject({ node_type_id: 'protein_io.import_structures', node_parameters: { model_indices: [1, 2] } })
  await page.reload()
  await expect(page.locator('.react-flow__node')).toHaveCount(1)
  const reopened = await (await request.get(`${base}/workspace`)).json()
  expect(reopened.draft.workflow).toEqual(saved.draft.workflow)
})

test('Prompt source chooses a model before offering its own chains', async ({ page, request }) => {
  const created = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'One selected conformer' } })
  expect(created.status()).toBe(201)
  const { id } = await created.json()
  await page.goto(`${appUrl}/?project=${id}`)
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  await page.getByRole('button', { name: 'PDB / mmCIF → Prompt' }).click()
  await page.getByLabel('来源文件', { exact: true }).setInputFiles({ name: 'ensemble.pdb', mimeType: 'chemical/x-pdb', buffer: Buffer.from(ensemble) })
  await page.getByRole('button', { name: '上传并检查输入', exact: true }).click()
  await expect(page.getByRole('button', { name: '进入 Prompt 预览', exact: true })).toBeDisabled()
  await page.getByLabel('Prompt 来源构象', { exact: true }).selectOption('2')
  await expect(page.getByLabel('选择 PDB Chain A', { exact: true })).toHaveCount(0)
  await page.getByLabel('选择 PDB Chain B', { exact: true }).check()
  const preview = page.waitForResponse(response => decodeURIComponent(response.url()).endsWith('prompt-authoring:open') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '进入 Prompt 预览', exact: true }).click()
  const response = await preview
  expect(response.status()).toBe(200)
  expect(JSON.stringify(response.request().postDataJSON())).toContain('"model_index":2')
})
