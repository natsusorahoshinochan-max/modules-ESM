import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SavedNodeConfiguration } from '../src/SavedNodeConfiguration'
import { copyWorkflowFragment, pasteWorkflowFragment } from '../src/workflow-fragments'
import { deleteWorkflowElements } from '../src/workflow-connections'
import { parameterPresentations, selectNodeBinding } from '../src/workflow-authoring'
import type { CatalogSnapshot, Workflow, WorkflowNode } from '../src/protocol/client'

test('a saved unavailable node can be copied and another node deleted without losing its configuration or internal wire', () => {
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: 'study', nodes: [
    { node_id: 'source', node_type_id: 'unavailable.source', binding_id: 'unavailable.source.direct', node_parameters: { project_input_ref: 'input-1' }, binding_parameters: {} },
    { node_id: 'retained', node_type_id: 'unavailable.operation', binding_id: 'unavailable.operation.direct', node_parameters: { obsolete: ['original', { threshold: 9 }] }, binding_parameters: { original: true } },
    { node_id: 'discard', node_type_id: 'unavailable.other', binding_id: 'unavailable.other.direct', node_parameters: {}, binding_parameters: {} },
  ], edges: [{ source_node_id: 'source', source_port: 'original', target_node_id: 'retained', target_port: 'original', target_slot: 'saved-slot' }], observation_selectors: [], selection_objectives: [] }
  const fragment = copyWorkflowFragment(workflow, new Set(['source', 'retained']))
  let nextId = 0
  const pasted = pasteWorkflowFragment(workflow, fragment, { x: 20, y: 30 }, () => `copy-${nextId++}`).workflow
  const edited = deleteWorkflowElements(pasted, { nodeIds: new Set(['discard']), edges: [] }).workflow
  assert.deepEqual(edited.nodes.find(node => node.node_id === 'copy-1'), {
    node_id: 'copy-1', node_type_id: 'unavailable.operation', binding_id: 'unavailable.operation.direct', node_parameters: { obsolete: ['original', { threshold: 9 }] }, binding_parameters: { original: true },
  })
  assert.deepEqual(edited.edges, [workflow.edges[0], { source_node_id: 'copy-0', source_port: 'original', target_node_id: 'copy-1', target_port: 'original', target_slot: 'saved-slot' }])
  assert.equal(workflow.nodes.length, 3)
})

test('a preserved node shows its non-runnable reason and original settings without suggesting module installation', () => {
  const view = renderToStaticMarkup(createElement(SavedNodeConfiguration, { node: { node_id: 'retained', node_type_id: 'same.operation', binding_id: 'same.direct', node_parameters: { old_rule: 'original node value' }, binding_parameters: { original_binding: true }, preserved_configuration: { reason: '旧操作含义无法等价转换', settings: { original_objective: 'original global value' }, project_input_parameters: ['project_input_ref'] } }, missingContracts: [] }))
  assert.match(view, /不可运行：旧操作含义无法等价转换/)
  assert.match(view, /original node value/)
  assert.match(view, /original global value/)
  assert.match(view, /original_binding/)
  assert.doesNotMatch(view, /安装并启用/)
})

test('preserved configuration is not admitted to a currently registered parameter editor or a new Binding', () => {
  const currentCatalog: CatalogSnapshot = { availability: [], contracts: [
    { reference: { contract_kind: 'node_type', contract_id: 'same.operation' }, descriptor: { node_parameters: { count: { value_contract: { type: 'integer' }, default: 5 } } } },
    { reference: { contract_kind: 'binding', contract_id: 'same.direct' }, descriptor: { node_type: { contract_kind: 'node_type', contract_id: 'same.operation' } } },
  ] }
  const node: WorkflowNode = { node_id: 'retained', node_type_id: 'same.operation', binding_id: 'same.direct', node_parameters: { old_rule: 'unchanged' }, binding_parameters: {}, preserved_configuration: { reason: '旧操作含义无法等价转换', settings: { original_rule: { count: 8 } }, project_input_parameters: [] } }
  assert.deepEqual(parameterPresentations(currentCatalog, node), [])
  const workflow: Workflow = { schema_version: '2.1.0', workflow_id: 'study', nodes: [node], edges: [], observation_selectors: [], selection_objectives: [] }
  assert.throws(() => selectNodeBinding(workflow, 'retained', 'same.direct', currentCatalog), /旧操作含义无法等价转换/)
  const fragment = copyWorkflowFragment(workflow, new Set(['retained']))
  const copied = pasteWorkflowFragment(workflow, fragment, { x: 0, y: 0 }, () => 'copy').workflow.nodes[1]
  assert.deepEqual(copied.preserved_configuration, node.preserved_configuration)
})
