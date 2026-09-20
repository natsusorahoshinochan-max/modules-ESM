import { expect, test, type APIRequestContext, type Page, type TestInfo } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { strFromU8, unzipSync } from 'fflate'
import { PublicV2Client, type CandidateReference, type ProjectMetadata, type PromptPreview, type PromptSnapshot, type RunProjection, type WorkflowDraft } from '../src/protocol/client'
import { observationKey, referenceKey, type CandidateView, type ResultCollection, type ResultIndex, type ScoreView } from '../src/result-explorer'
import { PublishedResults, type RunReference } from '../src/published-results'

// One worker serializes Providers; tests own their Projects and do not skip each other.

type Journey = { project: ProjectMetadata; run: RunProjection; index: ResultIndex }
const baseURL = process.env.PROTEIN_WORKBENCH_REAL_UI_URL!

async function publishedResults(run: RunReference) {
  const results = new PublishedResults(new PublicV2Client(baseURL))
  results.openRun(run)
  return (await results.ensureCandidates({ all: true }))!
}

async function projects(request: APIRequestContext) {
  const response = await request.get('/api/v2/projects')
  expect(response.status()).toBe(200)
  return (await response.json()).projects as ProjectMetadata[]
}

async function openProject(page: Page, project: ProjectMetadata) {
  await page.goto('/')
  await page.getByRole('button', { name: '项目', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '项目与版本' })
  await dialog.getByRole('button').filter({ has: page.getByText(project.name, { exact: true }) }).click()
  await dialog.getByRole('button', { name: '打开项目', exact: true }).click()
  await expect(page.locator('.project-identity strong')).toHaveText(project.name)
}

async function startOnce(page: Page, request: APIRequestContext, project: ProjectMetadata, info: TestInfo): Promise<Journey> {
  const base = `/api/v2/projects/${project.id}`
  let starts = 0
  page.on('request', item => { if (item.method() === 'POST' && item.url().endsWith(`${base}/runs`)) starts += 1 })
  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  await page.getByRole('radio', { name: '完整流程', exact: true }).check()
  const preparing = page.waitForResponse(response => response.url().endsWith(`${base}/runs/preview`))
  await page.getByRole('button', { name: '准备并查看范围', exact: true }).click()
  const previewResponse = await preparing
  expect(previewResponse.status()).toBe(200)
  const preview = await previewResponse.json()
  expect(preview.blockers).toEqual([])
  await info.attach('confirmed-run-scope', { body: Buffer.from(JSON.stringify(preview, null, 2)), contentType: 'application/json' })
  const starting = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`${base}/runs`))
  await page.getByRole('button', { name: '开始运行已确认范围', exact: true }).click()
  const response = await starting
  expect(response.status()).toBe(202)
  const receipt = await response.json()
  info.annotations.push({ type: 'actual-run', description: `${project.id}/${receipt.run_id}` })
  await info.attach('actual-run-receipt', { body: Buffer.from(JSON.stringify(receipt, null, 2)), contentType: 'application/json' })
  console.info(`Actual UI Run: ${project.id}/${receipt.run_id}`)
  let run: RunProjection
  await expect.poll(async () => {
    const current = await request.get(`${base}/runs/${receipt.run_id}`)
    expect(current.status()).toBe(200)
    run = await current.json() as RunProjection
    return run.status
  }, { timeout: 25 * 60_000, intervals: [1000, 2500, 5000, 10_000] }).toMatch(/^(succeeded|failed|cancelled|interrupted)$/)
  await info.attach('actual-run-projection', { body: Buffer.from(JSON.stringify(run!, null, 2)), contentType: 'application/json' })
  expect(run!.status).toBe('succeeded')
  expect(starts).toBe(1)
  await expect(page.locator('.run-progress-bar')).toContainText('运行完成')
  const snapshot = await publishedResults(run!)
  await page.getByRole('button', { name: '打开 Results Workbench' }).click()
  await expect(page.locator('.results-explorer > aside').getByRole('heading', { name: '已发布结果', exact: true })).toBeVisible()
  return { project, run: snapshot.run!, index: snapshot.index }
}

function collection(index: ResultIndex, nodeId: string, outputPort?: string): ResultCollection {
  const result = index.collections.find(item => item.source.node_id === nodeId && (!outputPort || item.source.output_port === outputPort))
  expect(result, `published Candidate Collection for ${nodeId}/${outputPort ?? '*'}`).toBeDefined()
  return result!
}

async function showCollection(page: Page, value: ResultCollection) {
  await page.locator('.results-explorer > aside nav').getByRole('button').filter({ hasText: value.title }).click()
  await expect(page.getByRole('heading', { name: value.title, exact: true })).toBeVisible()
  await expect(page.locator('.result-table input[type=checkbox]')).toHaveCount(Math.min(50, value.items.length))
}

async function checkCandidate(page: Page, index: ResultIndex, candidate: CandidateView) {
  const stage = index.collections.find(item => item.source.node_id === candidate.source.node_id && item.source.output_port === candidate.source.output_port && item.source.value_index === candidate.source.value_index)!
  await showCollection(page, stage)
  await page.getByRole('checkbox', { name: `勾选 ${candidate.reference.candidate_id}`, exact: true }).check()
}

async function assertScore(page: Page, index: ResultIndex, candidate: CandidateView, score: ScoreView) {
  await page.locator('.result-table').getByRole('button', { name: candidate.reference.candidate_id, exact: true }).click()
  const definition = index.definitions.find(item => item.reference.contract_kind === 'metric' && item.reference.contract_id === score.metric.contract_id)!.descriptor
  const observation = page.locator('.result-detail .result-observation').filter({ has: page.getByText(score.method.contract_id, { exact: false }) }).filter({ hasText: String(definition.title ?? score.metric.contract_id) }).first()
  await expect(observation).toContainText((score.value as number).toPrecision(6))
  await observation.locator('summary').click()
  const facts = JSON.parse(await observation.locator('pre').innerText())
  expect.soft(facts.context).toEqual(score.context)
  expect.soft(facts.source).toEqual(score.source)
  expect.soft(facts.definition).toEqual(definition)
}

async function saveDisplayedFilter(page: Page, request: APIRequestContext, journey: Journey, stage: ResultCollection, score: ScoreView, threshold: number, info: TestInfo) {
  await showCollection(page, stage)
  const details = page.locator('details').filter({ has: page.getByText('临时条件筛选 · 支持 AND/OR 分组', { exact: true }) })
  await details.locator('summary').click()
  await details.getByRole('button', { name: '添加条件', exact: true }).click()
  await details.getByLabel('临时筛选分数', { exact: true }).selectOption(observationKey(score))
  await details.getByLabel('临时筛选比较符', { exact: true }).selectOption('>=')
  await details.getByLabel('阈值（分数原单位）', { exact: true }).fill(String(threshold))
  const expected = stage.items.filter(candidate => journey.index.scores.some(item => observationKey(item) === observationKey(score) && referenceKey(item.subject) === referenceKey(candidate.reference) && typeof item.value === 'number' && item.value >= threshold))
  await expect(page.locator('.result-table input[type=checkbox]')).toHaveCount(expected.length)
  await details.getByRole('button', { name: '条件保存为流程', exact: true }).click()
  const preview = page.getByRole('dialog', { name: '保存流程操作预览' })
  await expect(preview.getByLabel('范围外观察值', { exact: true })).toHaveValue('ignore')
  await expect(preview.getByLabel('阈值（Metric 原单位）', { exact: true })).toHaveValue(String(threshold))
  const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`/projects/${journey.project.id}/workflow/draft`))
  await preview.getByRole('button', { name: '确认保存到流程', exact: true }).click()
  const saved = await (await saving).json() as WorkflowDraft
  const added = saved.workflow.nodes.filter(node => node.node_id.startsWith('selection-'))
  expect(added.at(-1)?.node_type_id).toBe('selection.filter')
  expect(added.at(-1)?.node_parameters.expression).toEqual([{ selector_index: 0, operator: '>=', threshold }])
  const selectorId = (added.at(-1)!.node_parameters.selector_ids as string[])[0]
  const selector = saved.workflow.observation_selectors.find(item => item.selector_id === selectorId)!
  expect(selector).toMatchObject({ metric: score.metric, method: score.method, source_partition: score.source_partition, context_selector: score.context })
  const stored = await (await request.get(`/api/v2/projects/${journey.project.id}/workflow/draft`)).json() as WorkflowDraft
  expect(stored.workflow).toEqual(saved.workflow)
  const committed = await request.post(`/api/v2/projects/${journey.project.id}/workflow:commit`, { data: { workflow: saved.workflow } })
  expect(committed.status()).toBe(200)
  await info.attach('saved-display-filter', { body: Buffer.from(JSON.stringify(saved.workflow, null, 2)), contentType: 'application/json' })
  await details.getByRole('button', { name: '清除条件', exact: true }).click()
  return { [added.at(-1)!.node_id]: expected.map(item => item.reference) }
}

async function downloadSelection(page: Page, journey: Journey, expected: CandidateView[], info: TestInfo) {
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出所选 · ZIP', exact: true }).click()
  const download = await downloading
  const path = await download.path()
  expect(path).not.toBeNull()
  const bytes = await readFile(path!)
  const files = unzipSync(bytes)
  const manifest = JSON.parse(strFromU8(files['manifest.json']))
  expect.soft(manifest.run_id).toBe(journey.run.run_id)
  expect.soft(manifest.workflow_commit_id).toBe(journey.run.workflow_commit_id)
  expect(manifest.candidates.map((item: { reference: CandidateReference }) => referenceKey(item.reference)).sort()).toEqual(expected.map(item => referenceKey(item.reference)).sort())
  expect.soft(Object.keys(files).filter(name => name.endsWith('.pdb'))).toHaveLength(expected.filter(item => item.has_structure).length)
  expect(manifest.without_structure.map(referenceKey).sort()).toEqual(expected.filter(item => !item.has_structure).map(item => referenceKey(item.reference)).sort())
  for (const candidate of expected) {
    const saved = manifest.candidates.find((item: { reference: CandidateReference }) => referenceKey(item.reference) === referenceKey(candidate.reference))
    expect.soft(saved.parent_ids).toEqual(candidate.parent_ids)
    expect.soft(saved.output).toEqual(candidate.output)
    if (candidate.sequence) expect(strFromU8(files['candidates.fasta'])).toContain(`>${candidate.reference.candidate_id}\n${candidate.sequence}`)
    if (saved.structure_file) expect(strFromU8(files[saved.structure_file])).toMatch(/^ATOM\s/m)
  }
  expect(strFromU8(files['scores.csv'])).toContain('content_digest')
  await info.attach('actual-candidate-export.zip', { body: bytes, contentType: 'application/zip' })
}

async function saveTopOne(page: Page, request: APIRequestContext, journey: Journey, stage: ResultCollection, score: ScoreView) {
  await showCollection(page, stage)
  await page.getByRole('combobox', { name: '临时排序', exact: true }).selectOption(observationKey(score))
  const choices = page.waitForResponse(response => response.url().endsWith('/workflow:observation-options'))
  await page.getByRole('button', { name: '配置排序并取前 N 个', exact: true }).click()
  expect((await choices).status()).toBe(200)
  const preview = page.getByRole('dialog', { name: '保存流程操作预览' })
  await expect(preview.getByLabel('范围外观察值', { exact: true })).toHaveValue('ignore')
  const transformId = 'structure.plddt.mean_residue.esmfold2_fast_biohub_2026_05.percent_to_unit'
  await preview.getByLabel('Utility Transform（输出 0–1）', { exact: true }).selectOption(transformId)
  await preview.getByLabel('候选数量 N', { exact: true }).fill('1')
  const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`/projects/${journey.project.id}/workflow/draft`))
  await preview.getByRole('button', { name: '确认保存到流程', exact: true }).click()
  const saved = await (await saving).json() as WorkflowDraft
  const added = saved.workflow.nodes.findLast(node => node.node_id.startsWith('selection-') && node.node_type_id === 'selection.top_k')!
  expect(added.node_parameters.k).toBe(1)
  const objective = saved.workflow.selection_objectives.find(item => item.objective_id === added.node_parameters.objective_id)!
  expect(objective).toMatchObject({ candidate_input: { node_id: stage.source.node_id, output_port: stage.source.output_port }, metric: score.metric, method: score.method, source_partition: score.source_partition, context_selector: score.context, utility_transform: { contract_id: transformId } })
  expect(objective.score_collection_input).toEqual({ node_id: score.source.node_id, output_port: score.source.output_port })
  expect(saved.workflow.edges).toEqual(expect.arrayContaining([
    { source_node_id: stage.source.node_id, source_port: stage.source.output_port, target_node_id: added.node_id, target_port: 'candidates' },
    { source_node_id: score.source.node_id, source_port: score.source.output_port, target_node_id: added.node_id, target_port: 'scores' },
  ]))
  const committed = await request.post(`/api/v2/projects/${journey.project.id}/workflow:commit`, { data: { workflow: saved.workflow } })
  expect(committed.status()).toBe(200)
  await expect(preview).toHaveCount(0)
  return { [added.node_id]: stage.items.slice(0, 1).map(item => item.reference) }
}

async function executeSavedSelections(page: Page, request: APIRequestContext, journey: Journey, expected: Record<string, CandidateReference[]>) {
  const nodeIds = Object.keys(expected)
  await page.getByRole('button', { name: '返回 Workflow', exact: true }).click()
  await page.getByRole('button', { name: '适合视图', exact: true }).click()
  for (const [index, nodeId] of nodeIds.entries()) await page.getByTestId(`rf__node-${nodeId}`).click({ modifiers: index ? ['ControlOrMeta'] : [] })
  await page.getByRole('button', { name: '运行流程', exact: true }).click()
  await page.getByRole('radio', { name: '从所选节点继续', exact: true }).check()
  const previewing = page.waitForResponse(response => response.url().endsWith('/runs/preview'))
  await page.getByRole('button', { name: '准备并查看范围', exact: true }).click()
  const preview = await (await previewing).json()
  expect(preview.blockers).toEqual([])
  expect(preview.scope.execution_node_ids.sort()).toEqual([...nodeIds].sort())
  expect(preview.scope.source_run_id).toBe(journey.run.run_id)
  const base = `/api/v2/projects/${journey.project.id}`
  const starting = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`${base}/runs`))
  await page.getByRole('button', { name: '开始运行已确认范围', exact: true }).click()
  const response = await starting
  expect(response.status()).toBe(202)
  const receipt = await response.json()
  await expect.poll(async () => (await (await request.get(`${base}/runs/${receipt.run_id}`)).json()).status, { timeout: 60_000 }).toBe('succeeded')
  const snapshot = await publishedResults({ project_id: journey.project.id, run_id: receipt.run_id })
  expect(snapshot.run!.node_dispositions.filter(item => item.outcome === 'succeeded' && item.resolution === 'executed').map(item => item.node_id).sort()).toEqual([...nodeIds].sort())
  for (const nodeId of nodeIds) expect.soft(collection(snapshot.index, nodeId, 'candidates').items.map(item => item.reference)).toEqual(expected[nodeId])
}

async function screenshot(page: Page, info: TestInfo, name: string) {
  await info.attach(name, { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
}

test('real batch FASTA → solubility filter → fold → confidence ranking through the built WebUI', async ({ page, request }, info) => {
  const projectId = process.env.PROTEIN_WORKBENCH_REAL_FASTA_PROJECT_ID
  expect(projectId, 'prepare must provide a fresh project without an existing Run').toBeTruthy()
  const project = (await projects(request)).find(item => item.id === projectId)!
  expect(project).toBeDefined()
  expect(project.latest_run_id).toBeNull()
  await openProject(page, project)
  const journey = await startOnce(page, request, project, info)
  const imported = collection(journey.index, 'import-fasta', 'sequence_candidates')
  const filtered = collection(journey.index, 'prefilter-solubility', 'candidates')
  const folded = collection(journey.index, 'fold', 'structure_candidates')
  const ranked = collection(journey.index, 'rank-confidence', 'candidates')
  const postfiltered = collection(journey.index, 'postfilter-confidence', 'candidates')
  const final = collection(journey.index, 'passing-ranked-candidates', 'candidates')
  expect(imported.items).toHaveLength(2)
  expect(filtered.items).toHaveLength(1)
  expect(folded.items).toHaveLength(1)
  const solubility = journey.index.scores.find(item => item.source.node_id === 'score-solubility' && item.metric.contract_id === 'solubility.protein_sol_scaled' && item.method.contract_id === 'solubility.protein_sol.sequence_prediction_2017' && item.source_partition === 'protein_sol_scaled')!
  expect(solubility).toBeDefined()
  expect(solubility.context).toEqual({ kind: 'calibration', calibration_metric: 'population_scaled_solubility', calibration_value: 0.446, calibration_unit: 'dimensionless', population_id: 'niwa_non_membrane_2396' })
  const savedFilter = await saveDisplayedFilter(page, request, journey, imported, solubility, 0.446, info)
  await showCollection(page, folded)
  const confidence = journey.index.scores.find(item => item.source.node_id === 'materialize-confidence' && referenceKey(item.subject) === referenceKey(folded.items[0].reference) && item.metric.contract_id === 'structure.plddt.mean_residue' && item.method.contract_id === 'folding.fold.esmfold2_fast_biohub_2026_05' && item.source_partition === 'prediction_confidence')!
  expect(confidence).toBeDefined()
  expect.soft(confidence.context).toEqual({ kind: 'intrinsic' })
  expect(ranked.items.map(item => referenceKey(item.reference))).toEqual(folded.items.map(item => referenceKey(item.reference)))
  const expectedPostfilter = (confidence.value as number) >= 70 ? folded.items.map(item => referenceKey(item.reference)) : []
  expect(postfiltered.items.map(item => referenceKey(item.reference))).toEqual(expectedPostfilter)
  expect(final.items.map(item => referenceKey(item.reference))).toEqual(ranked.items.map(item => referenceKey(item.reference)).filter(key => expectedPostfilter.includes(key)))
  await assertScore(page, journey.index, folded.items[0], confidence)
  const savedTopOne = await saveTopOne(page, request, journey, ranked, confidence)
  await checkCandidate(page, journey.index, imported.items[0])
  await checkCandidate(page, journey.index, folded.items[0])
  await screenshot(page, info, 'fasta-provider-results')
  await downloadSelection(page, journey, [imported.items[0], folded.items[0]], info)
  await executeSavedSelections(page, request, journey, { ...savedFilter, ...savedTopOne })
})

async function preparePromptJourney(page: Page, request: APIRequestContext, info: TestInfo): Promise<ProjectMetadata> {
  const seed = (await projects(request)).find(project => project.project_kind === 'default_example')!
  const copied = await request.post(`/api/v2/projects/${seed.id}:copy`, { data: { name: `Real Prompt journey ${crypto.randomUUID().slice(0, 8)}` } })
  expect(copied.status()).toBe(201)
  const project = await copied.json() as ProjectMetadata
  const base = `/api/v2/projects/${project.id}`
  const draft = await (await request.get(`${base}/workflow/draft`)).json() as WorkflowDraft
  for (const node of draft.workflow.nodes) {
    if (node.node_id === 'generate-paired') node.node_parameters.num_samples = 1
    if (node.node_id === 'design-children') node.node_parameters.num_sequences = 1
    if (node.node_type_id === 'collection_ops.take_candidates') node.node_parameters.k = 1
  }
  expect((await request.put(`${base}/workflow/draft`, { data: { workflow: draft.workflow } })).status()).toBe(200)
  await openProject(page, project)
  const author = draft.workflow.nodes.find(node => node.node_type_id === 'prompt_authoring.author')!
  const opening = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:open') && response.request().postDataJSON().node_id === author.node_id)
  await page.getByTestId(`rf__node-${author.node_id}`).getByRole('button', { name: '打开 Prompt Studio', exact: true }).click()
  const prompt = await (await opening).json() as PromptSnapshot
  const masked = prompt.tracks.sequence.values.find(item => item.value === null && prompt.residues.some(residue => residue.residue_handle === item.residue_handle && residue.state !== 'pending-delete'))!
  expect(masked).toBeDefined()
  await page.locator(`[data-cell="${masked.residue_handle}:sequence"]`).click()
  await page.getByLabel('指定氨基酸', { exact: true }).fill('G')
  const editing = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:preview') && response.request().postDataJSON().node_id === author.node_id)
  await page.getByRole('button', { name: 'Specify', exact: true }).click()
  const edited = await (await editing).json() as PromptPreview
  expect(edited.diagnostics).toEqual([])
  expect(edited.tracks.sequence.values.find(item => item.residue_handle === masked.residue_handle)?.value).toBe('G')
  await page.getByRole('button', { name: '应用操作', exact: true }).click()
  await expect(page.getByRole('region', { name: 'ESM3 有效条件' })).toContainText('SDK 可以表示当前条件')
  await screenshot(page, info, 'own-prompt-effective-conditioning')
  await page.getByRole('button', { name: '保存 ProteinPrompt', exact: true }).click()
  const applying = page.waitForResponse(response => response.url().endsWith('/prompt-authoring:apply'))
  await page.getByRole('button', { name: '确认并写回 Workflow', exact: true }).click()
  expect((await applying).status()).toBe(200)
  return project
}

async function ownPromptJourney(page: Page, request: APIRequestContext, info: TestInfo): Promise<Journey> {
  return startOnce(page, request, await preparePromptJourney(page, request, info), info)
}

test('own Prompt → real ESM3 → refold preserves exact stage scores and saves a chosen filter', async ({ page, request }, info) => {
  const redesign = await ownPromptJourney(page, request, info)
  const generated = collection(redesign.index, 'generate-paired', 'structure_candidates')
  const refolded = collection(redesign.index, 'fold-stage-one', 'structure_candidates')
  expect(generated.items).toHaveLength(1)
  expect(refolded.items).toHaveLength(1)
  await checkCandidate(page, redesign.index, generated.items[0])
  await checkCandidate(page, redesign.index, refolded.items[0])
  await page.getByRole('button', { name: '并排比较 (2)', exact: true }).click()
  await expect(page.locator('.result-comparison .result-detail')).toHaveCount(2)
  await expect(page.locator('.result-comparison .result-structure canvas')).toHaveCount(2)
  await screenshot(page, info, 'esm3-refold-stage-comparison')
  await page.getByRole('button', { name: '关闭比较', exact: true }).click()
  const score = redesign.index.scores.find(item => item.source.node_id === 'confidence-stage-one' && referenceKey(item.subject) === referenceKey(refolded.items[0].reference) && item.metric.contract_id === 'structure.plddt.mean_residue' && item.method.contract_id === 'folding.fold.esmfold2_fast_biohub_2026_05' && item.source_partition === 'prediction_confidence')!
  expect(score).toBeDefined()
  expect.soft(score.context).toEqual({ kind: 'intrinsic' })
  await assertScore(page, redesign.index, refolded.items[0], score)
  const savedFilter = await saveDisplayedFilter(page, request, redesign, refolded, score, score.value as number, info)
  await executeSavedSelections(page, request, redesign, savedFilter)
})

test('real MPNN descendants expose parents, use exact alignment evidence and export mixed data', async ({ page, request }, info) => {
  const redesign = await ownPromptJourney(page, request, info)
  const children = collection(redesign.index, 'design-children', 'sequence_candidates')
  const final = collection(redesign.index, 'fold-final', 'structure_candidates')
  expect(children.items).toHaveLength(1)
  expect(final.items).toHaveLength(1)
  const child = children.items[0]
  const folded = final.items[0]
  expect.soft(folded.parent_ids).toContain(child.reference.candidate_id)
  await showCollection(page, final)
  await page.locator('.result-table').getByRole('button', { name: folded.reference.candidate_id, exact: true }).click()
  const parentButton = page.locator('.result-lineage').getByRole('button').filter({ hasText: child.reference.candidate_id })
  await expect(parentButton).toBeVisible()
  await parentButton.click()
  await expect(page.locator('.result-detail h3')).toHaveText(child.reference.candidate_id)
  const alignment = redesign.index.alignments.find(item => item.source.node_id === 'align-final' && referenceKey(item.subject) === referenceKey(folded.reference))!
  expect(alignment).toBeDefined()
  const parent = redesign.index.collections.flatMap(item => item.items).find(item => referenceKey(item.reference) === referenceKey(alignment.reference))!
  expect(parent).toBeDefined()
  expect.soft(child.parent_ids).toContain(parent.reference.candidate_id)
  await checkCandidate(page, redesign.index, child)
  await checkCandidate(page, redesign.index, folded)
  await checkCandidate(page, redesign.index, parent)
  await page.getByRole('button', { name: '并排比较 (3)', exact: true }).click()
  const overlay = page.locator('.alignment-comparison')
  await expect(overlay.locator('.alignment-viewer canvas')).toBeVisible()
  await expect(overlay).toContainText(`RMSD ${alignment.rmsd.toPrecision(5)} Å`)
  await overlay.getByText('精确角色、变换与来源', { exact: true }).click()
  expect(JSON.parse(await overlay.locator('pre').innerText())).toEqual(alignment)
  await expect(overlay.getByRole('alert')).toHaveCount(0)
  await screenshot(page, info, 'mpnn-lineage-published-alignment')
  await downloadSelection(page, redesign, [child, folded, parent], info)
  await page.getByRole('button', { name: '勾选保存为流程', exact: true }).click()
  const selection = page.getByRole('dialog', { name: '保存流程操作预览' })
  await expect(selection.getByRole('region', { name: '流程筛选编辑器' })).toHaveCount(3)
  const saving = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith(`/projects/${redesign.project.id}/workflow/draft`))
  await selection.getByRole('button', { name: '确认保存到流程', exact: true }).click()
  const saved = await (await saving).json() as WorkflowDraft
  const manual = saved.workflow.nodes.filter(node => node.node_type_id === 'selection.manual')
  expect(manual).toHaveLength(3)
  expect(manual.flatMap(node => node.node_parameters.selected_candidates as CandidateReference[]).map(referenceKey).sort()).toEqual([child, folded, parent].map(item => referenceKey(item.reference)).sort())
  const committed = await request.post(`/api/v2/projects/${redesign.project.id}/workflow:commit`, { data: { workflow: saved.workflow } })
  expect(committed.status()).toBe(200)
  await info.attach('saved-manual-candidate-references', { body: Buffer.from(JSON.stringify(manual, null, 2)), contentType: 'application/json' })
  await executeSavedSelections(page, request, redesign, Object.fromEntries(manual.map(node => [node.node_id, node.node_parameters.selected_candidates as CandidateReference[]])))
})


for (const action of ['cancel', 'cancel-delete', 'wait-delete'] as const) {
  test(`active real Run supports ${action} and retains published evidence`, async ({ page, request }, info) => {
    const project = await preparePromptJourney(page, request, info)
    const base = `/api/v2/projects/${project.id}`
    const draft = await (await request.get(`${base}/workflow/draft`)).json() as WorkflowDraft
    const committed = await request.post(`${base}/workflow:commit`, { data: { workflow: draft.workflow } })
    expect(committed.status()).toBe(200)
    const commit = await committed.json()
    const started = await request.post(`${base}/runs`, { data: { workflow_commit_id: commit.workflow_commit_id, client_request_id: crypto.randomUUID() } })
    expect(started.status()).toBe(202)
    const receipt = await started.json()
    await info.attach('active-run-receipt', { body: Buffer.from(JSON.stringify(receipt)), contentType: 'application/json' })
    await openProject(page, project)
    await expect(page.getByTestId('rf__node-generate-paired').getByText('运行中', { exact: true })).toHaveCount(1, { timeout: 60_000 })
    if (action === 'cancel') {
      await page.getByRole('button', { name: '取消整次运行', exact: true }).click()
      await expect.poll(async () => (await (await request.get(`${base}/runs/${receipt.run_id}`)).json()).status, { timeout: 60_000 }).toBe('cancelled')
      await expect(page.locator('.run-progress-bar')).toContainText('运行已取消')
      await page.getByRole('button', { name: '打开 Results Workbench', exact: true }).click()
      await expect(page.locator('.results-explorer > aside nav button').first()).toBeVisible()
    } else {
      await page.getByRole('button', { name: '项目', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '项目与版本', exact: true })
      await dialog.getByRole('button', { name: '移至最近删除', exact: true }).click()
      await expect(dialog.getByText('可以等待完成，或明确取消运行后删除。', { exact: true })).toBeVisible()
      expect((await (await request.get(`${base}/runs/${receipt.run_id}`)).json()).status).toBe('running')
      await dialog.getByRole('button', { name: action === 'cancel-delete' ? '取消运行后删除' : '等待完成后删除', exact: true }).click()
      await expect.poll(async () => ((await (await request.get('/api/v2/projects/deleted')).json()).projects as ProjectMetadata[]).some(item => item.id === project.id), { timeout: 25 * 60_000, intervals: [1000, 2500, 5000] }).toBe(true)
      await expect(dialog).toHaveCount(0)
      await page.getByRole('button', { name: '项目', exact: true }).click()
      await dialog.getByRole('tab', { name: /最近删除/ }).click()
      await dialog.getByRole('button').filter({ has: page.getByText(project.name, { exact: true }) }).click()
      await dialog.getByRole('button', { name: '恢复项目', exact: true }).click()
      await expect.poll(async () => (await request.get(`${base}/runs/${receipt.run_id}`)).status()).toBe(200)
      const retained = await (await request.get(`${base}/runs/${receipt.run_id}`)).json() as RunProjection
      expect(retained.status).toBe(action === 'cancel-delete' ? 'cancelled' : 'succeeded')
    }
    const projection = await (await request.get(`${base}/runs/${receipt.run_id}`)).json() as RunProjection
    expect(projection.outputs.length).toBeGreaterThan(0)
    expect(projection.project_id).toBe(project.id)
    await info.attach('retained-run', { body: Buffer.from(JSON.stringify(projection)), contentType: 'application/json' })
  })
}
