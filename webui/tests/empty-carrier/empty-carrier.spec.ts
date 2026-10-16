import { expect, test } from '@playwright/test'

test('empty production carrier creates, manually saves and reopens a project', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Protein Workbench' })).toBeVisible()
  await page.getByRole('button', { name: '创建项目', exact: true }).click()
  await expect(page.locator('.flow-canvas')).toBeVisible()
  await expect(page.locator('.react-flow__node')).toHaveCount(0)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.getByLabel('流程保存状态')).toContainText('已保存')
  const name = await page.locator('.project-identity strong').innerText()
  await page.reload()
  await expect(page.locator('.project-identity strong')).toHaveText(name)
  await expect(page.locator('.flow-canvas')).toBeVisible()
  await expect(page.getByLabel('流程保存状态')).toContainText('已保存')
})
