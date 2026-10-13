import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import type { PromptAuthoringDocument, PromptSnapshot, Workflow } from '../src/protocol/client'

type WorkflowEdge = Workflow['edges'][number]
const edge = (source: string, target: string, sourcePort = 'candidates', targetPort = 'candidates'): WorkflowEdge => ({ source_node_id: source, source_port: sourcePort, target_node_id: target, target_port: targetPort })

async function workspace(request: APIRequestContext, prompt = false, protectedMerge = false) {
  const created = await request.post('/api/v2/projects', { data: { name: `Port regression ${crypto.randomUUID().slice(0, 8)}` } })
  expect(created.status()).toBe(201)
  const project = await created.json() as { id: string; name: string }
  const base = `/api/v2/projects/${project.id}`
  const nodes: Workflow['nodes'] = prompt
    ? ['a', 'b', 'c', 'target'].map(node_id => ({ node_id, node_type_id: 'prompt_authoring.author', binding_id: 'prompt_authoring.author.direct', binding_parameters: {}, node_parameters: { document: { chains: [{ chain_id: 'A', length: 2 }], track_edits: [{ track: 'sequence', residue_id: 'A:1', action: 'replace', value: node_id === 'b' ? 'G' : 'A' }, { track: 'sequence', residue_id: 'A:2', action: 'replace', value: 'C' }] } } }))
    : ['a', 'b', 'c', 'target'].map(node_id => ({ node_id, node_type_id: 'collection_ops.take_candidates', binding_id: 'collection_ops.take_candidates.direct', binding_parameters: {}, node_parameters: { k: 1 } }))
  if (protectedMerge) nodes[3].node_parameters.document = { chains: [{ chain_id: 'A', length: 2 }], track_edits: [{ track: 'sequence', residue_id: 'A:2', action: 'replace', value: 'T' }], source_merges: [{ source_index: 1, correspondence: [{ disposition: 'match', source_residue_id: 'A:1', target_residue_id: 'A:1' }, { disposition: 'match', source_residue_id: 'A:2', target_residue_id: 'A:2' }], track_adoptions: [{ track: 'sequence', source_residue_ids: ['A:1'], mask_policy: 'adopt' }], adopt_annotations: [], remove_annotations: [] }] }
  const edges = prompt ? [edge('a', 'target', 'protein_prompt', 'merge_sources'), edge('b', 'target', 'protein_prompt', 'merge_sources')] : [edge('a', 'b'), edge('c', 'target')]
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: project.id, nodes, edges, observation_selectors: [], selection_objectives: [] }
  const saved = await request.put(`${base}/workspace`, { data: { workflow, ui_state: { canvas: { positions: { a: { x: 30, y: 30 }, b: { x: 470, y: 30 }, c: { x: 30, y: 540 }, target: { x: 940, y: 300 } }, collapsed: [] } } } })
  expect(saved.status()).toBe(200)
  return { base, project, workflow }
}
async function open(page: Page, name: string) {
  await page.goto('/')
  await page.getByRole('button', { name: '项目', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '项目与版本' })
  await dialog.getByRole('button').filter({ has: page.getByText(name, { exact: true }) }).click()
  await dialog.getByRole('button', { name: '打开项目', exact: true }).click()
  await expect(page.locator('.project-identity strong')).toHaveText(name)
  await page.getByRole('button', { name: '适合视图', exact: true }).click()
}
const node = (page: Page, id: string) => page.getByTestId(`rf__node-${id}`)
const wire = (page: Page, source: string, target: string) => page.getByRole('group', { name: `Edge from ${source} to ${target}`, exact: true })
const handle = (page: Page, id: string, port: string) => node(page, id).locator(`[data-handleid="${port}"]`)
async function drag(page: Page, from: Locator, to: Locator | { x: number; y: number }) {
  await from.hover()
  const box = (await from.boundingBox())!
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 25, box.y + box.height / 2, { steps: 5 })
  await expect(page.locator('.react-flow__connection')).toHaveCount(1)
  if ('hover' in to) await to.hover({ force: true })
  else await page.mouse.move(to.x, to.y, { steps: 5 })
  await page.mouse.up()
  await expect(page.locator('.react-flow__connection')).toHaveCount(0)
}
async function persisted(page: Page, base: string): Promise<Workflow> {
  return (await (await page.request.get(`${base}/workspace`)).json()).draft.workflow
}
async function selectWire(page: Page, source: string, target: string) {
  const selected = wire(page, source, target)
  await selected.focus()
  await selected.press('Enter')
  await expect(selected).toHaveClass(/selected/)
  return selected
}

test('multi-port handle centers stay aligned across zoom and folding', async ({ page, request }, testInfo) => {
  const { project } = await workspace(request, true)
  await open(page, project.name)
  const assertPortCenters = async () => {
    for (const port of ['sequence_source', 'structure_source', 'prompt_source', 'merge_sources']) {
      const row = node(page, 'target').locator(`.workflow-port-row[data-port-name="${port}"][data-direction="input"]`)
      await expect.poll(async () => {
        const dot = (await handle(page, 'target', `in-${port}`).boundingBox())!
        const text = (await row.boundingBox())!
        return Math.abs(dot.y + dot.height / 2 - text.y - text.height / 2)
      }).toBeLessThan(2)
    }
  }
  await assertPortCenters()
  const initialScreenshot = testInfo.outputPath('ports-fit-view.png')
  await page.screenshot({ path: initialScreenshot })
  await testInfo.attach('ports-fit-view', { path: initialScreenshot, contentType: 'image/png' })
  await page.locator('.react-flow__controls-zoomin').click()
  await assertPortCenters()
  await page.locator('.react-flow__controls-zoomout').click()
  await page.locator('.react-flow__controls-zoomout').click()
  await assertPortCenters()
  await node(page, 'target').locator('.node-header button').click()
  await expect(node(page, 'target').locator('article')).toHaveClass(/is-collapsed/)
  await node(page, 'target').getByRole('button', { name: /展开节点/ }).click()
  await expect(node(page, 'target').locator('article')).not.toHaveClass(/is-collapsed/)
  await assertPortCenters()
  const mergeSummary = node(page, 'target').getByLabel('merge_sources 端口详情', { exact: true })
  await mergeSummary.focus()
  await page.keyboard.press('Enter')
  const mergeDetails = node(page, 'target').locator('details.workflow-port').filter({ has: page.getByLabel('merge_sources 端口详情', { exact: true }) })
  await expect(mergeDetails).toHaveAttribute('open', '')
  await expect(mergeDetails.locator('.port-details > code')).toHaveText('protein.prompt')
  await expect(mergeDetails.locator('ol li')).toHaveText(['a · protein_prompt', 'b · protein_prompt'])
  await assertPortCenters()
  await mergeSummary.press('Enter')
  await expect(mergeDetails).not.toHaveAttribute('open', '')
  const titleDetails = node(page, 'target').locator('.node-title-details')
  await titleDetails.locator('summary').focus()
  await page.keyboard.press('Enter')
  await expect(titleDetails.locator('strong')).toHaveText('Author ProteinPrompt')
  await expect(titleDetails.locator('code')).toHaveText('target')
  await expect(titleDetails.locator('code')).toBeVisible()
  const finalScreenshot = testInfo.outputPath('ports-after-zoom-and-unfold.png')
  await page.screenshot({ path: finalScreenshot })
  await testInfo.attach('ports-after-zoom-and-unfold', { path: finalScreenshot, contentType: 'image/png' })
})

test('dropping an existing endpoint on empty canvas cancels reconnect without deleting it', async ({ page, request }) => {
  const { project, base, workflow } = await workspace(request)
  await open(page, project.name)
  const selected = await selectWire(page, 'a', 'b')
  const canvas = (await page.locator('.react-flow__pane').boundingBox())!
  await drag(page, selected.locator('.react-flow__edgeupdater-target'), { x: canvas.x + canvas.width - 30, y: canvas.y + canvas.height - 30 })
  await expect(wire(page, 'a', 'b')).toBeVisible()
  expect((await persisted(page, base)).edges).toEqual(workflow.edges)
})

test('reconnecting to an occupied single input replaces its previous wire', async ({ page, request }) => {
  const { project, base } = await workspace(request)
  await open(page, project.name)
  const selected = await selectWire(page, 'a', 'b')
  await drag(page, selected.locator('.react-flow__edgeupdater-target'), handle(page, 'target', 'in-candidates'))
  await expect.poll(async () => (await persisted(page, base)).edges).toEqual([edge('a', 'target')])
  await expect(wire(page, 'c', 'target')).toHaveCount(0)
})

test('dropping an endpoint on an incompatible input preserves the old wire', async ({ page, request }) => {
  const { project, base, workflow } = await workspace(request, true)
  await open(page, project.name)
  const selected = await selectWire(page, 'a', 'target')
  await drag(page, selected.locator('.react-flow__edgeupdater-target'), handle(page, 'target', 'in-structure_source'))
  await expect(wire(page, 'a', 'target')).toBeVisible()
  expect((await persisted(page, base)).edges).toEqual(workflow.edges)
})

test('reconnecting an ordered many input to its original endpoint preserves order without a write', async ({ page, request }) => {
  const { project, base, workflow } = await workspace(request, true)
  await open(page, project.name)
  const writes: unknown[] = []
  page.on('request', request => { if (request.method() === 'PUT' && request.url().endsWith(`${base}/workspace`) && request.postDataJSON().workflow) writes.push(request.postDataJSON()) })
  const selected = await selectWire(page, 'a', 'target')
  await drag(page, selected.locator('.react-flow__edgeupdater-target'), handle(page, 'target', 'in-merge_sources'))
  await expect(wire(page, 'a', 'target')).toBeVisible()
  expect((await persisted(page, base)).edges).toEqual(workflow.edges)
  expect(writes).toEqual([])
  await expect(page.getByRole('button', { name: '撤销画布修改' })).toBeDisabled()
  await page.locator('.react-flow__pane').click()
  await page.keyboard.press('Control+z')
  expect((await persisted(page, base)).edges).toEqual(workflow.edges)
  expect(writes).toEqual([])
})

test('replacing a source of an ordered many input keeps its slot and undo restores it', async ({ page, request }) => {
  const { project, base, workflow } = await workspace(request, true)
  await open(page, project.name)
  const selected = await selectWire(page, 'a', 'target')
  await drag(page, selected.locator('.react-flow__edgeupdater-source'), handle(page, 'c', 'out-protein_prompt'))
  await expect.poll(async () => (await persisted(page, base)).edges).toEqual([edge('c', 'target', 'protein_prompt', 'merge_sources'), workflow.edges[1]])
  await page.getByRole('button', { name: '撤销画布修改' }).click()
  await expect.poll(async () => (await persisted(page, base)).edges).toEqual(workflow.edges)
})

test('folding a node preserves separate anchors and prevents connecting or reconnecting it', async ({ page, request }) => {
  const { project, base, workflow } = await workspace(request, true)
  await open(page, project.name)
  await node(page, 'target').locator('.node-header button').click()
  await expect(node(page, 'target').locator('article')).toHaveClass(/is-collapsed/)
  await expect(node(page, 'target').getByRole('button', { name: /展开节点/ })).toHaveAttribute('aria-expanded', 'false')
  const centers = await node(page, 'target').locator('.react-flow__handle.target').evaluateAll(elements => elements.map(element => { const rect = element.getBoundingClientRect(); return rect.y + rect.height / 2 }))
  expect(new Set(centers).size).toBe(4)
  await expect(wire(page, 'a', 'target')).toBeVisible()
  await expect(wire(page, 'a', 'target').locator('.react-flow__edgeupdater')).toHaveCount(0)
  await drag(page, handle(page, 'c', 'out-protein_prompt'), handle(page, 'target', 'in-merge_sources'))
  await expect(wire(page, 'c', 'target')).toHaveCount(0)
  expect((await persisted(page, base)).edges).toEqual(workflow.edges)
  await node(page, 'target').getByRole('button', { name: /展开节点/ }).click()
  await expect(wire(page, 'a', 'target').locator('.react-flow__edgeupdater-target')).toHaveCount(1)
  await drag(page, handle(page, 'c', 'out-protein_prompt'), handle(page, 'target', 'in-merge_sources'))
  await expect.poll(async () => (await persisted(page, base)).edges).toEqual([...workflow.edges, edge('c', 'target', 'protein_prompt', 'merge_sources')])
})

test('invalid raw numeric input blocks a connection without leaving an optimistic wire', async ({ page, request }) => {
  const { project, base, workflow } = await workspace(request)
  await open(page, project.name)
  await node(page, 'a').getByLabel('编辑参数').click()
  await node(page, 'a').getByLabel('保留数量').fill('not-a-number')
  await drag(page, handle(page, 'a', 'out-candidates'), handle(page, 'target', 'in-candidates'))
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(wire(page, 'a', 'target')).toHaveCount(0)
  await expect(wire(page, 'c', 'target')).toBeVisible()
  expect((await persisted(page, base)).edges).toEqual(workflow.edges)
  await node(page, 'a').getByLabel('保留数量').fill('2')
  await node(page, 'a').getByLabel('保留数量').blur()
  await expect.poll(async () => (await persisted(page, base)).nodes[0].node_parameters.k).toBe(2)
  expect((await persisted(page, base)).edges).toEqual(workflow.edges)
})

for (const action of ['delete wire', 'delete source', 'replace source'] as const) {
  test(`a saved Prompt merge blocks ${action} and points to Studio`, async ({ page, request }) => {
    const { project, base, workflow } = await workspace(request, true, true)
    await open(page, project.name)
    if (action === 'delete wire') {
      const selected = await selectWire(page, 'a', 'target')
      await selected.focus()
      await page.keyboard.press('Delete')
    } else if (action === 'delete source') {
      await node(page, 'a').locator('.node-icon').click()
      await page.keyboard.press('Delete')
    } else {
      const selected = await selectWire(page, 'a', 'target')
      await drag(page, selected.locator('.react-flow__edgeupdater-source'), handle(page, 'c', 'out-protein_prompt'))
    }
    const alert = page.getByRole('alert').filter({ hasText: /target/ })
    await expect(alert).toContainText(/Prompt Studio/)
    await expect(alert.getByRole('button', { name: /Prompt Studio/ })).toBeVisible()
    await expect(wire(page, 'a', 'target')).toBeVisible()
    expect(await persisted(page, base)).toEqual(workflow)
    if (action === 'delete wire') {
      const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === 'target')
      await alert.getByRole('button', { name: /Prompt Studio/ }).click()
      const response = await opening
      expect(response.status()).toBe(200)
      const snapshot = await response.json() as PromptSnapshot
      const residue = snapshot.residues.find(value => value.residue_id === 'A:1')!
      expect(snapshot.tracks.sequence.values.find(value => value.residue_handle === residue.residue_handle)?.value).toBe('G')
      await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).toBeVisible()
      await page.getByRole('button', { name: '合并来源', exact: true }).click()
      await page.getByRole('region', { name: '手动来源合并', exact: true }).getByRole('button', { name: '移除', exact: true }).click()
      await page.getByRole('dialog', { name: '合并来源', exact: true }).getByRole('button', { name: '应用操作', exact: true }).click()
      await page.getByRole('button', { name: '返回矩阵', exact: true }).click()
      await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).toHaveCount(0)
      await expect(page.getByText('Prompt 已保存', { exact: true })).toBeVisible()
      await expect(page.getByRole('alert').filter({ hasText: /target/ })).toHaveCount(0)
      const savedDocument = (await persisted(page, base)).nodes[3].node_parameters.document as PromptAuthoringDocument
      expect(savedDocument.source_merges ?? []).toEqual([])
      expect(savedDocument.track_edits).toEqual([{ track: 'sequence', residue_id: 'A:2', action: 'replace', value: 'T' }])
      const unprotected = await selectWire(page, 'a', 'target')
      await unprotected.focus()
      await page.keyboard.press('Delete')
      await expect.poll(async () => (await persisted(page, base)).edges).toEqual([workflow.edges[1]])
      expect((await persisted(page, base)).nodes[3].node_parameters.document).toEqual(savedDocument)
      await expect(page.getByRole('alert').filter({ hasText: /target/ })).toHaveCount(0)
    }
  })
}

test('a Prompt with saved merges permits appending a source and deleting the whole dependent Prompt', async ({ page, request }) => {
  const { project, base, workflow } = await workspace(request, true, true)
  await open(page, project.name)
  await drag(page, handle(page, 'c', 'out-protein_prompt'), handle(page, 'target', 'in-merge_sources'))
  await expect.poll(async () => (await persisted(page, base)).edges).toEqual([...workflow.edges, edge('c', 'target', 'protein_prompt', 'merge_sources')])
  expect((await persisted(page, base)).nodes[3].node_parameters).toEqual(workflow.nodes[3].node_parameters)
  await node(page, 'a').locator('.node-icon').click()
  await node(page, 'target').locator('.node-icon').click({ modifiers: ['Control'] })
  await expect(node(page, 'a')).toHaveClass(/selected/)
  await expect(node(page, 'target')).toHaveClass(/selected/)
  await page.keyboard.press('Delete')
  await expect.poll(async () => (await persisted(page, base)).nodes.map(item => item.node_id)).toEqual(['b', 'c'])
  expect((await persisted(page, base)).edges).toEqual([])
})

test('a failed connection save retains the accepted edit, blocks another edit, and retries before undo', async ({ page, request }) => {
  const { project, base, workflow } = await workspace(request)
  await open(page, project.name)
  let workflowWrites = 0
  await page.route(`**${base}/workspace`, async route => {
    if (route.request().method() !== 'PUT' || !route.request().postDataJSON().workflow) {
      await route.continue()
      return
    }
    workflowWrites += 1
    if (workflowWrites === 1) {
      await route.fulfill({ status: 503, json: { error: { code: 'connection_save_test_failure', message: 'Connection save temporarily unavailable' } } })
      return
    }
    await route.continue()
  })
  const acceptedEdges = [workflow.edges[0], edge('a', 'target')]
  await drag(page, handle(page, 'a', 'out-candidates'), handle(page, 'target', 'in-candidates'))
  await expect(page.getByRole('alert')).toContainText('Connection save temporarily unavailable')
  await expect(wire(page, 'a', 'target')).toBeVisible()
  await expect(wire(page, 'c', 'target')).toHaveCount(0)
  expect((await persisted(page, base)).edges).toEqual(workflow.edges)
  expect(workflowWrites).toBe(1)

  // This connection must be rejected before the editor accepts it: the failed
  // first edit remains on the canvas, while the server still has the old graph.
  await drag(page, handle(page, 'c', 'out-candidates'), handle(page, 'b', 'in-candidates'))
  await expect(wire(page, 'c', 'b')).toHaveCount(0)
  await expect(wire(page, 'a', 'b')).toBeVisible()
  await expect(wire(page, 'a', 'target')).toBeVisible()
  expect((await persisted(page, base)).edges).toEqual(workflow.edges)
  expect(workflowWrites).toBe(1)

  await page.getByRole('button', { name: '重试保存', exact: true }).click()
  await expect.poll(async () => (await persisted(page, base)).edges).toEqual(acceptedEdges)
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(workflowWrites).toBe(2)
  await page.getByRole('button', { name: '撤销画布修改', exact: true }).click()
  await expect.poll(async () => (await persisted(page, base)).edges).toEqual(workflow.edges)
  await expect(wire(page, 'a', 'target')).toHaveCount(0)
  await expect(wire(page, 'c', 'target')).toBeVisible()
})
