import type { CatalogSnapshot, PromptAuthoringDocument, Workflow } from './protocol/client'
import { nodeTypePresentation, type PortPresentation } from './workflow-authoring'
import { removeWorkflowNodes, type FragmentNotice } from './workflow-fragments'

export type WorkflowPort = { nodeId: string; portName: string; direction: 'input' | 'output' }
export type WorkflowEdge = Workflow['edges'][number]

/** Stable identity includes all four endpoint fields, independently of edge ordering. */
export function workflowEdgeId(edge: WorkflowEdge): string {
  return JSON.stringify([edge.source_node_id, edge.source_port, edge.target_node_id, edge.target_port])
}

export function workflowPortPresentation(workflow: Workflow, catalog: CatalogSnapshot, port: WorkflowPort): PortPresentation {
  const node = workflow.nodes.find(item => item.node_id === port.nodeId)
  if (!node) throw new Error(`Workflow Node ${port.nodeId} is absent`)
  const presentation = nodeTypePresentation(catalog, node.node_type_id)
  const descriptor = (port.direction === 'input' ? presentation.inputs : presentation.outputs).find(item => item.name === port.portName)
  if (!descriptor) throw new Error(`Port ${port.nodeId}/${port.portName} is absent`)
  return descriptor
}

export function portTypeId(workflow: Workflow, catalog: CatalogSnapshot, port: WorkflowPort): string {
  return workflowPortPresentation(workflow, catalog, port).portTypeId
}

/** Local Port matching only: full Workflow validity belongs to the compiler. */
export function workflowPortsMatch(output: Pick<PortPresentation, 'portTypeId' | 'multiplicity'>, input: Pick<PortPresentation, 'portTypeId' | 'multiplicity'>): boolean {
  return output.portTypeId === input.portTypeId && !(output.multiplicity === 'many' && input.multiplicity === 'one')
}

export function compatibleWorkflowPorts(workflow: Workflow, catalog: CatalogSnapshot, anchor: WorkflowPort): WorkflowPort[] {
  const descriptor = workflowPortPresentation(workflow, catalog, anchor)
  return workflow.nodes.flatMap(node => {
    if (node.node_id === anchor.nodeId) return []
    const presentation = nodeTypePresentation(catalog, node.node_type_id)
    const ports = anchor.direction === 'input' ? presentation.outputs : presentation.inputs
    return ports.filter(port => anchor.direction === 'input' ? workflowPortsMatch(port, descriptor) : workflowPortsMatch(descriptor, port)).map((port): WorkflowPort => ({ nodeId: node.node_id, portName: port.name, direction: anchor.direction === 'input' ? 'output' : 'input' }))
  })
}

export class PromptMergeSourcesLockedError extends Error {
  readonly nodeIds: string[]

  constructor(nodeIds: string[]) {
    super(`请先在 Prompt Studio 调整并保存 ${nodeIds.join('、')} 的合并配置，再修改已有合并来源。`)
    this.name = 'PromptMergeSourcesLockedError'
    this.nodeIds = nodeIds
  }
}

/** Existing positional merge sources must remain the exact prefix for retained owners. */
function protectPromptMergeSources(before: Workflow, after: Workflow): Workflow {
  const retained = new Set(after.nodes.map(node => node.node_id))
  const affected = before.nodes.filter(node => {
    if (node.node_type_id !== 'prompt_authoring.author' || !retained.has(node.node_id)) return false
    const document = node.node_parameters.document as PromptAuthoringDocument | undefined
    if (!document?.source_merges?.length) return false
    const sources = (workflow: Workflow) => workflow.edges.filter(edge => edge.target_node_id === node.node_id && edge.target_port === 'merge_sources').map(workflowEdgeId)
    const oldSources = sources(before)
    const newSources = sources(after)
    return oldSources.some((source, index) => newSources[index] !== source)
  }).map(node => node.node_id)
  if (affected.length) throw new PromptMergeSourcesLockedError(affected)
  return after
}

function connectionEdge(output: WorkflowPort, input: WorkflowPort): WorkflowEdge {
  if (output.direction !== 'output' || input.direction !== 'input') throw new Error('Connections require an output and an input Port')
  return { source_node_id: output.nodeId, source_port: output.portName, target_node_id: input.nodeId, target_port: input.portName }
}

function editConnection(workflow: Workflow, catalog: CatalogSnapshot, output: WorkflowPort, input: WorkflowPort, previous?: WorkflowEdge): Workflow {
  const next = connectionEdge(output, input)
  const previousId = previous && workflowEdgeId(previous)
  const nextId = workflowEdgeId(next)
  if (previousId === nextId || workflow.edges.some(edge => workflowEdgeId(edge) === nextId)) return workflow
  if (previousId && !workflow.edges.some(edge => workflowEdgeId(edge) === previousId)) return workflow
  const target = workflowPortPresentation(workflow, catalog, input)
  if (output.nodeId === input.nodeId || !workflowPortsMatch(workflowPortPresentation(workflow, catalog, output), target)) return workflow
  const sameTarget = previous?.target_node_id === input.nodeId && previous.target_port === input.portName
  let edges: WorkflowEdge[]
  if (previous && sameTarget && target.multiplicity === 'many') {
    edges = workflow.edges.map(edge => workflowEdgeId(edge) === previousId ? next : edge)
  } else {
    edges = workflow.edges.filter(edge => workflowEdgeId(edge) !== previousId && !(target.multiplicity === 'one' && edge.target_node_id === input.nodeId && edge.target_port === input.portName))
    edges.push(next)
  }
  return protectPromptMergeSources(workflow, { ...workflow, edges })
}

/** One-valued inputs replace their connection; many-valued inputs append a new source. */
export function connectWorkflowPorts(workflow: Workflow, catalog: CatalogSnapshot, output: WorkflowPort, input: WorkflowPort): Workflow {
  return editConnection(workflow, catalog, output, input)
}

/** Replacing a source within the same many-valued input preserves its positional meaning. */
export function reconnectWorkflowPorts(workflow: Workflow, catalog: CatalogSnapshot, previous: WorkflowEdge, output: WorkflowPort, input: WorkflowPort): Workflow {
  return editConnection(workflow, catalog, output, input, previous)
}

/** Delete one atomic set, retaining Selection-reference cleanup and Prompt merge intent. */
export function deleteWorkflowElements(workflow: Workflow, catalog: CatalogSnapshot, selection: { nodeIds: ReadonlySet<string>; edges: readonly WorkflowEdge[] }): { workflow: Workflow; notices: FragmentNotice[] } {
  const removedEdgeIds = new Set(selection.edges.map(workflowEdgeId))
  const deletesNodes = workflow.nodes.some(node => selection.nodeIds.has(node.node_id))
  const deletesEdges = workflow.edges.some(edge => removedEdgeIds.has(workflowEdgeId(edge)))
  if (!deletesNodes && !deletesEdges) return { workflow, notices: [] }
  const result = deletesNodes ? removeWorkflowNodes(workflow, selection.nodeIds, catalog) : { workflow, notices: [] }
  const changed = deletesEdges ? { ...result.workflow, edges: result.workflow.edges.filter(edge => !removedEdgeIds.has(workflowEdgeId(edge))) } : result.workflow
  return { workflow: protectPromptMergeSources(workflow, changed), notices: result.notices }
}
