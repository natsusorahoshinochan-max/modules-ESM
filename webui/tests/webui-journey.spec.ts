import { expect, test } from '@playwright/test'

test('default 3GB1 workflow remains connected from authoring through export', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '3GB1 Local Redesign Example' })).toBeVisible()
  await expect(page.getByText(/36 GRAPH NODES/)).toBeVisible()
  await expect(page.getByText('只读示例')).toBeVisible()
  await expect(page.getByText(/66 persisted edges/)).toBeVisible()
  await expect(page.getByTestId('rf__node-relation-generated-structure-parent').getByRole('heading', { name: 'Relate Candidates to their parents' })).toBeVisible()
  await expect(page.getByTestId('rf__node-relation-generated-pairs').getByRole('heading', { name: 'Invert a Candidate relation' })).toBeVisible()

  await expect(page.getByRole('button', { name: /Results 0/ })).toBeDisabled()

  const generationNode = page.getByTestId('rf__node-generate-paired')
  await generationNode.getByLabel('编辑参数').click()
  const seed = generationNode.getByLabel('有效种子')
  await seed.fill('1604')
  await seed.press('Tab')
  await expect(page.getByText('已自动保存')).toBeVisible()
  await expect(page.getByText('personal', { exact: true })).toBeVisible()
  await expect(page.getByText('来自修改前的流程')).toBeVisible()

  const persistedEdge = { source_node_id: 'rank-generated', source_port: 'candidates', target_node_id: 'take-top-four', target_port: 'candidates' }
  const edge = page.getByRole('group', { name: 'Edge from rank-generated to take-top-four' })
  await edge.locator('.react-flow__edge-interaction').evaluate((element) => element.dispatchEvent(new MouseEvent('click', { bubbles: true })))
  await expect(edge).toHaveClass(/selected/)
  await edge.focus()
  const deletionSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft') && !JSON.parse(response.request().postData()!).workflow.edges.some((item: typeof persistedEdge) => JSON.stringify(item) === JSON.stringify(persistedEdge)))
  await page.keyboard.press('Delete')
  const deletedDraft = await (await deletionSave).json()
  expect(deletedDraft.workflow.edges).not.toContainEqual(persistedEdge)
  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft') && JSON.parse(response.request().postData()!).workflow.edges.some((item: typeof persistedEdge) => JSON.stringify(item) === JSON.stringify(persistedEdge)))
  await page.getByRole('button', { name: '撤销画布修改' }).click()
  const undoResponse = await undoSave
  const restoredDraft = await undoResponse.json()
  expect(restoredDraft.workflow.edges).toContainEqual(persistedEdge)
  const fetchedDraft = await page.request.get(undoResponse.url())
  expect((await fetchedDraft.json()).workflow.edges).toContainEqual(persistedEdge)
  await expect(page.getByText('已撤销画布修改')).toBeVisible()

  await page.getByRole('button', { name: /打开 Prompt Studio/ }).click()
  await expect(page.getByRole('heading', { name: '3GB1 局部环区重设计' })).toBeVisible()
  await expect(page.getByText('57 residues')).toBeVisible()
  await page.getByRole('button', { name: '状态图例' }).click()
  await expect(page.locator('.ps-state-legend').getByText('pending-delete', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '保存 ProteinPrompt' }).click()
  await expect(page.getByRole('heading', { name: '确认写回 Workflow' })).toBeVisible()
  await expect(page.getByText('Preview digest')).toBeVisible()
  await page.getByRole('button', { name: '确认并写回 Workflow' }).click()
  await expect(page.getByText('Prompt 已保存')).toBeVisible()

  await page.getByRole('button', { name: '运行完整流程' }).click()
  await expect(page.getByRole('heading', { name: '确认运行完整流程' })).toBeVisible()
  await expect(page.getByText('36 个 materialized Node Instances')).toBeVisible()
  await expect(page.getByText('7 → 4 → 4 → 2 → 6 → 6 → 3', { exact: true })).toBeVisible()
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
  await page.getByRole('button', { name: 'Take an ordered Candidate prefix collection' }).dragTo(page.locator('.react-flow__pane'), { targetPosition: { x: 520, y: 620 } })
  const prefixNode = page.locator('article.workflow-node').filter({ has: page.getByRole('heading', { name: 'Take an ordered Candidate prefix' }) }).last()
  await prefixNode.locator('summary[aria-label="编辑参数"]').click()
  await expect(prefixNode.getByLabel('保留数量')).toHaveValue('')

  const foldNode = page.locator('article.workflow-node').filter({ has: page.getByRole('heading', { name: 'Fold protein sequences' }) }).first()
  const foldModel = foldNode.getByRole('combobox', { name: 'Fold protein sequences的执行模型' })
  await foldModel.selectOption('folding.fold.simplefold_local')
  await foldNode.locator('summary[aria-label="编辑参数"]').click()
  const samplingSteps = foldNode.getByLabel('模型参数 · num_steps')
  await expect(samplingSteps).toHaveValue('50')
  await samplingSteps.fill('42')
  const parameterSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft'))
  await samplingSteps.blur()
  await parameterSave
  const remoteSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft'))
  await foldModel.selectOption('folding.fold.esmfold2_remote')
  await remoteSave
  const simpleFoldSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft'))
  await foldModel.selectOption('folding.fold.simplefold_local')
  await simpleFoldSave
  await expect(foldNode.getByLabel('模型参数 · num_steps')).toHaveValue('42')
})

test('an unavailable Binding remains visible but cannot be selected', async ({ page }) => {
  await page.route('**/api/v2/catalog', async (route) => {
    const response = await route.fetch()
    const catalog = await response.json()
    const unavailable = catalog.availability.find((item: { binding: { contract_id: string } }) => item.binding.contract_id === 'esm3.generate_paired.biohub_open')
    unavailable.available = false
    await route.fulfill({ response, json: catalog })
  })
  await page.goto('/')

  const option = page.getByRole('combobox', { name: 'Generate paired sequences and structures with remote ESM-3的执行模型' }).locator('option[value="esm3.generate_paired.biohub_open"]')
  await expect(option).toBeDisabled()
  await expect(option).toHaveText('esm3-open-2024-03（不可用）')
})

test('a model selector changes the pinned Execution Binding on an ordinary Node Instance', async ({ page }) => {
  await page.goto('/')

  const generationModel = page.getByRole('combobox', { name: 'Generate paired sequences and structures with remote ESM-3的执行模型' })
  await expect(generationModel).toHaveValue('esm3.generate_paired.biohub_medium')
  await expect(generationModel.locator('option')).toHaveText([
    'esm3-medium-2024-08',
    'esm3-open-2024-03',
    'esm3_sm_open_v1',
  ])
  await expect(page.getByRole('combobox', { name: 'Fold protein sequences的执行模型' }).first().locator('option')).toHaveText([
    'biohub/ESMFold2',
    'esmfold2-fast-2026-05',
    'simplefold_100M',
  ])

  await generationModel.selectOption('esm3.generate_paired.biohub_open')

  await expect(generationModel).toHaveValue('esm3.generate_paired.biohub_open')
  await expect(page.getByText('已自动保存')).toBeVisible()
  await expect(page.getByText('personal', { exact: true })).toBeVisible()

  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft'))
  await page.keyboard.press('Meta+z')
  const restored = await (await undoSave).json()
  expect(restored.workflow.nodes.find((node: { node_id: string }) => node.node_id === 'generate-paired').binding_id).toBe('esm3.generate_paired.biohub_medium')
  await expect(generationModel).toHaveValue('esm3.generate_paired.biohub_medium')
})

test('dragging an ordinary Palette operation adds and saves a Node Instance', async ({ page }) => {
  await page.goto('/')

  const operation = page.getByRole('button', { name: 'Invert a Candidate relation collection_ops' })
  const canvas = page.locator('.react-flow__pane')
  await operation.dragTo(canvas, { targetPosition: { x: 520, y: 620 } })

  await expect(page.getByRole('heading', { name: 'Invert a Candidate relation' })).toBeVisible()
  await expect(page.getByText(/37 GRAPH NODES/)).toBeVisible()
  await expect(page.getByText('已自动保存')).toBeVisible()
  await expect(page.getByText('personal', { exact: true })).toBeVisible()

  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft'))
  await page.keyboard.press('Meta+z')
  const restored = await (await undoSave).json()
  expect(restored.workflow.nodes.some((node: { node_type_id: string }) => node.node_type_id === 'collection_ops.invert_relation' && node.node_id.startsWith('collection_ops-invert_relation-'))).toBe(false)
  await expect(page.getByText(/36 GRAPH NODES/)).toBeVisible()
})

test('a committed parameter edit can be undone with the keyboard', async ({ page }) => {
  await page.goto('/')
  const generationNode = page.getByTestId('rf__node-generate-paired')
  await generationNode.getByLabel('编辑参数').click()
  const seed = generationNode.getByLabel('有效种子')
  await expect(seed).toHaveValue('1603')
  await seed.fill('1604')
  const parameterSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft'))
  await seed.press('Tab')
  await parameterSave

  await page.locator('.react-flow__pane').click({ force: true, position: { x: 1100, y: 800 } })
  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft'))
  await page.keyboard.press('Meta+z')
  const restored = await (await undoSave).json()
  expect(restored.workflow.nodes.find((node: { node_id: string }) => node.node_id === 'generate-paired').node_parameters.effective_seed).toBe(1603)
  await expect(seed).toHaveValue('1603')
})

test('Prompt Studio edits the backend projection and shows every prompt track', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '打开 Prompt Studio' }).click()

  await expect(page.getByRole('navigation', { name: 'Prompt Studio 模式' })).toBeVisible()
  await expect(page.getByRole('button', { name: '条件' })).toHaveClass(/active/)
  await expect(page.getByRole('rowheader', { name: 'Residue axis chain / locator' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'Sequence amino acid' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'Coordinates named atoms' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'Secondary structure SS8' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'SASA Å²' })).toBeVisible()
  await expect(page.getByRole('rowheader', { name: 'Function annotations tuple interval' })).toBeVisible()
  expect((await page.locator('.ps-residue-column > button:first-child').allTextContents()).join(' ')).not.toMatch(/insert-[0-9a-f]|inserted\./)

  await page.getByRole('button', { name: /A30 Sequence/ }).click()
  await page.getByRole('button', { name: 'Preserve', exact: true }).click()
  await expect(page.getByRole('button', { name: /A30 Sequence .* current/ })).toBeVisible()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: 'Clear', exact: true }).click()
  await expect(page.getByRole('button', { name: 'A30 Sequence Mask cleared' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /即时预览 · Sequence · clear/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存 ProteinPrompt' })).toBeDisabled()

  await page.getByRole('button', { name: '应用操作' }).click()
  await expect(page.getByRole('heading', { name: /即时预览/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '撤销' })).toBeEnabled()

  const a31 = page.getByRole('button', { name: /A31 Sequence/ })
  await a31.click()
  await a31.press('Q')
  await expect(page.getByRole('button', { name: 'A31 Sequence Q changed' })).toBeVisible()
  await a31.press('Enter')
  await expect(page.getByRole('heading', { name: /即时预览/ })).toHaveCount(0)

  const currentBeforeInsert = await page.locator('.ps-residue-column:not(.tombstone)').count()
  await page.getByRole('button', { name: 'Insert after focus' }).click()
  await expect(page.getByRole('button', { name: 'A31+1 Sequence Mask inserted' })).toBeVisible()
  const insertedColumn = page.locator('.ps-residue-column').filter({ has: page.locator('.state-inserted') }).first()
  await expect(insertedColumn).not.toHaveClass(/tombstone/)
  await expect(insertedColumn.locator('button').first()).toBeEnabled()
  await page.getByRole('button', { name: '应用操作' }).click()
  await expect(page.locator('.ps-residue-column:not(.tombstone)')).toHaveCount(currentBeforeInsert + 1)
  await page.getByRole('button', { name: '撤销' }).click()
  await expect(page.locator('.ps-residue-column:not(.tombstone)')).toHaveCount(currentBeforeInsert)
  await page.getByRole('button', { name: 'Insert after focus' }).click()
  await page.getByRole('button', { name: '取消', exact: true }).click()

  await page.getByRole('button', { name: '保存 ProteinPrompt' }).click()
  await expect(page.getByRole('dialog')).toContainText('Preview digest')
  await expect(page.getByRole('dialog')).toContainText('changed')
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
  const deletionSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft') && !JSON.parse(response.request().postData()!).workflow.nodes.some((node: { node_id: string }) => node.node_id === nodeId))
  await page.keyboard.press('Delete')
  const deletedDraft = await (await deletionSave).json()
  expect(deletedDraft.workflow.nodes.map((node: { node_id: string }) => node.node_id)).not.toContain(nodeId)
  expect(deletedDraft.workflow.edges).not.toEqual(expect.arrayContaining(incidentEdges))
  const undoSave = page.waitForResponse((response) => response.request().method() === 'PUT' && response.url().endsWith('/workflow/draft'))
  await page.keyboard.press('Meta+z')
  const restoredDraft = await (await undoSave).json()
  expect(restoredDraft.workflow.nodes.map((node: { node_id: string }) => node.node_id)).toContain(nodeId)
  expect(restoredDraft.workflow.edges).toEqual(expect.arrayContaining(incidentEdges))
})

test('starting a run waits for the latest autosaved Workflow revision', async ({ page }) => {
  let releaseSave!: () => void
  let markSaveStarted!: () => void
  const saveRelease = new Promise<void>((resolve) => { releaseSave = resolve })
  const saveStarted = new Promise<void>((resolve) => { markSaveStarted = resolve })
  let committedSeed: number | undefined

  await page.route('**/workflow/draft', async (route) => {
    if (route.request().method() === 'PUT') {
      markSaveStarted()
      await saveRelease
    }
    await route.continue()
  })
  await page.route('**/workflow:commit', async (route) => {
    const body = JSON.parse(route.request().postData()!)
    committedSeed = body.workflow.nodes.find((node: { node_id: string }) => node.node_id === 'generate-paired').node_parameters.effective_seed
    await route.fulfill({ json: { workflow_commit_id: 'workflow-commit-current-draft' } })
  })
  await page.route('**/api/v2/projects/*/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    await route.fulfill({ json: {
      project_id: 'project-current-draft',
      run_id: 'run-current-draft',
      workflow_commit_id: 'workflow-commit-current-draft',
      admitted_sequence: 1,
      event_cursor: 'cursor-current-draft',
    } })
  })

  await page.goto('/')
  const generationNode = page.getByTestId('rf__node-generate-paired')
  await generationNode.getByLabel('编辑参数').click()
  const seed = generationNode.getByLabel('有效种子')
  await seed.fill('1604')
  await seed.press('Tab')
  await saveStarted
  await page.getByRole('button', { name: '运行完整流程' }).click()
  await page.getByRole('button', { name: '开始运行' }).click()
  await page.waitForTimeout(150)
  expect(committedSeed).toBeUndefined()

  releaseSave()
  await expect.poll(() => committedSeed).toBe(1604)
})

test('a started workflow reports its live status and current stage', async ({ page }) => {
  await page.routeWebSocket(/\/runs\/run-ui-progress\/events/, (webSocket) => {
    setTimeout(() => {
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        sequence: 2,
        cursor: 'cursor-node-started',
        emitted_at: '2026-09-01T00:00:00Z',
        event: {
          type: 'node_attempt_started',
          node_id: 'generate-paired',
          node_attempt_id: 'attempt-generate-paired',
        },
      }))
    }, 100)
    setTimeout(() => {
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        sequence: 3,
        cursor: 'cursor-node-succeeded',
        emitted_at: '2026-09-01T00:00:01Z',
        event: {
          type: 'node_disposition',
          disposition: {
            node_id: 'generate-paired',
            outcome: 'succeeded',
            blocked_by: [],
            resolution: 'executed',
            terminal_sequence: 3,
          },
        },
      }))
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        sequence: 4,
        cursor: 'cursor-internal-node-started',
        emitted_at: '2026-09-01T00:00:01Z',
        event: {
          type: 'node_attempt_started',
          node_id: 'confidence-generated',
          node_attempt_id: 'attempt-confidence-generated',
        },
      }))
    }, 1000)
    setTimeout(() => {
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        sequence: 5,
        cursor: 'cursor-internal-node-failed',
        emitted_at: '2026-09-01T00:00:02Z',
        event: {
          type: 'node_disposition',
          disposition: {
            node_id: 'confidence-generated',
            outcome: 'failed',
            blocked_by: [],
            terminal_sequence: 5,
          },
        },
      }))
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        sequence: 6,
        cursor: 'cursor-downstream-blocked',
        emitted_at: '2026-09-01T00:00:03Z',
        event: {
          type: 'node_disposition',
          disposition: {
            node_id: 'select-paired-sequences',
            outcome: 'blocked',
            blocked_by: ['confidence-generated'],
            terminal_sequence: 6,
          },
        },
      }))
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        sequence: 7,
        cursor: 'cursor-run-failed',
        emitted_at: '2026-09-01T00:00:04Z',
        event: { type: 'run_terminal', status: 'failed' },
      }))
    }, 2200)
  })
  await page.route('**/api/v2/projects/*/runs', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ json: {
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        workflow_commit_id: 'commit-ui-progress',
        admitted_sequence: 1,
        event_cursor: 'cursor-admitted',
      } })
      return
    }
    await route.continue()
  })
  await page.route('**/api/v2/projects/*/runs/run-ui-progress', async (route) => {
    await route.fulfill({
      json: {
        project_id: 'project-ui-progress',
        run_id: 'run-ui-progress',
        workflow_commit_id: 'commit-ui-progress',
        status: 'failed',
        ledger_cursor: '0',
        node_dispositions: [
          {
            node_id: 'generate-paired',
            outcome: 'succeeded',
            blocked_by: [],
            resolution: 'executed',
            terminal_sequence: 3,
          },
          {
            node_id: 'confidence-generated',
            outcome: 'failed',
            blocked_by: [],
            terminal_sequence: 5,
          },
          {
            node_id: 'select-paired-sequences',
            outcome: 'blocked',
            blocked_by: ['confidence-generated'],
            terminal_sequence: 6,
          },
        ],
        outputs: [],
        artifact_index: [],
      },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '运行完整流程' }).click()
  await page.getByRole('button', { name: '开始运行' }).click()

  await expect(page.getByRole('status')).toContainText('正在运行')
  await expect(page.getByRole('status')).toContainText('当前阶段')
  await expect(page.getByRole('status')).toContainText('generate-paired')
  await expect(page.getByTestId('rf__node-generate-paired').getByLabel('Generate paired sequences and structures with remote ESM-3：运行中')).toBeVisible()
  await expect(page.getByTestId('rf__node-generate-paired').getByLabel('Generate paired sequences and structures with remote ESM-3：成功')).toBeVisible()
  await expect(page.getByRole('status')).toContainText('confidence-generated')
  await expect(page.getByTestId('rf__node-confidence-generated').getByLabel('Materialize structure-prediction confidence：运行中')).toBeVisible()
  await expect(page.getByRole('status')).toContainText('运行失败')
  await expect(page.getByTestId('rf__node-confidence-generated').getByLabel('Materialize structure-prediction confidence：失败')).toBeVisible()
  await expect(page.getByTestId('rf__node-select-paired-sequences').getByLabel('Select related subjects by reference：未执行')).toBeVisible()
  await expect(page.getByRole('status')).toContainText('3 / 36 Nodes')
})

test('an active run reload restores waiting stages and replays the current node', async ({ page }) => {
  await page.route('**/api/v2/projects', async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    const example = payload.projects.find((item: { id: string }) => item.id === 'webui-3gb1-example')
    example.latest_run_id = 'active-run'
    await route.fulfill({ response, json: payload })
  })
  await page.route(/\/api\/v2\/projects\/[^/]+\/runs\/[^/]+$/, async (route) => {
    const parts = new URL(route.request().url()).pathname.split('/')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: parts[4],
        run_id: parts[6],
        workflow_commit_id: 'commit-active-reload',
        status: 'running',
        ledger_cursor: 'cursor-after-generate',
        node_dispositions: [{
          node_id: 'generate-paired',
          outcome: 'succeeded',
          blocked_by: [],
          resolution: 'executed',
          terminal_sequence: 3,
        }],
        outputs: [],
        artifact_index: [],
      }),
    })
  })
  let replayStarted!: () => void
  await page.routeWebSocket(/\/runs\/[^/]+\/events/, (webSocket) => {
    expect(webSocket.url()).not.toContain('after_sequence')
    replayStarted = () => {
      webSocket.send(JSON.stringify({
        schema_namespace: 'protein-workbench-public/v2',
        project_id: 'default-example',
        run_id: 'active-run',
        sequence: 4,
        cursor: 'cursor-confidence-started',
        emitted_at: '2026-09-01T00:00:01Z',
        event: {
          type: 'node_attempt_started',
          node_id: 'confidence-generated',
          node_attempt_id: 'attempt-confidence-generated',
        },
      }))
    }
  })

  await page.goto('/')

  await expect(page.getByTestId('rf__node-generate-paired').getByLabel('Generate paired sequences and structures with remote ESM-3：成功')).toBeVisible()
  await expect(page.getByTestId('rf__node-confidence-generated').getByLabel('Materialize structure-prediction confidence：等待')).toBeVisible()
  await expect.poll(() => typeof replayStarted).toBe('function')
  replayStarted()
  await expect(page.getByTestId('rf__node-confidence-generated').getByLabel('Materialize structure-prediction confidence：运行中')).toBeVisible()
})
