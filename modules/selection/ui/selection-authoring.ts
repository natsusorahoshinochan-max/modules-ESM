import type { CandidateReference, CatalogSnapshot, ContractReference, JsonObject, Workflow, WorkflowNode } from '../../../webui/src/protocol/client'

export type SelectionOperation = 'filter' | 'sort' | 'top_k' | 'weighted_rank' | 'pareto' | 'diversity' | 'manual'
export const selectionNodeTypes = new Set(['filter', 'sort', 'top_k', 'weighted_rank', 'pareto', 'diversity', 'manual'].map((name) => `selection.${name}`))
export type SelectionSource = { node_id: string; output_port: string }
export type ComparisonOperator = '>' | '>=' | '<' | '<=' | '==' | '!='
export type Predicate = { kind: 'comparison'; selectorId: string; operator: ComparisonOperator; threshold?: number } | { kind: 'group'; operator: 'and' | 'or'; children: Predicate[] }
export type ExpressionToken = { selector_index: number; operator: ComparisonOperator; threshold?: number } | { operator: 'and' | 'or'; operand_count: number }
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
  reference?: CandidateReference
  exactContexts?: Array<{ subject: CandidateReference; context: JsonObject; residue_axis?: unknown }>
  relationInput?: string
  relationSource?: SelectionSource
}
export type SelectionDraft = {
  operation: SelectionOperation
  candidateSource?: SelectionSource
  observations: ObservationDraft[]
  predicate: Predicate
  selectedCandidates: CandidateReference[]
  k?: number
  direction?: 'ascending' | 'descending'
  outOfScope: 'error' | 'ignore'
}

const ref = (contract_kind: string, contract_id: string): ContractReference => ({ contract_kind, contract_id })
export const sourceKey = (source: SelectionSource) => JSON.stringify([source.node_id, source.output_port])
export const candidateReferenceKey = (reference: CandidateReference) => JSON.stringify([reference.candidate_id, reference.data_type_id, reference.content_digest])

export function newObservation(): ObservationDraft {
  const id = `preference-${crypto.randomUUID()}`
  return { id, scoreInput: id, metricId: '', methodId: '', partition: '', context: { kind: 'intrinsic' }, transformId: '', transformParameters: {}, weight: 1 }
}

export function decodePredicate(tokens: ExpressionToken[], selectorIds: string[]): Predicate {
  if (tokens.length === 0) return { kind: 'group', operator: 'and', children: [] }
  const stack: Predicate[] = []
  for (const token of tokens) {
    if ('operand_count' in token) stack.push({ kind: 'group', operator: token.operator, children: stack.splice(-token.operand_count) })
    else stack.push({ kind: 'comparison', selectorId: selectorIds[token.selector_index], operator: token.operator, threshold: token.threshold })
  }
  return stack[0]
}

export function encodePredicate(predicate: Predicate, selectorIds: string[]): ExpressionToken[] {
  if (predicate.kind === 'comparison') return [{ selector_index: selectorIds.indexOf(predicate.selectorId), operator: predicate.operator, ...(predicate.threshold === undefined ? {} : { threshold: predicate.threshold }) }]
  const children = predicate.children.map((child) => encodePredicate(child, selectorIds)).filter((tokens) => tokens.length > 0)
  return children.length > 1 ? [...children.flat(), { operator: predicate.operator, operand_count: children.length }] : children.flat()
}

export function createSelectionDraft(operation: SelectionOperation, candidateSource?: SelectionSource): SelectionDraft {
  return { operation, candidateSource, observations: [], predicate: { kind: 'group', operator: 'and', children: [] }, selectedCandidates: [], outOfScope: 'error' }
}

function nodeReferenceIds(node: WorkflowNode): { selectors: string[]; objectives: string[] } {
  return {
    selectors: (node.node_parameters.selector_ids as string[] | undefined) ?? [],
    objectives: (node.node_parameters.objective_ids as string[] | undefined) ?? (node.node_parameters.objective_id ? [node.node_parameters.objective_id as string] : []),
  }
}

export function readSelectionDraft(workflow: Workflow, nodeId: string): SelectionDraft {
  const node = workflow.nodes.find((item) => item.node_id === nodeId)!
  const operation = node.node_type_id.slice('selection.'.length) as SelectionOperation
  if (operation === 'sort' || operation === 'top_k') {
    const selection = node.node_parameters.selection as JsonObject | undefined
    const unfinished = newObservation()
    const source = (port: string, slot?: string): SelectionSource | undefined => {
      if (port !== 'candidates' && slot === undefined) return undefined
      const edge = workflow.edges.find((value) => value.target_node_id === nodeId && value.target_port === port && (slot === undefined || value.target_slot === slot))
      return edge ? { node_id: edge.source_node_id, output_port: edge.source_port } : undefined
    }
    return {
      ...createSelectionDraft(operation, source('candidates')),
      direction: node.node_parameters.direction as SelectionDraft['direction'],
      k: node.node_parameters.k as number | undefined,
      observations: selection ? [{
        ...unfinished, id: (selection.score_input as string | undefined) ?? unfinished.id, scoreInput: selection.score_input as string | undefined,
        scoreSource: source('scores', selection.score_input as string),
        metricId: (selection.metric_id as string | undefined) ?? '', methodId: (selection.method_id as string | undefined) ?? '',
        partition: (selection.source_partition as string | undefined) ?? '', context: (selection.context as JsonObject | undefined) ?? { kind: 'intrinsic' },
        reference: selection.reference as CandidateReference | undefined,
        exactContexts: selection.exact_contexts as ObservationDraft['exactContexts'],
        relationInput: selection.relation_input as string | undefined,
        relationSource: selection.relation_input ? source('relations', selection.relation_input as string) : undefined,
      }] : [],
    }
  }
  const ids = nodeReferenceIds(node)
  const definitions = operation === 'filter' ? workflow.observation_selectors.filter((value) => ids.selectors.includes(value.selector_id as string)) : workflow.selection_objectives.filter((value) => ids.objectives.includes(value.objective_id as string))
  const orderedIds = operation === 'filter' ? ids.selectors : ids.objectives
  const byId = new Map(definitions.map((value) => [(value.selector_id ?? value.objective_id) as string, value]))
  const observations = orderedIds.filter((id) => byId.has(id)).map((id): ObservationDraft => {
    const value = byId.get(id)!
    return { id, scoreSource: value.score_collection_input as SelectionSource, metricId: (value.metric as ContractReference).contract_id, methodId: (value.method as ContractReference).contract_id, partition: value.source_partition as string, context: value.context_selector as JsonObject, transformId: value.utility_transform ? (value.utility_transform as ContractReference).contract_id : '', transformParameters: (value.utility_parameters as JsonObject | undefined) ?? {}, weight: operation === 'filter' ? 1 : value.weight as number | undefined }
  })
  const edge = workflow.edges.find((item) => item.target_node_id === nodeId && item.target_port === 'candidates')
  return {
    operation,
    candidateSource: edge ? { node_id: edge.source_node_id, output_port: edge.source_port } : undefined,
    observations,
    predicate: node.node_parameters.expression ? decodePredicate(node.node_parameters.expression as ExpressionToken[], ids.selectors) : { kind: 'group', operator: 'and', children: [] },
    selectedCandidates: (node.node_parameters.selected_candidates as CandidateReference[] | undefined) ?? [],
    k: node.node_parameters.k as number | undefined,
    outOfScope: (node.node_parameters.out_of_scope_policy as 'error' | 'ignore' | undefined) ?? 'error',
  }
}

/** Publish one complete editing transaction. */
export function saveSelectionDraft(workflow: Workflow, nodeId: string, draft: SelectionDraft): Workflow {
  if (draft.operation === 'sort' || draft.operation === 'top_k') return saveRawSelectionDraft(workflow, nodeId, draft)
  const existing = workflow.nodes.find((node) => node.node_id === nodeId)
  const oldIds = existing ? nodeReferenceIds(existing) : { selectors: [], objectives: [] }
  const source = draft.candidateSource
  const observations = draft.operation === 'manual' ? [] : ['sort', 'top_k'].includes(draft.operation) ? draft.observations.slice(0, 1) : draft.observations
  const preferences = observations.map((observation) => ({
    candidate_input: source ? { node_id: source.node_id, output_port: source.output_port } : undefined,
    score_collection_input: observation.scoreSource ? { node_id: observation.scoreSource.node_id, output_port: observation.scoreSource.output_port } : undefined,
    source_partition: observation.partition,
    metric: ref('metric', observation.metricId), method: ref('method', observation.methodId),
    context_selector: observation.context, match_cardinality: 'exactly_one', missing_policy: 'error',
    ...(draft.operation === 'filter' ? { selector_id: observation.id } : { objective_id: observation.id, utility_transform: ref('utility_transform', observation.transformId), utility_parameters: observation.transformParameters, weight: observation.weight }),
  }))
  const parameters: JsonObject = draft.operation === 'manual' ? { selected_candidates: draft.selectedCandidates } : draft.operation === 'filter' ? { selector_ids: observations.map((value) => value.id), expression: encodePredicate(draft.predicate, observations.map((value) => value.id)), out_of_scope_policy: draft.outOfScope } : {
    ...(['sort', 'top_k'].includes(draft.operation) ? { objective_id: observations[0]?.id, out_of_scope_policy: draft.outOfScope } : { objective_ids: observations.map((value) => value.id) }),
    tie_policy: 'candidate_id_ascending', ...(['top_k', 'diversity'].includes(draft.operation) && draft.k !== undefined ? { k: draft.k } : {}),
  }
  const node: WorkflowNode = { node_id: nodeId, node_type_id: `selection.${draft.operation}`, binding_id: `selection.${draft.operation}.direct`, node_parameters: parameters, binding_parameters: {} }
  const scoreSources = new Map(observations.filter((value) => value.scoreSource).map((value) => [sourceKey(value.scoreSource!), value.scoreSource!]))
  return {
    ...workflow,
    nodes: existing ? workflow.nodes.map((value) => value.node_id === nodeId ? node : value) : [...workflow.nodes, node],
    edges: [...workflow.edges.filter((value) => value.target_node_id !== nodeId || !['candidates', 'scores'].includes(value.target_port)), ...(source ? [{ source_node_id: source.node_id, source_port: source.output_port, target_node_id: nodeId, target_port: 'candidates' }] : []), ...[...scoreSources.values()].map((value) => ({ source_node_id: value.node_id, source_port: value.output_port, target_node_id: nodeId, target_port: 'scores' }))],
    observation_selectors: [...workflow.observation_selectors.filter((value) => !oldIds.selectors.includes(value.selector_id as string)), ...(draft.operation === 'filter' ? preferences : [])],
    selection_objectives: [...workflow.selection_objectives.filter((value) => !oldIds.objectives.includes(value.objective_id as string)), ...(draft.operation === 'filter' ? [] : preferences)],
  }
}

function saveRawSelectionDraft(workflow: Workflow, nodeId: string, draft: SelectionDraft): Workflow {
  const existing = workflow.nodes.find((node) => node.node_id === nodeId)
  const previous = existing?.node_parameters.selection as JsonObject | undefined
  const observation = draft.observations[0]
  const scoreInput = observation?.scoreInput ?? observation?.id
  const selection = observation ? {
    score_input: scoreInput, metric_id: observation.metricId, method_id: observation.methodId,
    source_partition: observation.partition, context: structuredClone(observation.context),
    ...(observation.reference ? { reference: structuredClone(observation.reference) } : {}),
    ...(observation.exactContexts ? { exact_contexts: structuredClone(observation.exactContexts) } : {}),
    ...(observation.relationInput ? { relation_input: observation.relationInput } : {}),
  } : undefined
  const node: WorkflowNode = {
    node_id: nodeId, node_type_id: `selection.${draft.operation}`, binding_id: `selection.${draft.operation}.direct`,
    node_parameters: { ...(selection ? { selection } : {}), ...(draft.direction ? { direction: draft.direction } : {}), ...(draft.operation === 'top_k' && draft.k !== undefined ? { k: draft.k } : {}) },
    binding_parameters: {},
  }
  const ownedSlots = new Set([previous?.score_input, previous?.relation_input, scoreInput, observation?.relationInput].filter(Boolean))
  const selectedSource = (edge: Workflow['edges'][number]) => {
    const source = edge.target_port === 'scores' ? observation?.scoreSource : edge.target_port === 'relations' ? observation?.relationSource : undefined
    return source && edge.source_node_id === source.node_id && edge.source_port === source.output_port
  }
  const edges = workflow.edges.filter((edge) => edge.target_node_id !== nodeId || edge.target_port !== 'candidates' && !ownedSlots.has(edge.target_slot) && !selectedSource(edge))
  const connect = (port: string, source?: SelectionSource, slot?: string) => {
    if (source) edges.push({ source_node_id: source.node_id, source_port: source.output_port, target_node_id: nodeId, target_port: port, ...(slot ? { target_slot: slot } : {}) })
  }
  connect('candidates', draft.candidateSource)
  connect('scores', observation?.scoreSource, scoreInput)
  connect('relations', observation?.relationSource, observation?.relationInput)
  return { ...workflow, nodes: existing ? workflow.nodes.map((value) => value.node_id === nodeId ? node : value) : [...workflow.nodes, node], edges }
}

export function selectionSources(workflow: Workflow, catalog: CatalogSnapshot, excludedNode: string, portType: string): Array<SelectionSource & { label: string }> {
  const descendants = new Set([excludedNode])
  let changed = true
  while (changed) {
    changed = false
    for (const edge of workflow.edges) if (descendants.has(edge.source_node_id) && !descendants.has(edge.target_node_id)) { descendants.add(edge.target_node_id); changed = true }
  }
  return workflow.nodes.filter((node) => !descendants.has(node.node_id)).flatMap((node) => {
    const contract = catalog.contracts.find((item) => item.reference.contract_kind === 'node_type' && item.reference.contract_id === node.node_type_id)
    if (!contract) return []
    return (contract.descriptor.outputs as Array<{ name: string; port_type: ContractReference; multiplicity: string }>).filter((output) => output.port_type.contract_id === portType && output.multiplicity === 'one').map((output) => ({ node_id: node.node_id, output_port: output.name, label: `${contract.descriptor.title} · ${node.node_id} / ${output.name}` }))
  })
}

export function observationLabel(observation: ObservationDraft, catalog: CatalogSnapshot): string {
  const metric = catalog.contracts.find((item) => item.reference.contract_kind === 'metric' && item.reference.contract_id === observation.metricId)
  return metric ? `${metric.descriptor.title} · ${observation.methodId}` : '选择 Metric / Method'
}
