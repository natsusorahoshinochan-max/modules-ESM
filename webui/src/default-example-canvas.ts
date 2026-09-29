import type { Workflow } from './protocol/client'
import { groupPorts, type CanvasGroup, type CanvasState, type GroupPort, type Point } from './canvas-groups'

export const defaultStageLayout = { cardWidth: 360, cardStep: 440, columnStep: 340, rowStep: 380 } as const
const source = 'prompt-composition-webui-3gb1.source.'

/** Presentation only: exact membership in the shipped 3GB1 workflow. */
const stages: CanvasGroup[] = [
  {
    id: 'stage-input', label: '模板 → Prompt', parentId: null,
    nodeIds: [`${source}import_structure`, `${source}select_chains`, `${source}resolve_axis`, `${source}author`], ports: [],
    stage: { order: 1, description: '选择来源结构与链，编辑残基条件。', controls: [
      { kind: 'prompt', nodeId: `${source}author`, label: '编辑 ProteinPrompt' },
    ] },
  },
  {
    id: 'stage-generate', label: '生成候选与初筛', parentId: null,
    nodeIds: ['generate-paired', 'confidence-generated', 'rank-generated', 'take-top-four', 'relation-generated-structure-parent', 'relation-generated-pairs', 'select-paired-sequences'], ports: [],
    stage: { order: 2, description: '生成成对候选，评分后保留配对序列。', controls: [
      { kind: 'parameter', nodeId: 'generate-paired', key: 'num_samples', label: '生成数量' },
      { kind: 'parameter', nodeId: 'take-top-four', key: 'k', label: '初筛保留数量' },
    ] },
  },
  {
    id: 'stage-refold', label: '首轮折叠与筛选', parentId: null,
    nodeIds: ['fold-stage-one', 'confidence-stage-one', 'relation-stage-one-fold-parent', 'relation-stage-one', 'axes-stage-one', 'axes-generated-top-four', 'align-stage-one', 'tm-stage-one', 'scores-stage-one', 'rank-stage-one', 'take-top-two'], ports: [],
    stage: { order: 3, description: '回折序列，综合置信度与亲本结构相似度筛选。', controls: [
      { kind: 'selection', nodeId: 'rank-stage-one', label: '回折筛选规则' },
      { kind: 'parameter', nodeId: 'take-top-two', key: 'k', label: '骨架保留数量' },
    ] },
  },
  {
    id: 'stage-design', label: '设计序列', parentId: null,
    nodeIds: ['axes-top-two', 'design-children'], ports: [],
    stage: { order: 4, description: '依据筛选后的结构骨架设计子代序列。', controls: [
      { kind: 'parameter', nodeId: 'design-children', key: 'num_sequences', label: '每个骨架设计数量' },
    ] },
  },
  {
    id: 'stage-final', label: '末轮折叠与筛选', parentId: null,
    nodeIds: ['fold-final', 'confidence-final', 'relation-final-fold-parent', 'relation-design-parent', 'relation-final', 'axes-final', 'align-final', 'tm-final', 'scores-final', 'rank-final', 'take-top-three'], ports: [],
    stage: { order: 5, description: '回折设计序列，比较亲本结构并选出最终候选。', controls: [
      { kind: 'selection', nodeId: 'rank-final', label: '最终排序规则' },
      { kind: 'parameter', nodeId: 'take-top-three', key: 'k', label: '最终保留数量' },
    ] },
  },
]

const portLabels: Record<string, string> = {
  protein_prompt: 'ProteinPrompt 条件', sequence_candidates: '序列候选', structure_candidates: '结构候选',
  structure_residue_axes: '骨架残基轴', residue_axes: '结构残基轴', subject_residue_axes: '待比较残基轴', reference_residue_axes: '亲本残基轴',
  structure_source: '结构来源', subjects: '子代候选', parents: '亲本候选', references: '参考结构', structures: '最终结构',
  relation: '候选对应关系', right_relation: '亲本对应关系', candidates: '筛选候选',
}
function labelPort(port: GroupPort): GroupPort {
  const label = port.portName === 'candidates' && port.nodeId === 'select-paired-sequences' ? '配对序列' : portLabels[port.portName] ?? port.portName
  return { ...port, label }
}

/** Lay out each stage by internal dependencies; no graph or edge is rewritten. */
function stagePositions(group: CanvasGroup, workflow: Workflow, origin: Point): Record<string, Point> {
  const members = new Set(group.nodeIds)
  const columns = new Map<string, number>()
  const visiting = new Set<string>()
  const column = (id: string): number => {
    const known = columns.get(id)
    if (known !== undefined) return known
    if (visiting.has(id)) throw new Error('Default example stage contains a dependency cycle')
    visiting.add(id)
    const parents = workflow.edges.filter(edge => edge.target_node_id === id && members.has(edge.source_node_id))
    const depth = parents.length ? Math.max(...parents.map(edge => column(edge.source_node_id) + 1)) : 0
    visiting.delete(id); columns.set(id, depth)
    return depth
  }
  const rows = new Map<number, number>()
  return Object.fromEntries(group.nodeIds.map(id => {
    const depth = column(id), row = rows.get(depth) ?? 0
    rows.set(depth, row + 1)
    return [id, { x: origin.x + depth * defaultStageLayout.columnStep, y: origin.y + row * defaultStageLayout.rowStep }]
  }))
}

export function createDefaultExampleCanvas(workflow: Workflow): CanvasState {
  const expected = new Set([...stages.flatMap(group => group.nodeIds), 'export-final'])
  if (workflow.nodes.length !== expected.size || workflow.nodes.some(node => !expected.has(node.node_id))) throw new Error('Default stage layout requires the shipped 3GB1 workflow nodes')
  const groups = structuredClone(stages)
  const viewport = { x: 32, y: 140, zoom: 1 }
  const canvas: CanvasState = { positions: {}, collapsed: [], groups, currentGroup: null, viewport, views: { root: { ...viewport } }, selections: {} }
  for (const [index, group] of groups.entries()) {
    const origin = { x: index * defaultStageLayout.cardStep, y: 0 }
    canvas.positions[group.id] = origin
    Object.assign(canvas.positions, stagePositions(group, workflow, origin))
    canvas.views![group.id] = { x: 32 - origin.x, y: 140, zoom: 1 }
    group.ports = groupPorts(canvas, workflow, group.id).map(labelPort)
  }
  canvas.positions['export-final'] = { x: groups.length * defaultStageLayout.cardStep, y: 0 }
  return canvas
}
