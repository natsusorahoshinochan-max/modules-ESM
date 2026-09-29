import { expect, test } from '@playwright/test'
import { placeCanvasCopy, createCanvasGroup, currentCanvasGroup, groupNodes, groupPorts, groupPortId, moveCanvasItems, resolveCanvasPort, selectedLeafNodes, ungroupCanvas, visibleOwner, type CanvasState } from '../src/canvas-groups'
import type { Workflow } from '../src/protocol/client'

const workflow: Workflow = { schema_version: '2.1.0', workflow_id: 'groups', nodes: ['a', 'b', 'c', 'target'].map(node_id => ({ node_id, node_type_id: 'test', binding_id: 'test', node_parameters: {}, binding_parameters: {} })), edges: [
  { source_node_id: 'a', source_port: 'value', target_node_id: 'target', target_port: 'values' },
  { source_node_id: 'b', source_port: 'value', target_node_id: 'target', target_port: 'values' },
  { source_node_id: 'c', source_port: 'value', target_node_id: 'target', target_port: 'values' },
], observation_selectors: [], selection_objectives: [] }
const initial: CanvasState = { positions: { a: { x: 10, y: 10 }, b: { x: 100, y: 10 }, c: { x: 200, y: 10 }, target: { x: 300, y: 10 } }, collapsed: [] }

test('nested grouping and ungrouping preserve direct members and hidden positions', () => {
  const first = createCanvasGroup(initial, new Set(['b', 'target']), 'inner', 'Inner')
  const nested = createCanvasGroup(first, new Set(['inner', 'a']), 'outer', 'Outer')
  expect([...groupNodes(nested, 'outer')].sort()).toEqual(['a', 'b', 'target'])
  expect(visibleOwner(nested, 'target')).toBe('outer')
  expect(visibleOwner(nested, 'target', 'outer')).toBe('inner')
  const moved = moveCanvasItems(nested, { outer: { x: 50, y: 50 } })
  expect(moved.positions.target).toEqual({ x: 340, y: 50 })
  expect(moved.positions.c).toEqual(initial.positions.c)
  const removed = ungroupCanvas(moved, 'outer')
  expect(removed.groups?.find(group => group.id === 'inner')?.parentId).toBeNull()
  expect(visibleOwner(removed, 'target')).toBe('inner')
  expect(visibleOwner(removed, 'a')).toBe('a')
  expect(removed.positions.target).toEqual(moved.positions.target)
})

test('one exact proxy retains interleaved internal/external ordered inputs', () => {
  const before = structuredClone(workflow)
  const canvas = createCanvasGroup(initial, new Set(['b', 'target']), 'group', 'Ordered')
  const ports = groupPorts(canvas, workflow, 'group')
  expect(ports).toEqual([{ nodeId: 'target', portName: 'values', direction: 'input' }])
  expect(resolveCanvasPort(canvas, workflow, 'group', groupPortId(ports[0]), 'input')).toEqual(ports[0])
  expect(workflow).toEqual(before)
  expect(workflow.edges.map(edge => edge.source_node_id)).toEqual(['a', 'b', 'c'])
  expect([...selectedLeafNodes(canvas, new Set(['group']))]).toEqual(['b', 'target'])
})

test('noncontiguous group can show both incoming and outgoing edges without changing the graph', () => {
  const chain = { ...workflow, edges: [
    { source_node_id: 'a', source_port: 'value', target_node_id: 'b', target_port: 'value' },
    { source_node_id: 'b', source_port: 'value', target_node_id: 'c', target_port: 'value' },
  ] }
  const canvas = createCanvasGroup(initial, new Set(['a', 'c']), 'group', 'Across')
  expect(groupPorts(canvas, chain, 'group').map(port => [port.direction, port.nodeId])).toEqual([['output', 'a'], ['input', 'c']])
  expect(visibleOwner(canvas, 'b')).toBe('b')
  expect(currentCanvasGroup({ ...canvas, currentGroup: 'missing' })).toBeNull()
})


test('copying groups retains whitespace and nested relative positions', () => {
  const positions = { outer: { x: 0, y: 0 }, inner: { x: 100, y: 50 }, leaf: { x: 180, y: 90 } }
  expect(placeCanvasCopy(positions, new Map([['outer', 'copy-outer'], ['inner', 'copy-inner'], ['leaf', 'copy-leaf']]), { x: 500, y: 300 })).toEqual({
    'copy-outer': { x: 500, y: 300 }, 'copy-inner': { x: 600, y: 350 }, 'copy-leaf': { x: 680, y: 390 },
  })
})

test('an explicitly exposed ancestor port traverses nested groups even without an external edge', () => {
  const inner = createCanvasGroup(initial, new Set(['target']), 'inner', 'Inner')
  const outer = createCanvasGroup(inner, new Set(['inner']), 'outer', 'Outer')
  const port = { nodeId: 'target', portName: 'values', direction: 'input' as const }
  const exposed = { ...outer, groups: outer.groups!.map(group => group.id === 'outer' ? { ...group, ports: [port] } : group) }
  expect(groupPorts(exposed, { ...workflow, edges: [] }, 'inner')).toEqual([port])
  expect(groupPorts(exposed, { ...workflow, edges: [] }, 'outer')).toEqual([port])
})
