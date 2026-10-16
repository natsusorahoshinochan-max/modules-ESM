import { matrixCell } from '../support/matrix-cell'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import type { ProjectMetadata, PromptPreview, PromptSnapshot, WorkflowDraft } from '../../src/protocol/client'
import type { ProjectWorkspace } from '../../src/project-workspace'

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

test('API-copied example edits the exact Prompt preview without publishing workspace changes', async ({ page, request }) => {
  const projects = (await (await request.get('/api/v2/projects')).json()).projects as ProjectMetadata[]
  const seed = projects.find(project => project.project_kind === 'default_example')!
  const copied = await request.post(`/api/v2/projects/${seed.id}:copy`, { data: { name: `Flat Prompt ${crypto.randomUUID().slice(0, 8)}` } })
  expect(copied.status()).toBe(201)
  const project = await copied.json() as ProjectMetadata
  const base = `/api/v2/projects/${project.id}`
  const draft = await (await request.get(`${base}/workflow/draft`)).json() as WorkflowDraft
  const author = draft.workflow.nodes.find(node => node.node_type_id === 'prompt_authoring.author')!
  await page.goto('/')
  await openProject(page, project.name)
  await expect(page.getByRole('navigation', { name: '流程阶段', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '适合视图', exact: true }).click()
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === author.node_id)
  await page.getByTestId(`rf__node-${author.node_id}`).getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
  const prompt = await (await opening).json() as PromptSnapshot
  const masked = prompt.tracks.sequence.values.find(item => item.value === null && prompt.residues.some(residue => residue.residue_handle === item.residue_handle && residue.state !== 'pending-delete'))!
  await (await matrixCell(page, masked.residue_handle, 'sequence')).click()
  await page.getByLabel('指定氨基酸', { exact: true }).fill('G')
  const previewing = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:preview') && response.request().postDataJSON().node_id === author.node_id)
  await page.getByRole('button', { name: 'Specify', exact: true }).click()
  const preview = await (await previewing).json() as PromptPreview
  expect(preview.diagnostics).toEqual([])
  expect(preview.tracks.sequence.values.find(item => item.residue_handle === masked.residue_handle)?.value).toBe('G')
  const before = await (await request.get(`${base}/workspace`)).json() as ProjectWorkspace
  await expect((await matrixCell(page, masked.residue_handle, 'sequence')).locator('strong')).toHaveText('G')
  await expect(page.locator('.ps-session-state')).toContainText('有未保存修改')
  expect((await (await request.get(`${base}/workspace`)).json()) as ProjectWorkspace).toEqual(before)
  expect(before.draft!.workflow).toEqual(draft.workflow)
})

test('viewing and editing a saved version keeps persistent work and the named version unchanged', async ({ page, request }) => {
  const { project, ui } = await createWorkspace(request)
  const prefix = `/api/v2/projects/${project.id}`
  const version = await (await request.post(`${prefix}/versions`, { data: { name: 'Original layout' } })).json()
  const latestUi = { canvas: { positions: { import: { x: 430, y: 260 } }, collapsed: [] } }
  await request.put(`${prefix}/workspace`, { data: { ui_state: latestUi } })
  const originalWork = await (await request.get(`${prefix}/workspace`)).json()
  await page.goto('/')
  await openProject(page, project.name)
  const dialog = await showProjects(page)
  await dialog.getByRole('button', { name: '查看版本', exact: true }).click()
  await expect(page.getByTestId('rf__node-import').locator('article')).not.toHaveClass(/is-collapsed/)
  expect((await (await request.get(`${prefix}/workspace`)).json())).toEqual(originalWork)
  const publications: string[] = []
  page.on('request', outgoing => {
    if (outgoing.method() === 'PUT' && outgoing.url().endsWith(`${prefix}/workspace`)
      || outgoing.method() === 'POST' && outgoing.url().endsWith(`/versions/${version.version_id}:fork`)) publications.push(outgoing.url())
  })
  await page.getByTestId('rf__node-import').locator('.node-header .icon-button').click()
  await expect(page.getByTestId('rf__node-import').locator('article')).toHaveClass(/is-collapsed/)
  expect(publications).toEqual([])
  expect((await (await request.get(`${prefix}/workspace`)).json())).toEqual(originalWork)
  expect((await (await request.get(`${prefix}/versions/${version.version_id}`)).json()).workspace.ui_state).toEqual(ui)
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
  expect((await (await request.get(`${prefix}/workflow/draft`)).json()).workflow).toEqual(workflow)
  const beforeConfirmation = await (await request.get(`${prefix}/workspace`)).json()
  const publications: unknown[] = []
  page.on('request', outgoing => {
    if (outgoing.method() === 'PUT' && outgoing.url().endsWith(`${prefix}/workspace`)) publications.push(outgoing.postDataJSON())
  })
  const beforeNodes = await page.locator('[data-testid^="rf__node-"]').count()
  await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).not.toBeVisible()
  await expect(page.locator('[data-testid^="rf__node-"]')).toHaveCount(beforeNodes + 1)
  expect(publications).toEqual([])
  expect((await (await request.get(`${prefix}/workspace`)).json())).toEqual(beforeConfirmation)
  await expect(page.getByRole('button', { name: '打开 Prompt Studio', exact: true })).toBeVisible()
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

for (const choice of ['保存后退出', '放弃修改退出'] as const) {
  test(`unsaved project switch supports cancel and ${choice}`, async ({ page, request }) => {
    const { project } = await createWorkspace(request)
    const destination = await createWorkspace(request)
    const base = `/api/v2/projects/${project.id}`
    await page.goto('/')
    await openProject(page, project.name)
    const before = await (await request.get(`${base}/workspace`)).json() as ProjectWorkspace
    await page.getByTestId('rf__node-import').locator('.node-header .icon-button').click()
    await expect(page.getByTestId('rf__node-import').locator('article')).toHaveClass(/is-collapsed/)
    expect(await (await request.get(`${base}/workspace`)).json()).toEqual(before)
    const manager = await showProjects(page)
    await manager.getByRole('button').filter({ has: page.getByText(destination.project.name, { exact: true }) }).click()
    await manager.getByRole('button', { name: '打开项目', exact: true }).click()
    const unsaved = page.getByRole('dialog', { name: '尚未保存的修改', exact: true })
    await unsaved.getByRole('button', { name: '取消退出，继续编辑', exact: true }).click()
    await expect(page.locator('.project-identity strong')).toHaveText(project.name)
    expect(await (await request.get(`${base}/workspace`)).json()).toEqual(before)
    await manager.getByRole('button', { name: '打开项目', exact: true }).click()
    await unsaved.getByRole('button', { name: choice, exact: true }).click()
    await expect(page.locator('.project-identity strong')).toHaveText(destination.project.name)
    const after = await (await request.get(`${base}/workspace`)).json() as ProjectWorkspace
    if (choice === '放弃修改退出') expect(after).toEqual(before)
    else {
      expect(after.draft!.workflow).toEqual(before.draft!.workflow)
      expect((after.ui_state.canvas as { collapsed: string[] }).collapsed).toContain('import')
    }
  })
}

test('unsaved run cancels without writing, failed save does not start, successful explicit save allows execution', async ({ page, request }) => {
  const { project } = await createWorkspace(request)
  const prefix = `/api/v2/projects/${project.id}`
  await page.goto('/')
  await openProject(page, project.name)
  await page.getByTestId('rf__node-import').locator('.node-header .icon-button').click()
  const writes: string[] = []
  page.on('request', outgoing => {
    if (outgoing.method() === 'PUT' && outgoing.url().endsWith(`${prefix}/workspace`) || outgoing.method() === 'POST' && outgoing.url().endsWith(`${prefix}/runs`)) writes.push(outgoing.url())
  })
  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  await page.getByRole('dialog', { name: '保存后运行' }).getByRole('button', { name: '取消', exact: true }).click()
  expect(writes).toEqual([])
  await page.route(`**${prefix}/workspace`, async route => {
    if (route.request().method() === 'PUT') await route.fulfill({ status: 500, json: { error: { code: 'storage_error', message: 'save unavailable' } } })
    else await route.continue()
  })
  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: '保存后运行' })
  await confirmation.getByRole('button', { name: '保存并运行', exact: true }).click()
  await expect(confirmation.getByRole('alert')).toContainText('save unavailable')
  expect(writes.filter(url => url.endsWith('/runs'))).toEqual([])
  await page.unroute(`**${prefix}/workspace`)
  await confirmation.getByRole('button', { name: '保存并运行', exact: true }).click()
  const run = page.getByRole('dialog', { name: '确认运行范围' })
  await expect(run).toBeVisible()
  await run.getByRole('button', { name: '准备并查看范围', exact: true }).click()
  await run.getByRole('button', { name: '开始运行已确认范围', exact: true }).click()
  await expect.poll(() => writes.filter(url => url.endsWith('/runs')).length).toBe(1)
  expect(writes[0]).toContain('/workspace')
})

test('teaching edits create exactly one personal project on manual save and keep the original unchanged', async ({ page, request }) => {
  const projects = (await (await request.get('/api/v2/projects')).json()).projects as ProjectMetadata[]
  const seed = projects.find(project => project.project_kind === 'default_example')!
  const before = await (await request.get(`/api/v2/projects/${seed.id}/workspace`)).json() as ProjectWorkspace
  const copies: string[] = []
  page.on('request', outgoing => { if (outgoing.method() === 'POST' && outgoing.url().endsWith(`${seed.id}:copy`)) copies.push(outgoing.url()) })
  await page.goto('/')
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  const source = page.getByRole('dialog', { name: '添加来源', exact: true })
  await source.getByLabel('来源 Chain 1 length').fill('3')
  await source.getByRole('button', { name: '进入 Prompt 预览', exact: true }).click()
  await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
  expect(copies).toEqual([])
  await expect(page.locator('.project-identity strong')).toHaveText(seed.name)
  const saving = page.waitForResponse(response => response.url().endsWith(`${seed.id}:copy`))
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  const personal = await (await saving).json() as ProjectMetadata
  await expect(page.locator('.project-identity strong')).toHaveText(personal.name)
  expect(copies).toHaveLength(1)
  expect(personal.latest_run_id).toBeNull()
  expect(personal.reference_results_project_id).toBeNull()
  expect(await (await request.get(`/api/v2/projects/${seed.id}/workspace`)).json()).toEqual(before)
  const saved = await (await request.get(`/api/v2/projects/${personal.id}/workspace`)).json() as ProjectWorkspace
  expect(saved.draft!.workflow.nodes.length).toBe(before.draft!.workflow.nodes.length + 1)
  await page.reload()
  await openProject(page, personal.name)
  await expect(page.locator('.project-identity strong')).toHaveText(personal.name)
})

test('tutorial input inspection and preview stay in memory until the complete project is saved', async ({ page, request }) => {
  const projects = (await (await request.get('/api/v2/projects')).json()).projects as ProjectMetadata[]
  const seed = projects.find(project => project.project_kind === 'default_example')!
  const prefix = `/api/v2/projects/${seed.id}`
  const beforeInputs = await (await request.get(`${prefix}/inputs`)).json()
  const beforeWorkspace = await (await request.get(`${prefix}/workspace`)).json()
  const copies: string[] = []
  page.on('request', outgoing => { if (outgoing.method() === 'POST' && outgoing.url().endsWith(`${seed.id}:copy`)) copies.push(outgoing.url()) })
  await page.goto('/')
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  const source = page.getByRole('dialog', { name: '添加来源', exact: true })
  await source.getByRole('button', { name: /FASTA → Prompt/ }).click()
  await source.getByRole('button', { name: '粘贴文本', exact: true }).click()
  await source.getByLabel('来源文本').fill('>tutorial input\nACDE\n')
  await source.getByRole('button', { name: '上传并检查输入', exact: true }).click()
  await expect(source.getByRole('heading', { name: '1 条记录 · 4 个残基' })).toBeVisible()
  await source.getByRole('button', { name: '进入 Prompt 预览', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).toBeVisible()
  expect(copies).toEqual([])
  expect(await (await request.get(`${prefix}/inputs`)).json()).toEqual(beforeInputs)
  expect(await (await request.get(`${prefix}/workspace`)).json()).toEqual(beforeWorkspace)
  await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
  const saving = page.waitForResponse(response => response.url().endsWith(`${seed.id}:copy`))
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  const personal = await (await saving).json() as ProjectMetadata
  await expect(page.locator('.project-identity strong')).toHaveText(personal.name)
  const savedInputs = (await (await request.get(`/api/v2/projects/${personal.id}/inputs`)).json()).inputs as Array<{ filename: string; project_input_ref: string }>
  const input = savedInputs.find(item => item.filename === 'input.fasta')!
  expect(input).toBeTruthy()
  const saved = await (await request.get(`/api/v2/projects/${personal.id}/workspace`)).json() as ProjectWorkspace
  expect(saved.draft!.workflow.nodes.some(node => node.node_parameters.project_input_ref === input.project_input_ref)).toBe(true)
  expect(await (await request.get(`${prefix}/inputs`)).json()).toEqual(beforeInputs)
  expect(copies).toHaveLength(1)
})

test('missing Node Types and Bindings open as placeholders and manual save preserves their graph and opaque configuration', async ({ page, request }) => {
  const { project, workflow, ui } = await createWorkspace(request)
  const prefix = `/api/v2/projects/${project.id}`
  const retainedWorkflow = {
    ...workflow,
    nodes: [
      { ...workflow.nodes[0], binding_id: 'uninstalled.import.direct', binding_parameters: { opaque: { choices: [null, 'keep', 3] } } },
      { node_id: 'missing', node_type_id: 'uninstalled.transform', binding_id: 'uninstalled.transform.direct', node_parameters: { document: { arbitrary: [false, { preserve: 'exact' }] } }, binding_parameters: { temperature: 0.25 } },
    ],
    edges: [{ source_node_id: 'import', source_port: 'sequence', target_node_id: 'missing', target_port: 'original' }],
  }
  const retainedUi = { ...ui, canvas: { ...ui.canvas, positions: { ...ui.canvas.positions, missing: { x: 520, y: 140 } } }, module_state: { opaque: ['retained'] } }
  const saved = await request.put(`${prefix}/workspace`, { data: { workflow: retainedWorkflow, ui_state: retainedUi } })
  expect(saved.status()).toBe(200)
  await page.goto('/')
  await openProject(page, project.name)
  await expect(page.getByTestId('rf__node-import')).toContainText('缺失模块')
  await expect(page.getByTestId('rf__node-missing')).toContainText('缺失模块')
  await expect(page.locator('.react-flow__edge')).toHaveCount(1)
  await page.getByTestId('rf__node-missing').locator('.node-header .icon-button').click()
  expect((await (await request.get(`${prefix}/workspace`)).json()).ui_state).toEqual(retainedUi)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect.poll(async () => (await (await request.get(`${prefix}/workspace`)).json()).ui_state.canvas.collapsed).toContain('missing')
  const after = await (await request.get(`${prefix}/workspace`)).json() as ProjectWorkspace
  expect(after.draft!.workflow).toEqual(retainedWorkflow)
  expect(after.ui_state.module_state).toEqual(retainedUi.module_state)
  expect((after.ui_state.canvas as typeof retainedUi.canvas).positions).toEqual(retainedUi.canvas.positions)
  await page.reload()
  await openProject(page, project.name)
  await expect(page.getByTestId('rf__node-missing').locator('article')).toHaveClass(/is-collapsed/)
  await expect(page.getByTestId('rf__node-missing')).toContainText('缺失模块')
  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  const run = page.getByRole('dialog', { name: '确认运行范围' })
  await run.getByRole('button', { name: '准备并查看范围', exact: true }).click()
  await expect(run.getByRole('alert')).toBeVisible()
  await expect(run.getByRole('button', { name: '开始运行已确认范围', exact: true })).toHaveCount(0)
})

test('historical runs retain exact selection across refresh and project reopen', async ({ page, request }) => {
  const { project, workflow } = await createWorkspace(request)
  const other = await createWorkspace(request)
  const prefix = `/api/v2/projects/${project.id}`
  const completed: Array<{ run_id: string; status: string }> = []
  for (const bad of [false, true]) {
    if (bad) {
      const input = await (await request.post(`${prefix}/inputs`, { data: { filename: 'multiple.fa', content_base64: Buffer.from('>a\nACDE\n>b\nGGGG\n').toString('base64') } })).json()
      workflow.nodes.push({ ...workflow.nodes[0], node_id: 'invalid-import', node_parameters: { project_input_ref: input.project_input_ref } })
    }
    const commit = await (await request.post(`${prefix}/workflow:commit`, { data: { workflow } })).json()
    const receipt = await (await request.post(`${prefix}/runs`, { data: { workflow_commit_id: commit.workflow_commit_id, client_request_id: crypto.randomUUID(), scope: { mode: 'full', node_ids: [] } } })).json()
    await expect.poll(async () => (await (await request.get(`${prefix}/runs/${receipt.run_id}`)).json()).status).toBe(bad ? 'failed' : 'succeeded')
    completed.push({ run_id: receipt.run_id, status: bad ? 'failed' : 'succeeded' })
  }
  await page.goto('/')
  await openProject(page, project.name)
  const workspaceWrites: string[] = []
  page.on('request', outgoing => { if (outgoing.method() === 'PUT' && outgoing.url().endsWith(`${prefix}/workspace`)) workspaceWrites.push(outgoing.url()) })
  await page.getByRole('button', { name: '运行历史', exact: true }).click()
  const history = page.getByRole('dialog', { name: '项目运行历史', exact: true })
  for (const run of completed) {
    const row = history.getByRole('listitem').filter({ hasText: run.run_id })
    await expect(row).toContainText(run.status)
    await row.getByRole('button', { name: '打开运行', exact: true }).click()
    await expect(row.getByRole('button', { name: '打开运行', exact: true })).toHaveAttribute('aria-current', 'true')
    await expect(history.getByRole('region', { name: '选中运行状态' })).toContainText(run.status)
  }
  const first = history.getByRole('listitem').filter({ hasText: completed[0].run_id })
  await first.getByRole('button', { name: '打开运行', exact: true }).click()
  await history.getByRole('button', { name: '关闭', exact: true }).click()
  await page.reload()
  await expect(page.locator('.project-identity strong')).toHaveText(project.name)
  await expect(page.locator('.run-progress-id')).toHaveText(completed[0].run_id)
  await openProject(page, other.project.name)
  await openProject(page, project.name)
  await expect(page.locator('.run-progress-id')).toHaveText(completed[0].run_id)
  await page.getByRole('button', { name: '查看结果', exact: true }).click()
  await expect(page.locator('.result-stages')).toContainText(completed[0].run_id)
  await expect(page.locator('.result-stages')).not.toContainText(completed[1].run_id)
  expect(workspaceWrites).toEqual([])
})

test('an active project run keeps editing locked while viewing a completed historical run', async ({ page, request }) => {
  const { project, workflow } = await createWorkspace(request)
  const prefix = `/api/v2/projects/${project.id}`
  const commit = await (await request.post(`${prefix}/workflow:commit`, { data: { workflow } })).json()
  const runs: string[] = []
  for (let index = 0; index < 2; index++) {
    const receipt = await (await request.post(`${prefix}/runs`, { data: { workflow_commit_id: commit.workflow_commit_id, client_request_id: crypto.randomUUID(), scope: { mode: 'full', node_ids: [] } } })).json()
    await expect.poll(async () => (await (await request.get(`${prefix}/runs/${receipt.run_id}`)).json()).status).toBe('succeeded')
    runs.push(receipt.run_id)
  }
  // Hold the public execution-state seam active while reading real persisted results.
  await page.route(`**${prefix}/runs`, async route => {
    const response = await route.fetch()
    const body = await response.json()
    body.runs.find((run: { run_id: string }) => run.run_id === runs[1]).status = 'running'
    await route.fulfill({ response, json: body })
  })
  await page.routeWebSocket(`**${prefix}/runs/${runs[1]}/events*`, () => {})
  await page.goto(`/?project=${project.id}&run=${runs[0]}`)
  await expect(page.locator('.run-progress-id')).toHaveText(runs[0])
  await expect(page.getByRole('button', { name: '保存项目', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '运行中', exact: true })).toBeDisabled()
  await expect(page.getByTestId('rf__node-import').locator('article')).toBeVisible()
})
