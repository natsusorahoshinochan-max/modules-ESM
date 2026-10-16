import type { JsonObject, Workflow } from '../../../webui/src/protocol/client'
import type { ObservationDraft, SelectionDraft, SelectionSource } from './selection-authoring'
import { reconcileObservationInputs, serializeObservationSelection } from './observation-inputs'

type WeightedObjective = { selection?: JsonObject; transform_id?: string; weight?: number }

export function readWeightedDraft(workflow: Workflow, nodeId: string): SelectionDraft {
  const node = workflow.nodes.find((entry) => entry.node_id === nodeId)!
  const source = (port: string, slot?: string): SelectionSource | undefined => {
    if (port !== 'candidates' && !slot) return undefined
    const edge = workflow.edges.find((entry) => entry.target_node_id === nodeId && entry.target_port === port && (port === 'candidates' || entry.target_slot === slot))
    return edge ? { node_id: edge.source_node_id, output_port: edge.source_port } : undefined
  }
  return {
    operation: 'weighted_rank', candidateSource: source('candidates'), selectedCandidates: [],
    observations: ((node.node_parameters.objectives ?? []) as WeightedObjective[]).map((objective, index) => {
      const selection = objective.selection ?? {}
      return {
        id: `objective-${index}`, scoreInput: selection.score_input as string | undefined,
        scoreSource: source('scores', selection.score_input as string),
        metricId: (selection.metric_id as string | undefined) ?? '', methodId: (selection.method_id as string | undefined) ?? '',
        partition: (selection.source_partition as string | undefined) ?? '', context: (selection.context as JsonObject | undefined) ?? { kind: 'intrinsic' },
        reference: selection.reference as ObservationDraft['reference'], exactContexts: selection.exact_contexts as ObservationDraft['exactContexts'],
        relationInput: selection.relation_input as string | undefined, relationSource: source('relations', selection.relation_input as string),
        transformId: objective.transform_id ?? '', transformParameters: {}, weight: objective.weight,
      }
    }),
  }
}

export function saveWeightedDraft(workflow: Workflow, nodeId: string, draft: SelectionDraft): Workflow {
  const previous = workflow.nodes.find((entry) => entry.node_id === nodeId)
  const old = (previous?.node_parameters.objectives ?? []) as WeightedObjective[]
  const { observations, edges } = reconcileObservationInputs(workflow, nodeId, 'selection.weighted_rank', draft, old.flatMap((value) => value.selection ? [value.selection] : []))
  const objectives = observations.map((value) => ({
    selection: serializeObservationSelection(value),
    transform_id: value.transformId,
    ...(value.weight === undefined ? {} : { weight: value.weight }),
  }))
  const node = { node_id: nodeId, node_type_id: 'selection.weighted_rank', binding_id: 'selection.weighted_rank.direct', node_parameters: { objectives }, binding_parameters: {} }
  return { ...workflow, nodes: previous ? workflow.nodes.map((entry) => entry.node_id === nodeId ? node : entry) : [...workflow.nodes, node], edges }
}
