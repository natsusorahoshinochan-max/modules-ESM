import { matrixCell } from '../support/matrix-cell'
import { expect, test, type Page } from '@playwright/test'
import type { PromptAuthoringDocument, PromptPreview, PromptSnapshot, WorkflowDraft } from '../../src/protocol/client'


async function matrixHandles(page: Page) {
  const columns = new Map<number, string>()
  const scroller = page.locator('.ag-body-horizontal-scroll-viewport')
  const { width, maximum } = await scroller.evaluate(element => ({ width: element.clientWidth, maximum: element.scrollWidth - element.clientWidth }))
  for (let offset = 0; offset <= maximum + width; offset += Math.max(1, width / 2)) {
    await scroller.evaluate((element, left) => { element.scrollLeft = left }, Math.min(offset, maximum))
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    const visible = await page.locator('[data-cell$=":sequence"]').evaluateAll(elements => elements.map(element => ({
      index: Number(element.closest('[role="gridcell"]')!.getAttribute('aria-colindex')),
      handle: element.getAttribute('data-cell')!.replace(':sequence', ''),
    })))
    for (const column of visible) columns.set(column.index, column.handle)
  }
  return [...columns].sort(([left], [right]) => left - right).map(([, handle]) => handle)
}

async function applyToolPreview(page: Page) {
  await page.getByRole('dialog').getByRole('button', { name: '应用操作', exact: true }).click()
  await page.getByRole('button', { name: '返回矩阵', exact: true }).click()
}

async function personalDraft(page: Page) {
  const projects = await (await page.request.get('/api/v2/projects')).json()
  const seed = projects.projects.find((project: { project_kind: string }) => project.project_kind === 'default_example')
  const copied = await page.request.post(`/api/v2/projects/${seed.id}:copy`, { data: { name: `Prompt fixture ${crypto.randomUUID()}` } })
  expect(copied.status()).toBe(201)
  const project = await copied.json()
  const url = `/api/v2/projects/${project.id}/workspace`
  const draft = (await (await page.request.get(url)).json()).draft as WorkflowDraft
  await page.goto('/')
  await reopenStoredDraft(page, url, draft.workflow.nodes.find(node => node.node_type_id === 'prompt_authoring.author')!.node_id)
  return { url, draft }
}

async function reopenStoredDraft(page: Page, url: string, authorNodeId: string) {
  const name = `Prompt regression ${crypto.randomUUID()}`
  expect((await page.request.patch(url.replace('/workspace', ''), { data: { name } })).status()).toBe(200)
  await page.getByRole('button', { name: '项目', exact: true }).click()
  const manager = page.getByRole('dialog', { name: '项目与版本', exact: true })
  await manager.getByRole('button').filter({ has: page.getByText(name, { exact: true }) }).click()
  await manager.getByRole('button', { name: '打开项目', exact: true }).click()
  await expect(manager).not.toBeVisible()
  const authorButton = page.getByTestId(`rf__node-${authorNodeId}`).getByRole('button', { name: '打开 Prompt Studio', exact: true })
  const geometry = async () => ({
    target: await authorButton.boundingBox(),
    canvas: await page.locator('.flow-canvas').boundingBox(),
    breadcrumb: await page.getByRole('navigation', { name: '节点组路径', exact: true }).boundingBox(),
    viewport: page.viewportSize(),
  })
  const before = await geometry()
  // API-authored nodes can lie outside the workspace's saved viewport. Use the same fit control as a user.
  await page.getByRole('button', { name: '适合视图', exact: true }).click()
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await test.info().attach('prompt-node-fit-geometry', {
    body: Buffer.from(JSON.stringify({ nodeId: authorNodeId, before, after: await geometry() }, null, 2)),
    contentType: 'application/json',
  })
  await expect(authorButton).toBeVisible()
  // Transformed nodes can produce intersection ratios fractionally below 1.
  // Require every button edge inside the visible canvas, allowing one CSS pixel of rounding.
  await expect.poll(async () => {
    const { target, canvas, viewport } = await geometry()
    if (!target || !canvas || !viewport || target.width <= 0 || target.height <= 0) return Infinity
    return Math.max(
      0,
      Math.max(0, canvas.x) - target.x,
      Math.max(0, canvas.y) - target.y,
      target.x + target.width - Math.min(viewport.width, canvas.x + canvas.width),
      target.y + target.height - Math.min(viewport.height, canvas.y + canvas.height),
    )
  }, { message: 'Prompt button must fit inside the visible canvas within 1 CSS pixel' }).toBeLessThanOrEqual(1)
}

for (const explicitTargets of [true, false]) {
  test(`random insertions remain editable, insertable and deletable; explicit targets=${explicitTargets}`, async ({ page }) => {
    const { draft, url } = await personalDraft(page)
    const author = draft.workflow.nodes.find(n => n.node_type_id === 'prompt_authoring.author')!
    const document = author.node_parameters.document as PromptAuthoringDocument
    document.random_operations = [{ kind: 'insert', seed: 42, count: 1 }]
    if (!explicitTargets) {
      delete document.target_residues
      delete document.track_edits
      delete document.function_annotations
    }
    expect((await page.request.put(url, { data: { workflow: draft.workflow } })).status()).toBe(200)
    await reopenStoredDraft(page, url, author.node_id)
    const opening = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:open') && r.request().postDataJSON().node_id === author.node_id)
    await page.getByRole('button', { name: '打开 Prompt Studio' }).click()
    const snapshot = await (await opening).json() as PromptSnapshot
    const handle = snapshot.random_selections.find(r => r.kind === 'insert')!.realized_residue_handles[0]
    const cell = await matrixCell(page, handle, 'sequence')
    await cell.click()
    await page.getByRole('button', { name: '布局', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Delete selected', exact: true })).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Insert after focus', exact: true })).toBeEnabled()
    await page.getByRole('button', { name: '返回矩阵', exact: true }).click()
    const other = snapshot.residues.find(r => r.residue_handle !== handle)!
    await (await matrixCell(page, other.residue_handle, 'sequence')).click({ modifiers: ['ControlOrMeta'] })
    await page.getByRole('button', { name: '布局', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Delete selected', exact: true })).toBeEnabled()
    await page.getByRole('button', { name: '返回矩阵', exact: true }).click()
    await (await matrixCell(page, handle, 'sequence')).click()
    await page.getByRole('button', { name: '条件', exact: true }).click()
    const previewing = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:preview'))
    const editable = await matrixCell(page, handle, 'sequence')
    await editable.press('F2')
    await editable.locator('input').fill('G')
    await editable.locator('input').press('Enter')
    const response = await previewing
    expect(response.status()).toBe(200)
    const preview = await response.json() as PromptPreview
    expect(preview.diagnostics).toEqual([])
    expect(preview.tracks.sequence.values.find(v => v.residue_handle === handle)?.value).toBe('G')
    expect(preview.normalized_document.random_operations).toEqual(document.random_operations)
    await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeEnabled()
    const ordinary = snapshot.residues.find(r => r.residue_handle === handle)!
    await (await matrixCell(page, ordinary.residue_handle, 'sequence')).click()
    await page.getByRole('button', { name: '布局', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Delete selected', exact: true })).toBeEnabled()
    const deleting = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:preview'))
    await page.getByRole('button', { name: 'Delete selected', exact: true }).click()
    const deleted = await (await deleting).json() as PromptPreview
    expect(deleted.diagnostics).toEqual([])
    expect(deleted.residues.find(r => r.residue_handle === ordinary.residue_handle)?.state).toBe('pending-delete')
    expect(deleted.normalized_document.random_operations).toEqual([{
      ...document.random_operations![0],
      target_residues: snapshot.merge_targets[0].residues.filter(residue => residue.residue_handle !== handle).map(residue => ({ residue_id: residue.residue_id, origin: 'source' })),
    }])
    await page.getByRole('button', { name: '返回矩阵', exact: true }).click()
    const displayed = await matrixHandles(page)
    expect(displayed).toEqual(deleted.residues.map(r => r.residue_handle))
  })
}

test('Palette author declares chains and applies a local preview', async ({ page }) => {
  await personalDraft(page)
  const existing = new Set(await page.locator('[data-testid^="rf__node-"]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-testid'))))
  await page.getByRole('button', { name: 'Author ProteinPrompt prompt_authoring', exact: true }).dragTo(page.locator('.react-flow__pane'), { targetPosition: { x: 520, y: 620 } })
  const addedNode = page.locator('[data-testid^="rf__node-"]').filter({ has: page.getByRole('button', { name: '打开 Prompt Studio' }) })
  await expect.poll(async () => (await addedNode.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-testid')))).filter(id => !existing.has(id)).length).toBe(1)
  const addedId = (await addedNode.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-testid')!))).find(id => !existing.has(id))!.replace('rf__node-', '')
  const opening = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:open') && r.request().postDataJSON().node_id === addedId)
  await page.getByTestId(`rf__node-${addedId}`).getByRole('button', { name: '打开 Prompt Studio' }).click()
  expect((await opening).status()).toBe(200)
  await page.getByRole('button', { name: '插入 / 删除', exact: true }).click()
  await page.getByRole('button', { name: '添加 Chain', exact: true }).click()
  await page.getByLabel('Chain 1 ID', { exact: true }).fill('!')
  await page.getByLabel('Chain 1 length', { exact: true }).fill('3')
  const invalid = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:preview'))
  await page.getByRole('button', { name: '预览 Chains', exact: true }).click()
  expect((await invalid).status()).toBe(400)
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Chain 1 ID', { exact: true })).toBeEnabled()
  await page.getByLabel('Chain 1 ID', { exact: true }).fill('A')
  await page.getByRole('button', { name: '预览 Chains', exact: true }).click()
  await applyToolPreview(page)
  await expect(page.getByRole('grid')).toHaveAttribute('aria-colcount', '4')
  await expect(page.locator('.ps-session-state')).toContainText('有未保存修改')
})

test('matrix selection and immediate toolbar typing preserve the new residue edit', async ({ page }) => {
  const { draft } = await personalDraft(page)
  const author = draft.workflow.nodes.find(node => node.node_type_id === 'prompt_authoring.author')!
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open'))
  await page.getByTestId(`rf__node-${author.node_id}`).getByRole('button', { name: '打开 Prompt Studio' }).click()
  const snapshot = await (await opening).json() as PromptSnapshot
  const [first, second] = snapshot.residues
  await (await matrixCell(page, first.residue_handle, 'sequence')).click()
  await page.getByLabel('指定氨基酸', { exact: true }).fill('W')
  const secondCell = await matrixCell(page, second.residue_handle, 'sequence')
  const previewResponse = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:preview'))
  // Keep click and typing ahead of AG Grid's deferred event callbacks.
  await secondCell.evaluate(async element => {
    (element as HTMLElement).click()
    // Flush React's discrete click update without dispatching AG Grid's deferred queue.
    await Promise.resolve()
    const input = document.querySelector<HTMLInputElement>('input[aria-label="指定氨基酸"]')!
    input.focus()
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'G')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await page.getByRole('button', { name: 'Specify', exact: true }).click()
  const preview = await (await previewResponse).json() as PromptPreview
  expect(preview.tracks.sequence.values.find(row => row.residue_handle === second.residue_handle)?.value).toBe('G')
  expect(preview.tracks.sequence.values.find(row => row.residue_handle === first.residue_handle)?.value).toEqual(snapshot.tracks.sequence.values.find(row => row.residue_handle === first.residue_handle)?.value)
  await (await matrixCell(page, first.residue_handle, 'sequence')).click()
  const firstValue = snapshot.tracks.sequence.values.find(row => row.residue_handle === first.residue_handle)?.value
  await expect(page.getByLabel('指定氨基酸', { exact: true })).toHaveValue(firstValue == null ? '' : String(firstValue))
  await (await matrixCell(page, second.residue_handle, 'sequence')).click()
  await expect(page.getByLabel('指定氨基酸', { exact: true })).toHaveValue('G')
})

test('an external saved revision does not overwrite the local Prompt proposal', async ({ page }) => {
  const { draft, url } = await personalDraft(page)
  const author = draft.workflow.nodes.find(node => node.node_type_id === 'prompt_authoring.author')!
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open'))
  await page.getByTestId(`rf__node-${author.node_id}`).getByRole('button', { name: '打开 Prompt Studio' }).click()
  const snapshot = await (await opening).json() as PromptSnapshot
  const handle = snapshot.residues[0].residue_handle
  await (await matrixCell(page, handle, 'sequence')).click()
  await page.getByLabel('指定氨基酸', { exact: true }).fill('W')
  const proposal = await resultingPreview(page, () => page.getByRole('button', { name: 'Specify', exact: true }).click())
  const external = structuredClone(draft.workflow)
  external.nodes.find(node => node.node_id === author.node_id)!.node_parameters.document = { chains: [{ chain_id: 'A', length: 2 }] }
  expect((await page.request.put(url, { data: { workflow: external } })).status()).toBe(200)
  await expect((await matrixCell(page, handle, 'sequence')).locator('strong')).toHaveText('W')
  await expect(page.locator('.ps-session-state')).toContainText('有未保存修改')
  expect(proposal.tracks.sequence.values.find(item => item.residue_handle === handle)?.value).toBe('W')
  expect((await (await page.request.get(url)).json()).draft.workflow).toEqual(external)
})

test('a stale chain declaration can be repaired inside Studio', async ({ page }) => {
  const { draft, url } = await personalDraft(page)
  const author = draft.workflow.nodes.find(n => n.node_type_id === 'prompt_authoring.author')!
  author.node_parameters.document = { chains: [{ chain_id: 'A', length: 3 }] }
  const sourceDocument: PromptAuthoringDocument = { chains: [{ chain_id: 'A', length: 4 }], track_edits: [1, 2, 3, 4].map(i => ({ track: 'sequence', action: 'replace', residue_id: `A:${i}`, value: 'A' })) }
  draft.workflow.nodes.push(
    { node_id: 'review-source', node_type_id: 'prompt_authoring.author', binding_id: 'prompt_authoring.author.direct', node_parameters: { document: sourceDocument }, binding_parameters: {} },
    { node_id: 'review-decompose', node_type_id: 'prompt_authoring.decompose', binding_id: 'prompt_authoring.decompose.direct', node_parameters: {}, binding_parameters: {} },
    { node_id: 'review-materialize', node_type_id: 'residue_data.materialize_sequence', binding_id: 'residue_data.materialize_sequence.direct', node_parameters: {}, binding_parameters: {} },
  )
  draft.workflow.edges = draft.workflow.edges.filter(e => e.target_node_id !== author.node_id)
  draft.workflow.edges.push(
    { source_node_id: 'review-source', source_port: 'protein_prompt', target_node_id: 'review-decompose', target_port: 'protein_prompt' },
    { source_node_id: 'review-decompose', source_port: 'sequence', target_node_id: 'review-materialize', target_port: 'sequence' },
    { source_node_id: 'review-materialize', source_port: 'sequence', target_node_id: author.node_id, target_port: 'sequence_source' },
  )
  expect((await page.request.put(url, { data: { workflow: draft.workflow } })).status()).toBe(200)
  await reopenStoredDraft(page, url, author.node_id)
  await page.getByTestId(`rf__node-${author.node_id}`).getByRole('button', { name: '打开 Prompt Studio' }).click()
  await expect(page.getByText('无可比较的旧结果', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '插入 / 删除', exact: true }).click()
  await page.getByLabel('Chain 1 length', { exact: true }).fill('4')
  await page.getByRole('button', { name: '预览 Chains', exact: true }).click()
  await applyToolPreview(page)
  await expect(page.getByRole('grid')).toHaveAttribute('aria-colcount', '5')
  await expect(page.locator('.ps-session-state')).toContainText('有未保存修改')
})

async function openedPrompt(page: Page) {
  const { draft } = await personalDraft(page)
  const author = draft.workflow.nodes.find(node => node.node_type_id === 'prompt_authoring.author')!
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === author.node_id)
  await page.getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
  return await (await opening).json() as PromptSnapshot
}

async function resultingPreview(page: Page, action: () => Promise<void>) {
  const response = page.waitForResponse(item => item.url().endsWith('/prompt-authoring:preview'))
  await action()
  const result = await response
  expect(result.status()).toBe(200)
  const preview = await result.json() as PromptPreview
  expect(preview.diagnostics).toEqual([])
  return preview
}

test('successive track commits retain both values and each undo restores its preceding document', async ({ page }) => {
  const snapshot = await openedPrompt(page)
  const residue = snapshot.residues.find(item => item.state !== 'pending-delete')!
  await (await matrixCell(page, residue.residue_handle, 'sequence')).click()
  await page.getByLabel('指定氨基酸', { exact: true }).fill('W')
  await resultingPreview(page, () => page.getByRole('button', { name: 'Specify', exact: true }).click())
  await (await matrixCell(page, residue.residue_handle, 'sasa')).click()
  await page.getByLabel('指定 SASA', { exact: true }).fill('12.5')
  const joint = await resultingPreview(page, () => page.getByRole('button', { name: 'Specify', exact: true }).click())
  expect(joint.tracks.sequence.values.find(item => item.residue_handle === residue.residue_handle)!.value).toBe('W')
  expect(joint.tracks.sasa.values.find(item => item.residue_handle === residue.residue_handle)!.value).toBe(12.5)
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect((await matrixCell(page, residue.residue_handle, 'sequence')).locator('strong')).toHaveText('W')
  const priorSasa = snapshot.tracks.sasa.values.find(item => item.residue_handle === residue.residue_handle)?.value
  await expect((await matrixCell(page, residue.residue_handle, 'sasa')).locator('strong')).toHaveText(!snapshot.tracks.sasa.present ? 'Absent' : priorSasa == null ? 'Mask' : String(priorSasa))
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  const original = snapshot.tracks.sequence.values.find(item => item.residue_handle === residue.residue_handle)!.value
  await expect((await matrixCell(page, residue.residue_handle, 'sequence')).locator('strong')).toHaveText(original === null ? 'Mask' : String(original))
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
})

test('rigid controls use all atom centroid, compose transforms and retain other residues', async ({ page }) => {
  const snapshot = await openedPrompt(page)
  const coordinateRows = snapshot.tracks.coordinates.values.filter(item => item.value !== null)
  const chosen = coordinateRows.slice(0, 2)
  const atomValues = chosen.flatMap(item => (item.value as { atoms: Array<{ coordinates: number[] }> }).atoms)
  const origin = [0, 1, 2].map(index => atomValues.reduce((sum, atom) => sum + atom.coordinates[index], 0) / atomValues.length)
  await (await matrixCell(page, chosen[0].residue_handle, 'coordinates')).click()
  await (await matrixCell(page, chosen[1].residue_handle, 'coordinates')).click({ modifiers: ['ControlOrMeta'] })
  const coordinateCell = await matrixCell(page, chosen[1].residue_handle, 'coordinates')
  await coordinateCell.press('F2')
  await expect(page.getByRole('dialog', { name: '精确结构参数', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'G 位移', exact: true }).click()
  await page.getByRole('button', { name: 'X', exact: true }).click()
  await page.getByLabel('变换数值', { exact: true }).fill('10')
  await expect(page.getByLabel('变换数值', { exact: true })).toHaveValue('10')
  const moved = await resultingPreview(page, () => page.getByRole('button', { name: '预览刚体变换', exact: true }).click())
  const transform = moved.normalized_document.rigid_transforms!.at(-1)!
  expect(transform.origin).toEqual(origin)
  expect(transform.translation).toEqual([10, 0, 0])
  await page.getByLabel('变换数值', { exact: true }).fill('3')
  const composed = await resultingPreview(page, () => page.getByRole('button', { name: '预览刚体变换', exact: true }).click())
  const firstBefore = (chosen[0].value as { atoms: Array<{ coordinates: number[] }> }).atoms[0].coordinates
  const firstAfter = (composed.tracks.coordinates.values.find(item => item.residue_handle === chosen[0].residue_handle)!.value as { atoms: Array<{ coordinates: number[] }> }).atoms[0].coordinates
  expect(firstAfter[0]).toBeCloseTo(firstBefore[0] + 13)
  expect(firstAfter.slice(1)).toEqual(firstBefore.slice(1))
  const unselected = coordinateRows[2]
  expect(composed.tracks.coordinates.values.find(item => item.residue_handle === unselected.residue_handle)!.value).toEqual(unselected.value)
})

test('random controls expose backend realized selection and stable explicit seed', async ({ page }) => {
  const snapshot = await openedPrompt(page)
  await (await matrixCell(page, snapshot.residues[0].residue_handle, 'sequence')).click()
  await page.getByRole('button', { name: '随机操作', exact: true }).click()
  await page.getByLabel('随机数量', { exact: true }).fill('1')
  await page.getByLabel('随机 seed', { exact: true }).fill('123')
  const first = await resultingPreview(page, () => page.getByRole('button', { name: '预览随机操作', exact: true }).click())
  const repeated = await resultingPreview(page, () => page.getByRole('button', { name: '预览随机操作', exact: true }).click())
  expect(repeated.random_selections).toEqual(first.random_selections)
  const redrawn = await resultingPreview(page, () => page.getByRole('button', { name: '换 seed 重抽', exact: true }).click())
  expect(redrawn.normalized_document.random_operations!.at(-1)!.seed).toBe(124)
  await expect(page.getByText(/实际位置：/).last()).toContainText(/[A-Za-z]/)
})

test('manual region merge requires explicit correspondence and Mask choice', async ({ page }) => {
  const { draft, url } = await personalDraft(page)
  const author = draft.workflow.nodes.find(item => item.node_type_id === 'prompt_authoring.author')!
  author.node_parameters.document = {}
  const sourceNode = (node_id: string, letters: Array<string | null>) => ({ node_id, node_type_id: 'prompt_authoring.author', binding_id: 'prompt_authoring.author.direct', node_parameters: { document: { chains: [{ chain_id: 'A', length: letters.length }], track_edits: letters.flatMap((letter, index) => letter === null ? [] : [{ track: 'sequence', residue_id: `A:${index + 1}`, action: 'replace', value: letter }]) } }, binding_parameters: {} })
  draft.workflow.nodes.push(sourceNode('merge-base', ['A', 'C']), sourceNode('merge-source', ['G', null, 'T']))
  draft.workflow.edges = draft.workflow.edges.filter(item => item.target_node_id !== author.node_id)
  draft.workflow.edges.push(
    { source_node_id: 'merge-base', source_port: 'protein_prompt', target_node_id: author.node_id, target_port: 'prompt_source' },
    { source_node_id: 'merge-source', source_port: 'protein_prompt', target_node_id: author.node_id, target_port: 'merge_sources' },
  )
  expect((await page.request.put(url, { data: { workflow: draft.workflow } })).status()).toBe(200)
  await reopenStoredDraft(page, url, author.node_id)
  await page.getByTestId(`rf__node-${author.node_id}`).getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
  await page.getByRole('button', { name: '合并来源', exact: true }).click()
  await expect(page.getByRole('combobox', { name: '合并来源', exact: true })).toContainText('merge-source')
  await expect(page.getByRole('button', { name: '预览区域合并', exact: true })).toBeDisabled()
  for (const index of [1, 2, 3]) {
    await page.getByRole('button', { name: '添加手动对应行', exact: true }).click()
    await page.getByLabel(`对应 ${index} 来源`, { exact: true }).selectOption(`A:${index}`)
    if (index === 3) {
      await page.getByLabel('对应 3 类型', { exact: true }).selectOption('insert')
      await page.getByLabel('对应 3 新增目标', { exact: true }).fill('A:new')
    } else await page.getByLabel(`对应 ${index} 目标`, { exact: true }).selectOption(`A:${index}`)
    await page.getByLabel(`采用 A:${index} sequence`, { exact: true }).check()
  }
  await expect(page.getByRole('button', { name: '预览区域合并', exact: true })).toBeDisabled()
  await page.getByLabel('sequence Mask 处理', { exact: true }).selectOption('adopt')
  const preview = await resultingPreview(page, () => page.getByRole('button', { name: '预览区域合并', exact: true }).click())
  expect(preview.residues.filter(item => item.state !== 'pending-delete').map(item => item.residue_id)).toEqual(['A:1', 'A:2', 'A:new'])
  expect(preview.tracks.sequence.values.map(item => item.value)).toEqual(['G', null, 'T'])
  expect(preview.normalized_document.source_merges![0].track_adoptions).toEqual([{ track: 'sequence', source_residue_ids: ['A:1', 'A:2', 'A:3'], mask_policy: 'adopt' }])
  await page.getByRole('button', { name: '打开来源 / 目标证据分屏', exact: true }).click()
  const evidence = page.getByRole('dialog', { name: '来源 / 目标证据分屏', exact: true })
  await expect(evidence.getByRole('button', { name: '目标残基 A:1', exact: true })).toContainText('A')
  await expect(evidence.getByRole('button', { name: '目标残基 A:2', exact: true })).toContainText('C')
  await expect(evidence.getByRole('button', { name: '目标残基 A:new', exact: true })).toHaveCount(0)
  await evidence.getByRole('button', { name: '来源残基 A:2', exact: true }).click()
  await expect(evidence.getByRole('button', { name: '目标残基 A:2', exact: true })).toHaveClass(/selected/)
  await evidence.getByRole('button', { name: '来源残基 A:2', exact: true }).click({ modifiers: ['ControlOrMeta'] })
  await expect(evidence.getByRole('button', { name: '目标残基 A:2', exact: true })).not.toHaveClass(/selected/)
  await expect(evidence.getByLabel('区域采用影响')).toContainText('明确清除目标')
  await evidence.getByLabel('查看当前后端结果（编辑意图始终引用目标基线）').check()
  await expect(evidence.getByRole('button', { name: '目标残基 A:new', exact: true })).toContainText('T')
  await evidence.getByRole('button', { name: '关闭合并分屏', exact: true }).click()
  await applyToolPreview(page)
  await expect(page.locator('.ps-session-state')).toContainText('有未保存修改')
})

test('Function endpoint and split edits preserve exact tuple identity', async ({ page }) => {
  const { draft, url } = await personalDraft(page)
  const author = draft.workflow.nodes.find(item => item.node_type_id === 'prompt_authoring.author')!
  author.node_parameters.document = { chains: [{ chain_id: 'A', length: 4 }], function_annotations: [{ label: 'site', start_residue_id: 'A:1', end_residue_id: 'A:4' }] }
  draft.workflow.edges = draft.workflow.edges.filter(item => item.target_node_id !== author.node_id)
  expect((await page.request.put(url, { data: { workflow: draft.workflow } })).status()).toBe(200)
  await reopenStoredDraft(page, url, author.node_id)
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === author.node_id)
  await page.getByTestId(`rf__node-${author.node_id}`).getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
  const snapshot = await (await opening).json() as PromptSnapshot
  await page.getByRole('button', { name: '条件', exact: true }).click()
  await (await matrixCell(page, snapshot.residues[0].residue_handle, 'function')).getByRole('button', { name: /编辑 .* Function/ }).click()
  await expect(page.getByRole('dialog', { name: 'Function 区间', exact: true })).toBeVisible()
  await page.getByLabel('Function 终点', { exact: true }).selectOption('A:3')
  const edited = await resultingPreview(page, () => page.getByRole('button', { name: '预览端点修改', exact: true }).click())
  expect(edited.normalized_document.function_annotations).toEqual([{ label: 'site', start_residue_id: 'A:1', end_residue_id: 'A:3' }])
  await page.getByLabel('Function 拆分点', { exact: true }).selectOption('A:1')
  const split = await resultingPreview(page, () => page.getByRole('button', { name: '预览拆分', exact: true }).click())
  expect(split.normalized_document.function_annotations).toEqual([{ label: 'site', start_residue_id: 'A:1', end_residue_id: 'A:1' }, { label: 'site', start_residue_id: 'A:2', end_residue_id: 'A:3' }])
})

test('split evidence records explicit leading and trailing gaps with regional adoption', async ({ page }) => {
  const { draft, url } = await personalDraft(page)
  const author = draft.workflow.nodes.find(item => item.node_type_id === 'prompt_authoring.author')!
  author.node_parameters.document = {}
  const sourceNode = (node_id: string, sequence: string) => ({ node_id, node_type_id: 'prompt_authoring.author', binding_id: 'prompt_authoring.author.direct', node_parameters: { document: { chains: [{ chain_id: 'A', length: sequence.length }], track_edits: [...sequence].map((value, index) => ({ track: 'sequence', residue_id: `A:${index + 1}`, action: 'replace', value })) } }, binding_parameters: {} })
  draft.workflow.nodes.push(sourceNode('gap-base', 'ACT'), sourceNode('gap-source', 'GWS'))
  draft.workflow.edges = draft.workflow.edges.filter(item => item.target_node_id !== author.node_id)
  draft.workflow.edges.push({ source_node_id: 'gap-base', source_port: 'protein_prompt', target_node_id: author.node_id, target_port: 'prompt_source' }, { source_node_id: 'gap-source', source_port: 'protein_prompt', target_node_id: author.node_id, target_port: 'merge_sources' })
  expect((await page.request.put(url, { data: { workflow: draft.workflow } })).status()).toBe(200)
  await reopenStoredDraft(page, url, author.node_id)
  await page.getByTestId(`rf__node-${author.node_id}`).getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
  await page.getByRole('button', { name: '合并来源', exact: true }).click()
  await page.getByRole('button', { name: '打开来源 / 目标证据分屏', exact: true }).click()
  const evidence = page.getByRole('dialog', { name: '来源 / 目标证据分屏', exact: true })
  await expect(evidence.locator('.ps-evidence-correspondence button')).toHaveCount(0)
  await evidence.getByLabel('对应新增行位置', { exact: true }).selectOption('start')
  await evidence.getByRole('button', { name: '来源残基 A:1', exact: true }).click()
  await evidence.getByRole('button', { name: '所选来源设为 Source gap', exact: true }).click()
  await evidence.getByLabel('对应新增行位置', { exact: true }).selectOption('end')
  await evidence.getByRole('button', { name: '目标残基 A:1', exact: true }).click()
  await evidence.getByRole('button', { name: '所选目标设为 Target gap', exact: true }).click()
  await evidence.getByRole('button', { name: '来源残基 A:2', exact: true }).click()
  await evidence.getByRole('button', { name: '目标残基 A:2', exact: true }).click()
  await evidence.getByRole('button', { name: '明确匹配这两个残基', exact: true }).click()
  await evidence.locator('[data-merge-track="sequence"]').getByRole('button', { name: '采用所选区域', exact: true }).click()
  await evidence.getByLabel('分屏 sequence Mask 处理', { exact: true }).selectOption('preserve')
  await evidence.getByRole('button', { name: '来源残基 A:3', exact: true }).click()
  await evidence.getByRole('button', { name: '所选来源设为 Source gap', exact: true }).click()
  await evidence.getByRole('button', { name: '目标残基 A:3', exact: true }).click()
  await evidence.getByRole('button', { name: '所选目标设为 Target gap', exact: true }).click()
  await expect(evidence.locator('.ps-evidence-correspondence')).toContainText('首端 source / target gap 1 / 1 · 尾端 source / target gap 1 / 1')
  const result = await resultingPreview(page, () => evidence.getByRole('button', { name: '预览全部合并意图', exact: true }).click())
  expect(result.normalized_document.source_merges![0].correspondence.map(row => row.disposition)).toEqual(['source_gap', 'target_gap', 'match', 'source_gap', 'target_gap'])
  expect(result.normalized_document.source_merges![0].track_adoptions).toEqual([{ track: 'sequence', source_residue_ids: ['A:2'], mask_policy: 'preserve' }])
  expect(result.tracks.sequence.values.map(item => item.value)).toEqual(['A', 'W', 'T'])
  await evidence.getByRole('button', { name: '关闭合并分屏', exact: true }).click()
  await applyToolPreview(page)
})

test('undoing document edits retains unsaved source graph protection', async ({ page }) => {
  const snapshot = await openedPrompt(page)
  await (await matrixCell(page, snapshot.residues[0].residue_handle, 'sequence')).click()
  await page.getByLabel('指定氨基酸', { exact: true }).fill('W')
  await resultingPreview(page, () => page.getByRole('button', { name: 'Specify', exact: true }).click())
  await page.getByRole('button', { name: '合并来源', exact: true }).click()
  await page.getByRole('button', { name: '添加合并来源', exact: true }).click()
  const source = page.getByRole('dialog', { name: '添加手动合并来源', exact: true })
  await source.getByLabel('来源 Chain 1 length', { exact: true }).fill('2')
  await source.getByRole('button', { name: '进入 Prompt 预览', exact: true }).click()
  await expect(source).not.toBeVisible()
  await expect(page.getByRole('combobox', { name: '合并来源', exact: true }).locator('option')).toHaveCount(1)
  await page.getByRole('button', { name: '返回矩阵', exact: true }).click()
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(page.locator('.ps-session-state')).toContainText('有未保存修改')
  await page.getByRole('button', { name: '返回 Workflow', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '离开 Prompt 编辑', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '放弃修改', exact: true }).click()
})

test('ordinary layout after a merge preserves correspondence and deletes inserted identities explicitly', async ({ page }) => {
  const { draft, url } = await personalDraft(page)
  const author = draft.workflow.nodes.find(item => item.node_type_id === 'prompt_authoring.author')!
  const sourceNode = (node_id: string, sequence: string) => ({ node_id, node_type_id: 'prompt_authoring.author', binding_id: 'prompt_authoring.author.direct', node_parameters: { document: { chains: [{ chain_id: 'A', length: sequence.length }], track_edits: [...sequence].map((value, index) => ({ track: 'sequence', residue_id: `A:${index + 1}`, action: 'replace', value })) } }, binding_parameters: {} })
  author.node_parameters.document = { source_merges: [{ source_index: 0, correspondence: [{ disposition: 'match', source_residue_id: 'A:1', target_residue_id: 'A:1' }, { disposition: 'match', source_residue_id: 'A:2', target_residue_id: 'A:2' }, { disposition: 'insert', source_residue_id: 'A:3', target_residue_id: 'A:new' }], track_adoptions: [{ track: 'sequence', source_residue_ids: ['A:1', 'A:2', 'A:3'], mask_policy: 'preserve' }], adopt_annotations: [], remove_annotations: [] }] }
  draft.workflow.nodes.push(sourceNode('layout-base', 'AC'), sourceNode('layout-source', 'GWT'))
  draft.workflow.edges = draft.workflow.edges.filter(item => item.target_node_id !== author.node_id)
  draft.workflow.edges.push({ source_node_id: 'layout-base', source_port: 'protein_prompt', target_node_id: author.node_id, target_port: 'prompt_source' }, { source_node_id: 'layout-source', source_port: 'protein_prompt', target_node_id: author.node_id, target_port: 'merge_sources' })
  expect((await page.request.put(url, { data: { workflow: draft.workflow } })).status()).toBe(200)
  await reopenStoredDraft(page, url, author.node_id)
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === author.node_id)
  await page.getByTestId(`rf__node-${author.node_id}`).getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
  const snapshot = await (await opening).json() as PromptSnapshot
  const merged = snapshot.residues.find(item => item.residue_id === 'A:new')!
  await (await matrixCell(page, merged.residue_handle, 'sequence')).click()
  await page.getByRole('button', { name: '布局', exact: true }).click()
  await page.getByLabel('插入序列', { exact: true }).fill('C')
  const inserted = await resultingPreview(page, () => page.getByRole('button', { name: 'Insert after focus', exact: true }).click())
  expect(inserted.tracks.sequence.values.map(item => item.value)).toEqual(['G', 'W', 'T', 'C'])
  expect(inserted.normalized_document.target_residues!.some(item => item.residue_id === 'A:new')).toBe(false)
  expect(inserted.normalized_document.source_merges![0].correspondence.at(-1)!.disposition).toBe('target_gap')
  await applyToolPreview(page)
  const original = inserted.residues.find(item => item.residue_id === 'A:1')!
  await (await matrixCell(page, original.residue_handle, 'sequence')).click()
  await page.getByRole('button', { name: '插入 / 删除', exact: true }).click()
  const deletedOriginal = await resultingPreview(page, () => page.getByRole('button', { name: 'Delete selected', exact: true }).click())
  expect(deletedOriginal.normalized_document.source_merges![0].correspondence[0]).toEqual({ disposition: 'source_gap', source_residue_id: 'A:1' })
  expect(deletedOriginal.normalized_document.source_merges![0].track_adoptions[0].source_residue_ids).toEqual(['A:2', 'A:3'])
  await applyToolPreview(page)
  await (await matrixCell(page, merged.residue_handle, 'sequence')).click()
  await page.getByRole('button', { name: '插入 / 删除', exact: true }).click()
  const deletedMerged = await resultingPreview(page, () => page.getByRole('button', { name: 'Delete selected', exact: true }).click())
  expect(deletedMerged.normalized_document.source_merges![0].correspondence[2]).toEqual({ disposition: 'source_gap', source_residue_id: 'A:3' })
  expect(deletedMerged.normalized_document.source_merges![0].track_adoptions[0].source_residue_ids).toEqual(['A:2'])
  expect(deletedMerged.tracks.sequence.values.filter(item => item.state !== 'pending-delete').map(item => item.value)).toEqual(['W', 'C'])
  await applyToolPreview(page)
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect((await matrixCell(page, merged.residue_handle, 'sequence')).locator('strong')).toHaveText('T')
  await expect(page.locator('.ps-session-state')).toContainText('有未保存修改')
})
