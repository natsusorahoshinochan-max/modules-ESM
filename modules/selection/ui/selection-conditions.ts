import type { CandidateReference, JsonObject, Workflow, WorkflowNode } from '../../../webui/src/protocol/client'
import type { ComparisonOperator, ObservationDraft, SelectionDraft, SelectionSource } from './selection-authoring'

export type ConditionDraft =
  | { kind: 'comparison'; selection: ObservationDraft; operator: ComparisonOperator; threshold?: number }
  | { kind: 'group'; operator: 'and' | 'or'; children: ConditionDraft[] }

function sourceAt(workflow: Workflow, nodeId: string, port: string, slot?: string): SelectionSource | undefined {
  if (port !== 'candidates' && !slot) return undefined
  const edge = workflow.edges.find((value) => value.target_node_id === nodeId && value.target_port === port && (slot === undefined || value.target_slot === slot))
  return edge ? { node_id: edge.source_node_id, output_port: edge.source_port } : undefined
}

export function readConditionDraft(workflow: Workflow, nodeId: string, value: JsonObject): ConditionDraft {
  if (value.kind === 'group') return { kind: 'group', operator: value.operator as 'and' | 'or', children: ((value.children as JsonObject[] | undefined) ?? []).map((child) => readConditionDraft(workflow, nodeId, child)) }
  const selection = (value.selection as JsonObject | undefined) ?? {}
  const scoreInput = selection.score_input as string | undefined
  const relationInput = selection.relation_input as string | undefined
  return {
    kind: 'comparison', operator: value.operator as ComparisonOperator, threshold: value.threshold as number | undefined,
    selection: {
      id: `condition-${crypto.randomUUID()}`, scoreInput,
      scoreSource: sourceAt(workflow, nodeId, 'scores', scoreInput),
      metricId: (selection.metric_id as string | undefined) ?? '', methodId: (selection.method_id as string | undefined) ?? '',
      partition: (selection.source_partition as string | undefined) ?? '', context: (selection.context as JsonObject | undefined) ?? { kind: 'intrinsic' },
      reference: selection.reference as CandidateReference | undefined, exactContexts: selection.exact_contexts as ObservationDraft['exactContexts'],
      relationInput, relationSource: sourceAt(workflow, nodeId, 'relations', relationInput),
      transformId: '', transformParameters: {},
    },
  }
}

function observations(condition?: ConditionDraft): ObservationDraft[] {
  return condition ? condition.kind === 'comparison' ? [condition.selection] : condition.children.flatMap(observations) : []
}

export function readFilterDraft(workflow: Workflow, nodeId: string, draft: SelectionDraft): SelectionDraft {
  const node = workflow.nodes.find((value) => value.node_id === nodeId)!
  return { ...draft, candidateSource: sourceAt(workflow, nodeId, 'candidates'), condition: node.node_parameters.condition ? readConditionDraft(workflow, nodeId, node.node_parameters.condition as JsonObject) : undefined }
}

export function saveFilterDraft(workflow: Workflow, nodeId: string, draft: SelectionDraft): Workflow {
  const existing = workflow.nodes.find((value) => value.node_id === nodeId)
  const previous = existing?.node_parameters.condition ? readConditionDraft(workflow, nodeId, existing.node_parameters.condition as JsonObject) : undefined
  const leaves = observations(draft.condition)
  const ownedSlots = new Set([...observations(previous), ...leaves].flatMap((value) => [value.scoreInput ?? value.id, value.relationInput]).filter(Boolean))
  const connections = new Map<string, { port: string; slot: string; source: SelectionSource }>()
  const inputSlot = (port: string, input: string, source?: SelectionSource) => {
    if (!source) return input
    const key = JSON.stringify([port, source.node_id, source.output_port])
    if (!connections.has(key)) connections.set(key, { port, slot: input, source })
    return connections.get(key)!.slot
  }
  const write = (condition: ConditionDraft): JsonObject => {
    if (condition.kind === 'group') return { kind: 'group', operator: condition.operator, children: condition.children.map(write) }
    const value = condition.selection
    return {
      kind: 'comparison', operator: condition.operator, ...(condition.threshold === undefined ? {} : { threshold: condition.threshold }),
      selection: {
        score_input: inputSlot('scores', value.scoreInput ?? value.id, value.scoreSource), metric_id: value.metricId, method_id: value.methodId,
        source_partition: value.partition, context: structuredClone(value.context),
        ...(value.reference ? { reference: structuredClone(value.reference) } : {}),
        ...(value.exactContexts !== undefined ? { exact_contexts: structuredClone(value.exactContexts) } : {}),
        ...(value.relationInput ? { relation_input: inputSlot('relations', value.relationInput, value.relationSource) } : {}),
      },
    }
  }
  const node: WorkflowNode = { node_id: nodeId, node_type_id: 'selection.filter', binding_id: 'selection.filter.direct', node_parameters: draft.condition ? { condition: write(draft.condition) } : {}, binding_parameters: {} }
  const edges = workflow.edges.filter((edge) => edge.target_node_id !== nodeId || edge.target_port !== 'candidates' && !ownedSlots.has(edge.target_slot) && !connections.has(JSON.stringify([edge.target_port, edge.source_node_id, edge.source_port])))
  if (draft.candidateSource) edges.push({ source_node_id: draft.candidateSource.node_id, source_port: draft.candidateSource.output_port, target_node_id: nodeId, target_port: 'candidates' })
  for (const { port, slot, source } of connections.values()) edges.push({ source_node_id: source.node_id, source_port: source.output_port, target_node_id: nodeId, target_port: port, target_slot: slot })
  return { ...workflow, nodes: existing ? workflow.nodes.map((value) => value.node_id === nodeId ? node : value) : [...workflow.nodes, node], edges }
}
