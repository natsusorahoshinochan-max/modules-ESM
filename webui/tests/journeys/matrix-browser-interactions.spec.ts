import { expect, test, type Page } from '@playwright/test'
import type { PromptPreview, PromptSnapshot } from '../../src/protocol/client'

async function openMatrix(page: Page) {
  await page.goto('/')
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === 'prompt-composition-webui-3gb1.source.author')
  await page.getByRole('button', { name: '编辑 ProteinPrompt', exact: true }).click()
  const snapshot = await (await opening).json() as PromptSnapshot
  await page.locator('.ag-body-horizontal-scroll-viewport').evaluate(element => { element.scrollLeft = 0 })
  return snapshot
}

function gridCell(page: Page, handle: string) {
  return page.locator(`.residue-matrix [row-id="sequence"] [role="gridcell"][col-id="${handle}"]`)
}

test('browser clipboard preserves residue order and rejects a whole invalid paste without an undo entry', async ({ page, context }) => {
  const snapshot = await openMatrix(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new URL(page.url()).origin })
  const [first, second, third] = snapshot.residues.filter(residue => residue.state !== 'pending-delete')
  const original = (handle: string) => String(snapshot.tracks.sequence.values.find(value => value.residue_handle === handle)!.value ?? 'Mask')
  const previewRequests: string[] = []
  page.on('request', request => { if (request.url().endsWith('/prompt-authoring:preview')) previewRequests.push(request.postData()!) })

  await gridCell(page, third.residue_handle).click()
  await gridCell(page, first.residue_handle).click({ modifiers: ['ControlOrMeta'] })
  await expect(page.locator('.ag-cell.rm-selected')).toHaveCount(2)
  await page.keyboard.press('ControlOrMeta+c')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`${original(first.residue_handle)}\t${original(third.residue_handle)}`)
  await expect(page.locator('.ag-cell-inline-editing')).toHaveCount(0)
  expect(previewRequests).toHaveLength(0)

  await page.evaluate(text => navigator.clipboard.writeText(text), 'W\tG')
  const previewing = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:preview'))
  await page.keyboard.press('ControlOrMeta+v')
  const response = await previewing
  expect(response.status()).toBe(200)
  const pasted = await response.json() as PromptPreview
  expect(pasted.tracks.sequence.values.find(value => value.residue_handle === first.residue_handle)!.value).toBe('W')
  expect(pasted.tracks.sequence.values.find(value => value.residue_handle === third.residue_handle)!.value).toBe('G')
  await expect(gridCell(page, first.residue_handle).locator('strong')).toHaveText('W')
  await expect(gridCell(page, third.residue_handle).locator('strong')).toHaveText('G')
  await expect(gridCell(page, second.residue_handle).locator('strong')).toHaveText(original(second.residue_handle))
  await expect(page.locator('.ag-cell-inline-editing')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeEnabled()
  expect(previewRequests).toHaveLength(1)

  await page.evaluate(text => navigator.clipboard.writeText(text), 'Y\t!')
  await page.keyboard.press('ControlOrMeta+v')
  await expect(page.locator('.residue-matrix').getByRole('alert')).toContainText('氨基酸')
  await expect(gridCell(page, first.residue_handle).locator('strong')).toHaveText('W')
  await expect(gridCell(page, third.residue_handle).locator('strong')).toHaveText('G')
  await expect(page.locator('.ag-cell.rm-selected')).toHaveCount(2)
  expect(previewRequests).toHaveLength(1)
  await page.keyboard.press('ControlOrMeta+z')
  await expect(gridCell(page, first.residue_handle).locator('strong')).toHaveText(original(first.residue_handle))
  await expect(gridCell(page, third.residue_handle).locator('strong')).toHaveText(original(third.residue_handle))
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
})

test('clipboard shortcuts in a native cell editor change only its draft until Enter', async ({ page, context }) => {
  const snapshot = await openMatrix(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new URL(page.url()).origin })
  const first = snapshot.residues.find(residue => residue.state !== 'pending-delete')!
  const requests: string[] = []
  page.on('request', request => { if (request.url().endsWith('/prompt-authoring:preview')) requests.push(request.postData()!) })
  const cell = gridCell(page, first.residue_handle)
  await cell.click()
  await cell.press('F2')
  const editor = cell.locator('input')
  await editor.press('ControlOrMeta+a')
  await page.evaluate(text => navigator.clipboard.writeText(text), 'G')
  await editor.press('ControlOrMeta+v')
  await expect(editor).toHaveValue('G')
  await expect(editor).toBeFocused()
  expect(requests).toHaveLength(0)
  await editor.press('ControlOrMeta+a')
  await editor.press('ControlOrMeta+c')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('G')
  expect(requests).toHaveLength(0)
  const previewing = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:preview'))
  await editor.press('Enter')
  expect((await previewing).status()).toBe(200)
  await expect(cell.locator('strong')).toHaveText('G')
  expect(requests).toHaveLength(1)
})

test('mouse and keyboard Shift selection retain the first anchor when extending and shrinking', async ({ page }) => {
  const snapshot = await openMatrix(page)
  const [first, second, third, fourth] = snapshot.residues.filter(residue => residue.state !== 'pending-delete')
  await gridCell(page, first.residue_handle).click()
  await gridCell(page, third.residue_handle).click({ modifiers: ['Shift'] })
  await expect(page.locator('.ag-cell.rm-selected')).toHaveCount(3)
  await gridCell(page, fourth.residue_handle).click({ modifiers: ['Shift'] })
  await expect(page.locator('.ag-cell.rm-selected')).toHaveCount(4)
  for (const residue of [first, second, third, fourth]) await expect(gridCell(page, residue.residue_handle)).toHaveClass(/rm-selected/)
  await expect(gridCell(page, fourth.residue_handle)).toBeFocused()
  await page.keyboard.press('Shift+ArrowLeft')
  await expect(page.locator('.ag-cell.rm-selected')).toHaveCount(3)
  for (const residue of [first, second, third]) await expect(gridCell(page, residue.residue_handle)).toHaveClass(/rm-selected/)
  await expect(gridCell(page, fourth.residue_handle)).not.toHaveClass(/rm-selected/)
  await expect(gridCell(page, third.residue_handle)).toBeFocused()
  await expect(page.locator('.ag-cell-inline-editing')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
})
