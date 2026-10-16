import { expect, test, type Page } from '@playwright/test'
import type { PromptSnapshot } from '../../src/protocol/client'

async function openMatrix(page: Page) {
  await page.goto('/')
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === 'prompt-composition-webui-3gb1.source.author')
  await page.getByRole('button', { name: '编辑 ProteinPrompt', exact: true }).click()
  const snapshot = await (await opening).json() as PromptSnapshot
  await page.locator('.ag-body-horizontal-scroll-viewport').evaluate(element => { element.scrollLeft = 0 })
  return snapshot
}
function gridCell(page: Page, handle: string, track = 'sequence') {
  return page.locator(`[row-id="${track}"] [role="gridcell"][col-id="${handle}"]`)
}

test('fast Tab commits remain separate undo operations while a preview is in flight', async ({ page }) => {
  const snapshot = await openMatrix(page)
  const [first, second] = snapshot.residues.filter(item => item.state !== 'pending-delete')
  const original = (handle: string) => String(snapshot.tracks.sequence.values.find(item => item.residue_handle === handle)!.value ?? 'Mask')
  let release: (() => void) | undefined
  let seenFirst = false
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/prompt-authoring:preview', async route => {
    if (!seenFirst) { seenFirst = true; await gate }
    await route.continue()
  })
  await gridCell(page, first.residue_handle).click()
  await page.keyboard.press('W')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Y')
  await page.keyboard.press('Tab')
  await expect(gridCell(page, first.residue_handle)).toContainText('W')
  await expect(gridCell(page, second.residue_handle)).toContainText('Y')
  release!()
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(gridCell(page, second.residue_handle)).toContainText(original(second.residue_handle))
  await expect(gridCell(page, first.residue_handle)).toContainText('W')
  await page.keyboard.press('ControlOrMeta+z')
  await expect(gridCell(page, first.residue_handle)).toContainText(original(first.residue_handle))
  await page.keyboard.press('ControlOrMeta+Shift+z')
  await expect(gridCell(page, first.residue_handle)).toContainText('W')
})

test('SS8 accepts the first typed key, Enter moves tracks and Tab moves residues without losing Esc cancellation', async ({ page }) => {
  const snapshot = await openMatrix(page)
  const [first, second] = snapshot.residues.filter(item => item.state !== 'pending-delete')
  const firstSS8 = gridCell(page, first.residue_handle, 'secondary_structure')
  await firstSS8.click()
  await page.keyboard.press('H')
  const editor = page.locator('.ag-cell-inline-editing input')
  await expect(editor).toHaveValue('H')
  await editor.click()
  await expect(editor).toBeFocused()
  await expect(editor).toHaveValue('H')
  await editor.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true })
  await expect(editor).toHaveValue('H')
  await editor.press('Enter')
  await expect(gridCell(page, first.residue_handle, 'sasa')).toBeFocused()
  await expect(firstSS8).toContainText('H')
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeEnabled()

  await firstSS8.click()
  await page.keyboard.press('F2')
  await expect(editor).toHaveValue('H')
  await editor.fill('C')
  await editor.press('Escape')
  await expect(editor).toHaveCount(0)
  await expect(firstSS8).toContainText('H')

  await page.keyboard.press('E')
  await expect(editor).toHaveValue('E')
  await editor.press('Tab')
  await expect(gridCell(page, second.residue_handle, 'secondary_structure').locator('input')).toBeFocused()
  await expect(firstSS8).toContainText('E')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(firstSS8).toContainText('H')
})

test('mouse Ctrl selection preserves the first cell, exposes actual values, and invalid input remains editable', async ({ page }) => {
  const snapshot = await openMatrix(page)
  const [first, second] = snapshot.residues.filter(item => item.state !== 'pending-delete')
  await gridCell(page, first.residue_handle).click()
  const actual = snapshot.tracks.sequence.values.find(item => item.residue_handle === first.residue_handle)!.value
  await expect(page.getByLabel('指定氨基酸', { exact: true })).toHaveValue(typeof actual === 'string' ? actual : '')
  await gridCell(page, second.residue_handle).click({ modifiers: ['ControlOrMeta'] })
  await expect(page.locator('.ag-cell.rm-selected')).toHaveCount(2)
  await gridCell(page, first.residue_handle).click()
  await page.keyboard.press('F2')
  const input = page.locator('.ag-cell-inline-editing input')
  await input.fill('!')
  await input.press('Enter')
  await expect(input).toHaveValue('!')
  await input.press('Escape')
  await expect(input).toHaveCount(0)
  await expect(gridCell(page, first.residue_handle)).toContainText(String(actual ?? 'Mask'))
})

test('matrix stays reachable in the resizable desktop and narrow two-view layouts', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1288, height: 989 })
  await openMatrix(page)
  const separator = page.getByRole('separator', { name: '调整结构与矩阵宽度' })
  await separator.focus()
  const before = Number(await separator.getAttribute('aria-valuenow'))
  await separator.press('ArrowRight')
  await expect(separator).toHaveAttribute('aria-valuenow', String(before + 2))
  await expect(page.getByRole('grid')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('prompt-desktop-1288.png'), fullPage: true })
  await page.setViewportSize({ width: 1024, height: 800 })
  await page.getByRole('tab', { name: '结构视图', exact: true }).click()
  await expect(page.locator('.ps-structure-card')).toBeVisible()
  await expect(page.getByRole('grid')).not.toBeVisible()
  await page.getByRole('tab', { name: '残基矩阵', exact: true }).click()
  await expect(page.getByRole('grid')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('prompt-narrow-matrix-1024.png'), fullPage: true })
})


test('Function composition confirmation keeps the label draft until a separate Enter commits', async ({ page }) => {
  const snapshot = await openMatrix(page)
  const first = snapshot.residues.find(item => item.state !== 'pending-delete')!
  await gridCell(page, first.residue_handle, 'function').getByRole('button', { name: /编辑 .* Function/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Function 区间', exact: true })
  const label = dialog.getByLabel('Function label', { exact: true })
  await label.fill('活性位点')
  await label.dispatchEvent('compositionstart', { data: '' })
  await label.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true })
  await expect(label).toHaveValue('活性位点')
  await expect(dialog.getByRole('button', { name: 'Add', exact: true })).toBeEnabled()
  await expect(dialog.getByRole('button', { name: '应用操作', exact: true })).toHaveCount(0)
  await label.dispatchEvent('compositionend', { data: '活性位点' })
  const previewing = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:preview'))
  await label.press('Enter')
  expect((await previewing).status()).toBe(200)
  await expect(dialog.getByRole('button', { name: '应用操作', exact: true })).toBeEnabled()
})


test('embedded Coordinates control opens the clicked residue without a preceding cell selection', async ({ page }) => {
  const snapshot = await openMatrix(page)
  const first = snapshot.residues.find(item => item.state !== 'pending-delete')!
  await gridCell(page, first.residue_handle, 'coordinates').getByRole('button', { name: /编辑 .* Coordinates/ }).click()
  await expect(page.getByRole('dialog', { name: '精确结构参数', exact: true })).toBeVisible()
  await expect(page.locator('.rm-context strong')).toHaveText(`${first.chain_id}${first.residue_label} · Coordinates`)
})
