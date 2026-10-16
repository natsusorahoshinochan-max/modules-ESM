import { expect, test } from '@playwright/test'
import type { ProjectMetadata } from '../src/protocol/client'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5307'

test('first manual save of the default teaching example creates a personal project and preserves the original', async ({ page, request }) => {
  const projects = (await (await request.get(`${appUrl}/api/v2/projects`)).json()).projects as ProjectMetadata[]
  const teaching = projects.find(project => project.project_kind === 'default_example')!
  expect(teaching.seed).toBe(true)
  const sourceUrl = `${appUrl}/api/v2/projects/${teaching.id}`
  const original = await (await request.get(`${sourceUrl}/workspace`)).json()
  const inputs = await (await request.get(`${sourceUrl}/inputs`)).json()

  await page.goto(appUrl)
  await expect(page.locator('.project-identity')).toContainText(teaching.name)
  await expect(page.locator('.project-identity')).toContainText('只读示例')
  await page.getByRole('button', { name: '添加节点', exact: true }).click()
  await page.getByRole('dialog', { name: '添加节点', exact: true }).getByRole('button', { name: /Export protein sequence/ }).click()
  await expect(page.getByLabel('流程保存状态')).toContainText('未保存')
  expect(await (await request.get(`${sourceUrl}/workspace`)).json()).toEqual(original)
  expect((await (await request.get(`${appUrl}/api/v2/projects`)).json()).projects).toEqual(projects)

  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.getByLabel('流程保存状态')).toContainText('已保存')
  await expect(page.locator('.project-identity')).not.toContainText('只读示例')
  const personalId = new URL(page.url()).searchParams.get('project')!
  expect(personalId).not.toBe(teaching.id)
  const current = (await (await request.get(`${appUrl}/api/v2/projects`)).json()).projects as ProjectMetadata[]
  expect(current).toHaveLength(projects.length + 1)
  const personal = current.find(project => project.id === personalId)!
  expect(personal).toMatchObject({ seed: false, project_kind: 'personal', copied_from_project_id: teaching.id })
  const saved = await (await request.get(`${appUrl}/api/v2/projects/${personalId}/workspace`)).json()
  expect(saved.draft.workflow.nodes).toHaveLength(original.draft.workflow.nodes.length + 1)
  const added = saved.draft.workflow.nodes.find((node: { node_id: string }) => !original.draft.workflow.nodes.some((old: { node_id: string }) => old.node_id === node.node_id))
  expect(added.node_type_id).toBe('protein_io.export_sequence')
  expect(saved.draft.workflow.workflow_id).toBe(personalId)
  expect(await (await request.get(`${sourceUrl}/workspace`)).json()).toEqual(original)
  expect(await (await request.get(`${sourceUrl}/inputs`)).json()).toEqual(inputs)

  await page.reload()
  await expect(page.locator('.project-identity')).toContainText(personal.name)
  await expect(page.locator(`.react-flow__node[data-id="${added.node_id}"]`)).toBeVisible()
  await page.getByRole('button', { name: '项目', exact: true }).click()
  await page.getByRole('button').filter({ has: page.getByText(teaching.name, { exact: true }) }).click()
  await page.getByRole('button', { name: '打开项目', exact: true }).click()
  await expect(page.locator('.project-identity')).toContainText('只读示例')
  await expect(page.locator(`.react-flow__node[data-id="${added.node_id}"]`)).toHaveCount(0)
  await page.getByRole('button', { name: '项目', exact: true }).click()
  await page.getByRole('button', { name: `${personal.name} 个人项目`, exact: true }).click()
  await page.getByRole('button', { name: '打开项目', exact: true }).click()
  await expect(page.locator(`.react-flow__node[data-id="${added.node_id}"]`)).toBeVisible()
  expect(await (await request.get(`${appUrl}/api/v2/projects/${personalId}/workspace`)).json()).toEqual(saved)
})
