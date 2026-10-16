import { test, expect } from '@playwright/test'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5194'

test('unsaved project switching offers discard or cancel without saving', async ({ page, request }) => {
  const first = await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'Unsaved source' } })
  expect(first.status()).toBe(201)
  const { id } = await first.json()
  const second = await request.post(`${appUrl}/api/v2/projects`, { data: { name: `Switch target ${id}` } })
  expect(second.status()).toBe(201)
  const base = `${appUrl}/api/v2/projects/${id}`
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [
    { node_id: 'input', node_type_id: 'protein_io.import_sequences', binding_id: 'protein_io.import_sequences.direct', node_parameters: {}, binding_parameters: {} },
  ], edges: [] }
  const saved = await request.put(`${base}/workspace`, { data: { workflow, ui_state: {} } })
  expect(saved.status()).toBe(200)
  const before = await (await request.get(`${base}/workspace`)).json()
  await page.goto(`${appUrl}/?project=${id}`)
  const node = page.locator('.react-flow__node[data-id="input"]')
  await expect(node).toBeVisible()
  const box = await node.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + 25)
  await page.mouse.down()
  await page.mouse.move(box!.x + box!.width / 2 + 90, box!.y + 75, { steps: 8 })
  await page.mouse.up()
  await expect(page.getByLabel('布局保存状态')).toContainText('未保存')
  await page.getByRole('button', { name: '项目', exact: true }).click()
  await page.getByRole('button', { name: `Switch target ${id} 个人项目`, exact: true }).click()
  await page.getByRole('button', { name: '打开项目', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '尚未保存的修改' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: '保存后退出', exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: '取消退出，继续编辑', exact: true }).click()
  await expect(page.getByLabel('布局保存状态')).toContainText('未保存')
  expect(await (await request.get(`${base}/workspace`)).json()).toEqual(before)
  await page.getByRole('button', { name: '关闭项目管理', exact: true }).click()
  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  const runDialog = page.getByRole('dialog', { name: '保存后运行' })
  await expect(runDialog.getByRole('button', { name: '保存并运行', exact: true })).toBeVisible()
  await runDialog.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '项目', exact: true }).click()
  await page.getByRole('button', { name: `Switch target ${id} 个人项目`, exact: true }).click()
  await page.getByRole('button', { name: '打开项目', exact: true }).click()
  await dialog.getByRole('button', { name: '放弃修改退出', exact: true }).click()
  await expect(page.locator('.project-identity')).toContainText(`Switch target ${id}`)
  expect(await (await request.get(`${base}/workspace`)).json()).toEqual(before)
})
