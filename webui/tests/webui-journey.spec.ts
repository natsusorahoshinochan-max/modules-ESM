import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import type { PromptPreview, PromptSnapshot, RunEventEnvelope, RunProjection, Workflow } from '../src/protocol/client'

test('default 3GB1 workflow remains connected from authoring through a real run preview', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '3GB1 Local Redesign Example' })).toBeVisible()
  await expect(page.getByText(/36 GRAPH NODES/)).toBeVisible()
  await expect(page.getByText('只读示例')).toBeVisible()
  await expect(page.getByText(/61 条草稿连线/)).toBeVisible()
  await expect(page.getByTestId('rf__node-relation-generated-structure-parent').getByRole('heading', { name: 'Relate Candidates to their parents' })).toBeVisible()
  await expect(page.getByTestId('rf__node-relation-generated-pairs').getByRole('heading', { name: 'Invert a Candidate relation' })).toBeVisible()

  const examples = await (await page.request.get('/api/v2/projects')).json()
  const example = examples.projects.find((project: { project_kind: string }) => project.project_kind === 'default_example')
  expect(example.latest_run_id).toBeTruthy()
  const published = await (await page.request.get(`/api/v2/projects/${example.id}/runs/${example.latest_run_id}`)).json() as RunProjection
  expect(published.status).toBe('succeeded')
  expect(published.outputs.length).toBeGreaterThan(0)
  await expect(page.getByRole('button', { name: /Results [1-9]/ })).toBeEnabled({ timeout: 20_000 })

  const generationNode = page.getByTestId('rf__node-generate-paired')
  await generationNode.getByLabel('编辑参数').click()
  const seed = generationNode.getByLabel('有效种子')
  await seed.fill('1604')
  await seed.press('Tab')
  await expect(page.getByText('已自动保存')).toBeVisible()
  await expect(page.getByText('personal', { exact: true })).toBeVisible()

  const persistedEdge = { source_node_id: 'rank-generated', source_port: 'candidates', target_node_id: 'take-top-four', target_port: 'candidates' }
  const edge = page.getByRole('group', { name: 'Edge from rank-generated to take-top-four' })
  await edge.locator('.react-flow__edge-interaction').evaluate((element) => element.dispatchEvent(new MouseEvent('click', { bubbles: true })))
  await expect(edge).toHaveClass(/selected/)
  await edge.focus()
  const deletionSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow && !JSON.parse(response.request().postData()!).workflow.edges.some((item: typeof persistedEdge) => JSON.stringify(item) === JSON.stringify(persistedEdge)))
  await page.keyboard.press('Delete')
  const deletedDraft = await (await deletionSave).json()
  expect(deletedDraft.draft.workflow.edges).not.toContainEqual(persistedEdge)
  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow && JSON.parse(response.request().postData()!).workflow.edges.some((item: typeof persistedEdge) => JSON.stringify(item) === JSON.stringify(persistedEdge)))
  await page.getByRole('button', { name: '撤销画布修改' }).click()
  const undoResponse = await undoSave
  const restoredDraft = await undoResponse.json()
  expect(restoredDraft.draft.workflow.edges).toContainEqual(persistedEdge)
  const fetchedDraft = await page.request.get(undoResponse.url())
  expect((await fetchedDraft.json()).draft.workflow.edges).toContainEqual(persistedEdge)
  await expect(page.getByText('已撤销画布修改')).toBeVisible()

  await page.getByRole('button', { name: /打开 Prompt Studio/ }).click()
  await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).toBeVisible()
  await expect(page.getByText('57 residues')).toBeVisible()
  await page.getByRole('button', { name: '状态图例' }).click()
  await expect(page.locator('.ps-state-legend').getByText('pending-delete', { exact: true })).toBeVisible()
  const promptSave = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith('/workspace'))
  await page.getByRole('button', { name: '保存 ProteinPrompt' }).click()
  const promptResponse = await promptSave
  expect(promptResponse.request().postDataJSON()).not.toHaveProperty('ui_state')
  expect((await promptResponse.json()).ui_state).toEqual(restoredDraft.ui_state)
  await expect(page.getByText('Prompt 已保存')).toBeVisible()

  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '确认运行范围' })).toBeVisible()
  const previewResponse = page.waitForResponse(response => response.url().endsWith('/runs/preview'))
  await page.getByRole('button', { name: '准备并查看范围', exact: true }).click()
  const preview = await (await previewResponse).json()
  expect(preview.scope.execution_node_ids).toHaveLength(36)
  expect(preview.scope.reused_node_ids).toEqual([])
  await expect(page.getByRole('dialog').getByText('执行 36', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始运行已确认范围' })).toBeEnabled()
})

test('the Palette switches between research-purpose and provider classifications', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('button', { name: '按研究目的' })).toHaveClass(/active/)
  await expect(page.getByRole('button', { name: 'Author ProteinPrompt prompt_authoring' })).toBeVisible()
  await expect(page.getByText('collection', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: '按包 / 模型' }).click()

  await expect(page.getByRole('button', { name: '按包 / 模型' })).toHaveClass(/active/)
  await expect(page.getByRole('button', { name: '按研究目的' })).not.toHaveClass(/active/)
  await expect(page.getByText('collection_ops', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('simplefold_100M', { exact: true }).first()).toBeVisible()
})

test('Catalog parameter schemas expose required and Binding-specific fields', async ({ page }) => {
  await page.goto('/')

  await page.getByPlaceholder('搜索 active Catalog…').fill('Take an ordered Candidate prefix')
  const adding = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await page.getByRole('button', { name: 'Take an ordered Candidate prefix collection' }).dragTo(page.locator('.react-flow__pane'), { targetPosition: { x: 520, y: 620 } })
  const added = (await (await adding).json()).draft.workflow.nodes.at(-1)
  expect(added.node_type_id).toBe('collection_ops.take_candidates')
  const prefixNode = page.getByTestId(`rf__node-${added.node_id}`)
  await prefixNode.locator('summary[aria-label="编辑参数"]').click()
  await expect(prefixNode.getByLabel('保留数量')).toHaveValue('')

  const foldNode = page.locator('article.workflow-node').filter({ has: page.getByRole('heading', { name: 'Fold protein sequences' }) }).first()
  const foldModel = foldNode.getByRole('combobox', { name: 'Fold protein sequences的执行模型' })
  await foldModel.selectOption('folding.fold.simplefold_local')
  await foldNode.locator('summary[aria-label="编辑参数"]').click()
  const samplingSteps = foldNode.getByLabel('模型参数 · num_steps')
  await expect(samplingSteps).toHaveValue('50')
  await samplingSteps.fill('42')
  const parameterSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await samplingSteps.blur()
  await parameterSave
  const remoteSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await foldModel.selectOption('folding.fold.esmfold2_remote')
  await remoteSave
  const simpleFoldSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await foldModel.selectOption('folding.fold.simplefold_local')
  await simpleFoldSave
  await expect(foldNode.getByLabel('模型参数 · num_steps')).toHaveValue('42')
})

test('an unavailable Binding remains selectable for authoring without running a model', async ({ page }) => {
  await page.route('**/api/v2/catalog', async (route) => {
    const response = await route.fetch()
    const catalog = await response.json()
    const unavailable = catalog.availability.find((item: { binding: { contract_id: string } }) => item.binding.contract_id === 'esm3.generate_paired.biohub_open')
    unavailable.available = false
    await route.fulfill({ response, json: catalog })
  })
  await page.goto('/')

  const option = page.getByRole('combobox', { name: 'Generate paired sequences and structures with remote ESM-3的执行模型' }).locator('option[value="esm3.generate_paired.biohub_open"]')
  await expect(option).toBeEnabled()
  await expect(option).toHaveText('esm3-open-2024-03（不可用）')
  const saved = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await page.getByRole('combobox', { name: 'Generate paired sequences and structures with remote ESM-3的执行模型' }).selectOption('esm3.generate_paired.biohub_open')
  expect((await (await saved).json()).draft.workflow.nodes.find((node: { node_id: string }) => node.node_id === 'generate-paired').binding_id).toBe('esm3.generate_paired.biohub_open')
})

test('a model selector changes the pinned Execution Binding on an ordinary Node Instance', async ({ page }) => {
  await page.goto('/')

  const generationModel = page.getByRole('combobox', { name: 'Generate paired sequences and structures with remote ESM-3的执行模型' })
  await expect(generationModel).toHaveValue('esm3.generate_paired.biohub_medium')
  await expect(generationModel.locator('option')).toHaveText([
    /^esm3-medium-2024-08(?:（不可用）)?$/,
    /^esm3-open-2024-03(?:（不可用）)?$/,
    /^esm3_sm_open_v1(?:（不可用）)?$/,
  ])
  await expect(page.getByRole('combobox', { name: 'Fold protein sequences的执行模型' }).first().locator('option')).toHaveText([
    /^biohub\/ESMFold2(?:（不可用）)?$/,
    /^esmfold2-fast-2026-05(?:（不可用）)?$/,
    /^simplefold_100M(?:（不可用）)?$/,
  ])

  await generationModel.selectOption('esm3.generate_paired.biohub_open')

  await expect(generationModel).toHaveValue('esm3.generate_paired.biohub_open')
  await expect(page.getByText('已自动保存')).toBeVisible()
  await expect(page.getByText('personal', { exact: true })).toBeVisible()

  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await page.keyboard.press('Meta+z')
  const restored = await (await undoSave).json()
  expect(restored.draft.workflow.nodes.find((node: { node_id: string }) => node.node_id === 'generate-paired').binding_id).toBe('esm3.generate_paired.biohub_medium')
  await expect(generationModel).toHaveValue('esm3.generate_paired.biohub_medium')
})

test('dragging an ordinary Palette operation adds and saves a Node Instance', async ({ page }) => {
  await page.goto('/')

  const operation = page.getByRole('button', { name: 'Invert a Candidate relation collection_ops' })
  const canvas = page.locator('.react-flow__pane')
  await operation.dragTo(canvas, { targetPosition: { x: 520, y: 620 } })

  await expect(page.getByRole('heading', { name: 'Invert a Candidate relation' })).toHaveCount(2)
  await expect(page.getByText(/37 GRAPH NODES/)).toBeVisible()
  await expect(page.getByText('已自动保存')).toBeVisible()
  await expect(page.getByText('personal', { exact: true })).toBeVisible()

  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await page.keyboard.press('Meta+z')
  const restored = await (await undoSave).json()
  expect(restored.draft.workflow.nodes.some((node: { node_id: string; node_type_id: string }) => node.node_type_id === 'collection_ops.invert_relation' && node.node_id.startsWith('collection_ops-invert_relation-'))).toBe(false)
  await expect(page.getByText(/36 GRAPH NODES/)).toBeVisible()
})

test('a committed parameter edit can be undone with the keyboard', async ({ page }) => {
  await page.goto('/')
  const generationNode = page.getByTestId('rf__node-generate-paired')
  await generationNode.getByLabel('编辑参数').click()
  const seed = generationNode.getByLabel('有效种子')
  await expect(seed).toHaveValue('1603')
  await seed.fill('1604')
  const parameterSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await seed.press('Tab')
  await parameterSave

  await page.locator('.react-flow__pane').click({ force: true, position: { x: 1100, y: 800 } })
  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await page.keyboard.press('Meta+z')
  const restored = await (await undoSave).json()
  expect(restored.draft.workflow.nodes.find((node: { node_id: string }) => node.node_id === 'generate-paired').node_parameters.effective_seed).toBe(1603)
  await expect(seed).toHaveValue('1603')
})

test('Prompt Studio edits the backend projection and shows every prompt track', async ({ page }) => {
  await page.goto('/')
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === 'prompt-composition-webui-3gb1.source.author')
  await page.getByRole('button', { name: '打开 Prompt Studio' }).click()
  const snapshot = await (await opening).json() as PromptSnapshot
  const a30 = snapshot.residues.find(residue => residue.residue_id === 'A:30')!
  const a31 = snapshot.residues.find(residue => residue.residue_id === 'A:31')!
  const cellFor = async (handle: string) => {
    const cell = page.locator(`[data-cell="${handle}:sequence"]`)
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
    // Native editors replace the renderer; row/column attributes survive F2 and direct typing.
    return page.locator(`.residue-matrix [row-id="sequence"] [role="gridcell"][col-id="${handle}"]`)
  }
  await expect(page.getByRole('navigation', { name: 'Prompt Studio 模式' })).toBeVisible()
  await expect(page.getByRole('button', { name: '条件', exact: true })).toHaveClass(/active/)
  await expect(page.getByRole('columnheader', { name: '残基 / 轨道' })).toBeVisible()
  await expect(page.locator('.rm-row-title strong')).toHaveText(['Sequence', 'Coordinates', 'SS8', 'SASA', 'Function'])
  await expect(page.locator('.rm-row-title small')).toHaveText(['氨基酸', 'named atoms', '二级结构', 'Å²', '区间注释'])
  expect((await page.getByRole('columnheader').allTextContents()).join(' ')).not.toMatch(/insert-[0-9a-f]|inserted\./)

  await (await cellFor(a30.residue_handle)).click()
  await page.getByRole('button', { name: 'Preserve', exact: true }).click()
  await expect(page.locator(`[data-cell="${a30.residue_handle}:sequence"]`)).toHaveClass(/state-current/)
  await page.getByRole('button', { name: '取消操作', exact: true }).click()
  const clearing = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:preview'))
  await page.getByRole('button', { name: 'Clear', exact: true }).click()
  const cleared = await (await clearing).json() as PromptPreview
  expect(cleared.tracks.sequence.values.find(value => value.residue_handle === a30.residue_handle)?.value).toBeNull()
  await expect((await cellFor(a30.residue_handle)).locator('strong')).toHaveText('Mask')
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeEnabled()

  const sequence = await cellFor(a31.residue_handle)
  await sequence.click()
  await sequence.press('Q')
  await expect(sequence.locator('input')).toHaveValue('Q')
  const editing = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:preview'))
  await sequence.locator('input').press('Enter')
  const edited = await (await editing).json() as PromptPreview
  await expect(sequence.locator('strong')).toHaveText('Q')
  await expect(page.getByRole('button', { name: '保存 ProteinPrompt' })).toBeEnabled()

  const currentBeforeInsert = snapshot.residues.length
  await page.getByRole('button', { name: '插入 / 删除', exact: true }).click()
  const inserting = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:preview'))
  await page.getByRole('button', { name: 'Insert after focus' }).click()
  const inserted = await (await inserting).json() as PromptPreview
  const newResidue = inserted.residues.find(residue => !snapshot.residues.some(original => original.residue_handle === residue.residue_handle))!
  expect(newResidue).toBeDefined()
  expect(newResidue.state).toBe('inserted')
  expect(inserted.tracks.sequence.values.find(value => value.residue_handle === newResidue.residue_handle)?.value).toBeNull()
  await page.getByRole('dialog').getByRole('button', { name: '应用操作', exact: true }).click()
  await page.getByRole('button', { name: '返回矩阵', exact: true }).click()
  await expect(page.getByRole('grid')).toHaveAttribute('aria-colcount', String(currentBeforeInsert + 2))
  const insertedCell = await cellFor(newResidue.residue_handle)
  await expect(insertedCell).not.toHaveClass(/rm-deleted/)
  await expect(insertedCell.locator('[data-cell]')).toHaveAttribute('aria-label', /A31\+1 Sequence Mask/)
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(page.getByRole('grid')).toHaveAttribute('aria-colcount', String(currentBeforeInsert + 1))
  await (await cellFor(a31.residue_handle)).click()
  await page.getByRole('button', { name: '插入 / 删除', exact: true }).click()
  await page.getByRole('button', { name: 'Insert after focus' }).click()
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '返回矩阵', exact: true }).click()
  await expect(page.getByRole('grid')).toHaveAttribute('aria-colcount', String(currentBeforeInsert + 1))

  const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith('/workspace'))
  await page.getByRole('button', { name: '保存 ProteinPrompt' }).click()
  const savedResponse = await saving
  expect(savedResponse.status()).toBe(200)
  expect(savedResponse.request().postDataJSON().workflow.nodes.find((node: { node_id: string }) => node.node_id === 'prompt-composition-webui-3gb1.source.author').node_parameters.document).toEqual(edited.normalized_document)
  expect(edited.residues).toHaveLength(currentBeforeInsert)
  expect(edited.tracks.sequence.values.find(value => value.residue_handle === a30.residue_handle)?.value).toBeNull()
  expect(edited.tracks.sequence.values.find(value => value.residue_handle === a31.residue_handle)?.value).toBe('Q')
  await expect(page.getByText('Prompt 已保存')).toBeVisible()
})

test('deleting a Node Instance persists and undo restores the backend Draft', async ({ page }) => {
  await page.goto('/')
  const nodeId = 'relation-generated-pairs'
  const initial = await (await page.request.get('/api/v2/projects/webui-3gb1-example/workflow/draft')).json()
  const incidentEdges = initial.workflow.edges.filter((edge: { source_node_id: string; target_node_id: string }) => edge.source_node_id === nodeId || edge.target_node_id === nodeId)
  expect(incidentEdges.length).toBeGreaterThan(0)
  const connectedNode = page.getByTestId(`rf__node-${nodeId}`)
  await connectedNode.click({ force: true })
  await expect(connectedNode).toHaveClass(/selected/)
  await connectedNode.focus()
  const deletionSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow && !JSON.parse(response.request().postData()!).workflow.nodes.some((node: { node_id: string }) => node.node_id === nodeId))
  await page.keyboard.press('Delete')
  const deletedDraft = await (await deletionSave).json()
  expect(deletedDraft.draft.workflow.nodes.map((node: { node_id: string }) => node.node_id)).not.toContain(nodeId)
  expect(deletedDraft.draft.workflow.edges).not.toEqual(expect.arrayContaining(incidentEdges))
  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await page.keyboard.press('Meta+z')
  const restoredDraft = await (await undoSave).json()
  expect(restoredDraft.draft.workflow.nodes.map((node: { node_id: string }) => node.node_id)).toContain(nodeId)
  expect(restoredDraft.draft.workflow.edges).toEqual(expect.arrayContaining(incidentEdges))
})

test('preparing a run waits for the latest autosaved Workflow revision', async ({ page }) => {
  let releaseSave!: () => void
  let markSaveStarted!: () => void
  const saveRelease = new Promise<void>((resolve) => { releaseSave = resolve })
  const saveStarted = new Promise<void>((resolve) => { markSaveStarted = resolve })
  let committedSeed: number | undefined
  await page.route('**/workspace', async route => {
    if (route.request().method() === 'PUT') {
      markSaveStarted()
      await saveRelease
    }
    await route.continue()
  })
  await page.route('**/workflow:commit', async route => {
    const body = JSON.parse(route.request().postData()!)
    committedSeed = body.workflow.nodes.find((node: { node_id: string }) => node.node_id === 'generate-paired').node_parameters.effective_seed
    await route.continue()
  })
  await page.goto('/')
  const generation = page.getByTestId('rf__node-generate-paired')
  await generation.getByLabel('编辑参数').click()
  await generation.getByLabel('有效种子').fill('1604')
  await generation.getByLabel('有效种子').press('Tab')
  await saveStarted
  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '确认运行范围' })).toHaveCount(0)
  expect(committedSeed).toBeUndefined()
  releaseSave()
  await expect(page.getByRole('dialog', { name: '确认运行范围' })).toBeVisible()
  const previewing = page.waitForResponse(response => response.url().endsWith('/runs/preview'))
  await page.getByRole('button', { name: '准备并查看范围', exact: true }).click()
  expect((await previewing).status()).toBe(200)
  expect(committedSeed).toBe(1604)
  await expect(page.getByRole('button', { name: '开始运行已确认范围', exact: true })).toBeEnabled()
})

async function createRunWorkspace(request: APIRequestContext, fasta = '>one\nACD\n>two\nEFG\n>three\nHIK\n') {
  const created = await request.post('/api/v2/projects', { data: { name: `Run scope ${crypto.randomUUID().slice(0, 8)}` } })
  expect(created.status()).toBe(201)
  const project = await created.json() as { id: string; name: string }
  const base = `/api/v2/projects/${project.id}`
  const uploaded = await request.post(`${base}/inputs`, { data: { filename: 'ordered.fa', content_base64: Buffer.from(fasta).toString('base64') } })
  expect(uploaded.status()).toBe(201)
  const input = await uploaded.json()
  const source = { node_id: 'source', node_type_id: 'protein_io.import_sequences', binding_id: 'protein_io.import_sequences.direct', node_parameters: { project_input_ref: input.project_input_ref }, binding_parameters: {} }
  const prefix = { node_id: 'prefix', node_type_id: 'collection_ops.take_candidates', binding_id: 'collection_ops.take_candidates.direct', node_parameters: { k: 2 }, binding_parameters: {} }
  const workflow: Workflow = {
    schema_version: '2.1.0', workflow_id: project.id,
    nodes: [source, prefix, { ...prefix, node_id: 'sink', node_parameters: { k: 1 } }, { ...source, node_id: 'independent' }],
    edges: [
      { source_node_id: 'source', source_port: 'sequence_candidates', target_node_id: 'prefix', target_port: 'candidates' },
      { source_node_id: 'prefix', source_port: 'candidates', target_node_id: 'sink', target_port: 'candidates' },
    ], observation_selectors: [], selection_objectives: [],
  }
  expect((await request.put(`${base}/workspace`, { data: { workflow, ui_state: { canvas: { positions: { source: { x: 50, y: 80 }, prefix: { x: 400, y: 80 }, sink: { x: 750, y: 80 }, independent: { x: 50, y: 450 } }, collapsed: [] } } } })).status()).toBe(200)
  return { project, base }
}

async function openRunWorkspace(page: Page, name: string) {
  await page.getByRole('button', { name: '项目', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '项目与版本' })
  await dialog.getByRole('button').filter({ has: page.getByText(name, { exact: true }) }).click()
  await dialog.getByRole('button', { name: '打开项目', exact: true }).click()
  await expect(page.locator('.project-identity strong')).toHaveText(name)
}

async function prepareScope(page: Page, nodeId: string, label: string) {
  await page.getByTestId(`rf__node-${nodeId}`).click()
  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  await page.getByRole('radio', { name: label, exact: true }).check()
  const response = page.waitForResponse(item => item.url().endsWith('/runs/preview'))
  await page.getByRole('button', { name: '准备并查看范围', exact: true }).click()
  const preview = await response
  expect(preview.status()).toBe(200)
  return await preview.json()
}

async function startPreparedScope(page: Page, request: APIRequestContext, base: string) {
  const starting = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`${base}/runs`))
  await page.getByRole('button', { name: '开始运行已确认范围', exact: true }).click()
  const response = await starting
  expect(response.status()).toBe(202)
  const receipt = await response.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${receipt.run_id}`)).json() as RunProjection).status).toBe('succeeded')
  await expect(page.locator('.run-progress-bar')).toContainText('运行完成')
  return await (await request.get(`${base}/runs/${receipt.run_id}`)).json() as RunProjection
}

async function holdPublishedCollection(page: Page, projection: RunProjection) {
  const output = projection.outputs.find(item => item.port_type.contract_id === 'candidate.collection')!
  expect(output).toBeTruthy()
  let release!: () => void
  let received!: () => void
  const barrier = new Promise<void>(resolve => { release = resolve })
  const ready = new Promise<void>(resolve => { received = resolve })
  const url = `/api/v2/projects/${projection.project_id}/runs/${projection.run_id}/results:collection`
  await page.route(`**${url}`, async route => {
    const source = route.request().postDataJSON()
    if (source.node_id !== output.node_id || source.output_port !== output.output_port) return route.continue()
    const response = await route.fetch()
    expect(response.ok()).toBe(true)
    received()
    await barrier
    await route.fulfill({ response })
  })
  return { ready, release }
}

test('a delayed real seed result cannot overwrite a personal project, new Run or saved edits', async ({ page, request }, testInfo) => {
  const { project, base } = await createRunWorkspace(request)
  const projects = await (await request.get('/api/v2/projects')).json()
  const example = projects.projects.find((item: { project_kind: string }) => item.project_kind === 'default_example')
  const seed = await (await request.get(`/api/v2/projects/${example.id}/runs/${example.latest_run_id}`)).json() as RunProjection
  const held = await holdPublishedCollection(page, seed)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  try {
    await page.goto('/')
    await held.ready
    await openRunWorkspace(page, project.name)
    const prefix = page.getByTestId('rf__node-prefix')
    await prefix.getByLabel('编辑参数').click()
    const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`${base}/workspace`) && response.request().postDataJSON().workflow)
    await prefix.getByLabel('保留数量').fill('1')
    await prefix.getByLabel('保留数量').blur()
    expect((await saving).status()).toBe(200)
    await expect(page.getByLabel('流程保存状态')).toHaveText('已自动保存')
    await prepareScope(page, 'source', '运行到所选节点')
    const personalRun = await startPreparedScope(page, request, base)
    await expect(page.getByRole('button', { name: 'Results 3', exact: true })).toBeEnabled()
    held.release()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.project-identity strong')).toHaveText(project.name)
    await expect(page.getByLabel('流程保存状态')).toHaveText('已自动保存')
    await expect(page.getByTestId('rf__node-prefix').getByLabel('保留数量')).toHaveValue('1')
    await page.getByRole('button', { name: 'Results 3', exact: true }).click()
    await expect(page.locator('.results-explorer > aside')).toContainText(`Run ${personalRun.run_id}`)
    await expect(page.locator('.results-explorer > aside')).not.toContainText(seed.run_id)
    await expect(page.getByRole('heading', { name: 'source / sequence_candidates', exact: true })).toBeVisible()
    await expect(page.locator('.result-table').getByRole('checkbox')).toHaveCount(3)
    expect(errors).toEqual([])
    await testInfo.attach('personal-run-after-delayed-seed', { body: await page.screenshot(), contentType: 'image/png' })
  } finally {
    held.release()
  }
})

test('a delayed real previous Run result cannot replace a newer Run in the same project', async ({ page, request }) => {
  const { project, base } = await createRunWorkspace(request)
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  await prepareScope(page, 'source', '运行到所选节点')
  const previous = await startPreparedScope(page, request, base)
  await expect(page.getByRole('button', { name: 'Results 3', exact: true })).toBeEnabled()
  const held = await holdPublishedCollection(page, previous)
  try {
    // Start a fresh reader; reopening the same Run now reuses its loaded page.
    await page.reload()
    await openRunWorkspace(page, project.name)
    await held.ready
    await prepareScope(page, 'prefix', '运行到所选节点')
    const latest = await startPreparedScope(page, request, base)
    expect(latest.run_id).not.toBe(previous.run_id)
    await expect(page.getByRole('button', { name: 'Results 5', exact: true })).toBeEnabled()
    held.release()
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'Results 5', exact: true }).click()
    await expect(page.locator('.results-explorer > aside')).toContainText(`Run ${latest.run_id}`)
    await expect(page.locator('.results-explorer > aside')).not.toContainText(previous.run_id)
    await page.locator('.results-explorer > aside nav').getByRole('button').filter({ hasText: 'prefix / candidates' }).click()
    await expect(page.locator('.result-table').getByRole('checkbox')).toHaveCount(2)
  } finally {
    held.release()
  }
})

test('scoped UI runs publish real results, force descendants and preserve independent branches', async ({ page, request }, testInfo) => {
  const { project, base } = await createRunWorkspace(request)
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  const first = await prepareScope(page, 'prefix', '运行到所选节点')
  expect(new Set(first.scope.execution_node_ids)).toEqual(new Set(['source', 'prefix']))
  expect(new Set(first.scope.out_of_scope_node_ids)).toEqual(new Set(['sink', 'independent']))
  const sourceRun = await startPreparedScope(page, request, base)
  expect(new Set(sourceRun.node_dispositions.map(item => item.node_id))).toEqual(new Set(['source', 'prefix']))
  await expect(page.getByTestId('rf__node-sink').getByText('范围外', { exact: true })).toBeVisible()
  await expect(page.getByTestId('rf__node-independent').getByText('范围外', { exact: true })).toBeVisible()
  const continuation = await prepareScope(page, 'prefix', '从所选节点继续')
  expect(continuation.scope.source_run_id).toBe(sourceRun.run_id)
  expect(new Set(continuation.scope.forced_node_ids)).toEqual(new Set(['prefix', 'sink']))
  expect(continuation.scope.reused_node_ids).toEqual(['source'])
  const continued = await startPreparedScope(page, request, base)
  expect(continued.run_id).not.toBe(sourceRun.run_id)
  expect(continued.node_dispositions).toEqual(expect.arrayContaining([
    expect.objectContaining({ node_id: 'source', resolution: 'cache_replayed' }),
    expect.objectContaining({ node_id: 'prefix', resolution: 'executed' }),
    expect.objectContaining({ node_id: 'sink', resolution: 'executed' }),
  ]))
  expect(continued.node_dispositions.some(item => item.node_id === 'independent')).toBe(false)
  await expect(page.getByTestId('rf__node-source').getByText('仅复用', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Results [1-9]/ })).toBeEnabled()
  await page.reload()
  await openRunWorkspace(page, project.name)
  await expect(page.getByTestId('rf__node-source').getByText('仅复用', { exact: true })).toBeVisible()
  await expect(page.getByTestId('rf__node-independent').getByText('范围外', { exact: true })).toBeVisible()
  expect((await (await request.get(`${base}/runs/${sourceRun.run_id}`)).json()).scope).toEqual(sourceRun.scope)
  await testInfo.attach('continued-run-scope', { body: await page.screenshot(), contentType: 'image/png' })
})

test('continuation without matching upstream evidence is blocked before any new Run', async ({ page, request }, testInfo) => {
  const { project, base } = await createRunWorkspace(request)
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  await prepareScope(page, 'independent', '运行到所选节点')
  const independentRun = await startPreparedScope(page, request, base)
  const blocked = await prepareScope(page, 'prefix', '从所选节点继续')
  expect(blocked.blockers).toEqual(expect.arrayContaining([expect.objectContaining({ code: 'upstream_result_missing', node_id: 'source' })]))
  await expect(page.getByRole('dialog', { name: '确认运行范围' }).getByRole('alert')).toContainText(blocked.blockers.map((blocker: { message: string }) => blocker.message))
  await expect(page.getByRole('button', { name: '开始运行已确认范围', exact: true })).toBeDisabled()
  const projects = await (await request.get('/api/v2/projects')).json()
  expect(projects.projects.find((item: { id: string }) => item.id === project.id).latest_run_id).toBe(independentRun.run_id)
  await testInfo.attach('missing-upstream-blocked', { body: await page.screenshot(), contentType: 'image/png' })
})

test('a disconnected real event stream reconnects from its received cursor without resubmitting the Run', async ({ page, request }) => {
  const { project, base } = await createRunWorkspace(request)
  const socketUrls: string[] = []
  let releaseProjection!: () => void
  const projectionBarrier = new Promise<void>(resolve => { releaseProjection = resolve })
  let reconnected!: () => void
  const reconnection = new Promise<void>(resolve => { reconnected = resolve })
  // Keep the real terminal projection from hiding the interrupted-stream state
  // before the user explicitly reconnects. No backend response is rewritten.
  await page.route(new RegExp(`${base}/runs/[^/?]+$`), async route => {
    if (route.request().method() !== 'GET') return route.continue()
    await projectionBarrier
    const response = await route.fetch()
    await route.fulfill({ response })
  })
  let receivedCursor: string | undefined
  let submissions = 0
  page.on('request', item => { if (item.method() === 'POST' && item.url().endsWith(`${base}/runs`)) submissions += 1 })
  await page.routeWebSocket(new RegExp(`/projects/${project.id}/runs/[^/]+/events`), socket => {
    socketUrls.push(socket.url())
    const upstream = socket.connectToServer()
    if (socketUrls.length !== 1) { reconnected(); return }
    let closed = false
    upstream.onMessage(message => {
      if (closed) return
      const envelope = JSON.parse(String(message)) as RunEventEnvelope
      socket.send(message)
      if (envelope.event.type === 'node_attempt_started') {
        receivedCursor = envelope.cursor
        closed = true
        void socket.close({ code: 1011, reason: 'Test transport interruption' })
        void upstream.close()
      }
    })
  })
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  await prepareScope(page, 'prefix', '运行到所选节点')
  const starting = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`${base}/runs`))
  try {
    await page.getByRole('button', { name: '开始运行已确认范围', exact: true }).click()
    const receipt = await (await starting).json()
    await expect(page.getByText('运行状态连接已断开；Run 仍可能在执行。')).toBeVisible()
    expect(receivedCursor).toBeTruthy()
    await page.getByRole('button', { name: '从已接收位置重新连接', exact: true }).click()
    await reconnection
    releaseProjection()
    await expect(page.locator('.run-progress-bar')).toContainText('运行完成')
    expect(socketUrls).toHaveLength(2)
    expect(new URL(socketUrls[1]).searchParams.get('after_sequence')).toBe(receivedCursor)
    expect(submissions).toBe(1)
    const projects = await (await request.get('/api/v2/projects')).json()
    expect(projects.projects.find((item: { id: string }) => item.id === project.id).latest_run_id).toBe(receipt.run_id)
    await expect(page.getByTestId('rf__node-prefix').getByText('成功', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /Results [1-9]/ })).toBeEnabled()
  } finally {
    releaseProjection()
  }
})

test('terminal events wait for the REST projection without reporting a normal stream close as failure', async ({ page, request }) => {
  const { project, base } = await createRunWorkspace(request)
  let releaseProjection!: () => void
  const projectionBarrier = new Promise<void>(resolve => { releaseProjection = resolve })
  let terminalReceived!: () => void
  const terminal = new Promise<void>(resolve => { terminalReceived = resolve })
  await page.route(new RegExp(`${base}/runs/[^/?]+$`), async route => {
    if (route.request().method() !== 'GET') return route.continue()
    await projectionBarrier
    await route.fulfill({ response: await route.fetch() })
  })
  await page.routeWebSocket(new RegExp(`/projects/${project.id}/runs/[^/]+/events`), socket => {
    const upstream = socket.connectToServer()
    upstream.onMessage(message => {
      socket.send(message)
      if ((JSON.parse(String(message)) as RunEventEnvelope).event.type === 'run_terminal') terminalReceived()
    })
  })
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  await prepareScope(page, 'prefix', '运行到所选节点')
  try {
    await page.getByRole('button', { name: '开始运行已确认范围', exact: true }).click()
    await terminal
    await expect(page.locator('.run-progress-bar')).toHaveCount(0)
    await expect(page.locator('.run-button')).toBeDisabled()
    await expect(page.locator('.run-connection-error')).toHaveCount(0)
    releaseProjection()
    await expect(page.locator('.run-progress-bar')).toContainText('运行完成')
    await expect(page.getByTestId('rf__node-prefix').getByText('成功', { exact: true })).toBeVisible()
    await expect(page.locator('.run-connection-error')).toHaveCount(0)
  } finally {
    releaseProjection()
  }
})

test('a failed real FASTA Run exposes located diagnostics and can focus the failed node', async ({ page, request }, testInfo) => {
  const { project, base } = await createRunWorkspace(request, '>valid\nACD\n>bad\nA?D\n')
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  await prepareScope(page, 'source', '运行到所选节点')
  const starting = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`${base}/runs`))
  await page.getByRole('button', { name: '开始运行已确认范围', exact: true }).click()
  const receipt = await (await starting).json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${receipt.run_id}`)).json()).status).toBe('failed')
  await expect(page.locator('.run-progress-bar')).toContainText('运行失败')
  const diagnostics = page.getByRole('region', { name: '运行失败诊断' })
  await expect(diagnostics.getByRole('alert')).toContainText(/record 2.*line 3/i)
  await diagnostics.getByRole('button', { name: '定位节点 source', exact: true }).click()
  await expect(page.getByTestId('rf__node-source')).toHaveClass(/selected/)
  await expect(page.getByTestId('rf__node-source').getByText('失败', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Results 0/ })).toBeDisabled()
  await testInfo.attach('located-fasta-failure', { body: await page.screenshot(), contentType: 'image/png' })
})

test('canvas copy and paste preserve internal edges and undo the saved fragment', async ({ page, request }) => {
  const { project, base } = await createRunWorkspace(request)
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  const original = await (await request.get(`${base}/workflow/draft`)).json()
  await page.getByTestId('rf__node-source').click()
  await page.getByTestId('rf__node-prefix').click({ modifiers: ['Control'] })
  await expect(page.getByTestId('rf__node-source')).toHaveClass(/selected/)
  await expect(page.getByTestId('rf__node-prefix')).toHaveClass(/selected/)
  await page.keyboard.press('Control+c')
  const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`${base}/workspace`) && response.request().postDataJSON().workflow)
  await page.keyboard.press('Control+v')
  const pasted = await (await saving).json()
  const added = pasted.draft.workflow.nodes.filter((node: { node_id: string }) => !original.workflow.nodes.some((item: { node_id: string }) => item.node_id === node.node_id))
  expect(added).toHaveLength(2)
  expect(added.map((node: { node_type_id: string }) => node.node_type_id)).toEqual(['protein_io.import_sequences', 'collection_ops.take_candidates'])
  expect(added[0].node_parameters).toEqual(original.workflow.nodes[0].node_parameters)
  expect(pasted.draft.workflow.edges).toEqual([...original.workflow.edges, { source_node_id: added[0].node_id, source_port: 'sequence_candidates', target_node_id: added[1].node_id, target_port: 'candidates' }])
  await expect(page.getByText('片段已粘贴', { exact: true })).toBeVisible()
  const undoing = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`${base}/workspace`) && response.request().postDataJSON().workflow)
  await page.keyboard.press('Control+z')
  expect((await (await undoing).json()).draft.workflow).toEqual(original.workflow)
  await expect(page.getByText(/4 GRAPH NODES/)).toBeVisible()
})

test('dragging compatible Ports replaces one-input wiring in the saved Workflow', async ({ page, request }) => {
  const { project, base } = await createRunWorkspace(request)
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  const source = page.getByTestId('rf__node-source').locator('[data-handleid="out-sequence_candidates"]')
  const target = page.getByTestId('rf__node-sink').locator('[data-handleid="in-candidates"]')
  const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`${base}/workspace`) && response.request().postDataJSON().workflow)
  await page.getByRole('button', { name: '适合视图', exact: true }).click()
  await source.hover()
  const from = (await source.boundingBox())!
  await page.mouse.down()
  await page.mouse.move(from.x + from.width + 20, from.y + from.height / 2, { steps: 5 })
  await expect(page.locator('.react-flow__connection')).toBeVisible()
  await target.hover()
  await page.mouse.up()
  const saved = await (await saving).json()
  expect(saved.draft.workflow.edges.filter((edge: { target_node_id: string }) => edge.target_node_id === 'sink')).toEqual([{ source_node_id: 'source', source_port: 'sequence_candidates', target_node_id: 'sink', target_port: 'candidates' }])
  expect(saved.draft.workflow.edges).toHaveLength(2)
  await expect(page.getByRole('group', { name: 'Edge from source to sink' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Edge from prefix to sink' })).toHaveCount(0)
})

test('a real Prompt source failure leaves the Draft intact and shows the owner diagnostic', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const created = await request.post('/api/v2/projects', { data: { name: `Missing Prompt source ${crypto.randomUUID().slice(0, 8)}` } })
  expect(created.status()).toBe(201)
  const project = await created.json()
  const base = `/api/v2/projects/${project.id}`
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: project.id, nodes: [
    { node_id: 'missing-source', node_type_id: 'protein_io.import_sequence', binding_id: 'protein_io.import_sequence.direct', node_parameters: { project_input_ref: 'missing-source.fasta' }, binding_parameters: {} },
    { node_id: 'author', node_type_id: 'prompt_authoring.author', binding_id: 'prompt_authoring.author.direct', node_parameters: { document: {} }, binding_parameters: {} },
  ], edges: [{ source_node_id: 'missing-source', source_port: 'sequence', target_node_id: 'author', target_port: 'sequence_source' }], observation_selectors: [], selection_objectives: [] }
  const saving = await request.put(`${base}/workspace`, { data: { workflow } })
  expect(saving.status()).toBe(200)
  const original = (await saving.json()).draft
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  const opening = page.waitForResponse(response => response.url().endsWith(`${base}/prompt-authoring:open`) && response.request().postDataJSON().node_id === 'author')
  await page.getByTestId('rf__node-author').getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
  const failure = await opening
  expect(failure.ok()).toBe(false)
  const diagnostic = await failure.json()
  const alert = page.getByRole('alert').filter({ hasText: '无法打开节点 author 的 Prompt' })
  await expect(alert).toContainText(diagnostic.error.message)
  await expect(alert.getByRole('button', { name: '重新打开', exact: true })).toBeVisible()
  await expect(page.getByTestId('rf__node-author')).toBeVisible()
  await expect(page.locator('.prompt-studio')).toHaveCount(0)
  expect(await (await request.get(`${base}/workflow/draft`)).json()).toEqual(original)
  expect(errors).toEqual([])
  await alert.getByRole('button', { name: '关闭提示', exact: true }).click()
  await expect(alert).toHaveCount(0)
})

test('a delayed real Prompt response cannot replace a newly opened project', async ({ page, request }) => {
  const { project } = await createRunWorkspace(request)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  let release!: () => void
  let received!: () => void
  const releaseResponse = new Promise<void>(resolve => { release = resolve })
  const responseReady = new Promise<void>(resolve => { received = resolve })
  const nodeId = 'prompt-composition-webui-3gb1.source.author'
  await page.route('**/prompt-authoring:open', async route => {
    if (route.request().postDataJSON().node_id !== nodeId || !route.request().url().includes('/projects/webui-3gb1-example/')) return route.continue()
    const response = await route.fetch()
    expect(response.ok()).toBe(true)
    received()
    await releaseResponse
    await route.fulfill({ response })
  })
  await page.goto('/')
  await page.getByTestId(`rf__node-${nodeId}`).getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
  await responseReady
  await openRunWorkspace(page, project.name)
  const oldResponse = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === nodeId)
  release()
  await oldResponse
  await expect(page.locator('.project-identity strong')).toHaveText(project.name)
  await expect(page.locator('.prompt-studio')).toHaveCount(0)
  await expect(page.getByTestId('rf__node-source')).toBeVisible()
  expect(errors).toEqual([])
})

test('clicking the Palette opens an explicit Binding choice and saves the selected ordinary node', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Fold protein sequences folding', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '为 Fold protein sequences 选择执行模型' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button').filter({ hasText: 'simplefold_100M' })).toBeEnabled()
  const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith('/workspace') && response.request().postDataJSON().workflow)
  await dialog.getByRole('button').filter({ hasText: 'folding.fold.esmfold2_remote' }).click()
  const saved = await (await saving).json()
  expect(saved.draft.workflow.nodes).toHaveLength(37)
  expect(saved.draft.workflow.nodes.at(-1)).toMatchObject({ node_type_id: 'folding.fold', binding_id: 'folding.fold.esmfold2_remote' })
  await expect(dialog).toHaveCount(0)
})


test('scientific edits become stale and reverting them restores current results; layout stays independent', async ({ page, request }) => {
  const { project, base } = await createRunWorkspace(request)
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  await prepareScope(page, 'prefix', '运行到所选节点')
  await startPreparedScope(page, request, base)
  await expect(page.locator('.old-result-note')).toContainText('与当前科学流程一致')
  const node = page.getByTestId('rf__node-prefix')
  await node.getByLabel('编辑参数').click()
  const count = node.getByLabel('保留数量')
  await count.fill('1')
  await count.blur()
  await expect(page.locator('.old-result-note')).toContainText('来自修改前的科学流程')
  await count.fill('2')
  await count.blur()
  await expect(page.locator('.old-result-note')).toContainText('与当前科学流程一致')
  await node.locator('.node-header .icon-button').click()
  await expect(page.getByLabel('布局保存状态')).toContainText('布局已保存')
  await expect(page.locator('.old-result-note')).toContainText('与当前科学流程一致')
  await page.reload()
  await openRunWorkspace(page, project.name)
  await expect(page.locator('.old-result-note')).toContainText('与当前科学流程一致')
})

test('canvas context search adds an ordinary node and keyboard undo restores the graph', async ({ page, request }) => {
  const { project, base } = await createRunWorkspace(request)
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  await page.locator('.react-flow__pane').click({ button: 'right', position: { x: 650, y: 550 } })
  await page.getByRole('menuitem', { name: '添加节点', exact: true }).click()
  const picker = page.getByRole('dialog', { name: '添加节点', exact: true })
  const search = picker.getByLabel('搜索节点', { exact: true })
  const entries = picker.locator('[data-picker-entry]')
  await search.focus()
  await search.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  await expect(search).toBeFocused()
  await search.dispatchEvent('keydown', { key: 'Escape', isComposing: true })
  await expect(picker).toBeVisible()
  await search.press('ArrowUp')
  await expect(entries.last()).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(entries.first()).toBeFocused()
  await page.keyboard.press('ArrowUp')
  await expect(entries.last()).toBeFocused()
  await search.fill('Invert a Candidate relation')
  await expect(entries).toHaveCount(1)
  await search.press('ArrowUp')
  await expect(entries.first()).toBeFocused()
  const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`${base}/workspace`) && response.request().postDataJSON().workflow)
  await picker.getByRole('button', { name: /Invert a Candidate relation/ }).click()
  const saved = await (await saving).json()
  expect(saved.draft.workflow.nodes.filter((node: { node_type_id: string }) => node.node_type_id === 'collection_ops.invert_relation')).toHaveLength(1)
  await page.getByRole('button', { name: '适合视图', exact: true }).click()
  const undoing = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`${base}/workspace`) && response.request().postDataJSON().workflow)
  await page.keyboard.press('Meta+z')
  expect((await (await undoing).json()).draft.workflow.nodes).toHaveLength(4)
})

test('a held candidate page cannot change another stage and revisiting reuses the loaded page', async ({ page, request }) => {
  const fasta = Array.from({ length: 250 }, (_, index) => `>record-${index}\nACDE\n`).join('')
  const { project, base } = await createRunWorkspace(request, fasta)
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  await prepareScope(page, 'prefix', '运行到所选节点')
  const run = await startPreparedScope(page, request, base)
  await page.getByRole('button', { name: '打开 Results Workbench' }).click()
  const navigation = page.locator('.results-explorer > aside nav')
  await navigation.getByRole('button').filter({ hasText: 'source / sequence_candidates' }).click()
  await expect(page.locator('.result-table').getByRole('checkbox')).toHaveCount(50)
  let release!: () => void
  let received!: () => void
  const barrier = new Promise<void>(resolve => { release = resolve })
  const held = new Promise<void>(resolve => { received = resolve })
  const offsets: number[] = []
  await page.route(`**${base}/runs/${run.run_id}/results:collection`, async route => {
    const body = route.request().postDataJSON()
    if (body.node_id !== 'source') return route.continue()
    offsets.push(body.offset)
    const response = await route.fetch()
    expect(response.ok()).toBe(true)
    received()
    await barrier
    await route.fulfill({ response })
  })
  try {
    await page.getByRole('button', { name: '下一页', exact: true }).click()
    await expect(page.locator('.results-explorer footer').first()).toContainText('2 / 5')
    await page.getByRole('button', { name: '下一页', exact: true }).click()
    await held
    await navigation.getByRole('button').filter({ hasText: 'prefix / candidates' }).click()
    await expect(page.locator('.result-table').getByRole('checkbox')).toHaveCount(2)
    release()
    await expect(page.getByRole('button', { name: '配置排序并取前 N 个' })).toBeEnabled()
    await expect(page.locator('.results-explorer footer').first()).toContainText('1 / 1')
    await navigation.getByRole('button').filter({ hasText: 'source / sequence_candidates' }).click()
    await page.getByRole('button', { name: '下一页', exact: true }).click()
    await expect(page.locator('.results-explorer footer').first()).toContainText('2 / 5')
    await page.getByRole('button', { name: '下一页', exact: true }).click()
    await expect(page.locator('.results-explorer footer').first()).toContainText('3 / 5')
    expect(offsets).toEqual([100])
  } finally {
    release()
  }
})

test('the example selection chain keeps complete Candidate sources and axes-based score sources', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText(/36 GRAPH NODES/)).toBeVisible()

  const selectionNode = page.getByTestId('rf__node-rank-final')
  await selectionNode.getByRole('button', { name: /编辑筛选与排序/ }).click()
  const dialog = page.getByRole('dialog', { name: '编辑流程筛选' })
  await expect(dialog).toBeVisible()

  // Complete Candidate values keep coming from the original Candidate branch.
  const candidateOptions = await dialog.getByLabel('Candidate Collection 来源').locator('option').allTextContents()
  expect(candidateOptions.some((text) => text.includes('fold-final / structure_candidates'))).toBe(true)
  expect(candidateOptions.some((text) => text.includes('take-top-two / candidates'))).toBe(true)
  expect(candidateOptions.some((text) => text.includes('当前不可用'))).toBe(false)

  // Every offered score source belongs to a Node whose structure subjects are
  // carried by the ordered resolved-axis value, not by a parallel Candidate
  // input, and each one is still a real declared Score Collection output.
  const scoreSelect = dialog.getByLabel('Score Collection 来源').first()
  const scoreOptions = await scoreSelect.locator('option').allTextContents()
  expect(scoreOptions.some((text) => text.includes('confidence-final / observations'))).toBe(true)
  expect(scoreOptions.some((text) => text.includes('tm-final / scores'))).toBe(true)
  expect(scoreOptions.some((text) => text.includes('当前不可用'))).toBe(false)

  // The shipped objective still resolves to declared scalar observations.
  const observationOptions = dialog.getByLabel('科学观察').first().locator('option')
  await expect(observationOptions).toHaveCount(3)
  await expect(observationOptions).not.toContainText([/已保存观察与当前来源不匹配/])
  const observations = await observationOptions.allTextContents()
  expect(observations.filter((text) => text.length > 0 && !text.startsWith('选择来源声明的观察'))).toHaveLength(2)
})

for (const raw of ['1.5', '-', '1e']) {
  test(`unfinished numeric input ${raw} blocks a long edit and stays raw until corrected`, async ({ page, request }) => {
    const { project, base } = await createRunWorkspace(request)
    await page.goto('/')
    await openRunWorkspace(page, project.name)
    const prefix = page.getByTestId('rf__node-prefix')
    await prefix.getByLabel('编辑参数').click()
    const count = prefix.getByLabel('保留数量')
    const before = await (await request.get(`${base}/workspace`)).json()
    const scientificWrites: unknown[] = []
    page.on('request', outgoing => {
      if (outgoing.method() === 'PUT' && outgoing.url().endsWith(`${base}/workspace`) && outgoing.postDataJSON().workflow) scientificWrites.push(outgoing.postDataJSON())
    })
    await count.fill(raw)
    await page.getByRole('button', { name: '添加来源', exact: true }).click()
    await expect(count).toHaveValue(raw)
    await expect(page.getByRole('dialog', { name: '添加来源', exact: true })).toHaveCount(0)
    expect((await (await request.get(`${base}/workspace`)).json()).draft).toEqual(before.draft)
    expect(scientificWrites).toEqual([])
    const saved = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`${base}/workspace`) && response.request().postDataJSON().workflow)
    await count.fill('1')
    await count.blur()
    expect((await saved).status()).toBe(200)
    await page.getByRole('button', { name: '添加来源', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '添加来源', exact: true })).toBeVisible()
  })
}


test('node groups preserve editing context, parameter Escape and independent copies', async ({ page, request }) => {
  const { project, base } = await createRunWorkspace(request)
  await page.goto('/')
  await openRunWorkspace(page, project.name)
  await page.getByTestId('rf__node-source').click()
  await page.getByTestId('rf__node-prefix').click({ modifiers: ['Control'] })
  const grouped = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`${base}/workspace`) && response.request().postDataJSON().ui_state?.canvas?.groups?.length === 1)
  await page.getByRole('button', { name: '组合 Ctrl/⌘G', exact: true }).click()
  const saved = await (await grouped).json()
  expect(saved.draft.workflow.nodes).toHaveLength(4)
  const groupId = saved.ui_state.canvas.groups[0].id
  const group = page.getByTestId(`rf__node-${groupId}`)
  await group.locator('.node-header strong').click()
  await expect(group).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('navigation', { name: '节点组路径' })).toContainText('节点组')
  const prefix = page.getByTestId('rf__node-prefix')
  await prefix.getByLabel('编辑参数').click()
  const count = prefix.getByLabel('保留数量')
  await count.fill('99')
  await count.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  await expect(count).toBeFocused()
  await count.dispatchEvent('keydown', { key: 'Escape', isComposing: true })
  await expect(count).toHaveValue('99')
  await count.press('Escape')
  await expect(count).toHaveValue('2')
  await page.getByRole('button', { name: '返回上层 · Tab' }).click()
  await group.locator('.node-header strong').click()
  await expect(group).toBeFocused()
  await page.keyboard.press('Control+c')
  const pasted = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`${base}/workspace`) && response.request().postDataJSON().workflow?.nodes.length === 6)
  await page.keyboard.press('Control+v')
  const duplicate = await (await pasted).json()
  expect(duplicate.ui_state.canvas.groups).toHaveLength(2)
  expect(duplicate.ui_state.canvas.groups[1].nodeIds.every((id: string) => !saved.ui_state.canvas.groups[0].nodeIds.includes(id))).toBe(true)
  const copiedGroup = page.getByTestId(`rf__node-${duplicate.ui_state.canvas.groups[1].id}`)
  await expect(copiedGroup).toHaveClass(/selected/)
  await expect(page.locator('.flow-canvas')).toBeFocused()
  // Continue directly from paste, without clicking to repair the selected-node ref.
  await page.keyboard.press('Tab')
  const copiedPrefix = duplicate.draft.workflow.nodes.find((node: { node_id: string; node_type_id: string }) => duplicate.ui_state.canvas.groups[1].nodeIds.includes(node.node_id) && node.node_type_id === 'collection_ops.take_candidates')
  expect(copiedPrefix).toBeDefined()
  await expect(page.getByTestId(`rf__node-${copiedPrefix.node_id}`)).toBeVisible()
  await expect(page.getByTestId('rf__node-prefix')).toHaveCount(0)
  await page.getByRole('button', { name: '返回上层 · Tab' }).click()
  await page.reload()
  await openRunWorkspace(page, project.name)
  await expect(page.getByRole('button', { name: '进入组 节点组', exact: true })).toHaveCount(2)
})
