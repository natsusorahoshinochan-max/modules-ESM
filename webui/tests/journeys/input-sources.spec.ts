import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import type { CatalogSnapshot, PromptPreview, PromptSnapshot, RunProjection, Workflow, WorkflowDraft } from '../../src/protocol/client'
import { existingPromptSources, prepareCandidateInput, preparePromptSource, type FastaInputInspection, type ProjectInputPublication } from '../../src/input-sources'

async function sourceWorkspace(request: APIRequestContext) {
  const projectResponse = await request.post('/api/v2/projects', { data: { name: 'Source integration review' } })
  expect(projectResponse.status()).toBe(201)
  const project = await projectResponse.json() as { id: string }
  const base = `/api/v2/projects/${project.id}`
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: project.id, nodes: [], edges: [], observation_selectors: [], selection_objectives: [] }
  const saved = await request.put(`${base}/workspace`, { data: { workflow } })
  expect(saved.status()).toBe(200)
  const draft = (await saved.json()).draft as WorkflowDraft
  const catalog = await (await request.get('/api/v2/catalog')).json() as CatalogSnapshot
  return { base, workflow, draft, catalog }
}

async function publish(request: APIRequestContext, base: string, filename: string, content: string) {
  const response = await request.post(`${base}/inputs`, { data: { filename, content_base64: Buffer.from(content).toString('base64') } })
  expect(response.status()).toBe(201)
  return await response.json() as ProjectInputPublication
}

async function openPersonalSourceDialog(page: Page) {
  // Public API setup supplies a personal project; editing the tutorial is not
  // a project-creation mechanism and is tested separately.
  const created = await page.request.post('/api/v2/projects', { data: { name: `Source dialog ${crypto.randomUUID()}` } })
  expect(created.status()).toBe(201)
  const project = await created.json() as { id: string; name: string }
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: project.id, nodes: [], edges: [], observation_selectors: [], selection_objectives: [] }
  const prepared = await page.request.put(`/api/v2/projects/${project.id}/workspace`, { data: { workflow } })
  expect(prepared.status()).toBe(200)
  const draft = (await prepared.json()).draft as WorkflowDraft
  await page.goto('/')
  await page.getByRole('button', { name: '项目', exact: true }).click()
  const projects = page.getByRole('dialog', { name: '项目与版本' })
  await projects.getByRole('button').filter({ has: page.getByText(project.name, { exact: true }) }).click()
  await projects.getByRole('button', { name: '打开项目', exact: true }).click()
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '添加来源', exact: true })
  await expect(dialog).toBeVisible()
  return { dialog, draft, url: `/api/v2/projects/${project.id}/workflow/draft` }
}

test('multi-record single Prompt input is rejected while cancelling preserves the Workflow and uploaded input', async ({ page }) => {
  const { dialog, draft, url } = await openPersonalSourceDialog(page)
  await dialog.getByRole('button', { name: /FASTA → Prompt/ }).click()
  await dialog.getByRole('button', { name: '粘贴文本', exact: true }).click()
  await dialog.getByLabel('来源文本').fill('>one\nACD\n>two\nEFG\n')
  const publishing = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/inputs'))
  const inspecting = page.waitForResponse(response => response.url().includes(`/projects/${draft.project_id}/inputs/`) && response.url().endsWith(':inspect') && response.request().postDataJSON().format === 'fasta')
  await dialog.getByRole('button', { name: '上传并检查输入', exact: true }).click()
  const publication = await (await publishing).json() as ProjectInputPublication
  expect((await inspecting).status()).toBe(200)
  await expect(dialog.getByRole('heading', { name: '2 条记录 · 6 个残基' })).toBeVisible()
  await expect(dialog.getByLabel('来源 Chain 1 length')).toHaveValue('6')
  await expect(dialog.getByRole('button', { name: '进入 Prompt 预览', exact: true })).toBeDisabled()
  await expect(dialog.getByText('单条 Prompt 来源只接受一条记录。多条记录请改用批量导入；Header 不会自动成为链标识。')).toBeVisible()
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  expect(await (await page.request.get(url)).json()).toEqual(draft)
  const inputs = await (await page.request.get(url.replace('/workflow/draft', '/inputs'))).json() as { inputs: ProjectInputPublication[] }
  expect(inputs.inputs.some(input => input.project_input_ref === publication.project_input_ref)).toBe(true)
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  await dialog.getByRole('button', { name: /FASTA → Prompt/ }).click()
  await dialog.getByRole('button', { name: '已有 Input', exact: true }).click()
  await expect(dialog.getByLabel('已有 Input').locator('option').filter({ hasText: publication.project_input_ref })).toHaveCount(1)
})

test('source dialog reports the invalid record and blocks the entire batch import', async ({ page }) => {
  const { dialog, draft, url } = await openPersonalSourceDialog(page)
  await dialog.getByRole('button', { name: /批量 FASTA Candidates/ }).click()
  await dialog.getByRole('button', { name: '粘贴文本', exact: true }).click()
  await dialog.getByLabel('来源文本').fill('>valid\nACD\n>bad\nA?D\n')
  const inspecting = page.waitForResponse(response => response.url().includes(`/projects/${draft.project_id}/inputs/`) && response.url().endsWith(':inspect') && response.request().postDataJSON().format === 'fasta')
  await dialog.getByRole('button', { name: '上传并检查输入', exact: true }).click()
  expect((await inspecting).status()).toBe(422)
  await expect(dialog.getByRole('alert')).toContainText(/record 2.*line 3/i)
  await expect(dialog.getByRole('button', { name: '确认导入独立 Candidates', exact: true })).toBeDisabled()
  expect(await (await page.request.get(url)).json()).toEqual(draft)
})

test('a single-record FASTA Prompt stages explicit multi-chain layout and saves the complete confirmed graph', async ({ request }) => {
  const { base, workflow, draft, catalog } = await sourceWorkspace(request)
  const input = await publish(request, base, 'sequence.fasta', '>single-sequence\nACDEFGH\n')
  const inspected = await request.post(`${base}/inputs/${input.project_input_ref}:inspect`, { data: { format: 'fasta' } })
  expect(inspected.status()).toBe(200)
  const inspection = await inspected.json() as FastaInputInspection
  expect(inspection.records.map(record => [record.record_index, record.header, record.length])).toEqual([[1, 'single-sequence', 7]])
  expect(inspection.total_length).toBe(7)
  const plan = preparePromptSource(workflow, catalog, { kind: 'fasta', projectInputRef: input.project_input_ref, chains: [{ chain_id: 'A', length: 3 }, { chain_id: 'B', length: 4 }] })
  expect(workflow.nodes).toEqual([])
  const opened = await request.post(`${base}/prompt-authoring:open`, { data: { node_id: plan.nodeId, workflow: plan.workflow } })
  expect(opened.status()).toBe(200)
  const snapshot = await opened.json() as PromptSnapshot
  expect(snapshot.residues.map(residue => residue.chain_id)).toEqual(['A', 'A', 'A', 'B', 'B', 'B', 'B'])
  expect(snapshot.tracks.sequence.values.map(value => value.value).join('')).toBe('ACDEFGH')
  const previewed = await request.post(`${base}/prompt-authoring:preview`, { data: { node_id: plan.nodeId, workflow: plan.workflow, document: plan.document } })
  expect(previewed.status()).toBe(200)
  const preview = await previewed.json() as PromptPreview
  expect(preview.diagnostics).toEqual([])
  expect(await (await request.get(`${base}/workflow/draft`)).json()).toEqual(draft)
  const inputs = await (await request.get(`${base}/inputs`)).json() as { inputs: ProjectInputPublication[] }
  expect(inputs.inputs).toContainEqual(input)
  const confirmedWorkflow = { ...plan.workflow, nodes: plan.workflow.nodes.map(node => node.node_id === plan.nodeId ? { ...node, node_parameters: { ...node.node_parameters, document: preview.normalized_document } } : node) }
  const applied = await request.put(`${base}/workspace`, { data: { workflow: confirmedWorkflow, expected_draft_revision: draft.draft_revision } })
  expect(applied.status()).toBe(200)
  const saved = (await applied.json()).draft as WorkflowDraft
  expect(saved.workflow.nodes.map(node => node.node_type_id)).toEqual(['protein_io.import_sequence', 'prompt_authoring.author'])
  expect(saved.workflow.edges).toEqual(plan.workflow.edges)
  expect(saved.workflow.nodes.find(node => node.node_id === plan.nodeId)!.node_parameters.document).toEqual(plan.document)
})

test('PDB chain choice is represented by ordinary selection and axis nodes', async ({ request }) => {
  const { base, workflow, catalog } = await sourceWorkspace(request)
  const input = await publish(request, base, '3GB1.pdb', readFileSync('../examples/v2/structures/3GB1.pdb', 'utf8'))
  const inspected = await request.post(`${base}/inputs/${input.project_input_ref}:inspect`, { data: { format: 'pdb' } })
  expect(inspected.status()).toBe(200)
  expect((await inspected.json()).chain_ids).toContain('A')
  const plan = preparePromptSource(workflow, catalog, { kind: 'structure', projectInputRef: input.project_input_ref, chainIds: ['A'] })
  expect(plan.workflow.nodes.map(node => node.node_type_id)).toEqual(['protein_io.import_structure', 'structure_transform.select_chains', 'structure_transform.resolve_residue_axis', 'prompt_authoring.author'])
  expect(plan.workflow.nodes[1].node_parameters).toEqual({ chain_ids: ['A'] })
  const response = await request.post(`${base}/prompt-authoring:open`, { data: { node_id: plan.nodeId, workflow: plan.workflow } })
  expect(response.status()).toBe(200)
  const snapshot = await response.json() as PromptSnapshot
  expect(snapshot.residues.length).toBeGreaterThan(0)
  expect(new Set(snapshot.residues.map(residue => residue.chain_id))).toEqual(new Set(['A']))
  expect(snapshot.tracks.coordinates.values.some(value => value.value !== null)).toBe(true)
  expect((await (await request.get(`${base}/workflow/draft`)).json()).workflow.nodes).toEqual([])
})

test('adding a merge source exposes manual input without adopting values or allowing cycles', async ({ request }) => {
  const { base, workflow, catalog } = await sourceWorkspace(request)
  const target = preparePromptSource(workflow, catalog, { kind: 'blank', chains: [{ chain_id: 'A', length: 3 }] })
  expect((await request.put(`${base}/workspace`, { data: { workflow: target.workflow } })).status()).toBe(200)
  const input = await publish(request, base, 'merge.fasta', '>source\nACD\n')
  const plan = preparePromptSource(target.workflow, catalog, { kind: 'fasta', projectInputRef: input.project_input_ref, chains: [{ chain_id: 'A', length: 3 }] }, target.nodeId)
  expect(plan.nodeId).toBe(target.nodeId)
  expect(plan.document.source_merges).toBeUndefined()
  const opened = await request.post(`${base}/prompt-authoring:open`, { data: { node_id: plan.nodeId, workflow: plan.workflow } })
  expect(opened.status()).toBe(200)
  const snapshot = await opened.json() as PromptSnapshot
  expect(snapshot.tracks.sequence.values.map(value => value.value)).toEqual([null, null, null])
  expect(snapshot.source.merge_sources![0].tracks.sequence.values.map(value => value.value).join('')).toBe('ACD')
  const downstream = preparePromptSource(plan.workflow, catalog, { kind: 'prompt', nodeId: target.nodeId, outputPort: 'protein_prompt' })
  expect(existingPromptSources(downstream.workflow, catalog, target.nodeId)).toEqual([])
  expect(target.workflow.edges).toEqual([])
})

test('batch FASTA retains duplicate records as independent Candidates through a real Run', async ({ request }) => {
  const { base, workflow, catalog } = await sourceWorkspace(request)
  const input = await publish(request, base, 'batch.fasta', '>same\nACD\n>same\nACD\n>\nEFG\n')
  const plan = prepareCandidateInput(workflow, catalog, input.project_input_ref)
  expect(plan.workflow.nodes[0].node_type_id).toBe('protein_io.import_sequences')
  expect(plan.workflow.edges).toEqual([])
  const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: plan.workflow } })
  expect(committed.status()).toBe(200)
  const { workflow_commit_id } = await committed.json()
  const started = await request.post(`${base}/runs`, { data: { workflow_commit_id, client_request_id: crypto.randomUUID(), scope: { mode: 'full', node_ids: [] } } })
  expect(started.status()).toBe(202)
  const { run_id } = await started.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${run_id}`)).json() as RunProjection).status).toBe('succeeded')
  const collection = await request.post(`${base}/runs/${run_id}/results:collection`, { data: { node_id: plan.nodeId, output_port: 'sequence_candidates', value_index: 0, offset: 0, limit: 100 } })
  expect(collection.status()).toBe(200)
  const candidates = await collection.json()
  expect(candidates.items.map((item: { sequence: string }) => item.sequence)).toEqual(['ACD', 'ACD', 'EFG'])
  expect(new Set(candidates.items.map((item: { reference: { candidate_id: string } }) => item.reference.candidate_id)).size).toBe(3)
})

test('opening and cancelling tutorial source and merge dialogs does not create a personal copy', async ({ page }) => {
  const copies: string[] = []
  const writes: string[] = []
  page.on('request', outgoing => {
    if (outgoing.method() === 'POST' && outgoing.url().endsWith(':copy')) copies.push(outgoing.url())
    if (outgoing.method() === 'PUT' && outgoing.url().endsWith('/workspace')) writes.push(outgoing.url())
  })
  await page.goto('/')
  await expect(page.getByText('只读示例')).toBeVisible()
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  const source = page.getByRole('dialog', { name: '添加来源', exact: true })
  await expect(source).toBeVisible()
  await source.getByRole('button', { name: '取消', exact: true }).click()
  await expect(source).toHaveCount(0)
  expect(copies).toEqual([])
  expect(writes).toEqual([])
  await page.getByRole('button', { name: '编辑 ProteinPrompt', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '合并来源', exact: true }).click()
  await page.getByRole('button', { name: '添加合并来源', exact: true }).click()
  const merge = page.getByRole('dialog', { name: '添加手动合并来源', exact: true })
  await expect(merge).toBeVisible()
  await merge.getByRole('button', { name: '取消', exact: true }).click()
  await expect(merge).toHaveCount(0)
  await page.getByRole('button', { name: '返回矩阵', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).toBeVisible()
  expect(copies).toEqual([])
  expect(writes).toEqual([])
})

test('tutorial source inspection keeps the original and creates no personal project before manual save', async ({ page, request }) => {
  const copies: string[] = []
  page.on('request', outgoing => { if (outgoing.method() === 'POST' && outgoing.url().endsWith(':copy')) copies.push(outgoing.url()) })
  const projects = await (await request.get('/api/v2/projects')).json()
  const seed = projects.projects.find((item: { project_kind: string }) => item.project_kind === 'default_example')
  const original = await (await request.get(`/api/v2/projects/${seed.id}/workspace`)).json()
  await page.goto('/')
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  const source = page.getByRole('dialog', { name: '添加来源', exact: true })
  await source.getByRole('button', { name: /FASTA → Prompt/ }).click()
  await source.getByRole('button', { name: '粘贴文本', exact: true }).click()
  await source.getByLabel('来源文本').fill('>new source\nACD\n')
  await source.getByRole('button', { name: '上传并检查输入', exact: true }).click()
  await expect(source.getByRole('heading', { name: '1 条记录 · 3 个残基' })).toBeVisible()
  expect(copies).toEqual([])
  expect(await (await request.get(`/api/v2/projects/${seed.id}/workspace`)).json()).toEqual(original)
})

test('a tutorial blank Prompt preview can be cancelled without copying or publishing its staged graph', async ({ page, request }) => {
  const copies: string[] = []
  const writes: string[] = []
  page.on('request', outgoing => {
    if (outgoing.method() === 'POST' && outgoing.url().endsWith(':copy')) copies.push(outgoing.url())
    if (outgoing.method() === 'PUT' && outgoing.url().endsWith('/workspace')) writes.push(outgoing.url())
  })
  await page.goto('/')
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  const source = page.getByRole('dialog', { name: '添加来源', exact: true })
  await source.getByLabel('来源 Chain 1 length').fill('3')
  const openedResponse = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open'))
  await source.getByRole('button', { name: '进入 Prompt 预览', exact: true }).click()
  const opened = await openedResponse
  expect(opened.status()).toBe(200)
  const base = opened.url().replace('/prompt-authoring:open', '')
  const before = await (await request.get(`${base}/workspace`)).json()
  await expect(page.getByRole('heading', { name: 'ProteinPrompt 编辑', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '返回 Workflow', exact: true }).click()
  await expect(page.getByRole('button', { name: '添加来源', exact: true })).toBeVisible()
  expect(await (await request.get(`${base}/workspace`)).json()).toEqual(before)
  expect(copies).toEqual([])
  expect(writes).toEqual([])
})

test('switching source file modes never uploads an invisible previous file', async ({ page }) => {
  const { dialog } = await openPersonalSourceDialog(page)
  await dialog.getByRole('button', { name: /FASTA → Prompt/ }).click()
  await dialog.getByLabel('来源文件').setInputFiles({ name: 'sequence.fa', mimeType: 'text/plain', buffer: Buffer.from('>one\nACDE\n') })
  await expect(dialog.getByRole('button', { name: '上传并检查输入', exact: true })).toBeEnabled()
  await dialog.getByRole('button', { name: '粘贴文本', exact: true }).click()
  await dialog.getByRole('button', { name: '上传文件', exact: true }).click()
  await expect(dialog.getByLabel('来源文件')).toHaveValue('')
  await expect(dialog.getByRole('button', { name: '上传并检查输入', exact: true })).toBeDisabled()
  await dialog.getByLabel('来源文件').setInputFiles({ name: 'sequence.fa', mimeType: 'text/plain', buffer: Buffer.from('>one\nACDE\n') })
  await dialog.getByRole('button', { name: /PDB \/ mmCIF → Prompt/ }).click()
  await expect(dialog.getByLabel('来源文件')).toHaveValue('')
  await expect(dialog.getByRole('button', { name: '上传并检查输入', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: /FASTA → Prompt/ }).click()
  await dialog.getByLabel('来源文件').setInputFiles({ name: 'sequence.fa', mimeType: 'text/plain', buffer: Buffer.from('>one\nACDE\n') })
  await dialog.getByRole('button', { name: /FASTA → Prompt/ }).click()
  await expect(dialog.getByRole('button', { name: '上传并检查输入', exact: true })).toBeEnabled()
})
