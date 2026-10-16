import { expect, test } from '@playwright/test'
import type { ProjectWorkspace } from '../../src/project-workspace'

test('external editor cancels, applies locally, saves, reopens and runs through the same package UI contract', async ({ page, request }) => {
  const project = await (await request.post('/api/v2/projects', { data: { name: 'External module editor' } })).json()
  const base = `/api/v2/projects/${project.id}`
  const workflow = { schema_version: '2.1.0', workflow_id: project.id, nodes: [{ node_id: 'source', node_type_id: 'contract_test.synthetic_candidate_source', binding_id: 'contract_test.synthetic_candidate_source.direct', node_parameters: { message: 'Original' }, binding_parameters: { repeat_count: 2 } }], edges: [], observation_selectors: [], selection_objectives: [] }
  expect((await request.put(`${base}/workspace`, { data: { workflow, ui_state: {} } })).status()).toBe(200)
  await page.goto('/')
  const editorAsset = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v2/module-ui/external.editor/assets/editor.js')
  await page.getByRole('button', { name: 'External editor', exact: true }).click()
  const assetResponse = await editorAsset
  expect(new URL(assetResponse.url()).search).toBe('')
  expect(assetResponse.status()).toBe(200)
  const dialog = page.getByRole('dialog', { name: 'External editor', exact: true })
  await dialog.getByLabel('External label').fill('Cancelled')
  await dialog.getByRole('button', { name: 'Cancel external edit' }).click()
  await expect(dialog).not.toBeVisible()
  await page.getByRole('button', { name: 'External editor', exact: true }).click()
  await expect(dialog.getByLabel('External label')).toHaveValue('Original')
  await dialog.getByLabel('External label').fill('Retained')
  await dialog.getByRole('button', { name: 'Apply external edit' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByLabel('流程保存状态')).toContainText('未保存')
  const before = await (await request.get(`${base}/workspace`)).json() as ProjectWorkspace
  expect(before.draft!.workflow.nodes[0].node_parameters.message).toBe('Original')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect.poll(async () => ((await (await request.get(`${base}/workspace`)).json()) as ProjectWorkspace).draft!.workflow.nodes[0].node_parameters.message).toBe('Retained')
  await page.reload()
  await page.getByRole('button', { name: 'External editor', exact: true }).click()
  await expect(dialog.getByLabel('External label')).toHaveValue('Retained')
  await dialog.getByRole('button', { name: 'Cancel external edit' }).click()
  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  const run = page.getByRole('dialog', { name: '确认运行范围' })
  await run.getByRole('button', { name: '准备并查看范围' }).click()
  const started = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`${base}/runs`))
  await run.getByRole('button', { name: '开始运行已确认范围' }).click()
  const receipt = await (await started).json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${receipt.run_id}`)).json()).status).toBe('succeeded')
  const committed = await (await request.get(`${base}/runs/${receipt.run_id}`)).json()
  const commit = await (await request.get(`${base}/workflow/commits/${committed.workflow_commit_id}`)).json()
  expect(commit.workflow.nodes[0].node_parameters.message).toBe('Retained')
})
