import type { JsonObject, Workflow } from '../../../webui/src/protocol/client'
import type { ObservationDraft, SelectionDraft, SelectionSource } from './selection-authoring'

export function serializeObservationSelection(value: ObservationDraft): JsonObject {
  return {
    ...(value.scoreInput ? { score_input: value.scoreInput } : {}), metric_id: value.metricId, method_id: value.methodId,
    source_partition: value.partition, context: structuredClone(value.context),
    ...(value.reference ? { reference: structuredClone(value.reference) } : {}),
    ...(value.exactContexts ? { exact_contexts: structuredClone(value.exactContexts) } : {}),
    ...(value.relationInput ? { relation_input: value.relationInput } : {}),
  }
}

export function reconcileObservationInputs(workflow: Workflow, nodeId: string, nodeTypeId: string, draft: Pick<SelectionDraft, 'candidateSource' | 'observations'>, previous: JsonObject[]): { observations: ObservationDraft[]; edges: Workflow['edges'] } {
  const existing = workflow.nodes.find((node) => node.node_id === nodeId)
  const slots = new Map<string, string>()
  const associate = (port: string, source?: SelectionSource, slot?: string) => {
    if (!source) return slot
    const key = JSON.stringify([port, source.node_id, source.output_port])
    const edge = workflow.edges.find((entry) => entry.target_node_id === nodeId && entry.target_port === port && entry.source_node_id === source.node_id && entry.source_port === source.output_port)
    if (!slots.has(key)) slots.set(key, edge?.target_slot ?? slot ?? `input-${crypto.randomUUID()}`)
    return slots.get(key)
  }
  const observations = draft.observations.map((value) => ({
    ...value, scoreInput: associate('scores', value.scoreSource, value.scoreInput ?? value.id),
    relationInput: associate('relations', value.relationSource, value.relationInput),
  }))
  const ownedSlots = new Set([...previous.flatMap((value) => [value.score_input, value.relation_input]), ...observations.flatMap((value) => [value.scoreInput, value.relationInput])].filter(Boolean))
  const operationChanged = existing !== undefined && existing.node_type_id !== nodeTypeId
  const selectedSource = (edge: Workflow['edges'][number]) => observations.some((value) => {
    const source = edge.target_port === 'scores' ? value.scoreSource : edge.target_port === 'relations' ? value.relationSource : undefined
    return source?.node_id === edge.source_node_id && source.output_port === edge.source_port
  })
  const edges = workflow.edges.filter((edge) => edge.target_node_id !== nodeId || edge.target_port !== 'candidates' && !(operationChanged && ['scores', 'relations'].includes(edge.target_port)) && !ownedSlots.has(edge.target_slot) && !selectedSource(edge))
  const connect = (port: string, source?: SelectionSource, slot?: string) => {
    if (source && !edges.some((edge) => edge.target_node_id === nodeId && edge.target_port === port && edge.target_slot === slot)) edges.push({ source_node_id: source.node_id, source_port: source.output_port, target_node_id: nodeId, target_port: port, ...(slot ? { target_slot: slot } : {}) })
  }
  connect('candidates', draft.candidateSource)
  for (const value of observations) {
    connect('scores', value.scoreSource, value.scoreInput)
    connect('relations', value.relationSource, value.relationInput)
  }
  return { observations, edges }
}
