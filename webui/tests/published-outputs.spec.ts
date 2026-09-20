import { expect, test, type Page } from '@playwright/test'
import type { PublishedOutput, RunProjection } from '../src/protocol/client'

const digest = `sha256:${'a'.repeat(64)}`
const artifactReference = `sha256:${'b'.repeat(64)}`
function output(nodeId: string, outputPort: string, typeId: string, count = 1): PublishedOutput {
  return { node_id: nodeId, output_port: outputPort, port_type: { contract_kind: 'port_type', contract_id: typeId }, content_digest: digest, result_identity: digest, value_count: count, producer_provenance: { producer_run_id: 'run-1', producer_result_identity: digest, output_port: outputPort } }
}
function run(outputs: PublishedOutput[]): RunProjection {
  return { project_id: 'project-1', run_id: 'run-1', workflow_commit_id: 'commit-1', status: 'succeeded', scope: { mode: 'full', selected_node_ids: [], execution_node_ids: outputs.map((entry) => entry.node_id), forced_node_ids: [], reused_node_ids: [], out_of_scope_node_ids: [], out_of_scope_selection_ids: [] }, ledger_cursor: 'cursor-1', node_dispositions: [], outputs, artifact_index: [] }
}
async function mount(page: Page, projection: RunProjection) {
  await page.goto('/tests/fixtures/published-outputs.html')
  await expect(page.locator('html')).toHaveAttribute('data-fixture-ready', 'true')
  await page.evaluate((detail) => window.dispatchEvent(new CustomEvent('render-output-fixture', { detail })), projection)
}
const valueUrl = (node: string, port: string, index: number) => `**/api/v2/projects/project-1/runs/run-1/outputs/${node}/${port}/values/${index}`
const dataclass = (tag: string, fields: object) => ({ $dataclass: tag, fields })

test('non-candidate outputs load only the explicitly chosen value and download actual published artifacts', async ({ page }) => {
  const projection = run([output('import', 'sequence', 'protein.sequence', 2)])
  projection.artifact_index = [{ artifact_reference: artifactReference, artifact_kind: 'sequence_fasta', node_id: 'import', output_port: 'sequence', media_type: 'text/plain', filename: 'original.fasta', size: 14, content_digest: digest }]
  const requested: string[] = []
  await page.route('**/outputs/**/values/*', async (route) => {
    requested.push(route.request().url())
    await route.fulfill({ json: { port_type_id: 'protein.sequence', value: dataclass('protein_sequence', { sequence: 'GASW', residue_ids: ['A:7', 'A:8', 'A:9', 'A:10'] }) } })
  })
  await page.route('**/artifacts/*', (route) => route.fulfill({ status: 200, contentType: 'text/plain', headers: { 'Content-Disposition': 'attachment; filename="original.fasta"' }, body: '>original\nGASW\n' }))
  await mount(page, projection)
  await expect(page.getByRole('heading', { name: '已发布输出与附件' })).toBeVisible()
  expect(requested).toEqual([])
  await page.getByRole('button', { name: 'import / sequence' }).click()
  await page.getByLabel('输出值索引').selectOption('1')
  expect(requested).toEqual([])
  await page.getByRole('button', { name: '加载此值', exact: true }).click()
  await expect(page.getByLabel('已发布序列')).toContainText('GASW')
  expect(requested).toHaveLength(1)
  expect(requested[0]).toContain('/outputs/import/sequence/values/1')
  await page.getByText('查看已发布残基身份', { exact: true }).click()
  await expect(page.getByLabel('已发布序列')).toContainText('A:7')
  const artifact = page.getByRole('link', { name: 'original.fasta' })
  await expect(artifact).toHaveAttribute('href', `/api/v2/projects/project-1/runs/run-1/artifacts/${encodeURIComponent(artifactReference)}`)
  const downloading = page.waitForEvent('download')
  await artifact.click()
  expect((await downloading).suggestedFilename()).toBe('original.fasta')
})

test('Prompt view preserves residue identities, Mask, absent tracks, zero SASA and annotation endpoints', async ({ page }) => {
  const prompt = dataclass('protein_prompt', {
    layout: dataclass('residue_layout', { residue_ids: ['A:7', 'A:8'] }),
    sequence: ['G', null],
    coordinates: [dataclass('named_atom_coordinates', { atoms: { $tuple: [{ $tuple: ['CA', { $tuple: [1.25, -2, 3] }] }] } }), null],
    secondary_structure: null, sasa: [0, null],
    function_annotations: [dataclass('function_annotation', { label: 'active site', start_residue_id: 'A:7', end_residue_id: 'A:8' })],
  })
  await page.route(valueUrl('author', 'prompt', 0), (route) => route.fulfill({ json: { port_type_id: 'protein.prompt', value: prompt } }))
  await mount(page, run([output('author', 'prompt', 'protein.prompt')]))
  await page.getByRole('button', { name: 'author / prompt' }).click()
  await page.getByRole('button', { name: '加载此值', exact: true }).click()
  const table = page.getByLabel('已发布 Prompt').getByRole('table')
  const first = table.getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'A:7', exact: true }) })
  await expect(first.getByRole('cell')).toHaveText(['G', '1 个原子', '未提供整条轨道', '0'], { useInnerText: true })
  await first.getByText('1 个原子', { exact: true }).click()
  await expect(first).toContainText('CA: (1.25, -2, 3)')
  const masked = table.getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'A:8', exact: true }) })
  await expect(masked.getByRole('cell')).toHaveText(['Mask', 'Mask', '未提供整条轨道', 'Mask'])
  await expect(page.getByLabel('已发布 Prompt')).toContainText('active site · A:7 → A:8')
})

test('unknown typed values preserve their published JSON and changing Run clears the loaded selection', async ({ page }) => {
  await page.route(valueUrl('evidence', 'facts', 0), (route) => route.fulfill({ json: { port_type_id: 'extension.facts', value: { subjects: ['a', 'b'], $tuple: ['extension-owned-key'], field: 42 } } }))
  await mount(page, run([output('evidence', 'facts', 'extension.facts')]))
  await page.getByRole('button', { name: 'evidence / facts' }).click()
  await page.getByRole('button', { name: '加载此值', exact: true }).click()
  await expect(page.getByText('已加载 extension.facts 的完整类型值。', { exact: true })).toBeVisible()
  await expect(page.locator('pre')).toHaveCount(0)
  await page.getByText('查看原始已发布值', { exact: true }).click()
  await expect(page.locator('pre')).toContainText('extension-owned-key')
  await expect(page.locator('pre')).toContainText('"field": 42')
  const next = { ...run([output('evidence', 'facts', 'extension.facts')]), run_id: 'run-2' }
  await page.evaluate((detail) => window.dispatchEvent(new CustomEvent('render-output-fixture', { detail })), next)
  await expect(page.getByText('选择输出后按需查看任意值。', { exact: true })).toBeVisible()
  await expect(page.locator('pre')).toHaveCount(0)
})

test('structure value presents its actual PDB text and never synthesizes a sequence', async ({ page }) => {
  const pdb = 'ATOM      1  CA  GLY A   1       1.000   2.000   3.000  1.00 20.00           C\nEND\n'
  await page.route(valueUrl('import', 'structure', 0), (route) => route.fulfill({ json: { port_type_id: 'protein.structure', value: dataclass('protein_structure', { pdb_string: pdb }) } }))
  await mount(page, run([output('import', 'structure', 'protein.structure')]))
  await page.getByRole('button', { name: 'import / structure' }).click()
  await page.getByRole('button', { name: '加载此值', exact: true }).click()
  await page.getByText('查看原始 PDB 文本', { exact: true }).click()
  await expect(page.getByLabel('已发布结构').locator('pre')).toHaveText(pdb)
  await expect(page.getByLabel('已发布序列')).toHaveCount(0)
})
