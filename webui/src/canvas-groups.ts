import type { Workflow } from './protocol/client'
import type { WorkflowPort } from './workflow-connections'

export type Point = { x: number; y: number }
export type CanvasViewport = Point & { zoom: number }
export type GroupPort = WorkflowPort & { label?: string }
export type CanvasGroup = { id: string; label: string; parentId: string | null; nodeIds: string[]; ports: GroupPort[] }
export type CanvasState = {
  positions: Record<string, Point>
  collapsed: string[]
  viewport?: CanvasViewport
  groups?: CanvasGroup[]
  currentGroup?: string | null
  views?: Record<string, CanvasViewport>
  selections?: Record<string, string[]>
}
export const emptyCanvas: CanvasState = { positions: {}, collapsed: [] }
export const groupPortId = (port: WorkflowPort): string => JSON.stringify([port.direction, port.nodeId, port.portName])
export const currentCanvasGroup = (canvas: CanvasState): string | null => canvas.groups?.some(group => group.id === canvas.currentGroup) ? canvas.currentGroup! : null
export function groupNodes(canvas: CanvasState, id: string): Set<string> {
  const group = canvas.groups?.find(item => item.id === id)
  if (!group) throw new Error(`节点组不存在：${id}`)
  const ids = new Set(group.nodeIds)
  for (const child of canvas.groups!.filter(item => item.parentId === id)) for (const node of groupNodes(canvas, child.id)) ids.add(node)
  return ids
}
export function selectedLeafNodes(canvas: CanvasState, selected: ReadonlySet<string>): Set<string> {
  return new Set([...selected].flatMap(id => canvas.groups?.some(group => group.id === id) ? [...groupNodes(canvas, id)] : [id]))
}
export function groupPath(canvas: CanvasState, id: string | null): CanvasGroup[] {
  if (!id) return []
  const group = canvas.groups?.find(item => item.id === id)
  return group ? [...groupPath(canvas, group.parentId), group] : []
}
export function visibleOwner(canvas: CanvasState, nodeId: string, scope = currentCanvasGroup(canvas)): string | null {
  let owner = canvas.groups?.find(group => group.nodeIds.includes(nodeId))
  if (!owner) return scope === null ? nodeId : null
  if (owner.id === scope) return nodeId
  while (owner.parentId !== scope) {
    if (owner.parentId === null) return null
    owner = canvas.groups!.find(group => group.id === owner!.parentId)!
  }
  return owner.id
}
/** Explicitly exposed ports plus every crossing endpoint, preserving exact leaf identity. */
export function groupPorts(canvas: CanvasState, workflow: Workflow, id: string): GroupPort[] {
  const inside = groupNodes(canvas, id)
  const ports = new Map<string, GroupPort>()
  for (const group of groupPath(canvas, id)) for (const port of group.ports) if (inside.has(port.nodeId)) ports.set(groupPortId(port), port)
  for (const edge of workflow.edges) {
    const source = inside.has(edge.source_node_id), target = inside.has(edge.target_node_id)
    if (source === target) continue
    const port: GroupPort = source ? { nodeId: edge.source_node_id, portName: edge.source_port, direction: 'output' } : { nodeId: edge.target_node_id, portName: edge.target_port, direction: 'input' }
    if (!ports.has(groupPortId(port))) ports.set(groupPortId(port), port)
  }
  return [...ports.values()]
}
export function resolveCanvasPort(canvas: CanvasState, workflow: Workflow, nodeId: string, name: string, direction: 'input' | 'output'): WorkflowPort | undefined {
  if (nodeId.startsWith('@boundary:')) return undefined
  if (!canvas.groups?.some(group => group.id === nodeId)) return { nodeId, portName: name, direction }
  return groupPorts(canvas, workflow, nodeId).find(port => groupPortId(port) === name && port.direction === direction)
}
export function createCanvasGroup(canvas: CanvasState, selected: ReadonlySet<string>, id: string, label: string): CanvasState {
  if (!selected.size) return canvas
  const scope = currentCanvasGroup(canvas)
  const existing = canvas.groups ?? []
  const childGroups = existing.filter(group => selected.has(group.id))
  if (childGroups.some(group => group.parentId !== scope)) throw new Error('只能组合当前层的节点。')
  const nodeIds = [...selected].filter(nodeId => !existing.some(group => group.id === nodeId))
  if (nodeIds.some(nodeId => visibleOwner(canvas, nodeId, scope) !== nodeId)) throw new Error('只能组合当前层的节点。')
  const points = [...selected].map(key => canvas.positions[key] ?? { x: 0, y: 0 })
  return { ...canvas, positions: { ...canvas.positions, [id]: { x: Math.min(...points.map(point => point.x)), y: Math.min(...points.map(point => point.y)) } }, groups: [
    ...existing.map(group => ({ ...group, parentId: selected.has(group.id) ? id : group.parentId, nodeIds: group.nodeIds.filter(nodeId => !selected.has(nodeId)) })),
    { id, label, parentId: scope, nodeIds, ports: [] },
  ] }
}
export function ungroupCanvas(canvas: CanvasState, id: string): CanvasState {
  const group = canvas.groups!.find(item => item.id === id)!
  const positions = { ...canvas.positions }; delete positions[id]
  return { ...canvas, positions, groups: canvas.groups!.filter(item => item.id !== id).map(item => ({ ...item, parentId: item.parentId === id ? group.parentId : item.parentId, nodeIds: item.id === group.parentId ? [...item.nodeIds, ...group.nodeIds] : item.nodeIds })), currentGroup: canvas.currentGroup === id ? group.parentId : canvas.currentGroup }
}
/** Apply visible drags without erasing hidden layout; a group translates all descendants. */
export function moveCanvasItems(canvas: CanvasState, updates: Record<string, Point>): CanvasState {
  const positions = { ...canvas.positions }
  for (const [id, point] of Object.entries(updates)) {
    const old = canvas.positions[id] ?? point
    const group = canvas.groups?.find(item => item.id === id)
    if (group) {
      const descendants = [...groupNodes(canvas, id), ...canvas.groups!.filter(item => groupPath(canvas, item.id).some(parent => parent.id === id) && item.id !== id).map(item => item.id)]
      for (const childId of descendants) if (positions[childId]) positions[childId] = { x: positions[childId].x + point.x - old.x, y: positions[childId].y + point.y - old.y }
    }
    positions[id] = point
  }
  return { ...canvas, positions }
}
export function cleanCanvasGroups(canvas: CanvasState, remainingNodeIds: ReadonlySet<string>, removedGroupIds: ReadonlySet<string> = new Set()): CanvasState {
  const groups = (canvas.groups ?? []).filter(group => !groupPath(canvas, group.id).some(parent => removedGroupIds.has(parent.id))).map(group => ({ ...group, nodeIds: group.nodeIds.filter(id => remainingNodeIds.has(id)), ports: group.ports.filter(port => remainingNodeIds.has(port.nodeId)) }))
  return { ...canvas, groups, currentGroup: groups.some(group => group.id === canvas.currentGroup) ? canvas.currentGroup : null }
}

/** One origin for group cards and leaf positions, including a group's internal whitespace. */
export function placeCanvasCopy(positions: Record<string, Point>, ids: ReadonlyMap<string, string>, destination: Point): Record<string, Point> {
  const points = [...ids.keys()].map(id => positions[id])
  const origin = { x: Math.min(...points.map(point => point.x)), y: Math.min(...points.map(point => point.y)) }
  return Object.fromEntries([...ids].map(([oldId, newId]) => [newId, { x: destination.x + positions[oldId].x - origin.x, y: destination.y + positions[oldId].y - origin.y }]))
}
