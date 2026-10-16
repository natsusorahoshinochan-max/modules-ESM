import { expect, test } from '@playwright/test'

test('module settings save a service address and retain it after reopening', async ({ page }) => {
  await page.goto(process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5189')
  await page.getByRole('button', { name: '模块管理', exact: true }).click()
  await page.getByRole('button', { name: '运行设置', exact: true }).click()
  await page.getByLabel('运行路线', { exact: true }).selectOption('folding.fold.esmfold2_remote')
  await page.getByLabel('service_url', { exact: true }).fill('https://configured.example')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '模块运行设置' }).getByRole('status')).toHaveText('设置已保存')
  await page.reload()
  await page.getByRole('button', { name: '模块管理', exact: true }).click()
  await page.getByRole('button', { name: '运行设置', exact: true }).click()
  await page.getByLabel('运行路线', { exact: true }).selectOption('folding.fold.esmfold2_remote')
  await expect(page.getByLabel('service_url', { exact: true })).toHaveValue('https://configured.example')
})
