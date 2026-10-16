import { expect, test } from '@playwright/test'
import type { PromptPreview, PromptSnapshot } from '../../src/protocol/client'

for (const mode of ['g', 'r']) test(`${mode}: local display, cancel, one confirmation, undo and redo preserve the confirmed coordinates`, async ({ page }) => {
  await page.goto('/')
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === 'prompt-composition-webui-3gb1.source.author')
  await page.getByRole('button', { name: '编辑 ProteinPrompt', exact: true }).click()
  const initial: PromptSnapshot = await (await opening).json()
  const first = initial.residues.find(residue => residue.state !== 'pending-delete')!
  await page.locator(`[data-cell="${first.residue_handle}:sequence"]`).click()
  const viewport = page.getByLabel('三维结构视口', { exact: true })
  const canvas = viewport.locator('canvas')
  await expect(canvas).toBeVisible()
  // Exclude the overlaid toolbar/status text: focus can change its antialiasing.
  const structureImage = async () => {
    const bounds = (await canvas.boundingBox())!
    return page.screenshot({ clip: { x: bounds.x, y: bounds.y + 70, width: bounds.width, height: bounds.height - 130 } })
  }
  const baseline = await structureImage()
  const requests: string[] = []
  page.on('request', request => { if (request.url().endsWith('/prompt-authoring:preview')) requests.push(request.postData()!) })
  await viewport.focus()
  await viewport.press(mode)
  await viewport.press('x')
  await viewport.press(mode === 'g' ? '2' : '9')
  if (mode === 'r') await viewport.press('0')
  await expect.poll(async () => (await structureImage()).equals(baseline)).toBe(false)
  expect(requests).toHaveLength(0)
  await viewport.press('Escape')
  await expect.poll(async () => (await structureImage()).equals(baseline)).toBe(true)
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()

  await viewport.press(mode)
  await viewport.press('x')
  await viewport.press('2')
  const response = page.waitForResponse(item => item.url().endsWith('/prompt-authoring:preview'))
  await viewport.press('Enter')
  const preview: PromptPreview = await (await response).json()
  expect(requests).toHaveLength(1)
  for (const value of initial.tracks.coordinates.values) {
    // Handles belong to a projection; compare residues across projections by ID.
    const residue = initial.residues.find(item => item.residue_handle === value.residue_handle)!
    const updated = preview.residues.find(item => item.residue_id === residue.residue_id)!
    const after = preview.tracks.coordinates.values.find(item => item.residue_handle === updated.residue_handle)!
    if (value.residue_handle === first.residue_handle) expect(after.value).not.toEqual(value.value)
    else expect(after.value).toEqual(value.value)
  }
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect.poll(async () => (await structureImage()).equals(baseline)).toBe(true)
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '重做', exact: true }).click()
  await expect.poll(async () => (await structureImage()).equals(baseline)).toBe(false)
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeEnabled()
  await expect(page.locator('.ps-session-state')).toContainText('有未保存修改')
})
