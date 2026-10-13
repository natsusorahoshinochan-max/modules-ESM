import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { PublicV2Client, type Workflow } from '../src/protocol/client'
import { PublishedResults } from '../src/published-results'
import { loadWorkflowParameterChoices } from '../src/parameter-choices'

async function sourceWorkspace(client: PublicV2Client) {
  const project = await client.createProject(`Parameter sources ${crypto.randomUUID().slice(0, 8)}`)
  const input = await client.publishProjectInput(project.id, { filename: '3GB1.pdb', content_base64: readFileSync('../examples/v2/structures/3GB1.pdb').toString('base64') })
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: project.id, nodes: [
    { node_id: 'structure', node_type_id: 'protein_io.import_structure', binding_id: 'protein_io.import_structure.direct', node_parameters: { project_input_ref: input.project_input_ref }, binding_parameters: {} },
    { node_id: 'chains', node_type_id: 'structure_transform.select_chains', binding_id: 'structure_transform.select_chains.direct', node_parameters: { chain_ids: ['A'] }, binding_parameters: {} },
    { node_id: 'axis', node_type_id: 'structure_transform.resolve_residue_axis', binding_id: 'structure_transform.resolve_residue_axis.direct', node_parameters: {}, binding_parameters: {} },
    { node_id: 'constraints', node_type_id: 'proteinmpnn.constraints', binding_id: 'proteinmpnn.constraints.local', node_parameters: { designed_chains: ['Z'], fixed_residue_ids: ['Z:999'] }, binding_parameters: {} },
  ], edges: [
    { source_node_id: 'structure', source_port: 'structure', target_node_id: 'chains', target_port: 'structure' },
    { source_node_id: 'chains', source_port: 'structure', target_node_id: 'axis', target_port: 'structure' },
    { source_node_id: 'axis', source_port: 'residue_axis', target_node_id: 'constraints', target_port: 'structure_residue_axis' },
  ], observation_selectors: [], selection_objectives: [] }
  const draft = (await client.saveWorkspace(project.id, { workflow })).draft!
  return { project, input, workflow, draft }
}

test('parameter choices come from the exact current source owner and do not publish preview nodes', async ({ baseURL }) => {
  const client = new PublicV2Client(baseURL)
  const { project, input, workflow, draft } = await sourceWorkspace(client)
  const catalog = await client.catalog()
  const choices = await loadWorkflowParameterChoices(client, project.id, workflow, catalog)
  expect(choices.structure.choices.project_input_ref).toContainEqual({ value: input.project_input_ref, label: `3GB1.pdb · ${input.project_input_ref}` })
  expect(choices.chains.choices.chains).toEqual([{ value: 'A', label: 'Chain A' }])
  expect(choices.constraints.choices.chains).toEqual([{ value: 'A', label: 'Chain A' }])
  expect(choices.constraints.choices.residues.map(item => item.value)).toEqual(Array.from({ length: 56 }, (_, index) => `A:${index + 1}`))
  expect(choices.constraints.source).toContain('axis / residue_axis')
  expect((await client.projectWorkspace(project.id)).draft).toEqual(draft)
  const disconnected = { ...workflow, edges: workflow.edges.filter(edge => edge.target_node_id !== 'constraints') }
  const missing = await loadWorkflowParameterChoices(client, project.id, disconnected, catalog)
  expect(missing.constraints.choices.residues).toBeUndefined()
  expect(missing.constraints.notice).toContain('尚未连接')
  expect(disconnected.nodes[3].node_parameters).toEqual({ designed_chains: ['Z'], fixed_residue_ids: ['Z:999'] })
})

test('a current published residue axis supplies choices without requiring a prospective Prompt source', async ({ baseURL }) => {
  const client = new PublicV2Client(baseURL)
  const { project, workflow } = await sourceWorkspace(client)
  const current = { ...workflow, nodes: workflow.nodes.map(node => node.node_id === 'constraints'
    ? { ...node, node_parameters: { designed_chains: ['A'], fixed_residue_ids: ['A:1'] } }
    : node) }
  await client.saveWorkspace(project.id, { workflow: current })
  const commit = await client.commitWorkflow(project.id, current)
  const receipt = await client.startRun(project.id, commit.workflow_commit_id)
  await expect.poll(async () => (await client.runProjection(project.id, receipt.run_id)).status).toBe('succeeded')
  const run = await client.runProjection(project.id, receipt.run_id)
  const catalog = await client.catalog()
  let previewRequests = 0
  let valueRequests = 0
  class ReadingClient extends PublicV2Client {
    override runEvents() { return { close() {} } as WebSocket }
    override resultValue(...args: Parameters<PublicV2Client['resultValue']>) { valueRequests += 1; return super.resultValue(...args) }
  }
  const results = new PublishedResults(new ReadingClient(baseURL))
  results.openRun(run)
  await results.refresh()
  const choicesClient = {
    listProjectInputs: client.listProjectInputs.bind(client),
    inspectProjectInput: client.inspectProjectInput.bind(client),
    compareWorkflowScience: client.compareWorkflowScience.bind(client),
    openPrompt: async () => { previewRequests += 1; throw new Error('This source requires its published execution result') },
  }
  const choices = await loadWorkflowParameterChoices(choicesClient, project.id, current, catalog, results)
  expect(choices.constraints.source).toBe(`axis / residue_axis · Run ${run.run_id}`)
  expect(choices.constraints.choices.chains).toEqual([{ value: 'A', label: 'Chain A' }])
  expect(choices.constraints.choices.residues.map(item => item.value)).toEqual(Array.from({ length: 56 }, (_, index) => `A:${index + 1}`))
  expect(previewRequests).toBe(0)
  expect(valueRequests).toBe(1)

  const changed = { ...current, nodes: current.nodes.map(node => node.node_id === 'constraints'
    ? { ...node, node_parameters: { designed_chains: ['A'], fixed_residue_ids: ['A:2'] } }
    : node) }
  const stale = await loadWorkflowParameterChoices(choicesClient, project.id, changed, catalog, results)
  expect(stale.constraints.choices.residues).toBeUndefined()
  expect(stale.constraints.notice).toContain('尚未确认与当前流程一致')
  expect(previewRequests).toBe(0)
  expect(valueRequests).toBe(1)
})

test('canvas parameters expose live Input, chain and residue options while retaining unavailable saved values', async ({ page, baseURL }) => {
  const client = new PublicV2Client(baseURL)
  const { project, input } = await sourceWorkspace(client)
  await page.goto('/')
  await page.getByRole('button', { name: '项目', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '项目与版本' })
  await dialog.getByRole('button').filter({ has: page.getByText(project.name, { exact: true }) }).click()
  await dialog.getByRole('button', { name: '打开项目', exact: true }).click()
  const source = page.getByTestId('rf__node-structure')
  await source.getByLabel('编辑参数').click()
  await expect(source.getByLabel('project_input_ref').locator('option', { hasText: '3GB1.pdb' })).toHaveAttribute('value', input.project_input_ref)
  const constraints = page.getByTestId('rf__node-constraints')
  await constraints.getByLabel('编辑参数').click()
  await expect(constraints.getByText('Z:999 · 当前来源中未找到', { exact: false })).toBeVisible()
  const designedChains = constraints.getByRole('group', { name: 'designed_chains', exact: true })
  await expect(designedChains.getByRole('checkbox', { name: 'Chain A', exact: true })).toBeVisible()
  await designedChains.getByRole('checkbox', { name: 'Chain A', exact: true }).check()
  await expect.poll(async () => (await client.projectWorkspace(project.id)).draft!.workflow.nodes.find(node => node.node_id === 'constraints')!.node_parameters.designed_chains).toEqual(['Z', 'A'])
  const residues = constraints.getByRole('group', { name: 'designable_residue_ids', exact: true })
  await expect(residues.getByRole('checkbox')).toHaveCount(56)
  await residues.getByRole('checkbox', { name: 'A:1', exact: true }).check()
  await expect.poll(async () => (await client.projectWorkspace(project.id)).draft!.workflow.nodes.find(node => node.node_id === 'constraints')!.node_parameters.designable_residue_ids).toEqual(['A:1'])
  expect((await client.projectWorkspace(project.id)).draft!.workflow.nodes.find(node => node.node_id === 'constraints')!.node_parameters.fixed_residue_ids).toEqual(['Z:999'])
})
