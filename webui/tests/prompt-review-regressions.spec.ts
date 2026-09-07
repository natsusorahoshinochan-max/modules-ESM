import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import type { PromptAuthoringDocument, PromptPreview, PromptSnapshot, WorkflowDraft } from '../src/protocol/client'

async function personalDraft(page: Page) {
  await page.goto('/')
  const generation = page.getByTestId('rf__node-generate-paired')
  await generation.getByLabel('编辑参数').click()
  await generation.getByLabel('有效种子').fill('1704')
  const saving = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith('/workflow/draft'))
  await generation.getByLabel('有效种子').press('Tab')
  const saved = await saving
  return { url: saved.url(), draft: await saved.json() as WorkflowDraft }
}

for (const explicitTargets of [true, false]) {
  test(`random insertions restrict layout edits but allow values; explicit targets=${explicitTargets}`, async ({ page }) => {
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
    const opening = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:open'))
    await page.getByRole('button', { name: '打开 Prompt Studio' }).click()
    const snapshot = await (await opening).json() as PromptSnapshot
    const handle = snapshot.random_selections.find(r => r.kind === 'insert')!.realized_residue_handles[0]
    const cell = page.locator(`[data-cell="${handle}:sequence"]`)
    await cell.click()
    await expect(page.getByRole('button', { name: 'Delete selected', exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Insert after focus', exact: true })).toBeDisabled()
    await cell.press('+')
    await expect(page.getByRole('alert')).toContainText('随机生成残基保留 seed 规则')
    const other = snapshot.residues.find(r => r.residue_handle !== handle)!
    await page.locator(`[data-cell="${other.residue_handle}:sequence"]`).click({ modifiers: ['Control'] })
    await expect(page.getByRole('button', { name: 'Delete selected', exact: true })).toBeDisabled()
    await cell.click()
    const previewing = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:preview'))
    await cell.press('G')
    const response = await previewing
    expect(response.status()).toBe(200)
    const preview = await response.json() as PromptPreview
    expect(preview.diagnostics).toEqual([])
    expect(preview.tracks.sequence.values.find(v => v.residue_handle === handle)?.value).toBe('G')
    expect(preview.normalized_document.random_operations).toEqual(document.random_operations)
    await page.getByRole('button', { name: '应用操作', exact: true }).click()
    const ordinary = snapshot.residues.find(r => !snapshot.random_selections[0].realized_residue_handles.includes(r.residue_handle))!
    await page.locator(`[data-cell="${ordinary.residue_handle}:sequence"]`).click()
    await expect(page.getByRole('button', { name: 'Delete selected', exact: true })).toBeEnabled()
    const deleting = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:preview'))
    await page.getByRole('button', { name: 'Delete selected', exact: true }).click()
    const deleted = await (await deleting).json() as PromptPreview
    expect(deleted.diagnostics).toEqual([])
    expect(deleted.residues.find(r => r.residue_handle === ordinary.residue_handle)?.state).toBe('pending-delete')
    expect(deleted.normalized_document.random_operations).toEqual(document.random_operations)
    const displayed = await page.locator('[data-cell$=":sequence"]').evaluateAll(elements => elements.map(e => e.getAttribute('data-cell')!.replace(':sequence', '')))
    expect(displayed).toEqual(deleted.residues.map(r => r.residue_handle))
  })
}

test('Palette author can declare chains, preview and save', async ({ page }) => {
  await page.goto('/')
  const saving = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith('/workflow/draft'))
  await page.getByRole('button', { name: 'Author ProteinPrompt prompt_authoring', exact: true }).dragTo(page.locator('.react-flow__pane'), { targetPosition: { x: 520, y: 620 } })
  const draft = await (await saving).json() as WorkflowDraft
  const added = draft.workflow.nodes.find(n => n.node_type_id === 'prompt_authoring.author' && !n.node_id.startsWith('prompt-composition-'))!
  expect(added.node_parameters).toEqual({ document: {} })
  const opening = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:open'))
  await page.getByTestId(`rf__node-${added.node_id}`).getByRole('button', { name: '打开 Prompt Studio' }).click()
  expect((await opening).status()).toBe(200)
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
  await page.getByRole('button', { name: '应用操作', exact: true }).click()
  await expect(page.locator('.ps-residue-column')).toHaveCount(3)
  await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
  const applying = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:apply'))
  await page.getByRole('button', { name: '确认并写回 Workflow' }).click()
  const response = await applying
  expect(response.status()).toBe(200)
  const saved = (await response.json()).draft as WorkflowDraft
  expect(saved.workflow.nodes.find(n => n.node_id === added.node_id)!.node_parameters.document).toEqual({ chains: [{ chain_id: 'A', length: 3 }] })
  await expect(page.locator('.prompt-studio')).not.toBeVisible()
})

test('real stale-digest rejection preserves editing and permits a fresh preview', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/')
  await page.getByRole('button', { name: '打开 Prompt Studio' }).click()
  const previewing = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:preview'))
  await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
  const response = await previewing
  expect(response.status()).toBe(200)
  const preview = await response.json() as PromptPreview
  const base = response.url().replace('/prompt-authoring:preview', '')
  const draft = await (await page.request.get(`${base}/workflow/draft`)).json() as WorkflowDraft
  const imports = draft.workflow.nodes.filter(n => n.node_type_id === 'protein_io.import_structure')
  expect(imports.length).toBeGreaterThan(0)
  const original = readFileSync('../examples/v2/structures/3GB1.pdb', 'utf8')
  const payload = Buffer.from(`REMARK source revision\n${original}`).toString('base64')
  const publication = await page.request.post(`${base}/inputs`, { data: { filename: 'updated.pdb', content_base64: payload } })
  expect(publication.status()).toBe(201)
  const ref = (await publication.json()).project_input_ref
  for (const source of imports) source.node_parameters.project_input_ref = ref
  expect((await page.request.put(`${base}/workflow/draft`, { data: { workflow: draft.workflow } })).status()).toBe(200)
  const applying = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:apply'))
  await page.getByRole('button', { name: '确认并写回 Workflow' }).click()
  expect((await applying).status()).toBe(400)
  await expect(page.getByRole('alert')).toContainText('Preview digest does not match')
  await expect(page.locator('.ps-header .ps-primary')).toBeEnabled()
  const refreshing = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:preview'))
  await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
  const refreshed = await (await refreshing).json() as PromptPreview
  expect(refreshed.normalized_document).toEqual(preview.normalized_document)
  expect(refreshed.preview_digest).not.toBe(preview.preview_digest)
  const saving = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:apply'))
  await page.getByRole('button', { name: '确认并写回 Workflow' }).click()
  expect((await saving).status()).toBe(200)
  expect(errors).toEqual([])
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
  await page.getByRole('button', { name: '打开 Prompt Studio' }).click()
  await expect(page.getByText('无可比较的旧结果', { exact: true })).toBeVisible()
  await page.getByLabel('Chain 1 length', { exact: true }).fill('4')
  await page.getByRole('button', { name: '预览 Chains', exact: true }).click()
  await page.getByRole('button', { name: '应用操作', exact: true }).click()
  await expect(page.locator('.ps-residue-column')).toHaveCount(4)
  await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
  const applying = page.waitForResponse(r => r.url().endsWith('/prompt-authoring:apply'))
  await page.getByRole('button', { name: '确认并写回 Workflow' }).click()
  expect((await applying).status()).toBe(200)
})
