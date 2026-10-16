import { expect, type Page } from '@playwright/test'

export async function matrixCell(page: Page, handle: string, track: string) {
  const cell = page.locator(`[data-cell="${handle}:${track}"]`)
  if (!await cell.count()) {
    const scroller = page.locator('.ag-body-horizontal-scroll-viewport')
    const { width, maximum } = await scroller.evaluate(element => ({ width: element.clientWidth, maximum: element.scrollWidth - element.clientWidth }))
    for (let offset = 0; offset <= maximum + width; offset += Math.max(1, width / 2)) {
      await scroller.evaluate((element, left) => { element.scrollLeft = left }, Math.min(offset, maximum))
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
      if (await cell.count()) break
    }
  }
  await expect(cell).toBeAttached()
  await cell.scrollIntoViewIfNeeded()
  // Native editors replace the renderer; retain the domain row/column identity while editing.
  return page.locator(`.residue-matrix [row-id="${track}"] [role="gridcell"][col-id="${handle}"]`)
}
