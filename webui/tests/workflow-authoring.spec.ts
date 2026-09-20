import { expect, test } from '@playwright/test'
import type { CatalogSnapshot, JsonObject, Workflow, WorkflowNode } from '../src/protocol/client'
import { bindingOptions, parameterPresentations, projectPalette, selectNodeBinding } from '../src/workflow-authoring'
import { compatibleWorkflowPorts, connectWorkflowPorts } from '../src/workflow-connections'
import { copyWorkflowFragment, pasteWorkflowFragment, removeWorkflowNodes } from '../src/workflow-fragments'

function node(id: string, type = 'operation'): WorkflowNode {
  return { node_id: id, node_type_id: type, binding_id: `${type}.binding`, node_parameters: {}, binding_parameters: {} }
}

const selector: JsonObject = { selector_id: 'quality', candidate_input: { node_id: 'source', output_port: 'candidates' }, score_collection_input: { node_id: 'score', output_port: 'scores' }, metric: { contract_id: 'quality.metric', contract_kind: 'metric' }, method: { contract_id: 'quality.method', contract_kind: 'method' }, context_selector: { kind: 'intrinsic' } }
const objective: JsonObject = { ...selector, selector_id: undefined, objective_id: 'rank-quality', utility_transform: { contract_id: 'quality.utility', contract_kind: 'utility_transform' }, weight: 0.6 }
delete objective.selector_id

const catalog: CatalogSnapshot = {
  contracts: [
    { reference: { contract_kind: 'binding', contract_id: 'operation.binding' }, descriptor: {} },
    { reference: { contract_kind: 'binding', contract_id: 'filter.binding' }, descriptor: { observation_selector_consumption: { selector_ids_parameter: 'selector_ids' } } },
    { reference: { contract_kind: 'binding', contract_id: 'rank.binding' }, descriptor: { selection_objective_consumption: { objective_ids_parameter: 'objective_ids' } } },
    { reference: { contract_kind: 'binding', contract_id: 'manual.binding' }, descriptor: {} },
  ], availability: [],
}

function fragmentWorkflow(): Workflow {
  return {
    schema_version: '2.1.0', workflow_id: 'workspace',
    nodes: [node('source'), node('score'), { ...node('filter', 'filter'), node_parameters: { selector_ids: ['quality'], expression: [{ selector_index: 0, operator: '>', threshold: 0.5 }] } }, { ...node('rank', 'rank'), node_parameters: { objective_ids: ['rank-quality'], k: 3 } }, { ...node('manual', 'manual'), node_parameters: { selected_candidates: [{ candidate_id: 'candidate-A', data_type_id: 'protein.sequence', content_digest: 'exact-content' }] } }],
    edges: [
      { source_node_id: 'source', source_port: 'candidates', target_node_id: 'filter', target_port: 'candidates' },
      { source_node_id: 'score', source_port: 'scores', target_node_id: 'filter', target_port: 'scores' },
      { source_node_id: 'source', source_port: 'candidates', target_node_id: 'rank', target_port: 'candidates' },
      { source_node_id: 'score', source_port: 'scores', target_node_id: 'rank', target_port: 'scores' },
    ], observation_selectors: [selector], selection_objectives: [objective],
  }
}

test('copy/paste rebases complete internal references and keeps exact Candidate Data References unchanged', () => {
  const workflow = fragmentWorkflow()
  const before = structuredClone(workflow)
  const fragment = copyWorkflowFragment(workflow, new Set(workflow.nodes.map((item) => item.node_id)), catalog, { source: { x: 20, y: 60 }, score: { x: 220, y: 80 }, filter: { x: 420, y: 60 } })
  let serial = 0
  const pasted = pasteWorkflowFragment(workflow, fragment, { x: 800, y: 300 }, (kind) => `${kind}-${++serial}`)
  expect(pasted.notices).toEqual([])
  const copied = pasted.workflow.nodes.slice(workflow.nodes.length)
  expect(copied.map((item) => item.node_id)).toEqual(['node-1', 'node-2', 'node-3', 'node-4', 'node-5'])
  expect(copied[2].node_parameters).toEqual({ selector_ids: ['selector-6'], expression: [{ selector_index: 0, operator: '>', threshold: 0.5 }] })
  expect(copied[3].node_parameters.objective_ids).toEqual(['objective-7'])
  expect(copied[4].node_parameters.selected_candidates).toEqual(workflow.nodes[4].node_parameters.selected_candidates)
  expect(pasted.workflow.observation_selectors[1]).toMatchObject({ selector_id: 'selector-6', candidate_input: { node_id: 'node-1' }, score_collection_input: { node_id: 'node-2' } })
  expect(pasted.workflow.selection_objectives[1]).toMatchObject({ objective_id: 'objective-7', candidate_input: { node_id: 'node-1' }, score_collection_input: { node_id: 'node-2' }, weight: 0.6 })
  expect(pasted.positions['node-1']).toEqual({ x: 800, y: 300 })
  expect(pasted.positions['node-2']).toEqual({ x: 1000, y: 320 })
  expect(workflow).toEqual(before)
})

test('copying only a selection clears its external source references as one configuration', () => {
  const workflow = fragmentWorkflow()
  const fragment = copyWorkflowFragment(workflow, new Set(['filter', 'rank']), catalog)
  expect(fragment.edges).toEqual([])
  expect(fragment.observationSelectors).toEqual([])
  expect(fragment.selectionObjectives).toEqual([])
  expect(fragment.nodes[0].node_parameters).toEqual({})
  expect(fragment.nodes[1].node_parameters).toEqual({ k: 3 })
  expect(fragment.notices).toEqual([
    { nodeId: 'filter', parameter: 'selector_ids', reason: 'external_source' },
    { nodeId: 'rank', parameter: 'objective_ids', reason: 'external_source' },
  ])
})

test('deleting a referenced producer removes complete dependent configurations without dangling IDs', () => {
  const removed = removeWorkflowNodes(fragmentWorkflow(), new Set(['score']), catalog)
  expect(removed.workflow.nodes.map((item) => item.node_id)).toEqual(['source', 'filter', 'rank', 'manual'])
  expect(removed.workflow.observation_selectors).toEqual([])
  expect(removed.workflow.selection_objectives).toEqual([])
  expect(removed.workflow.nodes[1].node_parameters).toEqual({})
  expect(removed.workflow.nodes[2].node_parameters).toEqual({ k: 3 })
  expect(removed.workflow.edges.every((edge) => edge.source_node_id !== 'score')).toBe(true)
})

function parameterCatalog(): CatalogSnapshot {
  return { contracts: [
    { reference: { contract_kind: 'node_type', contract_id: 'generate' }, descriptor: { title: 'Generate Candidates', category: 'generation', inputs: [], outputs: [], parameter_groups: [{ id: 'sampling', title: 'Sampling controls', parameters: ['num_samples', 'strategy'] }], node_parameters: { num_samples: { required: true, scientific_meaning: 'Exact sample count.', value_contract: { type: 'integer', minimum: 1, maximum: 100 } }, strategy: { value_contract: { type: 'string', enum: ['random', 'entropy'] } } } } },
    { reference: { contract_kind: 'method', contract_id: 'method-A' }, descriptor: { model_identity: { model: 'Protein model A', provider: 'Research provider' } } },
    { reference: { contract_kind: 'binding', contract_id: 'binding-A' }, descriptor: { node_type: { contract_id: 'generate' }, method: { contract_id: 'method-A' }, binding_parameters: { steps: { default: 50, value_contract: { type: 'integer', minimum: 1, maximum: 500 } } } } },
    { reference: { contract_kind: 'binding', contract_id: 'binding-B' }, descriptor: { node_type: { contract_id: 'generate' }, method: { contract_id: 'method-A' }, binding_parameters: { steps: { default: 20, value_contract: { type: 'integer', minimum: 1, maximum: 100 } } } } },
  ], availability: [{ binding: { contract_id: 'binding-A' }, available: true }, { binding: { contract_id: 'binding-B' }, available: false, reason: { code: 'missing_asset', message: 'Local model is not installed.', retryable: false } }] }
}

test('parameter projection retains declared schema and grouping; Binding changes restore only explicitly remembered values', () => {
  const catalog = parameterCatalog()
  const item: WorkflowNode = { node_id: 'sample', node_type_id: 'generate', binding_id: 'binding-A', node_parameters: { num_samples: 6, strategy: 'entropy' }, binding_parameters: { steps: 42 } }
  const parameters = parameterPresentations(catalog, item)
  expect(parameters[0]).toMatchObject({ value: '6', valueType: 'integer', groupId: 'node:sampling', groupTitle: 'Sampling controls', contract: { minimum: 1, maximum: 100 } })
  expect(parameters[1].contract.enum).toEqual(['random', 'entropy'])
  expect(parameters[2].groupId).toEqual('binding:parameters')
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: 'workspace', nodes: [item], edges: [], observation_selectors: [], selection_objectives: [] }
  const changed = selectNodeBinding(workflow, item.node_id, 'binding-B', catalog)
  expect(changed.nodes[0].binding_parameters).toEqual({ steps: 20 })
  expect(changed.nodes[0].node_parameters).toEqual(item.node_parameters)
  expect(selectNodeBinding(changed, item.node_id, 'binding-A', catalog, item.binding_parameters).nodes[0].binding_parameters).toEqual({ steps: 42 })
  expect(bindingOptions(catalog, 'generate')[1]).toMatchObject({ available: false, availabilityReason: { code: 'missing_asset', message: 'Local model is not installed.' } })
})

test('Palette search matches provider and purpose terms without hiding unavailable operations', () => {
  const projected = projectPalette(parameterCatalog(), { schema_namespace: 'protein-workbench-public/v2', protocol_digest: 'test', node_roles: [{ role: 'ordinary_node', node_type: { contract_kind: 'node_type', contract_id: 'generate' } }] }, 'purpose', 'generation research')
  expect(projected.map((group) => group.entries.map((entry) => entry.id))).toEqual([['generate']])
})

test('compatible ports use nominal Port identity and one-input reconnection replaces the old edge', () => {
  const sourcePort = { name: 'sequence', port_type: { contract_id: 'protein.sequence' }, multiplicity: 'one', scientific_meaning: 'Sequence.' }
  const targetPort = { name: 'source', port_type: { contract_id: 'protein.sequence' }, multiplicity: 'one', scientific_meaning: 'Exact input sequence.' }
  const catalog: CatalogSnapshot = { availability: [], contracts: [
    { reference: { contract_kind: 'node_type', contract_id: 'source' }, descriptor: { title: 'Source', category: 'input', inputs: [], outputs: [sourcePort] } },
    { reference: { contract_kind: 'node_type', contract_id: 'target' }, descriptor: { title: 'Target', category: 'operation', inputs: [targetPort, { ...targetPort, name: 'structure', port_type: { contract_id: 'protein.structure' } }], outputs: [] } },
  ] }
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: 'workspace', nodes: [node('old', 'source'), node('new', 'source'), node('target', 'target')], edges: [{ source_node_id: 'old', source_port: 'sequence', target_node_id: 'target', target_port: 'source' }], observation_selectors: [], selection_objectives: [] }
  expect(compatibleWorkflowPorts(workflow, catalog, { nodeId: 'new', portName: 'sequence', direction: 'output' })).toEqual([{ nodeId: 'target', portName: 'source', direction: 'input' }])
  expect(connectWorkflowPorts(workflow, catalog, { nodeId: 'new', portName: 'sequence', direction: 'output' }, { nodeId: 'target', portName: 'source', direction: 'input' }).edges).toEqual([{ source_node_id: 'new', source_port: 'sequence', target_node_id: 'target', target_port: 'source' }])
})
