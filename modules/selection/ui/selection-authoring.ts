import type { CandidateReference, CatalogSnapshot, ContractReference, JsonObject, Workflow, WorkflowNode } from '../../../webui/src/protocol/client'
import { readWeightedDraft, saveWeightedDraft } from './weighted-authoring'
import { readFilterDraft, saveFilterDraft, type ConditionDraft } from './selection-conditions'
import { reconcileObservationInputs, serializeObservationSelection } from './observation-inputs'

export type SelectionOperation = 'filter' | 'sort' | 'top_k' | 'weighted_rank' | 'pareto' | 'manual'
export const selectionNodeTypes = new Set(['filter', 'sort', 'top_k', 'weighted_rank', 'pareto', 'manual'].map((name) => `selection.${name}`))
export type SelectionSource = { node_id: string; output_port: string }
export type ComparisonOperator = '>' | '>=' | '<' | '<=' | '==' | '!='
export type ObservationDraft = {
  id: string
  scoreInput?: string
  scoreSource?: SelectionSource
  metricId: string
  methodId: string
  partition: string
  context: JsonObject
  transformId: string
  transformParameters: JsonObject
  weight?: number
  direction?: 'ascending' | 'descending'
  reference?: CandidateReference
  exactContexts?: Array<{ subject: CandidateReference; context: JsonObject; residue_axis?: unknown }>
  relationInput?: string
  relationSource?: SelectionSource
}
export type SelectionDraft = {
  operation: SelectionOperation
  candidateSource?: SelectionSource
  observations: ObservationDraft[]
  condition?: ConditionDraft
  selectedCandidates: CandidateReference[]
  k?: number
  direction?: 'ascending' | 'descending'
}

export const sourceKey = (source: SelectionSource) => JSON.stringify([source.node_id, source.output_port])
export const candidateReferenceKey = (reference: CandidateReference) => JSON.stringify([reference.candidate_id, reference.data_type_id, reference.content_digest])

export function newObservation(): ObservationDraft {
  const id = `preference-${crypto.randomUUID()}`
  return { id, scoreInput: id, metricId: '', methodId: '', partition: '', context: { kind: 'intrinsic' }, transformId: '', transformParameters: {}, weight: 1 }
}

export function createSelectionDraft(operation: SelectionOperation, candidateSource?: SelectionSource): SelectionDraft {
  return { operation, candidateSource, observations: [], selectedCandidates: [] }
}

export function readSelectionDraft(workflow: Workflow, nodeId: string): SelectionDraft {
  const node = workflow.nodes.find((item) => item.node_id === nodeId)!
  const operation = node.node_type_id.slice('selection.'.length) as SelectionOperation
  if (operation === 'weighted_rank') return readWeightedDraft(workflow, nodeId)
  if (operation === 'filter') return readFilterDraft(workflow, nodeId, createSelectionDraft(operation))
  if (operation === 'sort' || operation === 'top_k' || operation === 'pareto') {
    const source = (port: string, slot?: string): SelectionSource | undefined => {
      if (port !== 'candidates' && slot === undefined) return undefined
      const edge = workflow.edges.find((value) => value.target_node_id === nodeId && value.target_port === port && (slot === undefined || value.target_slot === slot))
      return edge ? { node_id: edge.source_node_id, output_port: edge.source_port } : undefined
    }
    const objectives = operation === 'pareto'
      ? (node.node_parameters.objectives ?? []) as Array<{ selection?: JsonObject; direction?: ObservationDraft['direction'] }>
      : node.node_parameters.selection ? [{ selection: node.node_parameters.selection as JsonObject }] : []
    return {
      ...createSelectionDraft(operation, source('candidates')),
      direction: node.node_parameters.direction as SelectionDraft['direction'],
      k: node.node_parameters.k as number | undefined,
      observations: objectives.map((objective) => {
        const selection = objective.selection ?? {}
        const unfinished = newObservation()
        return {
          ...unfinished, id: operation === 'pareto' ? unfinished.id : (selection.score_input as string | undefined) ?? unfinished.id, scoreInput: selection.score_input as string | undefined,
          scoreSource: source('scores', selection.score_input as string),
          metricId: (selection.metric_id as string | undefined) ?? '', methodId: (selection.method_id as string | undefined) ?? '',
          partition: (selection.source_partition as string | undefined) ?? '', context: (selection.context as JsonObject | undefined) ?? { kind: 'intrinsic' },
          direction: objective.direction,
          reference: selection.reference as CandidateReference | undefined,
          exactContexts: selection.exact_contexts as ObservationDraft['exactContexts'],
          relationInput: selection.relation_input as string | undefined,
          relationSource: selection.relation_input ? source('relations', selection.relation_input as string) : undefined,
        }
      }),
    }
  }
  const edge = workflow.edges.find((item) => item.target_node_id === nodeId && item.target_port === 'candidates')
  return {
    ...createSelectionDraft(operation, edge ? { node_id: edge.source_node_id, output_port: edge.source_port } : undefined),
    selectedCandidates: (node.node_parameters.selected_candidates as CandidateReference[] | undefined) ?? [],
  }
}

/** Publish one complete editing transaction. */
export function saveSelectionDraft(workflow: Workflow, nodeId: string, draft: SelectionDraft): Workflow {
  if (draft.operation === 'weighted_rank') return saveWeightedDraft(workflow, nodeId, draft)
  if (draft.operation === 'filter') return saveFilterDraft(workflow, nodeId, draft)
  if (draft.operation === 'sort' || draft.operation === 'top_k' || draft.operation === 'pareto') return saveRawSelectionDraft(workflow, nodeId, draft)
  const existing = workflow.nodes.find((node) => node.node_id === nodeId)
  const source = draft.candidateSource
  const node: WorkflowNode = { node_id: nodeId, node_type_id: 'selection.manual', binding_id: 'selection.manual.direct', node_parameters: { selected_candidates: structuredClone(draft.selectedCandidates) }, binding_parameters: {} }
  return {
    ...workflow,
    nodes: existing ? workflow.nodes.map((value) => value.node_id === nodeId ? node : value) : [...workflow.nodes, node],
    edges: [...workflow.edges.filter((value) => value.target_node_id !== nodeId), ...(source ? [{ source_node_id: source.node_id, source_port: source.output_port, target_node_id: nodeId, target_port: 'candidates' }] : [])],
  }
}

function saveRawSelectionDraft(workflow: Workflow, nodeId: string, draft: SelectionDraft): Workflow {
  const existing = workflow.nodes.find((node) => node.node_id === nodeId)
  const previous = [
    ...(existing?.node_parameters.selection ? [existing.node_parameters.selection as JsonObject] : []),
    ...((existing?.node_parameters.objectives ?? []) as Array<{ selection?: JsonObject }>).flatMap((entry) => entry.selection ? [entry.selection] : []),
  ]
  const { observations, edges } = reconcileObservationInputs(workflow, nodeId, `selection.${draft.operation}`, {
    candidateSource: draft.candidateSource,
    observations: draft.operation === 'pareto' ? draft.observations : draft.observations.slice(0, 1),
  }, previous)
  const selections = observations.map((value) => ({ score_input: value.scoreInput, ...serializeObservationSelection(value) }))
  const node: WorkflowNode = {
    node_id: nodeId, node_type_id: `selection.${draft.operation}`, binding_id: `selection.${draft.operation}.direct`,
    node_parameters: draft.operation === 'pareto' ? { objectives: selections.map((selection, index) => ({ selection, ...(observations[index].direction ? { direction: observations[index].direction } : {}) })) }
      : { ...(selections[0] ? { selection: selections[0] } : {}), ...(draft.direction ? { direction: draft.direction } : {}), ...(draft.operation === 'top_k' && draft.k !== undefined ? { k: draft.k } : {}) },
    binding_parameters: {},
  }
  return { ...workflow, nodes: existing ? workflow.nodes.map((value) => value.node_id === nodeId ? node : value) : [...workflow.nodes, node], edges }
}

export function selectionSources(workflow: Workflow, catalog: CatalogSnapshot, excludedNode: string, portType: string): Array<SelectionSource & { label: string }> {
  const target = workflow.nodes.find((node) => node.node_id === excludedNode)
  const targetContract = catalog.contracts.find((item) => item.reference.contract_kind === 'node_type' && item.reference.contract_id === target?.node_type_id)
  const inputs = (targetContract?.descriptor.inputs ?? []) as Array<{ port_type: ContractReference; multiplicity: string }>
  const acceptsMany = ['score.collection', 'candidate.relation'].includes(portType) && inputs.some((input) => input.port_type.contract_id === portType && input.multiplicity === 'many')
  const descendants = new Set([excludedNode])
  let changed = true
  while (changed) {
    changed = false
    for (const edge of workflow.edges) if (descendants.has(edge.source_node_id) && !descendants.has(edge.target_node_id)) { descendants.add(edge.target_node_id); changed = true }
  }
  return workflow.nodes.filter((node) => !node.preserved_configuration && !descendants.has(node.node_id)).flatMap((node) => {
    const contract = catalog.contracts.find((item) => item.reference.contract_kind === 'node_type' && item.reference.contract_id === node.node_type_id)
    if (!contract) return []
    return (contract.descriptor.outputs as Array<{ name: string; port_type: ContractReference; multiplicity: string }>).filter((output) => output.port_type.contract_id === portType && (output.multiplicity === 'one' || acceptsMany)).map((output) => ({ node_id: node.node_id, output_port: output.name, label: `${contract.descriptor.title} · ${node.node_id} / ${output.name}` }))
  })
}

export function observationLabel(observation: ObservationDraft, catalog: CatalogSnapshot): string {
  const metric = catalog.contracts.find((item) => item.reference.contract_kind === 'metric' && item.reference.contract_id === observation.metricId)
  return metric ? `${metric.descriptor.title} · ${observation.methodId}` : '选择 Metric / Method'
}
