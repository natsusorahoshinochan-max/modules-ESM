import type { Workflow, WorkflowNode } from './protocol/client'

type Point = { x: number; y: number }
export type WorkflowFragment = {
  nodes: WorkflowNode[]
  edges: Workflow['edges']
  positions: Record<string, Point>
}

/** Copy opaque node configuration together with the selected internal graph. */
export function copyWorkflowFragment(workflow: Workflow, selectedNodeIds: ReadonlySet<string>, positions: Record<string, Point> = {}): WorkflowFragment {
  const selectedPositions = Object.entries(positions).filter(([id]) => selectedNodeIds.has(id))
  const left = selectedPositions.length ? Math.min(...selectedPositions.map(([, point]) => point.x)) : 0
  const top = selectedPositions.length ? Math.min(...selectedPositions.map(([, point]) => point.y)) : 0
  return {
    nodes: structuredClone(workflow.nodes.filter(node => selectedNodeIds.has(node.node_id))),
    edges: structuredClone(workflow.edges.filter(edge => selectedNodeIds.has(edge.source_node_id) && selectedNodeIds.has(edge.target_node_id))),
    positions: Object.fromEntries(selectedPositions.map(([id, point]) => [id, { x: point.x - left, y: point.y - top }])),
  }
}

export function pasteWorkflowFragment(workflow: Workflow, source: WorkflowFragment, position: Point, makeId: () => string = () => `node-${crypto.randomUUID()}`): { workflow: Workflow; nodeIds: string[]; positions: Record<string, Point> } {
  const fragment = structuredClone(source)
  const nodeIds = new Map(fragment.nodes.map(node => [node.node_id, makeId()]))
  return {
    workflow: {
      ...workflow,
      nodes: [...workflow.nodes, ...fragment.nodes.map(node => ({ ...node, node_id: nodeIds.get(node.node_id)! }))],
      edges: [...workflow.edges, ...fragment.edges.map(edge => ({ ...edge, source_node_id: nodeIds.get(edge.source_node_id)!, target_node_id: nodeIds.get(edge.target_node_id)! }))],
    },
    nodeIds: [...nodeIds.values()],
    positions: Object.fromEntries(fragment.nodes.map((node, index) => {
      const offset = fragment.positions[node.node_id] ?? { x: index * 40, y: index * 40 }
      return [nodeIds.get(node.node_id)!, { x: position.x + offset.x, y: position.y + offset.y }]
    })),
  }
}

export function removeWorkflowNodes(workflow: Workflow, removedNodeIds: ReadonlySet<string>): Workflow {
  return {
    ...workflow,
    nodes: workflow.nodes.filter(node => !removedNodeIds.has(node.node_id)),
    edges: workflow.edges.filter(edge => !removedNodeIds.has(edge.source_node_id) && !removedNodeIds.has(edge.target_node_id)),
  }
}
