import type { CatalogSnapshot, JsonObject, Workflow, WorkflowNode } from './protocol/client'

type Point = { x: number; y: number }
type ReferenceKind = 'selector' | 'objective'
type ReferenceParameter = { nodeId: string; kind: ReferenceKind; parameter: string; multiple: boolean }
export type FragmentNotice = { nodeId: string; parameter: string; reason: 'external_source' | 'unconfigured_reference' }
export type WorkflowFragment = {
  nodes: WorkflowNode[]
  edges: Workflow['edges']
  observationSelectors: JsonObject[]
  selectionObjectives: JsonObject[]
  referenceParameters: ReferenceParameter[]
  positions: Record<string, Point>
  notices: FragmentNotice[]
}

function referenceParameters(node: WorkflowNode, catalog: CatalogSnapshot): ReferenceParameter[] {
  const binding = catalog.contracts.find((contract) => contract.reference.contract_kind === 'binding' && contract.reference.contract_id === node.binding_id)!
  const selector = binding.descriptor.observation_selector_consumption as { selector_ids_parameter: string } | undefined
  const objective = binding.descriptor.selection_objective_consumption as { objective_id_parameter?: string; objective_ids_parameter?: string } | undefined
  return [
    ...(selector ? [{ nodeId: node.node_id, kind: 'selector' as const, parameter: selector.selector_ids_parameter, multiple: true }] : []),
    ...(objective ? [{ nodeId: node.node_id, kind: 'objective' as const, parameter: (objective.objective_ids_parameter ?? objective.objective_id_parameter)!, multiple: objective.objective_ids_parameter !== undefined }] : []),
  ]
}

function referenceSources(reference: JsonObject): string[] {
  return [(reference.candidate_input as { node_id: string }).node_id, (reference.score_collection_input as { node_id: string }).node_id]
}

/** Capture only internal graph relationships. Incomplete selections remain editable Drafts. */
export function copyWorkflowFragment(workflow: Workflow, selectedNodeIds: ReadonlySet<string>, catalog: CatalogSnapshot, positions: Record<string, Point> = {}): WorkflowFragment {
  const selected = structuredClone(workflow.nodes.filter((node) => selectedNodeIds.has(node.node_id)))
  const selectors = new Map(workflow.observation_selectors.map((selector) => [selector.selector_id as string, selector]))
  const objectives = new Map(workflow.selection_objectives.map((objective) => [objective.objective_id as string, objective]))
  const copiedSelectors = new Map<string, JsonObject>()
  const copiedObjectives = new Map<string, JsonObject>()
  const parameters: ReferenceParameter[] = []
  const notices: FragmentNotice[] = []
  for (const node of selected) {
    for (const reference of referenceParameters(node, catalog)) {
      const value = node.node_parameters[reference.parameter]
      if (value === undefined) continue
      const ids = reference.multiple ? value as string[] : [value as string]
      const source = reference.kind === 'selector' ? selectors : objectives
      const definitions = ids.map((id) => source.get(id))
      const reason = definitions.some((item) => item === undefined) ? 'unconfigured_reference' : definitions.some((item) => referenceSources(item!).some((id) => !selectedNodeIds.has(id))) ? 'external_source' : undefined
      if (reason) {
        delete node.node_parameters[reference.parameter]
        if (reference.kind === 'selector') delete node.node_parameters.expression
        notices.push({ nodeId: node.node_id, parameter: reference.parameter, reason })
        continue
      }
      const copied = reference.kind === 'selector' ? copiedSelectors : copiedObjectives
      definitions.forEach((definition, index) => copied.set(ids[index], structuredClone(definition!)))
      parameters.push(reference)
    }
  }
  const selectedPositions = Object.entries(positions).filter(([id]) => selectedNodeIds.has(id))
  const left = selectedPositions.length ? Math.min(...selectedPositions.map(([, point]) => point.x)) : 0
  const top = selectedPositions.length ? Math.min(...selectedPositions.map(([, point]) => point.y)) : 0
  return {
    nodes: selected,
    edges: structuredClone(workflow.edges.filter((edge) => selectedNodeIds.has(edge.source_node_id) && selectedNodeIds.has(edge.target_node_id))),
    observationSelectors: [...copiedSelectors.values()],
    selectionObjectives: [...copiedObjectives.values()],
    referenceParameters: parameters,
    positions: Object.fromEntries(selectedPositions.map(([id, point]) => [id, { x: point.x - left, y: point.y - top }])),
    notices,
  }
}

function rebaseReference(reference: JsonObject, kind: ReferenceKind, references: Map<string, string>, nodes: Map<string, string>): JsonObject {
  const field = `${kind}_id`
  const candidate = reference.candidate_input as JsonObject
  const scores = reference.score_collection_input as JsonObject
  return { ...reference, [field]: references.get(reference[field] as string)!, candidate_input: { ...candidate, node_id: nodes.get(candidate.node_id as string)! }, score_collection_input: { ...scores, node_id: nodes.get(scores.node_id as string)! } }
}

export function pasteWorkflowFragment(workflow: Workflow, source: WorkflowFragment, position: Point, makeId: (kind: 'node' | ReferenceKind) => string = (kind) => `${kind}-${crypto.randomUUID()}`): { workflow: Workflow; nodeIds: string[]; positions: Record<string, Point>; notices: FragmentNotice[] } {
  const fragment = structuredClone(source)
  const nodeIds = new Map(fragment.nodes.map((node) => [node.node_id, makeId('node')]))
  const selectorIds = new Map(fragment.observationSelectors.map((selector) => [selector.selector_id as string, makeId('selector')]))
  const objectiveIds = new Map(fragment.selectionObjectives.map((objective) => [objective.objective_id as string, makeId('objective')]))
  for (const parameter of fragment.referenceParameters) {
    const node = fragment.nodes.find((item) => item.node_id === parameter.nodeId)!
    const ids = parameter.kind === 'selector' ? selectorIds : objectiveIds
    const value = node.node_parameters[parameter.parameter]
    node.node_parameters[parameter.parameter] = parameter.multiple ? (value as string[]).map((id) => ids.get(id)!) : ids.get(value as string)!
  }
  return {
    workflow: {
      ...workflow,
      nodes: [...workflow.nodes, ...fragment.nodes.map((node) => ({ ...node, node_id: nodeIds.get(node.node_id)! }))],
      edges: [...workflow.edges, ...fragment.edges.map((edge) => ({ ...edge, source_node_id: nodeIds.get(edge.source_node_id)!, target_node_id: nodeIds.get(edge.target_node_id)! }))],
      observation_selectors: [...workflow.observation_selectors, ...fragment.observationSelectors.map((selector) => rebaseReference(selector, 'selector', selectorIds, nodeIds))],
      selection_objectives: [...workflow.selection_objectives, ...fragment.selectionObjectives.map((objective) => rebaseReference(objective, 'objective', objectiveIds, nodeIds))],
    },
    nodeIds: [...nodeIds.values()],
    positions: Object.fromEntries(fragment.nodes.map((node, index) => {
      const offset = fragment.positions[node.node_id] ?? { x: index * 40, y: index * 40 }
      return [nodeIds.get(node.node_id)!, { x: position.x + offset.x, y: position.y + offset.y }]
    })),
    notices: fragment.notices.map((notice) => ({ ...notice, nodeId: nodeIds.get(notice.nodeId)! })),
  }
}

/** Remove consumers' incomplete reference groups with their deleted source, never leave IDs dangling. */
export function removeWorkflowNodes(workflow: Workflow, removedNodeIds: ReadonlySet<string>, catalog: CatalogSnapshot): { workflow: Workflow; notices: FragmentNotice[] } {
  const retained = new Set(workflow.nodes.filter((node) => !removedNodeIds.has(node.node_id)).map((node) => node.node_id))
  const fragment = copyWorkflowFragment(workflow, retained, catalog)
  return {
    workflow: { ...workflow, nodes: fragment.nodes, edges: fragment.edges, observation_selectors: fragment.observationSelectors, selection_objectives: fragment.selectionObjectives },
    notices: fragment.notices,
  }
}
