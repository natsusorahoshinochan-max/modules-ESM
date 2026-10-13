import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { cleanCanvasGroups, copyCanvasGroup, groupPortId, resolveCanvasPort, visibleOwner } from '../src/canvas-groups'
import { createDefaultExampleCanvas, defaultStageLayout } from '../src/default-example-canvas'
import type { Workflow } from '../src/protocol/client'

const example = () => (JSON.parse(readFileSync('../examples/v2/webui-3gb1.example.json', 'utf8')) as { workflow: Workflow }).workflow

test('five default stages retain all 36 nodes, 61 scientific edges and 14 exact crossing edges', () => {
  const workflow = example(), before = structuredClone(workflow)
  const canvas = createDefaultExampleCanvas(workflow)
  expect(workflow.nodes).toHaveLength(36)
  expect(workflow.edges).toHaveLength(61)
  expect(canvas.groups?.map(group => group.nodeIds.length)).toEqual([4, 7, 11, 2, 11])
  expect(canvas.groups!.map(group => group.label)).toEqual(['模板 → Prompt', '生成候选与初筛', '首轮折叠与筛选', '设计序列', '末轮折叠与筛选'])
  expect(canvas.groups!.map(group => group.stage!.controls.map(control => control.kind === 'parameter' ? control.key : control.kind))).toEqual([
    ['prompt'], ['num_samples', 'k'], ['selection', 'k'], ['num_sequences'], ['selection', 'k'],
  ])
  const members = canvas.groups!.flatMap(group => group.nodeIds)
  expect(new Set(members).size).toBe(35)
  expect(workflow.nodes.filter(node => !members.includes(node.node_id)).map(node => node.node_id)).toEqual(['export-final'])
  const crossing = workflow.edges.filter(edge => visibleOwner(canvas, edge.source_node_id) !== visibleOwner(canvas, edge.target_node_id))
  expect(crossing).toHaveLength(14)
  for (const edge of crossing) {
    for (const direction of ['input', 'output'] as const) {
      const nodeId = direction === 'output' ? edge.source_node_id : edge.target_node_id
      const portName = direction === 'output' ? edge.source_port : edge.target_port
      const owner = visibleOwner(canvas, nodeId)!
      if (owner === nodeId) continue
      const port = { nodeId, portName, direction }
      expect(resolveCanvasPort(canvas, workflow, owner, groupPortId(port), direction)).toMatchObject(port)
      expect(canvas.groups!.find(group => group.id === owner)!.ports.find(candidate => groupPortId(candidate) === groupPortId(port))!.label).toBeTruthy()
    }
  }
  expect(workflow).toEqual(before)
})

test('overview is a six-card horizontal row at readable zoom and stage columns follow dependencies', () => {
  const workflow = example(), canvas = createDefaultExampleCanvas(workflow)
  const overviewIds = [...canvas.groups!.map(group => group.id), 'export-final']
  expect(overviewIds.map(id => canvas.positions[id])).toEqual(overviewIds.map((_, index) => ({ x: index * defaultStageLayout.cardStep, y: 0 })))
  expect(canvas.viewport).toEqual({ x: 32, y: 140, zoom: 1 })
  expect(canvas.views!.root).toEqual(canvas.viewport)
  for (const group of canvas.groups!) {
    expect(canvas.views![group.id]).toEqual({ x: 32 - canvas.positions[group.id].x, y: 140, zoom: 1 })
    for (const edge of workflow.edges.filter(edge => group.nodeIds.includes(edge.source_node_id) && group.nodeIds.includes(edge.target_node_id))) {
      expect(canvas.positions[edge.target_node_id].x).toBeGreaterThan(canvas.positions[edge.source_node_id].x)
    }
    for (const control of group.stage!.controls) {
      expect(group.nodeIds).toContain(control.nodeId)
      if (control.kind === 'parameter') expect(workflow.nodes.find(node => node.node_id === control.nodeId)!.node_parameters).toHaveProperty(control.key)
    }
  }
})

test('copied stage controls and exact ports reference only copied nodes and do not share metadata', () => {
  const canvas = createDefaultExampleCanvas(example()), original = canvas.groups![1]
  const nodes = new Map(original.nodeIds.map(id => [id, `${id}-copy`]))
  const copied = copyCanvasGroup(original, nodes, new Map([[original.id, 'stage-copy']]), null)
  expect(copied.id).toBe('stage-copy')
  expect(copied.label).toBe(`${original.label} 副本`)
  expect(copied.stage!.controls.map(control => control.nodeId)).toEqual(original.stage!.controls.map(control => nodes.get(control.nodeId)))
  expect(copied.ports.map(port => port.nodeId)).toEqual(original.ports.map(port => nodes.get(port.nodeId)))
  copied.stage!.controls[0].label = '独立标签'
  copied.ports[0].label = '独立端口'
  copied.nodeIds.push('extra')
  expect(original.stage!.controls[0].label).not.toBe('独立标签')
  expect(original.ports[0].label).not.toBe('独立端口')
  expect(original.nodeIds).not.toContain('extra')
  const fresh = createDefaultExampleCanvas(example())
  expect(fresh.groups![1]).toEqual(original)
})

test('deleting a referenced node removes its stage controls and exposed ports', () => {
  const workflow = example(), canvas = createDefaultExampleCanvas(workflow)
  const remaining = new Set(workflow.nodes.map(node => node.node_id).filter(id => id !== 'generate-paired'))
  const cleaned = cleanCanvasGroups(canvas, remaining)
  const stage = cleaned.groups!.find(group => group.id === 'stage-generate')!
  expect(stage.nodeIds).not.toContain('generate-paired')
  expect(stage.stage!.controls.some(control => control.nodeId === 'generate-paired')).toBe(false)
  expect(stage.ports.some(port => port.nodeId === 'generate-paired')).toBe(false)
  expect(stage.stage!.controls.map(control => control.nodeId)).toEqual(['take-top-four'])
})
