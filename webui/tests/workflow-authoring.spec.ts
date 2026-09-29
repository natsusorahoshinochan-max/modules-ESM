import { expect, test } from '@playwright/test'
import type { CatalogSnapshot, JsonObject, Workflow, WorkflowNode } from '../src/protocol/client'
import { bindingOptions, nodeTypePresentation, parameterPresentations, projectPalette, selectNodeBinding } from '../src/workflow-authoring'
import { compatibleWorkflowPorts, connectWorkflowPorts, deleteWorkflowElements, PromptMergeSourcesLockedError, reconnectWorkflowPorts, workflowEdgeId, type WorkflowPort } from '../src/workflow-connections'
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


function connectionFixture(locked = false) {
  const port = (name: string, multiplicity: 'one' | 'many', required: boolean) => ({ name, multiplicity, required, port_type: { contract_id: 'protein.prompt' }, scientific_meaning: `Meaning of ${name}.` })
  const catalog: CatalogSnapshot = { availability: [], contracts: [
    { reference: { contract_kind: 'node_type', contract_id: 'prompt_authoring.author' }, descriptor: { title: 'Author', category: 'prompt', inputs: [port('prompt_source', 'one', false), port('merge_sources', 'many', false)], outputs: [port('protein_prompt', 'one', true)] } },
    { reference: { contract_kind: 'binding', contract_id: 'prompt_authoring.author.binding' }, descriptor: {} },
  ] }
  const edge = (source: string, target = 'target', targetPort = 'merge_sources'): Workflow['edges'][number] => ({ source_node_id: source, source_port: 'protein_prompt', target_node_id: target, target_port: targetPort })
  const output = (nodeId: string): WorkflowPort => ({ nodeId, portName: 'protein_prompt', direction: 'output' })
  const input = (nodeId = 'target', portName = 'merge_sources'): WorkflowPort => ({ nodeId, portName, direction: 'input' })
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: 'connections', nodes: ['A', 'B', 'C', 'target', 'other'].map(id => ({ ...node(id, 'prompt_authoring.author'), node_parameters: { document: locked && id === 'target' ? { source_merges: [{ source_index: 1, correspondence: [], track_adoptions: [], adopt_annotations: [], remove_annotations: [] }] } : {} } })), edges: [edge('A'), edge('B')], observation_selectors: [], selection_objectives: [] }
  return { workflow, catalog, edge, output, input }
}

test('port presentation preserves a complete typed descriptor without parallel maps', () => {
  const { catalog } = connectionFixture()
  const presentation = nodeTypePresentation(catalog, 'prompt_authoring.author')
  expect(presentation.inputs[1]).toEqual({ name: 'merge_sources', portTypeId: 'protein.prompt', multiplicity: 'many', required: false, meaning: 'Meaning of merge_sources.' })
  expect(presentation.outputs[0].required).toBe(true)
  expect(presentation).not.toHaveProperty('inputPortTypes')
})

test('edge identity is independent of array position and delimiters in endpoint names', () => {
  const { edge } = connectionFixture()
  expect(workflowEdgeId(edge('A'))).toBe(workflowEdgeId({ ...edge('A') }))
  expect(workflowEdgeId({ ...edge('A'), source_node_id: 'A:B', source_port: 'C' })).not.toBe(workflowEdgeId({ ...edge('A'), source_node_id: 'A', source_port: 'B:C' }))
})

test('no-op and duplicate connections retain both owner identity and many-source order', () => {
  const { workflow, catalog, edge, output, input } = connectionFixture()
  expect(connectWorkflowPorts(workflow, catalog, output('A'), input())).toBe(workflow)
  expect(reconnectWorkflowPorts(workflow, catalog, edge('A'), output('A'), input())).toBe(workflow)
  expect(reconnectWorkflowPorts(workflow, catalog, edge('A'), output('B'), input())).toBe(workflow)
  expect(workflow.edges).toEqual([edge('A'), edge('B')])
})

test('reconnect preserves its many-input slot and appends only on transfer to another input', () => {
  const { workflow, catalog, edge, output, input } = connectionFixture()
  expect(reconnectWorkflowPorts(workflow, catalog, edge('A'), output('C'), input()).edges).toEqual([edge('C'), edge('B')])
  const withOther = { ...workflow, edges: [...workflow.edges, edge('C', 'other')] }
  expect(reconnectWorkflowPorts(withOther, catalog, edge('A'), output('A'), input('other')).edges).toEqual([edge('B'), edge('C', 'other'), edge('A', 'other')])
})

test('connect and reconnect replace occupied one-inputs consistently', () => {
  const { workflow, catalog, edge, output, input } = connectionFixture()
  const one = { ...workflow, edges: [edge('A', 'target', 'prompt_source'), edge('C', 'other', 'prompt_source')] }
  const target = input('target', 'prompt_source')
  expect(connectWorkflowPorts(one, catalog, output('B'), target).edges).toEqual([edge('C', 'other', 'prompt_source'), edge('B', 'target', 'prompt_source')])
  expect(reconnectWorkflowPorts(one, catalog, edge('C', 'other', 'prompt_source'), output('C'), target).edges).toEqual([edge('C', 'target', 'prompt_source')])
})

test('configured Prompt merges reject changed source identity or order but allow append and no-op', () => {
  const { workflow, catalog, edge, output, input } = connectionFixture(true)
  const before = structuredClone(workflow)
  expect(() => reconnectWorkflowPorts(workflow, catalog, edge('A'), output('C'), input())).toThrow(PromptMergeSourcesLockedError)
  expect(() => reconnectWorkflowPorts(workflow, catalog, edge('A'), output('A'), input('other'))).toThrow(PromptMergeSourcesLockedError)
  expect(() => deleteWorkflowElements(workflow, catalog, { nodeIds: new Set(), edges: [edge('A')] })).toThrow(PromptMergeSourcesLockedError)
  expect(() => deleteWorkflowElements(workflow, catalog, { nodeIds: new Set(['A']), edges: [] })).toThrow(PromptMergeSourcesLockedError)
  expect(reconnectWorkflowPorts(workflow, catalog, edge('A'), output('A'), input())).toBe(workflow)
  expect(connectWorkflowPorts(workflow, catalog, output('C'), input()).edges).toEqual([...workflow.edges, edge('C')])
  expect(workflow).toEqual(before)
})

test('batch deletion ignores removed Prompt owners but reports all retained affected owners atomically', () => {
  const { workflow, catalog, edge } = connectionFixture(true)
  const other = workflow.nodes.find(item => item.node_id === 'other')!
  const both = { ...workflow, nodes: workflow.nodes.map(item => item === other ? { ...item, node_parameters: workflow.nodes.find(node => node.node_id === 'target')!.node_parameters } : item), edges: [...workflow.edges, edge('A', 'other')] }
  try {
    deleteWorkflowElements(both, catalog, { nodeIds: new Set(['A', 'target']), edges: [] })
    throw new Error('Expected a locked merge error')
  } catch (error) {
    expect(error).toBeInstanceOf(PromptMergeSourcesLockedError)
    expect((error as PromptMergeSourcesLockedError).nodeIds).toEqual(['other'])
  }
  const removed = deleteWorkflowElements(workflow, catalog, { nodeIds: new Set(['A', 'target']), edges: [] })
  expect(removed.workflow.nodes.map(item => item.node_id)).toEqual(['B', 'C', 'other'])
  expect(removed.workflow.edges).toEqual([])
})

test('clearing merge operations permits source changes without altering other Prompt edits', () => {
  const { workflow, catalog, edge, output, input } = connectionFixture(true)
  const cleared = { ...workflow, nodes: workflow.nodes.map(item => item.node_id === 'target' ? { ...item, node_parameters: { document: { source_merges: [], chains: [{ chain_id: 'A', length: 2 }] } } } : item) }
  const changed = reconnectWorkflowPorts(cleared, catalog, edge('A'), output('C'), input())
  expect(changed.edges).toEqual([edge('C'), edge('B')])
  expect(changed.nodes).toBe(cleared.nodes)
})

test('unified deletion retains Selection cleanup and an empty operation retains workflow identity', () => {
  const workflow = fragmentWorkflow()
  expect(deleteWorkflowElements(workflow, catalog, { nodeIds: new Set(), edges: [] }).workflow).toBe(workflow)
  const removed = deleteWorkflowElements(workflow, catalog, { nodeIds: new Set(['score']), edges: [] })
  expect(removed.workflow.observation_selectors).toEqual([])
  expect(removed.workflow.selection_objectives).toEqual([])
  expect(removed.workflow.nodes.find(item => item.node_id === 'filter')!.node_parameters).toEqual({})
})


test('port matching rejects many outputs into one inputs and incompatible reconnect leaves the original edge', () => {
  const { workflow, catalog, edge, output, input } = connectionFixture()
  const descriptor = catalog.contracts.find(item => item.reference.contract_kind === 'node_type')!.descriptor
  descriptor.outputs = [{ name: 'protein_prompt', port_type: { contract_id: 'protein.prompt' }, multiplicity: 'many', required: true, scientific_meaning: 'Many prompts.' }]
  const candidates = compatibleWorkflowPorts(workflow, catalog, output('A'))
  expect(candidates.every(port => port.portName === 'merge_sources')).toBe(true)
  expect(connectWorkflowPorts(workflow, catalog, output('C'), input('target', 'prompt_source'))).toBe(workflow)
  expect(reconnectWorkflowPorts(workflow, catalog, edge('A'), output('A'), input('target', 'prompt_source'))).toBe(workflow)
  descriptor.outputs = [{ name: 'protein_prompt', port_type: { contract_id: 'protein.structure' }, multiplicity: 'one', required: true, scientific_meaning: 'Structure.' }]
  expect(reconnectWorkflowPorts(workflow, catalog, edge('A'), output('C'), input())).toBe(workflow)
})


test('incomplete Prompt drafts without a document permit connection editing', () => {
  const { workflow, catalog, output, input, edge } = connectionFixture()
  const incomplete = { ...workflow, nodes: workflow.nodes.map(item => item.node_id === 'target' ? { ...item, node_parameters: {} } : item) }
  expect(connectWorkflowPorts(incomplete, catalog, output('C'), input()).edges).toEqual([...workflow.edges, edge('C')])
})
