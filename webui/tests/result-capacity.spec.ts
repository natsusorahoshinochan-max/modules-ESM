import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { strFromU8, unzipSync } from 'fflate'
import type { ProjectMetadata, RunProjection, Workflow } from '../src/protocol/client'

test('a real 1000-record import pages results without loading structures and retains hidden checks', async ({ page, request }) => {
  const project = await (await request.post('/api/v2/projects', { data: { name: `Capacity ${crypto.randomUUID().slice(0, 8)}` } })).json() as ProjectMetadata
  const base = `/api/v2/projects/${project.id}`
  const input = await (await request.post(`${base}/inputs`, { data: { filename: '1000-records.fasta', content_base64: Buffer.from(Array.from({ length: 1000 }, (_, index) => `>record ${index + 1}\nACDEFG\n`).join('')).toString('base64') } })).json()
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: project.id, nodes: [{ node_id: 'batch', node_type_id: 'protein_io.import_sequences', binding_id: 'protein_io.import_sequences.direct', node_parameters: { project_input_ref: input.project_input_ref }, binding_parameters: {} }], edges: [], observation_selectors: [], selection_objectives: [] }
  await request.put(`${base}/workflow/draft`, { data: { workflow } })
  const committed = await (await request.post(`${base}/workflow:commit`, { data: { workflow } })).json()
  const started = await (await request.post(`${base}/runs`, { data: { workflow_commit_id: committed.workflow_commit_id, client_request_id: crypto.randomUUID() } })).json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${started.run_id}`)).json() as RunProjection).status, { timeout: 30_000 }).toBe('succeeded')
  const pageSizes: number[] = []
  const offsets: number[] = []
  const collectionUrl = `${base}/runs/${started.run_id}/results:collection`
  page.on('response', response => { if (response.url().endsWith(collectionUrl)) void response.json().then(value => pageSizes.push(value.items.length)) })
  let release!: () => void
  let received!: () => void
  const barrier = new Promise<void>(resolve => { release = resolve })
  const firstPageReady = new Promise<void>(resolve => { received = resolve })
  await page.route(`**${collectionUrl}`, async route => {
    offsets.push(route.request().postDataJSON().offset)
    if (route.request().postDataJSON().offset !== 0) return route.continue()
    const response = await route.fetch()
    expect(response.status()).toBe(200)
    received()
    await barrier
    await route.fulfill({ response })
  })
  try {
    await page.goto('/')
    await page.getByRole('button', { name: '项目', exact: true }).click()
    const projects = page.getByRole('dialog', { name: '项目与版本' })
    await projects.getByRole('button').filter({ has: page.getByText(project.name, { exact: true }) }).click()
    await projects.getByRole('button', { name: '打开项目', exact: true }).click()
    await firstPageReady
    await page.getByRole('button', { name: '打开 Results Workbench' }).click()
    await expect(page.locator('.results-explorer').getByRole('status')).toContainText(/加载/)
    await expect(page.getByRole('heading', { name: '尚无已发布候选', exact: true })).toHaveCount(0)
  } finally {
    release()
  }
  await expect(page.locator('.result-table input[type=checkbox]')).toHaveCount(50, { timeout: 20_000 })
  await expect(page.locator('.results-explorer').getByRole('status')).toHaveCount(0)
  await expect(page.locator('.results-explorer footer').first()).toContainText('1 / 20 · 1000 候选')
  expect(offsets).toEqual([0])
  await expect(page.getByLabel('搜索候选或序列')).toBeDisabled()
  await page.getByRole('button', { name: '加载全部候选以搜索、筛选和排序' }).click()
  await expect(page.getByLabel('搜索候选或序列')).toBeEnabled()
  expect(offsets).toEqual(Array.from({ length: 10 }, (_, index) => index * 100))
  expect(pageSizes).toHaveLength(10)
  expect(Math.max(...pageSizes)).toBeLessThanOrEqual(100)
  await expect(page.locator('.result-comparison canvas')).toHaveCount(0)
  await page.locator('.result-table input[type=checkbox]').first().check()
  const lastCandidate = page.locator('.result-table button').last()
  const filterName = await lastCandidate.textContent()
  await page.getByLabel('搜索候选或序列').fill(filterName!)
  await expect(page.locator('.result-controls')).toContainText('1 已勾选 · 1 项不在当前视图')
  await page.getByLabel('搜索候选或序列').fill('')
  await expect(page.locator('.result-table input[type=checkbox]').first()).toBeChecked()
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.locator('.results-explorer footer').first()).toContainText('2 / 20 · 1000 候选')
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出所选 · ZIP' }).click()
  const download = await downloading
  const files = unzipSync(await readFile((await download.path())!))
  expect(Object.keys(files).sort()).toEqual(['candidates.fasta', 'manifest.json', 'scores.csv'])
  expect(strFromU8(files['candidates.fasta'])).toContain('\nACDEFG\n')
  const manifest = JSON.parse(strFromU8(files['manifest.json']))
  expect(manifest.run_id).toBe(started.run_id)
  expect(manifest.workflow_commit_id).toBe(committed.workflow_commit_id)
  expect(manifest.candidates).toHaveLength(1)
  expect(manifest.without_structure).toHaveLength(1)
  expect(offsets).toEqual(Array.from({ length: 10 }, (_, index) => index * 100))
})
