import { expect, test, type Page } from '@playwright/test'
import { copyMatrix, emptyMatrixSelection, matrixTracks, parseMatrixValue, pasteMatrix, selectMatrixCell, type MatrixCell, type MatrixSelection } from '../src/residue-matrix'
import type { PromptSnapshot } from '../src/protocol/client'

const handles = ['first', 'second', 'third', 'fourth']
const cell = (handle: string): MatrixCell => ({ handle, track: 'sequence' })
const selected = (cells: MatrixCell[]): MatrixSelection => ({ active: cells[0], anchor: cells[0], cells })

test('Shift keeps its original anchor and Ctrl toggles only the requested cell', () => {
  const one = selectMatrixCell(emptyMatrixSelection, cell('first'), handles, matrixTracks, { shift: false, toggle: false })
  const two = selectMatrixCell(one, cell('third'), handles, matrixTracks, { shift: true, toggle: false })
  const three = selectMatrixCell(two, cell('fourth'), handles, matrixTracks, { shift: true, toggle: false })
  expect(three.cells.map(item => item.handle)).toEqual(handles)
  expect(three.anchor).toEqual(cell('first'))
  const toggled = selectMatrixCell(three, cell('second'), handles, matrixTracks, { shift: false, toggle: true })
  expect(toggled.cells.map(item => item.handle)).toEqual(['first', 'third', 'fourth'])
})

test('noncontiguous copy and paste use visible residue order, not click order', () => {
  const selection = selected([cell('third'), cell('first')])
  expect(copyMatrix(selection, handles, item => item.handle)).toBe('first\tthird')
  expect(pasteMatrix('W\tG', selection, handles)).toEqual([{ ...cell('first'), value: 'W' }, { ...cell('third'), value: 'G' }])
  expect(pasteMatrix('Y', selection, handles).map(item => item.value)).toEqual(['Y', 'Y'])
})

test('paste validates the whole selection and rejects mismatched or specialized cells', () => {
  const selection = selected([cell('first'), cell('third')])
  expect(() => pasteMatrix('W\t!', selection, handles)).toThrow('氨基酸')
  expect(() => pasteMatrix('W\tG\tL', selection, handles)).toThrow('范围不匹配')
  expect(() => pasteMatrix('2\n3', selected([{ handle: 'first', track: 'sasa' }]), handles)).toThrow('Function')
  expect(() => pasteMatrix('W\tG', selected([cell('fourth')]), handles)).toThrow('超出')
})

test('sequence accepts the current full alphabet and SS8 keeps explicit input normalization with the owner', () => {
  for (const value of 'ACDEFGHIKLMNPQRSTVWYBXZJUO') expect(parseMatrixValue('sequence', value)).toBe(value)
  expect(parseMatrixValue('secondary_structure', '-')).toBe('-')
  expect(() => parseMatrixValue('secondary_structure', 'P')).toThrow('SS8')
  expect(() => parseMatrixValue('secondary_structure', '_')).toThrow('SS8')
  expect(parseMatrixValue('sasa', '12.5')).toBe(12.5)
  expect(() => parseMatrixValue('sasa', 'Infinity')).toThrow('有限')
  expect(parseMatrixValue('sequence', 'Mask')).toBeNull()
})

async function openMatrix(page: Page) {
  await page.goto('/')
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === 'prompt-composition-webui-3gb1.source.author')
  await page.getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
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
  await page.keyboard.press('Control+z')
  await expect(gridCell(page, first.residue_handle)).toContainText(original(first.residue_handle))
  await page.keyboard.press('Control+Shift+z')
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
  await gridCell(page, second.residue_handle).click({ modifiers: ['Control'] })
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
