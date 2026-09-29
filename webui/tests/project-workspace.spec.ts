import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

async function createWorkspace(request: APIRequestContext) {
  const name = `Workspace ${crypto.randomUUID().slice(0, 8)}`
  const created = await request.post('/api/v2/projects', { data: { name } })
  const project = await created.json()
  const uploaded = await request.post(`/api/v2/projects/${project.id}/inputs`, { data: { filename: 'protein.fa', content_base64: Buffer.from('>protein\nACDE\n').toString('base64') } })
  const input = await uploaded.json()
  const workflow = { schema_version: '2.1.0', workflow_id: project.id, nodes: [{ node_id: 'import', node_type_id: 'protein_io.import_sequence', binding_id: 'protein_io.import_sequence.direct', node_parameters: { project_input_ref: input.project_input_ref }, binding_parameters: {} }], edges: [], observation_selectors: [], selection_objectives: [] }
  const ui = { canvas: { positions: { import: { x: 120, y: 140 } }, collapsed: [] } }
  await request.put(`/api/v2/projects/${project.id}/workspace`, { data: { workflow, ui_state: ui } })
  return { project, workflow, ui, input }
}

async function showProjects(page: Page) {
  await page.getByRole('button', { name: '项目', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '项目与版本' })).toBeVisible()
  return page.getByRole('dialog', { name: '项目与版本' })
}

async function openProject(page: Page, name: string) {
  const dialog = await showProjects(page)
  await dialog.getByRole('button').filter({ has: page.getByText(name, { exact: true }) }).click()
  await dialog.getByRole('button', { name: '打开项目', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.locator('.project-identity strong')).toHaveText(name)
}

test('viewing a version is read-only and the first layout edit preserves a return point', async ({ page, request }) => {
  const { project, workflow, ui } = await createWorkspace(request)
  const prefix = `/api/v2/projects/${project.id}`
  const version = await (await request.post(`${prefix}/versions`, { data: { name: 'Original layout' } })).json()
  const latestUi = { canvas: { positions: { import: { x: 430, y: 260 } }, collapsed: [] } }
  await request.put(`${prefix}/workspace`, { data: { ui_state: latestUi } })
  const originalWork = await (await request.get(`${prefix}/workspace`)).json()

  await page.goto('/')
  await openProject(page, project.name)
  const dialog = await showProjects(page)
  await dialog.getByRole('button', { name: '查看版本', exact: true }).click()
  await expect(page.getByText('正在查看版本“Original layout”；首次修改将另存为当前工作。')).toBeVisible()
  expect((await (await request.get(`${prefix}/workspace`)).json()).workspace_revision).toBe(originalWork.workspace_revision)
  const forkResponse = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith(`/versions/${version.version_id}:fork`))
  await page.getByTestId('rf__node-import').locator('.node-header .icon-button').click()
  const fork = await (await forkResponse).json()
  expect(fork.return_workspace_revision).toBe(originalWork.workspace_revision)
  expect(fork.draft.workflow).toEqual(workflow)
  expect(fork.ui_state.canvas.collapsed).toEqual(['import'])
  expect((await (await request.get(`${prefix}/versions/${version.version_id}`)).json()).workspace.ui_state).toEqual(ui)
  await expect(page.getByLabel('布局保存状态')).toContainText('布局已保存')
  await page.getByRole('button', { name: '返回原工作', exact: true }).click()
  await expect.poll(async () => (await (await request.get(`${prefix}/workspace`)).json()).ui_state).toEqual(latestUi)
  await expect(page.getByTestId('rf__node-import')).toHaveAttribute('style', /translate\(430px, 260px\)/)
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear() })
  await page.reload()
  await openProject(page, project.name)
  await expect(page.getByTestId('rf__node-import')).toHaveAttribute('style', /translate\(430px, 260px\)/)
  await expect(page.getByTestId('rf__node-import').locator('article')).not.toHaveClass(/is-collapsed/)
})

test('project manager copies only authoring content and supports rename, trash, restore and purge', async ({ page, request }) => {
  const { project, input } = await createWorkspace(request)
  await page.goto('/')
  await openProject(page, project.name)
  const dialog = await showProjects(page)
  const renamed = `${project.name} renamed`
  await dialog.getByLabel('项目名称', { exact: true }).fill(renamed)
  await dialog.getByRole('button', { name: '保存名称', exact: true }).click()
  await expect(dialog.getByRole('heading', { name: renamed, exact: true })).toBeVisible()
  const copyResponse = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith(`${project.id}:duplicate`))
  await dialog.getByRole('button', { name: '复制项目', exact: true }).click()
  const copied = await (await copyResponse).json()
  expect(copied.latest_run_id).toBeNull()
  expect(copied.reference_results_project_id).toBeNull()
  expect((await (await request.get(`/api/v2/projects/${copied.id}/versions`)).json()).versions).toEqual([])
  expect((await (await request.get(`/api/v2/projects/${copied.id}/inputs`)).json()).inputs[0].content_digest).toBe(input.content_digest)
  await expect(dialog.getByRole('heading', { name: copied.name, exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: '移至最近删除', exact: true }).click()
  await dialog.getByRole('tab', { name: /最近删除/ }).click()
  await dialog.getByRole('button').filter({ has: page.getByText(copied.name, { exact: true }) }).click()
  await dialog.getByRole('button', { name: '恢复项目', exact: true }).click()
  await expect(dialog.getByRole('button', { name: '移至最近删除', exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: '移至最近删除', exact: true }).click()
  await dialog.getByRole('tab', { name: /最近删除/ }).click()
  await dialog.getByRole('button').filter({ has: page.getByText(copied.name, { exact: true }) }).click()
  await dialog.getByRole('button', { name: '永久删除…', exact: true }).click()
  await dialog.getByRole('button', { name: '确认永久删除', exact: true }).click()
  await expect.poll(async () => (await (await request.get('/api/v2/projects/deleted')).json()).projects.some((item: { id: string }) => item.id === copied.id)).toBe(false)
  expect((await request.get(`/api/v2/projects/${project.id}/workspace`)).status()).toBe(200)
})

test('new Prompt sources stay staged until confirmed and cancel leaves the saved graph intact', async ({ page, request }) => {
  const { project, workflow } = await createWorkspace(request)
  const prefix = `/api/v2/projects/${project.id}`
  await page.goto('/')
  await openProject(page, project.name)
  const enterBlankPrompt = async () => {
    await page.getByRole('button', { name: '添加来源', exact: true }).click()
    const source = page.getByRole('dialog', { name: '添加来源', exact: true })
    await source.getByLabel('来源 Chain 1 length').fill('3')
    await source.getByRole('button', { name: '进入 Prompt 预览', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).toBeVisible()
    expect((await (await request.get(`${prefix}/workflow/draft`)).json()).workflow).toEqual(workflow)
  }
  await enterBlankPrompt()
  await page.getByRole('button', { name: '返回 Workflow', exact: true }).click()
  await expect(page.getByRole('button', { name: '添加来源', exact: true })).toBeVisible()
  expect((await (await request.get(`${prefix}/workflow/draft`)).json()).workflow).toEqual(workflow)

  await enterBlankPrompt()
  await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
  await expect(page.getByRole('heading', { name: '确认写回 Workflow', exact: true })).toBeVisible()
  expect((await (await request.get(`${prefix}/workflow/draft`)).json()).workflow).toEqual(workflow)
  const beforeConfirmation = await (await request.get(`${prefix}/workspace`)).json()
  const publications: unknown[] = []
  page.on('request', outgoing => {
    if (outgoing.method() === 'PUT' && outgoing.url().endsWith(`${prefix}/workspace`)) publications.push(outgoing.postDataJSON())
  })
  const applying = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await page.getByRole('button', { name: '确认并写回 Workflow', exact: true }).click()
  expect((await applying).status()).toBe(200)
  await expect(page.getByLabel('布局保存状态')).toContainText('布局已保存')
  const saved = await (await request.get(`${prefix}/workspace`)).json()
  expect(publications).toHaveLength(1)
  expect(saved.workspace_revision).toBe(beforeConfirmation.workspace_revision + 1)
  expect(publications[0]).toMatchObject({ workflow: saved.draft.workflow, ui_state: saved.ui_state })
  expect(saved.draft.workflow.nodes.map((node: { node_type_id: string }) => node.node_type_id)).toEqual(['protein_io.import_sequence', 'prompt_authoring.author'])
  expect(saved.draft.workflow.nodes[1].node_parameters.document.chains).toEqual([{ chain_id: 'A', length: 3 }])
  expect(Object.keys(saved.ui_state.canvas.positions)).toEqual(saved.draft.workflow.nodes.map((node: { node_id: string }) => node.node_id))
})

test('a delayed project-list refresh cannot overwrite an in-progress rename', async ({ page, request }) => {
  const { project } = await createWorkspace(request)
  await page.goto('/')
  await openProject(page, project.name)
  let releaseRefresh!: () => void
  let refreshReady!: () => void
  const released = new Promise<void>((resolve) => { releaseRefresh = resolve })
  const ready = new Promise<void>((resolve) => { refreshReady = resolve })
  let projectLists = 0
  await page.route('**/api/v2/projects', async (route) => {
    const response = await route.fetch()
    projectLists += 1
    if (projectLists === 2) { refreshReady(); await released }
    await route.fulfill({ response })
  })
  const dialog = await showProjects(page)
  await ready
  await expect(dialog.getByText('流程：Draft 1 已保存', { exact: false })).toBeVisible()
  const renamed = `${project.name} while refreshing`
  await dialog.getByLabel('项目名称', { exact: true }).fill(renamed)
  const reloadDetails = page.waitForRequest((item) => item.method() === 'GET' && item.url().endsWith(`/projects/${project.id}/workspace`))
  releaseRefresh()
  await reloadDetails
  await expect(dialog.getByLabel('项目名称', { exact: true })).toHaveValue(renamed)
  await expect(dialog.getByRole('button', { name: '保存名称', exact: true })).toBeEnabled()
  const renaming = page.waitForResponse((response) => response.request().method() === 'PATCH' && response.url().endsWith(`/projects/${project.id}`))
  await dialog.getByRole('button', { name: '保存名称', exact: true }).click()
  const response = await renaming
  expect(response.status()).toBe(200)
  expect(response.request().postDataJSON()).toEqual({ name: renamed })
  await expect(dialog.getByRole('heading', { name: renamed, exact: true })).toBeVisible()
})
