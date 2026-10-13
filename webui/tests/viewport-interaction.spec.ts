import { expect, test, type Page } from '@playwright/test'
import type { PromptSnapshot } from '../src/protocol/client'

async function openViewport(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: '编辑 ProteinPrompt', exact: true }).first().click()
  await page.locator('[data-cell$=":sequence"]').first().click()
  const viewport = page.getByLabel('三维结构视口', { exact: true })
  await expect(viewport.locator('canvas')).toBeVisible()
  return viewport
}

test('Escape cancels a captured box gesture before pointer release', async ({ page }) => {
  const viewport = await openViewport(page)
  const selection = page.getByLabel('当前选择', { exact: true }).locator('strong, small')
  await expect(selection).toHaveCount(2)
  const before = await selection.allTextContents()
  const bounds = await viewport.locator('.sv-canvas').boundingBox()
  expect(bounds).not.toBeNull()
  await viewport.focus()
  await viewport.press('b')
  await page.mouse.move(bounds!.x + 5, bounds!.y + 65)
  await page.mouse.down()
  await page.mouse.move(bounds!.x + bounds!.width - 5, bounds!.y + bounds!.height - 45)
  await expect(viewport.locator('.sv-box')).toBeVisible()
  await page.keyboard.press('Escape')
  await page.mouse.up()
  await expect(viewport.locator('.sv-box')).toHaveCount(0)
  await expect(selection).toHaveText(before)
})

test('modal transform isolates undo and cancellation restores its entry state', async ({ page }) => {
  const viewport = await openViewport(page)
  const selection = page.getByLabel('当前选择', { exact: true }).locator('strong, small')
  await expect(selection).toHaveCount(2)
  const before = await selection.allTextContents()
  await viewport.focus()
  await viewport.press('g')
  await viewport.press('x')
  await viewport.press('2')
  await expect(viewport.locator('.sv-status')).toContainText('Enter / 左键确认')
  await viewport.press('Control+z')
  await expect(viewport.locator('.sv-status')).toContainText('G 移动')
  await viewport.press('Meta+z')
  await expect(viewport.locator('.sv-status')).toContainText('G 移动')
  await viewport.press('Escape')
  await expect(viewport.locator('.sv-status')).not.toContainText('G 移动')
  await expect(selection).toHaveText(before)
  await expect(page.getByRole('button', { name: '应用操作', exact: true })).not.toBeVisible()
})

test('hover preserves matrix focus; offscreen structure picks reveal without stealing G and cancel preserves the camera', async ({ page }) => {
  await page.goto('/')
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === 'prompt-composition-webui-3gb1.source.author')
  await page.getByRole('button', { name: '编辑 ProteinPrompt', exact: true }).first().click()
  const snapshot = await (await opening).json() as PromptSnapshot
  const first = snapshot.residues.find(residue => residue.state !== 'pending-delete')!
  const firstCell = page.locator(`[row-id="sequence"] [role="gridcell"][col-id="${first.residue_handle}"]`)
  await firstCell.click()
  const viewport = page.getByLabel('三维结构视口', { exact: true })
  const bounds = (await viewport.locator('.sv-canvas').boundingBox())!
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(bounds.x + bounds.width / 2 + 35, bounds.y + bounds.height / 2 + 20, { steps: 4 })
  await page.mouse.up({ button: 'middle' })
  await page.keyboard.press('b')
  await expect.poll(() => viewport.locator('.sv-markers i').count()).toBeGreaterThan(15)
  const markerPositions = () => viewport.locator('.sv-markers i').evaluateAll(markers => markers.map(marker => marker.getAttribute('style')))
  const before = await markerPositions()
  const points = await viewport.locator('.sv-markers i').evaluateAll(markers => markers.map(marker => { const rect = marker.getBoundingClientRect(); return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 } }))
  await page.keyboard.press('Escape')
  // Use the visible hover identity to choose a real front-hit residue, rather
  // than assuming every projected CA is exposed through a cartoon surface.
  let target: { handle: string; identity: string; x: number; y: number } | undefined
  for (const point of points.reverse()) {
    if (point.x < bounds.x + 8 || point.x > bounds.x + bounds.width - 8 || point.y < bounds.y + 85 || point.y > bounds.y + bounds.height - 55) continue
    await page.mouse.move(point.x, point.y)
    const identity = (await viewport.locator('.sv-status').innerText()).split(' · ')[0]
    const residue = snapshot.residues.find(item => `${item.chain_id}${item.residue_label}` === identity && item.position > 15 && item.state === 'current')
    if (residue) { target = { ...point, identity, handle: residue.residue_handle }; break }
  }
  expect(target, 'the rendered structure exposes a residue beyond the first matrix columns').toBeDefined()
  const picked = target!
  await firstCell.click()
  const scroll = page.locator('.ag-body-horizontal-scroll-viewport')
  await scroll.evaluate(element => { element.scrollLeft = 0 })
  const scrollBefore = await scroll.evaluate(element => element.scrollLeft)
  const targetCell = page.locator(`[row-id="sequence"] [role="gridcell"][col-id="${picked.handle}"]`)
  await expect(targetCell).not.toBeInViewport()
  await expect(firstCell).toBeFocused()
  await page.mouse.move(picked.x, picked.y)
  await expect(viewport.locator('.sv-status')).toContainText(`${picked.identity} ·`)
  await expect(firstCell).toBeFocused()
  expect(await scroll.evaluate(element => element.scrollLeft)).toBe(scrollBefore)

  await page.mouse.click(picked.x, picked.y)
  await expect(targetCell).toBeInViewport()
  await expect(viewport).toBeFocused()
  await expect(page.getByLabel('当前选择', { exact: true }).locator('strong')).toHaveText(picked.identity)
  await page.keyboard.press('g')
  await expect(viewport.locator('.sv-status')).toContainText('G 移动')
  await page.keyboard.press('x')
  await page.keyboard.press('2')
  await expect(viewport.locator('.sv-status')).toContainText('Enter / 左键确认')
  await page.keyboard.press('Escape')
  await page.keyboard.press('b')
  await expect.poll(markerPositions).toEqual(before)
  await page.keyboard.press('Escape')
})
