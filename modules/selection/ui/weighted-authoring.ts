import type { JsonObject, Workflow } from '../../../webui/src/protocol/client'
import type { ObservationDraft, SelectionDraft, SelectionSource } from './selection-authoring'

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
  const objectives = draft.observations.map((value) => ({
    selection: {
      ...(value.scoreInput ? { score_input: value.scoreInput } : {}), metric_id: value.metricId, method_id: value.methodId,
      source_partition: value.partition, context: structuredClone(value.context),
      ...(value.reference ? { reference: structuredClone(value.reference) } : {}),
      ...(value.exactContexts ? { exact_contexts: structuredClone(value.exactContexts) } : {}),
      ...(value.relationInput ? { relation_input: value.relationInput } : {}),
    },
    transform_id: value.transformId,
    ...(value.weight === undefined ? {} : { weight: value.weight }),
  }))
  const old = (previous?.node_parameters.objectives ?? []) as WeightedObjective[]
  const ownedSlots = new Set([...old.flatMap((entry) => [entry.selection?.score_input, entry.selection?.relation_input]), ...draft.observations.flatMap((entry) => [entry.scoreInput, entry.relationInput])].filter(Boolean))
  const changingOperation = previous && previous.node_type_id !== 'selection.weighted_rank'
  const selectedSource = (edge: Workflow['edges'][number]) => draft.observations.some((entry) => {
    const source = edge.target_port === 'scores' ? entry.scoreSource : edge.target_port === 'relations' ? entry.relationSource : undefined
    return source?.node_id === edge.source_node_id && source.output_port === edge.source_port
  })
  const edges = workflow.edges.filter((edge) => edge.target_node_id !== nodeId || edge.target_port !== 'candidates' && !(changingOperation && ['scores', 'relations'].includes(edge.target_port)) && !ownedSlots.has(edge.target_slot) && !selectedSource(edge))
  const connections = new Map<string, Workflow['edges'][number]>()
  const connect = (port: string, source?: SelectionSource, slot?: string) => {
    if (source) connections.set(`${port}:${slot ?? ''}`, { source_node_id: source.node_id, source_port: source.output_port, target_node_id: nodeId, target_port: port, ...(slot ? { target_slot: slot } : {}) })
  }
  connect('candidates', draft.candidateSource)
  for (const value of draft.observations) {
    connect('scores', value.scoreSource, value.scoreInput)
    connect('relations', value.relationSource, value.relationInput)
  }
  const node = { node_id: nodeId, node_type_id: 'selection.weighted_rank', binding_id: 'selection.weighted_rank.direct', node_parameters: { objectives }, binding_parameters: {} }
  return { ...workflow, nodes: previous ? workflow.nodes.map((entry) => entry.node_id === nodeId ? node : entry) : [...workflow.nodes, node], edges: [...edges, ...connections.values()] }
}
