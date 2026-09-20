import type { CatalogSnapshot, Workflow } from './protocol/client'
import { nodeTypePresentation } from './workflow-authoring'

export type WorkflowPort = { nodeId: string; portName: string; direction: 'input' | 'output' }

export function portTypeId(workflow: Workflow, catalog: CatalogSnapshot, port: WorkflowPort): string {
  const node = workflow.nodes.find((item) => item.node_id === port.nodeId)!
  const presentation = nodeTypePresentation(catalog, node.node_type_id)
  return (port.direction === 'input' ? presentation.inputPortTypes : presentation.outputPortTypes)[port.portName]
}

export function compatibleWorkflowPorts(workflow: Workflow, catalog: CatalogSnapshot, anchor: WorkflowPort): WorkflowPort[] {
  const type = portTypeId(workflow, catalog, anchor)
  return workflow.nodes.flatMap((node) => {
    if (node.node_id === anchor.nodeId) return []
    const presentation = nodeTypePresentation(catalog, node.node_type_id)
    const ports = anchor.direction === 'input' ? presentation.outputPortTypes : presentation.inputPortTypes
    return Object.entries(ports).filter(([, targetType]) => targetType === type).map(([portName]): WorkflowPort => ({ nodeId: node.node_id, portName, direction: anchor.direction === 'input' ? 'output' : 'input' }))
  })
}

/** One-valued inputs are replaced; ordered many-valued inputs retain existing sources. */
export function connectWorkflowPorts(workflow: Workflow, catalog: CatalogSnapshot, output: WorkflowPort, input: WorkflowPort): Workflow {
  const node = workflow.nodes.find((item) => item.node_id === input.nodeId)!
  const many = nodeTypePresentation(catalog, node.node_type_id).inputMultiplicities[input.portName] === 'many'
  const edges = workflow.edges.filter((edge) => !(edge.target_node_id === input.nodeId && edge.target_port === input.portName && (!many || (edge.source_node_id === output.nodeId && edge.source_port === output.portName))))
  return { ...workflow, edges: [...edges, { source_node_id: output.nodeId, source_port: output.portName, target_node_id: input.nodeId, target_port: input.portName }] }
}
