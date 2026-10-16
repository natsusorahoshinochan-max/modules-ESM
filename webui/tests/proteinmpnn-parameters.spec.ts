import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

const appUrl = process.env.WORKBENCH_TEST_URL ?? 'http://127.0.0.1:5197'

test('ProteinMPNN evaluation chooses backbone residues without entering internal IDs', async ({ page, request }) => {
  const { id } = await (await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'ProteinMPNN correspondence' } })).json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const { project_input_ref } = await (await request.post(`${base}/inputs`, { data: { filename: '3GB1.pdb', content_base64: readFileSync('../examples/v2/structures/3GB1.pdb').toString('base64') } })).json()
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [
    { node_id: 'source', node_type_id: 'protein_io.import_structure', binding_id: 'protein_io.import_structure.direct', node_parameters: { project_input_ref }, binding_parameters: {} },
    { node_id: 'axes', node_type_id: 'structure_transform.resolve_candidate_residue_axes', binding_id: 'structure_transform.resolve_candidate_residue_axes.direct', node_parameters: {}, binding_parameters: {} },
    { node_id: 'score', node_type_id: 'proteinmpnn.score', binding_id: 'proteinmpnn.score.local', node_parameters: { sequence_correspondence: [{ sequence_position: 1, residue_id: 'A:1' }] }, binding_parameters: {} },
  ], edges: [
    { source_node_id: 'source', source_port: 'structure_candidates', target_node_id: 'axes', target_port: 'structure_candidates' },
    { source_node_id: 'axes', source_port: 'residue_axes', target_node_id: 'score', target_port: 'structure_residue_axes' },
  ] }
  expect((await request.put(`${base}/workspace`, { data: { workflow, ui_state: {} } })).status()).toBe(200)
  await page.goto(`${appUrl}/?project=${id}`)
  const node = page.locator('.react-flow__node[data-id="score"]')
  await node.getByLabel('编辑参数', { exact: true }).click()
  const residue = node.locator('select').filter({ has: page.locator('option[value="A:2"]') })
  await expect(residue).toHaveCount(1)
  await residue.selectOption('A:2')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect.poll(async () => (await (await request.get(`${base}/workspace`)).json()).draft.workflow.nodes.find((item: { node_id: string }) => item.node_id === 'score').node_parameters.sequence_correspondence).toEqual([{ sequence_position: 1, residue_id: 'A:2' }])
})

test('ProteinMPNN position constraints and PSSM controls can be edited and saved', async ({ page, request }) => {
  const { id } = await (await request.post(`${appUrl}/api/v2/projects`, { data: { name: 'ProteinMPNN design controls' } })).json()
  const base = `${appUrl}/api/v2/projects/${id}`
  const { project_input_ref } = await (await request.post(`${base}/inputs`, { data: { filename: '3GB1.pdb', content_base64: readFileSync('../examples/v2/structures/3GB1.pdb').toString('base64') } })).json()
  const workflow = { schema_version: '2.1.0', workflow_id: id, nodes: [
    { node_id: 'source', node_type_id: 'protein_io.import_structure', binding_id: 'protein_io.import_structure.direct', node_parameters: { project_input_ref }, binding_parameters: {} },
    { node_id: 'axis', node_type_id: 'structure_transform.resolve_residue_axis', binding_id: 'structure_transform.resolve_residue_axis.direct', node_parameters: {}, binding_parameters: {} },
    { node_id: 'constraints', node_type_id: 'proteinmpnn.constraints', binding_id: 'proteinmpnn.constraints.local', node_parameters: {
      omit_by_residue: [{ residue_id: 'A:1', amino_acids: ['C'] }],
      pssm_by_residue: [{ residue_id: 'A:2', coefficient: .2, probabilities: Array(20).fill(.05), log_odds: Array(20).fill(0) }],
      pssm_multi: .5, pssm_bias_flag: false,
    }, binding_parameters: {} },
  ], edges: [
    { source_node_id: 'source', source_port: 'structure', target_node_id: 'axis', target_port: 'structure' },
    { source_node_id: 'axis', source_port: 'residue_axis', target_node_id: 'constraints', target_port: 'structure_residue_axis' },
  ] }
  expect((await request.put(`${base}/workspace`, { data: { workflow, ui_state: {} } })).status()).toBe(200)
  await page.goto(`${appUrl}/?project=${id}`)
  const node = page.locator('.react-flow__node[data-id="constraints"]')
  await node.getByLabel('编辑参数', { exact: true }).click()
  await node.getByRole('combobox', { name: 'omit_by_residue 1 · 残基', exact: true }).selectOption('A:2')
  await node.getByRole('textbox', { name: 'pssm_by_residue 1 · 位置混合系数', exact: true }).fill('0.4')
  await node.getByRole('textbox', { name: 'pssm_by_residue 1 · 位置混合系数', exact: true }).press('Tab')
  await node.getByRole('combobox', { name: 'pssm_bias_flag', exact: true }).selectOption('true')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect.poll(async () => (await (await request.get(`${base}/workspace`)).json()).draft.workflow.nodes.find((item: { node_id: string }) => item.node_id === 'constraints').node_parameters).toMatchObject({
    omit_by_residue: [{ residue_id: 'A:2', amino_acids: ['C'] }],
    pssm_by_residue: [{ residue_id: 'A:2', coefficient: .4 }], pssm_bias_flag: true,
  })
})
