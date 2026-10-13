import { expect, type Page } from '@playwright/test'

export async function enterExampleStage(page: Page, order: number) {
  const navigation = page.getByRole('navigation', { name: '流程阶段', exact: true }).getByRole('button', { name: new RegExp(`^阶段 ${order} `) })
  const label = (await navigation.getAttribute('aria-label'))!.replace(/^阶段\s+\d+\s+/, '').trim()
  await navigation.click()
  await page.getByRole('button', { name: `进入组 ${label}`, exact: true }).click()
  await expect(page.getByRole('navigation', { name: '节点组路径', exact: true })).toContainText(label)
  await page.getByRole('button', { name: '适合视图', exact: true }).click()
}
