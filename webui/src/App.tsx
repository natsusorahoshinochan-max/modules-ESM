import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import * as ContextMenu from '@radix-ui/react-context-menu'
import { GroupInterfaceEditor } from './GroupInterfaceEditor'
import { InteractionDialog } from './InteractionDialog'
import { placeCanvasCopy, copyCanvasGroup, currentCanvasGroup, emptyCanvas, groupNodes, groupPath, groupPorts, groupPortId, visibleOwner, resolveCanvasPort, selectedLeafNodes, createCanvasGroup, ungroupCanvas, moveCanvasItems, cleanCanvasGroups, type CanvasState, type CanvasGroup } from './canvas-groups'
import { Background, BackgroundVariant, Controls, MiniMap, Panel, ReactFlow, applyEdgeChanges, applyNodeChanges, type Connection, type Edge, type EdgeChange, type Node, type NodeChange, type NodeProps, type ReactFlowInstance } from '@xyflow/react'
import { Activity, Atom, Braces, Check, ChevronDown, ChevronRight, CircleHelp, FolderOpen, Info, Layers3, LoaderCircle, Network, PanelLeftClose, Play, Plus, RotateCcw, Search, X } from 'lucide-react'
import { PromptStudio } from './PromptStudio'
import { InputSourceDialog } from './InputSourceDialog'
import type { CandidateInputPlan, PromptSourcePlan } from './input-sources'
import { ProjectWorkspaceDialog } from './ProjectWorkspaceDialog'
import { workspaceErrorMessage, type ProjectWorkspace, type WorkflowVersionView } from './project-workspace'
import { PublicV2Client, promptAuthorDocumentParameter, promptAuthorNodeTypeId, type AuthoringCapabilities, type CatalogSnapshot, type NodeDisposition, type ProjectMetadata, type PromptAuthoringDocument, type PromptSnapshot, type RunProjection, type RunScope, type RunStatus, type Workflow, type WorkflowDraft, type JsonObject } from './protocol/client'
import { RunDialog } from './RunDialog'
import { RunDiagnostics } from './RunDiagnostics'
import { ResultsWorkbench, type ResultsViewStateStore } from './ResultsWorkbench'
import { PublishedResults } from './published-results'
import { locationKey, type ResultCollection } from './result-explorer'
import type { ResultLocation } from './protocol/client'
import { WorkspaceEditor, type WorkspaceEditSession } from './workspace-editor'
import { WorkflowPorts, type PortSource } from './WorkflowPorts'
import { connectWorkflowPorts, reconnectWorkflowPorts, deleteWorkflowElements as deleteGraphElements, workflowEdgeId, workflowPortsMatch, PromptMergeSourcesLockedError } from './workflow-connections'
import { WorkflowParameters } from './WorkflowParameters'
import { loadWorkflowParameterChoices, type NodeParameterChoices, type WorkflowParameterChoices } from './parameter-choices'
import { loadNodeEditor, nodeEditor, type ModuleEditorProps, type ModuleUiManifest } from './module-ui'
import { CanvasOperationPicker } from './CanvasOperationPicker'
import { copyWorkflowFragment, pasteWorkflowFragment, type WorkflowFragment } from './workflow-fragments'
import { bindingOptions, insertOrdinaryNode, missingNodeContracts, missingPortPresentation, nodeTypePresentation, parameterPresentations, projectPalette, selectNodeBinding, type BindingOption, type PaletteTaxonomy, type ParameterPresentation, type PortPresentation } from './workflow-authoring'

const client = new PublicV2Client()
type Parameter = ParameterPresentation & { suffix?: string }
type NodeRunStatus = 'waiting' | 'running' | 'succeeded' | 'failed' | 'blocked' | 'cancelled' | 'interrupted' | 'outside' | 'reused'
type NodeRunState = { status: NodeRunStatus; blockedBy?: string[]; resolution?: 'executed' | 'cache_replayed' }
type StageControlView = { kind: 'parameter'; nodeId: string; parameter: Parameter; choices?: NodeParameterChoices } | { kind: 'prompt' | 'selection'; nodeId: string; label: string }
type StageState = { status: NodeRunStatus | 'idle'; label: string; completed: number; total: number }
type WorkflowNodeData = Record<string, unknown> & { missingContracts?: string[]; retainedConfiguration?: JsonObject; readOnly?: boolean; resultCollections?: ResultCollection[]; onOpenResult?: (source: ResultLocation) => void; kind: 'prompt' | 'ordinary' | 'group' | 'boundary'; stage?: CanvasGroup['stage']; stageControls?: StageControlView[]; stageState?: StageState; onStageAction?: (kind: 'prompt' | 'selection', nodeId: string) => void; onEnter?: () => void; onRename?: (label: string) => void; groupErrors?: number; onFocusError?: () => void; eyebrow: string; title: string; subtitle: string; index: string; inputs: PortPresentation[]; outputs: PortPresentation[]; sources: Record<string, PortSource[]>; parameters: Parameter[]; parameterChoices?: NodeParameterChoices; accent: string; count: string; sourceNodeId: string; bindingId?: string; bindingOptions?: BindingOption[]; collapsed?: boolean; runState?: NodeRunState; scopeState?: 'execute' | 'reuse'; onToggle?: (id: string) => void; onEditPrompt?: () => void; moduleEditorTitle?: string; onEditModule?: () => void; onParameter?: (id: string, parameter: Parameter, value: string, commit: boolean) => void; onCancelParameter?: (nodeId: string, parameter: Parameter) => void; onBinding?: (nodeId: string, bindingId: string) => void }
type FlowNode = Node<WorkflowNodeData>
type RunProgress = { status: RunStatus; totalNodes: number; completedNodeIds: string[]; nodeStates: Record<string, NodeRunState>; currentNodeId?: string; projectId?: string; runId?: string; }
type PendingNodeDrop = { nodeTypeId: string; position: { x: number; y: number }; bindings: BindingOption[]; connectionFrom?: { nodeId: string; portName: string }; connectionPort?: string }

const categoryColors: Record<string, string> = { generation: '#55c8b7', selection: '#e7b75f', structure_comparison: '#71a8ff', structure_prediction: '#71a8ff', collection_ops: '#92a79a', prompt_authoring: '#ae9cff' }

function defaultNodePosition(index: number) { return { x: 60 + index % 5 * 320, y: 100 + Math.floor(index / 5) * 500 } }

function canvasFromUi(uiState: JsonObject): CanvasState {
  return uiState.canvas as CanvasState | undefined ?? emptyCanvas
}

function canvasFromNodes(flowNodes: FlowNode[], previous: CanvasState): CanvasState {
  return {
    ...previous,
    ...moveCanvasItems(previous, Object.fromEntries(flowNodes.filter(node => node.data.kind !== 'boundary').map((node) => [node.id, node.position]))),
    collapsed: [...previous.collapsed.filter(id => !flowNodes.some(node => node.id === id)), ...flowNodes.filter((node) => node.data.collapsed).map((node) => node.id)],
  }
}

function nodeParameters(stepId: string, workflow: Workflow, catalog?: CatalogSnapshot): Parameter[] {
  const node = workflow.nodes.find((item) => item.node_id === stepId)
  if (!node || !catalog) return []
  const presentations = parameterPresentations(catalog, node)
  if (node.node_type_id !== promptAuthorNodeTypeId) return presentations
  return presentations.filter((parameter) => parameter.scope !== 'node' || parameter.key !== promptAuthorDocumentParameter)
}

function parameterInputValue(raw: string, valueType: string): unknown {
  if (valueType === 'integer' || valueType === 'number') {
    const value = Number(raw)
    if (raw.trim() === '' || !Number.isFinite(value) || valueType === 'integer' && !Number.isInteger(value)) throw new Error('请完成有效的数字输入后继续。')
    return value
  }
  if (valueType === 'boolean') return raw === 'true'
  if (valueType === 'array' || valueType === 'object') return JSON.parse(raw)
  return raw
}

function flowFromDraft(draft: WorkflowDraft, catalog?: CatalogSnapshot, stored: CanvasState = emptyCanvas, positionOverrides: Record<string, { x: number; y: number }> = {}): { nodes: FlowNode[]; edges: Edge[] } {
  if (!catalog) return { nodes: [], edges: [] }
  const nodes = draft.workflow.nodes.map((node, index): FlowNode => {
    const presentation = nodeTypePresentation(catalog, node.node_type_id)
    const missingContracts = missingNodeContracts(catalog, node)
    if (presentation.missing) {
      const endpoints = [
        ...draft.workflow.edges.flatMap(edge => [
          ...(edge.source_node_id === node.node_id ? [{ direction: 'output', name: edge.source_port }] : []),
          ...(edge.target_node_id === node.node_id ? [{ direction: 'input', name: edge.target_port }] : []),
        ]),
        ...(stored.groups ?? []).flatMap(group => group.ports.filter(port => port.nodeId === node.node_id).map(port => ({ direction: port.direction, name: port.portName }))),
      ]
      presentation.inputs = [...new Set(endpoints.filter(port => port.direction === 'input').map(port => port.name))].map(missingPortPresentation)
      presentation.outputs = [...new Set(endpoints.filter(port => port.direction === 'output').map(port => port.name))].map(missingPortPresentation)
    }
    return { id: node.node_id, type: 'workflow', position: positionOverrides[node.node_id] ?? stored.positions[node.node_id] ?? defaultNodePosition(index), data: { missingContracts, retainedConfiguration: { node_parameters: node.node_parameters, binding_parameters: node.binding_parameters }, kind: node.node_type_id === promptAuthorNodeTypeId ? 'prompt' : 'ordinary', eyebrow: presentation.category.toUpperCase(), title: presentation.title, subtitle: node.node_type_id, index: String(index + 1).padStart(2, '0'), inputs: presentation.inputs, outputs: presentation.outputs, sources: Object.fromEntries(presentation.inputs.map(port => [port.name, draft.workflow.edges.filter(edge => edge.target_node_id === node.node_id && edge.target_port === port.name).map(edge => ({ nodeId: edge.source_node_id, outputPort: edge.source_port }))])), parameters: nodeParameters(node.node_id, draft.workflow, catalog), accent: categoryColors[presentation.category] ?? '#9aa69b', count: '', sourceNodeId: node.node_id, bindingId: node.binding_id, collapsed: stored.collapsed.includes(node.node_id) } }
  })
  const edges = draft.workflow.edges.map((edge): Edge => ({ id: workflowEdgeId(edge), data: { workflowEdge: edge }, reconnectable: !stored.collapsed.includes(edge.source_node_id) && !stored.collapsed.includes(edge.target_node_id), source: edge.source_node_id, sourceHandle: `out-${edge.source_port}`, target: edge.target_node_id, targetHandle: `in-${edge.target_port}`, type: 'default', style: { stroke: '#637168', strokeWidth: 1.6 } }))
  const scope = currentCanvasGroup(stored)
  const visibleNodes = nodes.filter(node => visibleOwner(stored, node.id, scope) === node.id)
  const portPresentation = (port: { nodeId: string; portName: string; direction: 'input' | 'output'; label?: string }): PortPresentation => {
    const node = nodes.find(item => item.id === port.nodeId)!
    const original = (port.direction === 'input' ? node.data.inputs : node.data.outputs).find(item => item.name === port.portName)!
    return { ...original, name: groupPortId(port), label: port.label ?? `${node.data.title} · ${port.portName}`, meaning: `${port.nodeId} · ${port.portName} — ${original.meaning}` }
  }
  for (const group of stored.groups ?? []) if (group.parentId === scope) {
    const ports = groupPorts(stored, draft.workflow, group.id)
    visibleNodes.push({ id: group.id, type: 'workflow', position: stored.positions[group.id] ?? { x: 80, y: 80 }, data: { kind: 'group', stage: group.stage, eyebrow: 'NODE GROUP', title: group.label, subtitle: `${groupNodes(stored, group.id).size} 个节点 · 独立副本`, index: '', inputs: ports.filter(port => port.direction === 'input').map(portPresentation), outputs: ports.filter(port => port.direction === 'output').map(portPresentation), sources: Object.fromEntries(ports.filter(port => port.direction === 'input').map(port => [groupPortId(port), draft.workflow.edges.filter(edge => edge.target_node_id === port.nodeId && edge.target_port === port.portName).map(edge => ({ nodeId: edge.source_node_id, outputPort: edge.source_port, internal: groupNodes(stored, group.id).has(edge.source_node_id) }))])), parameters: [], accent: '#b79cec', count: '', sourceNodeId: group.id } })
  }
  if (scope) {
    const ports = groupPorts(stored, draft.workflow, scope)
    const left = Math.min(...visibleNodes.map(node => node.position.x), 100)
    const right = Math.max(...visibleNodes.map(node => node.position.x), 500)
    for (const direction of ['input', 'output'] as const) visibleNodes.push({ id: `@boundary:${direction}:${scope}`, type: 'workflow', position: { x: direction === 'input' ? left - 350 : right + 350, y: 80 }, draggable: false, selectable: false, data: { kind: 'boundary', eyebrow: 'GROUP INTERFACE', title: direction === 'input' ? 'Group Input' : 'Group Output', subtitle: '精确端口映射', index: '', inputs: direction === 'output' ? ports.filter(port => port.direction === direction).map(portPresentation) : [], outputs: direction === 'input' ? ports.filter(port => port.direction === direction).map(portPresentation) : [], sources: {}, parameters: [], accent: '#b79cec', count: '', sourceNodeId: scope } })
  }
  const visibleEdges: Edge[] = []
  for (const edge of draft.workflow.edges) {
    const sourceOwner = visibleOwner(stored, edge.source_node_id, scope), targetOwner = visibleOwner(stored, edge.target_node_id, scope)
    if ((!sourceOwner && !targetOwner) || (sourceOwner === targetOwner && sourceOwner !== edge.source_node_id)) continue
    const sourcePort = { nodeId: edge.source_node_id, portName: edge.source_port, direction: 'output' as const }
    const targetPort = { nodeId: edge.target_node_id, portName: edge.target_port, direction: 'input' as const }
    const boundary = !sourceOwner || !targetOwner
    if (boundary) continue
    const original = edges.find(item => item.id === workflowEdgeId(edge))!
    const ordered = draft.workflow.edges.filter(item => item.target_node_id === edge.target_node_id && item.target_port === edge.target_port)
    visibleEdges.push({ ...original, source: sourceOwner ?? `@boundary:input:${scope}`, target: targetOwner ?? `@boundary:output:${scope}`, sourceHandle: `out-${!sourceOwner ? groupPortId(targetPort) : sourceOwner === edge.source_node_id ? edge.source_port : groupPortId(sourcePort)}`, targetHandle: `in-${!targetOwner ? groupPortId(sourcePort) : targetOwner === edge.target_node_id ? edge.target_port : groupPortId(targetPort)}`, reconnectable: !stored.collapsed.includes(sourceOwner) && !stored.collapsed.includes(targetOwner), selectable: true, label: ordered.length > 1 ? `#${ordered.indexOf(edge) + 1}` : undefined, ...(boundary ? { style: { stroke: '#9b88ad', strokeDasharray: '4 4' } } : {}) })
  }
  if (scope) for (const port of groupPorts(stored, draft.workflow, scope)) {
    const owner = visibleOwner(stored, port.nodeId, scope)!
    const id = groupPortId(port)
    const leafHandle = owner === port.nodeId ? port.portName : id
    visibleEdges.push({ id: `@mapping:${scope}:${id}`, source: port.direction === 'input' ? `@boundary:input:${scope}` : owner, target: port.direction === 'input' ? owner : `@boundary:output:${scope}`, sourceHandle: `out-${port.direction === 'input' ? id : leafHandle}`, targetHandle: `in-${port.direction === 'input' ? leafHandle : id}`, selectable: false, reconnectable: false, style: { stroke: '#9b88ad', strokeDasharray: '4 4' } })
  }
  return { nodes: visibleNodes, edges: visibleEdges }
}

function nodeRunStateFromDisposition(disposition: NodeDisposition): NodeRunState {
  if (disposition.outcome === 'succeeded') return { status: 'succeeded', resolution: disposition.resolution }
  if (disposition.outcome === 'blocked') return { status: 'blocked', blockedBy: disposition.blocked_by }
  return { status: disposition.outcome }
}

function nodeStatesFromProjection(projection: RunProjection, workflowNodeIds: string[] = []): Record<string, NodeRunState> {
  return Object.fromEntries([
    ...workflowNodeIds.map((nodeId): [string, NodeRunState] => [nodeId, { status: projection.scope.execution_node_ids.includes(nodeId) ? 'waiting' : projection.scope.reused_node_ids.includes(nodeId) ? 'reused' : 'outside' }]),
    ...projection.node_dispositions.map((disposition): [string, NodeRunState] => [disposition.node_id, projection.scope.reused_node_ids.includes(disposition.node_id) ? { status: 'reused' } : nodeRunStateFromDisposition(disposition)]),
  ])
}

function NodeResultLinks({ data }: { data: WorkflowNodeData }) {
  if (!data.resultCollections?.length) return null
  return <details className="node-results nodrag nowheel"><summary aria-label={`查看 ${data.title} 的已发布输出`}>查看输出 <span>{data.resultCollections.length} 个集合</span></summary><div>{data.resultCollections.map(collection => <button key={locationKey(collection.source)} onClick={() => data.onOpenResult?.(collection.source)}><span><strong>{collection.source.node_id}</strong><small>{collection.source.output_port} · 值 {collection.source.value_index + 1}</small></span><b>{collection.total}</b><ChevronRight size={13} /></button>)}</div></details>
}

function WorkflowCard({ id, data, selected }: NodeProps<FlowNode>) {
  const [renaming, setRenaming] = useState(false)
  const Icon = data.kind === 'prompt' ? Braces : Atom
  if (data.kind === 'group' || data.kind === 'boundary') return <article className={`workflow-node canvas-group-node ${data.stage ? 'stage-group-node' : ''} ${selected ? 'is-selected' : ''}`} style={{ '--node-accent': data.accent } as React.CSSProperties}>
    <header className="node-header"><Layers3 size={16} /><strong>{data.stage && <span className="stage-number">{String(data.stage.order).padStart(2, '0')} </span>}{data.title}</strong>{data.kind === 'group' && <button className="nodrag" onClick={data.onEnter} aria-label={`进入组 ${data.title}`}>进入 ↵</button>}</header>
    {data.stage && <p className="stage-description">{data.stage.description}</p>}
    <div className="node-meta"><span>{data.subtitle}</span>{data.kind === 'group' && <button className="nodrag group-rename" disabled={data.readOnly} aria-label={`重命名节点组 ${data.title}`} onClick={() => setRenaming(true)}>重命名</button>}</div>
    {renaming && <input autoFocus className="nodrag" aria-label="节点组名称" defaultValue={data.title} key={data.title} onBlur={event => { if (event.target.value.trim() && event.target.value.trim() !== data.title) data.onRename?.(event.target.value.trim()); setRenaming(false) }} onKeyDown={event => { if (event.nativeEvent.isComposing) return; if (event.key === 'Enter') event.currentTarget.blur(); if (event.key === 'Escape') { event.stopPropagation(); event.currentTarget.value = data.title; event.currentTarget.blur() } }} />}
    {data.stageState && <div className={`stage-status status-${data.stageState.status}`} aria-label={`${data.title}阶段状态`}><span>{data.stageState.label}</span><small>{data.stageState.completed} / {data.stageState.total} 个节点完成</small></div>}
    {!!data.stageControls?.length && <section inert={data.readOnly} className="stage-controls nodrag nowheel" aria-label={`${data.title}常用设置`}>{data.stageControls.map(control => control.kind === 'parameter' ? <div className="stage-control-parameter" key={`${control.nodeId}:${control.parameter.scope}:${control.parameter.key}`}><WorkflowParameters initiallyOpen parameters={[control.parameter]} choices={control.choices?.choices} onCancel={parameter => data.onCancelParameter?.(control.nodeId, parameter)} onParameter={(parameter, raw, commit) => data.onParameter?.(control.nodeId, parameter, raw, commit)} /></div> : <button className="stage-editor-button" key={`${control.kind}:${control.nodeId}`} onClick={() => data.onStageAction?.(control.kind, control.nodeId)}>{control.kind === 'prompt' ? <Braces size={14} /> : <Layers3 size={14} />}{control.label}<ChevronRight size={14} /></button>)}</section>}
    <WorkflowPorts nodeId={id} inputs={data.inputs} outputs={data.outputs} sources={data.sources} collapsed={false} prompt={false} readOnly={data.readOnly || data.kind === 'boundary'} />
    {data.kind === 'group' && <NodeResultLinks data={data} />}
    {!!data.groupErrors && <button className="nodrag" onClick={data.onFocusError}>{data.groupErrors} 个节点有错误 · 定位</button>}
    {data.kind === 'group' && <small>Tab 进入 · 组内编辑完整流程</small>}
  </article>
  const runStatusLabel: Record<NodeRunStatus, string> = { waiting: '等待', running: '运行中', succeeded: '成功', failed: '失败', blocked: '未执行', cancelled: '已取消', interrupted: '已中断', outside: '范围外', reused: '仅复用' }
  return <article className={`workflow-node ${selected ? 'is-selected' : ''} ${data.collapsed ? 'is-collapsed' : ''} ${data.runState ? `run-status-${data.runState.status}` : ''} ${data.scopeState ? `scope-${data.scopeState}` : ''}`} style={{ '--node-accent': data.accent } as React.CSSProperties}>
    <header className="node-header"><span className="node-icon"><Icon size={15} /></span><div><span className="node-eyebrow">{data.eyebrow}</span><details className="node-title-details nodrag"><summary><h3 title={data.title}>{data.title}</h3></summary><div><strong>{data.title}</strong><code>{data.sourceNodeId}</code></div></details></div>{data.runState ? <span className={`node-run-status ${data.runState.status}`} aria-label={`${data.title}：${runStatusLabel[data.runState.status]}`}>{data.runState.status === 'running' ? <LoaderCircle size={11} /> : data.runState.status === 'succeeded' ? <Check size={11} /> : data.runState.status === 'failed' ? <X size={11} /> : <span />}{runStatusLabel[data.runState.status]}</span> : <span className="node-run-status" />}<span className="node-index">{data.index}</span><button className="icon-button nodrag" aria-label={`${data.collapsed ? '展开' : '折叠'}节点 ${data.title}`} aria-expanded={!data.collapsed} onClick={() => data.onToggle?.(id)}><ChevronDown size={15} /></button></header>
    {!!data.missingContracts?.length && <p className="parameter-empty-hint" role="status">缺失模块：{data.missingContracts.join('、')}。已保留配置；安装并启用兼容模块后重新打开项目。</p>}
    {!data.collapsed && <><div className="node-meta">{data.bindingOptions && (data.bindingOptions.length > 1 || !!data.missingContracts?.length && data.bindingOptions.length > 0) ? <select disabled={data.readOnly} className="node-binding-select nodrag" aria-label={`${data.title}的执行模型`} value={data.bindingId} onChange={(event) => data.onBinding?.(data.sourceNodeId, event.target.value)}>{!data.bindingOptions.some(option => option.id === data.bindingId) && <option value={data.bindingId}>{data.bindingId}（缺失）</option>}{data.bindingOptions.map((option) => <option value={option.id} key={option.id} title={option.availabilityReason?.message}>{option.label}{option.available ? '' : '（不可用）'}</option>)}</select> : <span>{data.bindingOptions?.find((option) => option.id === data.bindingId)?.label ?? data.subtitle}{data.bindingOptions?.some((option) => option.id === data.bindingId && !option.available) ? '（不可用）' : ''}</span>}<strong>{data.count}</strong></div></>}
    <WorkflowPorts nodeId={id} inputs={data.inputs} outputs={data.outputs} sources={data.sources} collapsed={!!data.collapsed} prompt={data.kind === 'prompt'} readOnly={data.readOnly} />
    <NodeResultLinks data={data} />
    {!data.collapsed && <>
      {data.bindingOptions?.find((option) => option.id === data.bindingId)?.availabilityReason?.message && <p className="parameter-empty-hint">{data.bindingOptions.find((option) => option.id === data.bindingId)!.availabilityReason!.message}</p>}
      {data.missingContracts?.length ? <details className="nodrag nowheel"><summary>已保留配置</summary><pre>{JSON.stringify(data.retainedConfiguration, null, 2)}</pre></details> : data.kind === 'prompt' ? <button className="prompt-edit-button nodrag" disabled={data.readOnly} onClick={data.onEditPrompt}><Braces size={14} /> 打开 Prompt Studio <ChevronRight size={14} /></button> : data.onEditModule ? <button className="prompt-edit-button nodrag" disabled={data.readOnly} onClick={data.onEditModule}>{data.moduleEditorTitle} <ChevronRight size={14} /></button> : <><div inert={data.readOnly}><WorkflowParameters onCancel={parameter => data.onCancelParameter?.(data.sourceNodeId, parameter)} parameters={data.parameters} choices={data.parameterChoices?.choices} onParameter={(parameter, raw, commit) => data.onParameter?.(data.sourceNodeId, parameter, raw, commit)} /></div>{data.parameterChoices?.source && <small className="parameter-description">选项来源：{data.parameterChoices.source}</small>}{data.parameterChoices?.notice && <p className="parameter-empty-hint" role="status">{data.parameterChoices.notice}</p>}</>}
    </>}
  </article>
}

function runProgressTitle(status: RunProgress['status']) {
  if (status === 'admitted') return '正在启动'
  if (status === 'running') return '正在运行'
  if (status === 'succeeded') return '运行完成'
  if (status === 'failed') return '运行失败'
  if (status === 'cancelled') return '运行已取消'
  return '运行已中断'
}

function RunProgressBar({ progress, nodeTitle, resultsLoading, resultsAvailable, onResults, onCancel }: { progress: RunProgress; nodeTitle: string; resultsLoading: boolean; resultsAvailable: boolean; onResults: () => void; onCancel: () => void }) {
  const terminal = ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(progress.status)
  const percent = progress.totalNodes === 0 ? 0 : Math.round(progress.completedNodeIds.length / progress.totalNodes * 100)
  const stage = progress.status === 'admitted' ? '已接纳，等待执行开始' : progress.currentNodeId ? nodeTitle : progress.status === 'running' ? '等待下一个 Node Instance' : progress.status === 'succeeded' && resultsLoading ? '加载 Run 结果' : 'Run Closure'
  return <section className={`run-progress-bar ${terminal ? 'terminal' : 'active'} status-${progress.status}`} role="status" aria-live="polite">
    <span className="run-progress-icon">{terminal && progress.status === 'succeeded' ? <Check size={15} /> : terminal ? <Info size={15} /> : <LoaderCircle size={16} />}</span>
    <div className="run-progress-state"><span className="page-kicker">LIVE RUN</span><strong>{progress.status === 'succeeded' && resultsLoading ? '运行完成 · 正在加载结果' : runProgressTitle(progress.status)}</strong></div>
    <div className="run-progress-stage"><span>当前阶段</span><strong>{stage}</strong>{progress.currentNodeId && <code>{progress.currentNodeId}</code>}</div>
    <div className="run-progress-meter" role="progressbar" aria-label="Run Node 进度" aria-valuemin={0} aria-valuemax={progress.totalNodes} aria-valuenow={progress.completedNodeIds.length}><div><span style={{ width: `${percent}%` }} /></div><small>{progress.completedNodeIds.length} / {progress.totalNodes} Nodes · {percent}%</small></div>
    {progress.runId && <code className="run-progress-id">{progress.runId}</code>}
    {!terminal && <button className="secondary-button" onClick={onCancel}>取消整次运行</button>}
    {resultsAvailable && <button className="secondary-button" onClick={onResults}>查看结果</button>}
  </section>
}

function App() {
  const [catalog, setCatalog] = useState<CatalogSnapshot>()
  const [capabilities, setCapabilities] = useState<AuthoringCapabilities>()
  const [editor] = useState(() => new WorkspaceEditor(client))
  const editing = useSyncExternalStore(editor.subscribe, editor.getSnapshot)
  const project = editing.project
  const workspace = editing.acknowledged
  const viewedVersion = editing.version
  const draft = useMemo<WorkflowDraft | undefined>(() => editing.desired && project ? { project_id: project.id, draft_revision: workspace?.draft?.draft_revision ?? 0, workflow: editing.desired.workflow } : undefined, [editing.desired, project, workspace?.draft?.draft_revision])
  const [scienceStatus, setScienceStatus] = useState<'current' | 'stale' | 'unknown'>('unknown')
  const [results] = useState(() => new PublishedResults(client))
  const [resultsViewStateStore] = useState<ResultsViewStateStore>(() => new Map())
  const resultSnapshot = useSyncExternalStore(results.subscribe, results.getSnapshot)
  const { run, index: resultIndex } = resultSnapshot
  const resultsLoading = resultSnapshot.phase === 'loading'
  const resultLoadError = resultSnapshot.phase === 'error' ? workspaceErrorMessage(resultSnapshot.error) : ''
  const resultsAvailable = !!run && (run.outputs.length > 0 || run.artifact_index.length > 0)
  // Reading an immutable Run does not save or fork the editable workspace.
  const resultsIdentity = run && project ? `${run.project_id}/${run.run_id}` : undefined
  const runProgress = useMemo<RunProgress | undefined>(() => {
    if (!run) return undefined
    const nodeStates = nodeStatesFromProjection(run, draft?.workflow.nodes.map((node) => node.node_id))
    if (resultSnapshot.currentNodeId) nodeStates[resultSnapshot.currentNodeId] = { status: 'running' }
    return { status: run.status, totalNodes: run.scope.execution_node_ids.length,
      completedNodeIds: run.node_dispositions.filter((item) => run.scope.execution_node_ids.includes(item.node_id)).map((item) => item.node_id),
      nodeStates, currentNodeId: resultSnapshot.currentNodeId, projectId: run.project_id, runId: run.run_id }
  }, [run, draft?.workflow.nodes, resultSnapshot.currentNodeId])
  const [nodes, setNodes] = useState<FlowNode[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [prompt, setPrompt] = useState<{ nodeId: string; snapshot: PromptSnapshot; workflow: Workflow; session: WorkspaceEditSession }>()
  const [promptOpenError, setPromptOpenError] = useState<{ nodeId: string; message: string }>()
  const promptOpenRevision = useRef(0)
  const promptReturnFocus = useRef<HTMLElement | null>(null)
  const [inputSource, setInputSource] = useState<{ projectId: string; workflow: Workflow; session: WorkspaceEditSession; mergeTargetNodeId?: string }>()
  const mergeSourceCompletion = useRef<((snapshot: PromptSnapshot | undefined) => void) | undefined>(undefined)
  const [moduleUi, setModuleUi] = useState<ModuleUiManifest>({ extensions: [] })
  const moduleOpenRevision = useRef(0)
  const [moduleEdit, setModuleEdit] = useState<{ nodeId: string; title: string; Component: React.ComponentType<ModuleEditorProps>; workflow: Workflow; session: WorkspaceEditSession }>()
  const [parameterChoices, setParameterChoices] = useState<{ workflow: Workflow; values: WorkflowParameterChoices }>()
  const [parameterChoicesError, setParameterChoicesError] = useState('')
  const [view, setView] = useState<'workflow' | 'results'>('workflow')
  const [requestedResultSource, setRequestedResultSource] = useState<ResultLocation & { requestId: number }>()
  const resultRequestSequence = useRef(0)
  const [pendingCanvasFocus, setPendingCanvasFocus] = useState<string[]>()
  const [visitedResults, setVisitedResults] = useState<Set<string>>(() => new Set())
  const [scopePreview, setScopePreview] = useState<RunScope>()
  const [runError, setRunError] = useState('')
  const [runOpen, setRunOpen] = useState(false)
  const [projectsOpen, setProjectsOpen] = useState(false)
  const [unsavedChoice, setUnsavedChoice] = useState<{ mode: 'leave' | 'run'; resolve: (proceed: boolean) => void }>()
  const [choiceBusy, setChoiceBusy] = useState(false)
  const [choiceError, setChoiceError] = useState('')
  const [canvasPicker, setCanvasPicker] = useState<{ x: number; y: number; from?: { nodeId: string; portName: string; portTypeId: string; multiplicity: 'one' | 'many' } }>()
  const clipboard = useRef<{ fragment: WorkflowFragment; canvas: CanvasState; selected: string[] } | undefined>(undefined)
  const canvasPointer = useRef({ x: 500, y: 350 })
  const reconnectGesture = useRef(false)
  const [rawEditCount, setRawEditCount] = useState(0)
  const [search, setSearch] = useState('')
  const [paletteTaxonomy, setPaletteTaxonomy] = useState<PaletteTaxonomy>('purpose')
  const [pendingNodeDrop, setPendingNodeDrop] = useState<PendingNodeDrop>()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [inputError, setInputError] = useState('')
  const [blockedMergeNodes, setBlockedMergeNodes] = useState<string[]>([])
  const [notice, setNotice] = useState<{ workspace: ProjectWorkspace; message: string }>()
  const saveError = editing.error !== undefined ? workspaceErrorMessage(editing.error) : inputError
  const saveState = rawEditCount ? '正在编辑参数…' : editing.phase === 'saving' ? '流程保存中…' : editing.phase === 'error' ? '流程保存失败' : viewedVersion ? editing.dirty ? '旧版修改尚未保存' : '旧版只读查看' : notice && notice.workspace === workspace ? notice.message : editing.dirty ? '尚未保存' : '已保存'
  const uiSaveState = editing.phase === 'saving' ? '布局保存中…' : editing.phase === 'error' ? '布局保存失败' : editing.dirty ? '布局尚未保存' : '布局已保存'
  const nodesRef = useRef<FlowNode[]>([])
  const edgesRef = useRef<Edge[]>([])
  const projectGeneration = useRef(0)
  const flowInstance = useRef<ReactFlowInstance<FlowNode, Edge> | null>(null)
  const activeParameterEdits = useRef(new Map<string, { nodeId: string; parameter: Parameter; raw: string; error?: unknown }>())

  // Never project an old graph's nodes against a newly opened workspace's contracts.
  const projectedFlow = useMemo(() => draft && catalog && editing.desired ? flowFromDraft(draft, catalog, canvasFromUi(editing.desired.ui_state)) : { nodes: [], edges: [] }, [draft, catalog, editing.desired])
  const projectedSource = useRef<typeof editing.desired>(undefined)
  const projectedGeneration = useRef(projectGeneration.current)
  const currentFlowNodes = projectedSource.current === editing.desired ? nodes : projectedFlow.nodes
  const currentFlowEdges = projectedSource.current === editing.desired ? edges : projectedFlow.edges
  // ReactFlow owns only transient measurements, selection, dragging and raw form strings.
  useLayoutEffect(() => {
    const previous = new Map(projectedGeneration.current === projectGeneration.current ? nodesRef.current.map(node => [node.id, node]) : [])
    const nextNodes = projectedFlow.nodes.map(node => ({ ...node, position: previous.get(node.id)?.dragging ? previous.get(node.id)!.position : node.position, dragging: previous.get(node.id)?.dragging, measured: previous.get(node.id)?.measured, selected: previous.get(node.id)?.selected, data: { ...node.data, parameters: node.data.parameters.map(parameter => {
      const raw = activeParameterEdits.current.get(`${node.id}:${parameter.scope}:${parameter.key}`)
      return raw ? { ...parameter, value: raw.raw } : parameter
    }) } }))
    projectedSource.current = editing.desired
    projectedGeneration.current = projectGeneration.current
    nodesRef.current = nextNodes; edgesRef.current = projectedFlow.edges
    setNodes(nextNodes); setEdges(projectedFlow.edges)
  }, [projectedFlow, editing.desired])

  const choicesProjectId = project?.id
  const choicesWorkflow = draft?.workflow
  useEffect(() => {
    if (!choicesProjectId || !choicesWorkflow || !catalog) return
    let current = true
    setParameterChoicesError('')
    void loadWorkflowParameterChoices(editor.sources, choicesProjectId, choicesWorkflow, catalog, results).then(values => {
      if (current) setParameterChoices({ workflow: choicesWorkflow, values })
    }, reason => { if (current) setParameterChoicesError(workspaceErrorMessage(reason)) })
    return () => { current = false }
  }, [choicesProjectId, choicesWorkflow, catalog, run, inputSource, results, editor])

  useEffect(() => {
    if (!project || !draft || !run) return
    let current = true
    void client.compareWorkflowScience(run.project_id, run.workflow_commit_id, project.id, draft.workflow).then((comparison) => {
      if (current) setScienceStatus(comparison.status)
    }, (reason) => { if (current) { setScienceStatus('unknown'); setRunError(JSON.stringify(reason)) } })
    return () => { current = false }
  }, [draft, project, run])

  useEffect(() => () => results.openRun(undefined), [results])

  useEffect(() => {
    let current = true
    void (async () => {
      const [catalogValue, capabilityValue, projects, moduleUiValue] = await Promise.all([client.catalog(), client.authoringCapabilities(), client.projects(), client.moduleUi()])
      const initialProject = projects.projects.find((item) => item.project_kind === 'default_example') ?? projects.projects.find(item => !item.seed)
      const initialWorkspace = initialProject ? await client.projectWorkspace(initialProject.id) : undefined
      if (!current) return
      setModuleUi(moduleUiValue)
      setCatalog(catalogValue)
      setCapabilities(capabilityValue)
      if (initialProject && initialWorkspace) editor.open(initialProject, initialWorkspace)
      if (initialProject?.latest_run_id) results.openRun({ project_id: initialProject.id, run_id: initialProject.latest_run_id })
    })().catch(reason => { if (current) setRunError(workspaceErrorMessage(reason)) })
    return () => { current = false }
  }, [results, editor])

  const reportSaveError = useCallback((reason: unknown) => setInputError(workspaceErrorMessage(reason)), [])

  const graphUi = useCallback((workflow: Workflow, currentUi: JsonObject, positions: Record<string, { x: number; y: number }> = {}) => {
    const canvas = canvasFromUi(currentUi)
    const known = new Set(workflow.nodes.map(node => node.node_id))
    const next = cleanCanvasGroups(canvas, known)
    const completePositions = { ...next.positions, ...positions }
    workflow.nodes.forEach((node, index) => { completePositions[node.node_id] ??= defaultNodePosition(index) })
    return { ...currentUi, canvas: { ...next, positions: completePositions } }

  }, [])
  const editWorkflow = useCallback((change: (workflow: Workflow) => Workflow, positions: Record<string, { x: number; y: number }> = {}, updateUi?: (ui: JsonObject, workflow: Workflow) => JsonObject, label = '流程修改') => {
    setInputError('')
    return editor.edit(current => {
      const workflow = change(current.workflow)
      const ui = updateUi ? updateUi(current.ui_state, workflow) : current.ui_state
      return { workflow, ui_state: graphUi(workflow, ui, positions) }
    }, label)
  }, [editor, graphUi])
  const persistCanvas = useCallback((nextNodes: FlowNode[], viewport?: CanvasState['viewport']) => viewport ? editor.navigate(ui => { const canvas = canvasFromUi(ui); return { ...ui, canvas: { ...canvas, viewport, views: { ...canvas.views, [currentCanvasGroup(canvas) ?? 'root']: viewport } } } }) : editor.edit(current => {
    const previous = canvasFromUi(current.ui_state)
    return { ui_state: { ...current.ui_state, canvas: canvasFromNodes(nextNodes, viewport ? { ...previous, viewport } : previous) } }
  }), [editor])
  const saveParameter = useCallback((nodeId: string, parameter: Parameter, raw: string) => {
    let value: unknown
    try { value = raw === '' ? undefined : parameterInputValue(raw, parameter.valueType) } catch (error) {
      const pending = activeParameterEdits.current.get(`${nodeId}:${parameter.scope}:${parameter.key}`)
      if (pending) pending.error = error
      throw error
    }
    activeParameterEdits.current.delete(`${nodeId}:${parameter.scope}:${parameter.key}`)
    setRawEditCount(activeParameterEdits.current.size)
    return editWorkflow(workflow => ({ ...workflow, nodes: workflow.nodes.map(node => {
      if (node.node_id !== nodeId) return node
      const field = parameter.scope === 'node' ? 'node_parameters' : 'binding_parameters'
      const parameters = { ...node[field] }
      if (value === undefined) delete parameters[parameter.key]; else parameters[parameter.key] = value
      return { ...node, [field]: parameters }
    }) }), {}, (ui, workflow) => {
      if (parameter.scope !== 'binding') return ui
      const node = workflow.nodes.find(node => node.node_id === nodeId)!
      const memory = ui.binding_parameter_memory as Record<string, Record<string, JsonObject>> | undefined ?? {}
      return { ...ui, binding_parameter_memory: { ...memory, [nodeId]: { ...memory[nodeId], [node.binding_id]: node.binding_parameters } } }
    }, `修改参数 ${parameter.label}`)
  }, [editWorkflow])
  const finishInputs = useCallback(async () => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
    if (document.querySelector('[data-workspace-invalid="true"]')) throw new Error('请完成有效的数字输入后继续。')
    const saves = [...activeParameterEdits.current.values()].map(({ nodeId, parameter, raw, error }) => { if (error !== undefined) throw error; return saveParameter(nodeId, parameter, raw) })
    await Promise.all(saves)
  }, [saveParameter])
  const beforeWorkspaceAction = useCallback(async () => {
    await finishInputs()
    setInputError('')
    return true
  }, [finishInputs])
  const beginCanvasEdit = useCallback(async () => {
    await finishInputs()
    return editor.beginEdit()
  }, [editor, finishInputs])
  const commitSession = useCallback(async (session: WorkspaceEditSession, workflow: Workflow, positions: Record<string, { x: number; y: number }> = {}) => {
    await finishInputs()
    const graphChanged = workflow.nodes.length !== session.base.workflow.nodes.length || workflow.nodes.some(node => !session.base.workflow.nodes.some(previous => previous.node_id === node.node_id))
    return session.commit({ workflow, ...(graphChanged || Object.keys(positions).length ? { updateUi: (currentUi: JsonObject) => {
      const canvas = canvasFromUi(currentUi), scope = currentCanvasGroup(canvas)
      const added = workflow.nodes.filter(node => !session.base.workflow.nodes.some(previous => previous.node_id === node.node_id)).map(node => node.node_id)
      const ui = scope ? { ...currentUi, canvas: { ...canvas, groups: canvas.groups!.map(group => group.id === scope ? { ...group, nodeIds: [...group.nodeIds, ...added] } : group) } } : currentUi
      return graphUi(workflow, ui, positions)
    } } : {}) })
  }, [finishInputs, graphUi])
  const saveProject = useCallback(async () => {
    await finishInputs()
    const wasSeed = editor.getSnapshot().project?.seed
    const saved = editor.getSnapshot().error === undefined ? await editor.save() : await editor.retry()
    if (saved && wasSeed) results.openRun(undefined)
    setInputError('')
    return saved
  }, [editor, finishInputs, results])
  const askUnsaved = useCallback(async (mode: 'leave' | 'run') => {
    await finishInputs()
    const snapshot = editor.getSnapshot()
    if (snapshot.phase === 'saving') throw new Error('正在保存，请等待保存完成。')
    if (!snapshot.dirty && (mode !== 'run' || !snapshot.project?.seed && !snapshot.version && snapshot.acknowledged?.draft)) return true
    setChoiceError('')
    return new Promise<boolean>(resolve => setUnsavedChoice({ mode, resolve }))
  }, [editor, finishInputs])
  const resolveUnsaved = useCallback((proceed: boolean) => {
    unsavedChoice?.resolve(proceed)
    setUnsavedChoice(undefined)
  }, [unsavedChoice])
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 's' || event.isComposing) return
      event.preventDefault()
      if (!prompt && !inputSource && !unsavedChoice && !editor.getSnapshot().readOnly) void saveProject().catch(reportSaveError)
    }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
  }, [editor, prompt, inputSource, unsavedChoice, saveProject, reportSaveError])
  useEffect(() => {
    if (!editing.dirty && !rawEditCount) return
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [editing.dirty, rawEditCount])

  const openProject = useCallback(async (selected: ProjectMetadata, suppliedWorkspace?: ProjectWorkspace, versionView?: WorkflowVersionView) => {
    if (!await askUnsaved('leave')) return
    const generation = ++projectGeneration.current
    promptOpenRevision.current += 1
    moduleOpenRevision.current += 1
    const selectedWorkspace = suppliedWorkspace ?? await client.projectWorkspace(selected.id)
    if (generation !== projectGeneration.current) return
    results.openRun(undefined)
    const openingResults = results.getSnapshot()
    activeParameterEdits.current.clear(); setRawEditCount(0)
    setBlockedMergeNodes([])
    editor.open(selected, selectedWorkspace, versionView)
    setPrompt(undefined); setPromptOpenError(undefined); setRunError(''); setInputError('')
    setModuleEdit(undefined); setView('workflow'); setProjectsOpen(false)
    setRequestedResultSource(undefined); setPendingCanvasFocus(undefined)
    const canvas = canvasFromUi(editor.getSnapshot().desired!.ui_state)
    requestAnimationFrame(() => { if (canvas.views?.[currentCanvasGroup(canvas) ?? 'root'] ?? canvas.viewport) void flowInstance.current?.setViewport((canvas.views?.[currentCanvasGroup(canvas) ?? 'root'] ?? canvas.viewport)!); else void flowInstance.current?.fitView({ padding: 0.16 }) })
    let resultProject = selected
    if (!resultProject.latest_run_id && selected.reference_results_project_id) {
      resultProject = (await client.projects()).projects.find(item => item.id === selected.reference_results_project_id)!
      if (generation !== projectGeneration.current || results.getSnapshot() !== openingResults) return
    }
    if (resultProject.latest_run_id) results.openRun({ project_id: resultProject.id, run_id: resultProject.latest_run_id })
  }, [askUnsaved, editor, results])
  const returnOriginalWork = useCallback(async () => {
    if (!await askUnsaved('leave')) return
    const returned = await editor.returnToSavedWork()
    if (returned) {
      const canvas = canvasFromUi(returned.ui_state)
      if (canvas.viewport) void flowInstance.current?.setViewport(canvas.viewport)
    }
  }, [askUnsaved, editor])
  const createProject = useCallback(async () => {
    if (!await askUnsaved('leave')) return
    const created = await client.createProject(`Untitled Project ${new Date().toLocaleString()}`)
    await openProject(created)
    await editor.edit(current => ({ workflow: current.workflow, ui_state: current.ui_state }))
  }, [askUnsaved, editor, openProject])
  const saveBinding = useCallback(async (nodeId: string, bindingId: string) => {
    await beforeWorkspaceAction()
    return editor.edit(current => {
      const source = current.workflow.nodes.find(node => node.node_id === nodeId)!
      const memory = current.ui_state.binding_parameter_memory as Record<string, Record<string, JsonObject>> | undefined ?? {}
      const nodeMemory = { ...memory[nodeId], [source.binding_id]: source.binding_parameters }
      const workflow = selectNodeBinding(current.workflow, nodeId, bindingId, catalog!, nodeMemory[bindingId])
      const selected = workflow.nodes.find(node => node.node_id === nodeId)!
      return { workflow, ui_state: graphUi(workflow, { ...current.ui_state, binding_parameter_memory: { ...memory, [nodeId]: { ...nodeMemory, [bindingId]: selected.binding_parameters } } }) }
    })
  }, [beforeWorkspaceAction, editor, catalog, graphUi])
  const addDroppedNode = useCallback(async (drop: PendingNodeDrop, bindingId: string) => {
    if (!catalog) return
    await beforeWorkspaceAction()
    const nodeId = `${drop.nodeTypeId.replaceAll('.', '-')}-${crypto.randomUUID().slice(0, 8)}`
    const position = drop.position
    await editWorkflow(workflow => {
      const inserted = insertOrdinaryNode(workflow, nodeId, drop.nodeTypeId, bindingId, catalog)
      return drop.connectionFrom && drop.connectionPort ? connectWorkflowPorts(inserted, catalog, { ...drop.connectionFrom, direction: 'output' }, { nodeId, portName: drop.connectionPort, direction: 'input' }) : inserted
    }, { [nodeId]: position }, ui => { const canvas = canvasFromUi(ui); const scope = currentCanvasGroup(canvas); return scope ? { ...ui, canvas: { ...canvas, groups: canvas.groups!.map(group => group.id === scope ? { ...group, nodeIds: [...group.nodeIds, nodeId] } : group) } } : ui }, drop.connectionFrom ? '添加并连接节点' : '添加节点')
    setPendingNodeDrop(undefined)
    requestAnimationFrame(() => {
      setNodes(current => { const next = current.map(node => ({ ...node, selected: node.id === nodeId })); nodesRef.current = next; return next })
      const zoom = flowInstance.current!.getViewport().zoom
      const viewport = { x: 32 - position.x * zoom, y: 140 - position.y * zoom, zoom }
      void flowInstance.current?.setViewport(viewport)
      void persistCanvas(nodesRef.current, viewport).catch(reportSaveError)
      document.querySelector<HTMLElement>('.app-shell:not([hidden]) .flow-canvas')?.focus({ preventScroll: true })
    })
  }, [beforeWorkspaceAction, catalog, editWorkflow, persistCanvas, reportSaveError])
  const reportConnectionError = useCallback((reason: unknown) => {
    if (reason instanceof PromptMergeSourcesLockedError) {
      setBlockedMergeNodes(reason.nodeIds)
      setInputError('')
    } else {
      setBlockedMergeNodes([])
      reportSaveError(reason)
    }
  }, [reportSaveError])
  const editConnections = useCallback(async (change: (workflow: Workflow) => Workflow) => {
    const generation = projectGeneration.current
    await beforeWorkspaceAction()
    if (generation !== projectGeneration.current) return
    const current = editor.getSnapshot().desired!.workflow
    const next = change(current)
    setBlockedMergeNodes([])
    if (next === current) return
    return editWorkflow(() => next, {}, undefined, '编辑连线')
  }, [beforeWorkspaceAction, editor, editWorkflow])
  const connectPorts = useCallback((connection: Connection, previous?: Workflow['edges'][number]) => editConnections(workflow => {
    const canvas = canvasFromUi(editor.getSnapshot().desired!.ui_state)
    const output = resolveCanvasPort(canvas, workflow, connection.source, connection.sourceHandle!.slice(4), 'output')
    const input = resolveCanvasPort(canvas, workflow, connection.target, connection.targetHandle!.slice(3), 'input')
    if (!output || !input) return workflow
    return previous ? reconnectWorkflowPorts(workflow, catalog!, previous, output, input) : connectWorkflowPorts(workflow, catalog!, output, input)
  }), [catalog, editConnections, editor])
  const deleteWorkflowElements = useCallback(async (deletedNodes: FlowNode[], deletedEdges: Edge[]) => {
    await beforeWorkspaceAction()
    const current = editor.getSnapshot().desired!
    const canvas = canvasFromUi(current.ui_state)
    const selected = new Set(deletedNodes.filter(node => node.data.kind !== 'boundary').map(node => node.id))
    const removed = deleteGraphElements(current.workflow, catalog!, { nodeIds: selectedLeafNodes(canvas, selected), edges: deletedEdges.filter(edge => edge.selectable !== false).map(edge => edge.data!.workflowEdge as Workflow['edges'][number]) })
    if (removed.workflow === current.workflow && !selected.size) return
    const saved = await editWorkflow(() => removed.workflow, {}, ui => ({ ...ui, canvas: cleanCanvasGroups(canvasFromUi(ui), new Set(removed.workflow.nodes.map(node => node.node_id)), selected) }), '删除所选节点与连线')
    if (saved && removed.notices.length) setNotice({ workspace: saved, message: `已删除；${removed.notices.length} 项依赖来源的筛选配置需要重新设置` })
  }, [beforeWorkspaceAction, editor, catalog, editWorkflow])
  const dropPaletteNode = useCallback((event: React.DragEvent) => { if (!catalog || !flowInstance.current) return; event.preventDefault(); const nodeTypeId = event.dataTransfer.getData('application/protein-workbench-node-type'); if (!nodeTypeId) return; const point = flowInstance.current.screenToFlowPosition({ x: event.clientX, y: event.clientY }); const drop = { nodeTypeId, position: { x: point.x - 137, y: point.y - 30 }, bindings: bindingOptions(catalog, nodeTypeId) }; if (drop.bindings.length === 1) void addDroppedNode(drop, drop.bindings[0].id).catch(reportSaveError); else setPendingNodeDrop(drop) }, [addDroppedNode, catalog, reportSaveError])
  const addPaletteNode = (nodeTypeId: string) => {
    const point = flowInstance.current!.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
    const position = { x: point.x - 137, y: point.y - 30 }
    const occupied = nodesRef.current.map(node => ({ ...node.position, width: node.measured?.width ?? (node.data.stage ? 360 : 275), height: node.measured?.height ?? 500 }))
    for (;;) {
      const collision = occupied.find(box => position.x < box.x + box.width + 24 && position.x + 275 + 24 > box.x && position.y < box.y + box.height + 24 && position.y + 500 + 24 > box.y)
      if (!collision) break
      position.x = collision.x + collision.width + 40
    }
    const drop = { nodeTypeId, position, bindings: bindingOptions(catalog!, nodeTypeId) }
    if (drop.bindings.length === 1) void addDroppedNode(drop, drop.bindings[0].id).catch(reportSaveError)
    else setPendingNodeDrop(drop)
  }
  const undo = useCallback(() => { void beforeWorkspaceAction().then(() => editor.undo()).then(saved => { if (saved) setNotice({ workspace: saved, message: '已撤销画布修改' }) }).catch(reportSaveError) }, [beforeWorkspaceAction, editor, reportSaveError])
  const showResults = useCallback(() => { void beforeWorkspaceAction().then(() => { if (!resultsIdentity) return; setVisitedResults(current => new Set([...current, resultsIdentity])); setView('results') }).catch(reportSaveError) }, [beforeWorkspaceAction, resultsIdentity, reportSaveError])
  const openResultSource = useCallback((source: ResultLocation) => {
    setRequestedResultSource({ ...source, requestId: ++resultRequestSequence.current })
    showResults()
  }, [showResults])
  const redo = useCallback(() => { void beforeWorkspaceAction().then(() => editor.redo()).catch(reportSaveError) }, [beforeWorkspaceAction, editor, reportSaveError])
  const navigateCanvas = useCallback(async (groupId: string | null, focusNodeId?: string) => {
    await finishInputs()
    const viewport = flowInstance.current?.getViewport()
    const leavingCanvas = canvasFromUi(editor.getSnapshot().desired!.ui_state)
    const leavingId = currentCanvasGroup(leavingCanvas)
    const leaving = leavingId ?? 'root'
    const returningFrom = leavingId && leavingCanvas.groups!.find(group => group.id === leavingId)!.parentId === groupId ? leavingId : undefined
    const selection = nodesRef.current.filter(node => node.selected).map(node => node.id)
    await editor.navigate(ui => { const canvas = canvasFromUi(ui); return { ...ui, canvas: { ...canvas, currentGroup: groupId, selections: { ...canvas.selections, [leaving]: selection }, views: { ...canvas.views, ...(viewport ? { [leaving]: viewport } : {}) } } } })
    requestAnimationFrame(() => {
      const canvas = canvasFromUi(editor.getSnapshot().desired!.ui_state)
      const selected = focusNodeId ? [focusNodeId] : returningFrom ? [returningFrom] : canvas.selections?.[groupId ?? 'root'] ?? []
      setNodes(current => { const next = current.map(node => ({ ...node, selected: selected.includes(node.id) })); nodesRef.current = next; return next })
      const focusId = focusNodeId ?? returningFrom
      const focusElement = focusId ? document.querySelector<HTMLElement>(`.react-flow__node[data-id="${focusId}"]`) : null
      ;(focusElement ?? document.querySelector<HTMLElement>('.app-shell:not([hidden]) .flow-canvas'))?.focus({ preventScroll: true })
      const targets = nodesRef.current.filter(node => node.data.kind !== 'boundary' && (!focusNodeId || node.id === focusNodeId))
      const zoom = focusNodeId ? viewport?.zoom ?? 1 : 1
      const targetViewport = !focusNodeId && canvas.views?.[groupId ?? 'root'] ? canvas.views[groupId ?? 'root'] : targets.length ? { x: 32 - Math.min(...targets.map(node => node.position.x)) * zoom, y: 140 - Math.min(...targets.map(node => node.position.y)) * zoom, zoom } : undefined
      if (targetViewport) {
        void flowInstance.current?.setViewport(targetViewport)
        void persistCanvas(nodesRef.current, targetViewport).catch(reportSaveError)
      }
    })
  }, [finishInputs, editor, persistCanvas, reportSaveError])
  const focusCanvasNode = useCallback((id: string) => {
    setView('workflow')
    const canvas = canvasFromUi(editor.getSnapshot().desired!.ui_state)
    const parent = canvas.groups?.find(group => group.nodeIds.includes(id))?.id ?? null
    void navigateCanvas(parent, id).catch(reportSaveError)
  }, [editor, navigateCanvas, reportSaveError])
  const locateResultNodes = useCallback((nodeIds: string[]) => {
    setView('workflow')
    setPendingCanvasFocus(nodeIds)
  }, [])
  useEffect(() => {
    if (view !== 'workflow' || prompt || !pendingCanvasFocus) return
    const nodeId = pendingCanvasFocus.find(id => draft?.workflow.nodes.some(node => node.node_id === id))
    const frame = requestAnimationFrame(() => {
      setPendingCanvasFocus(undefined)
      if (nodeId) focusCanvasNode(nodeId)
    })
    return () => cancelAnimationFrame(frame)
  }, [view, prompt, pendingCanvasFocus, draft?.workflow.nodes, focusCanvasNode])
  const makeGroup = useCallback(async () => {
    await beforeWorkspaceAction()
    const selected = new Set(nodesRef.current.filter(node => node.selected && node.data.kind !== 'boundary').map(node => node.id))
    if (!selected.size) return
    const id = `group-${crypto.randomUUID()}`
    await editor.edit(current => ({ ui_state: { ...current.ui_state, canvas: createCanvasGroup(canvasFromNodes(nodesRef.current, canvasFromUi(current.ui_state)), selected, id, '节点组') } }), '创建节点组')
    requestAnimationFrame(() => { setNodes(current => { const next = current.map(node => ({ ...node, selected: node.id === id })); nodesRef.current = next; return next }); document.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"]`)?.focus() })
  }, [beforeWorkspaceAction, editor])
  const ungroupSelection = useCallback(async () => {
    await beforeWorkspaceAction()
    const ids = nodesRef.current.filter(node => node.selected && node.data.kind === 'group').map(node => node.id)
    if (!ids.length) return
    await editor.edit(current => ({ ui_state: { ...current.ui_state, canvas: ids.reduce((canvas, id) => ungroupCanvas(canvas, id), canvasFromUi(current.ui_state)) } }), '解组')
  }, [beforeWorkspaceAction, editor])
  const copySelection = useCallback(() => {
    if (!catalog) return
    const current = editor.getSnapshot().desired!
    const selected = new Set(nodesRef.current.filter(node => node.selected && node.data.kind !== 'boundary').map(node => node.id))
    if (!selected.size) return
    const canvas = canvasFromNodes(nodesRef.current, canvasFromUi(current.ui_state))
    const withPorts = { ...canvas, groups: (canvas.groups ?? []).map(group => ({ ...group, ports: groupPorts(canvas, current.workflow, group.id) })) }
    clipboard.current = { fragment: copyWorkflowFragment(current.workflow, selectedLeafNodes(canvas, selected), catalog, canvas.positions), canvas: structuredClone(withPorts), selected: [...selected] }
  }, [catalog, editor])
  const pasteSelection = useCallback(async () => {
    if (!clipboard.current) return
    await beforeWorkspaceAction()
    const { fragment, canvas: sourceCanvas, selected } = clipboard.current
    const position = flowInstance.current!.screenToFlowPosition(canvasPointer.current)
    const current = editor.getSnapshot().desired!
    const pasted = pasteWorkflowFragment(current.workflow, fragment, position)
    const nodeMap = new Map(fragment.nodes.map((node, index) => [node.node_id, pasted.nodeIds[index]]))
    const copiedGroups = (sourceCanvas.groups ?? []).filter(group => groupPath(sourceCanvas, group.id).some(parent => selected.includes(parent.id)))
    const groupMap = new Map(copiedGroups.map(group => [group.id, `group-${crypto.randomUUID()}`]))
    const copiedPositions = placeCanvasCopy(sourceCanvas.positions, new Map([...nodeMap, ...groupMap]), position)
    const copiedIds = new Set(copiedGroups.flatMap(group => group.nodeIds))
    const saved = await editWorkflow(() => pasted.workflow, copiedPositions, ui => {
      const canvas = canvasFromUi(ui), scope = currentCanvasGroup(canvas)
      const groups: CanvasGroup[] = copiedGroups.map(group => copyCanvasGroup(group, nodeMap, groupMap, scope))
      return { ...ui, canvas: { ...canvas, groups: [...(canvas.groups ?? []).map(group => group.id === scope ? { ...group, nodeIds: [...group.nodeIds, ...fragment.nodes.filter(node => !copiedIds.has(node.node_id)).map(node => nodeMap.get(node.node_id)!)] } : group), ...groups] } }
    }, '粘贴独立副本')
    if (saved) { setNotice({ workspace: saved, message: pasted.notices.length ? '独立副本已粘贴；外部来源的选择配置需要重新连接' : '片段已粘贴' }); requestAnimationFrame(() => { setNodes(current => { const next = current.map(node => ({ ...node, selected: [...groupMap.values(), ...pasted.nodeIds].includes(node.id) })); nodesRef.current = next; return next }); document.querySelector<HTMLElement>('.app-shell:not([hidden]) .flow-canvas')?.focus({ preventScroll: true }) }) }
  }, [beforeWorkspaceAction, editor, editWorkflow])
  const closePromptEditor = useCallback(() => { setPrompt(undefined); requestAnimationFrame(() => { if (promptReturnFocus.current?.isConnected) promptReturnFocus.current.focus({ preventScroll: true }); else document.querySelector<HTMLElement>('.app-shell:not([hidden]) .flow-canvas')?.focus({ preventScroll: true }) }) }, [])
  const openPromptEditor = useCallback((nodeId: string) => {
    promptReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const request = ++promptOpenRevision.current
    setPromptOpenError(undefined)
    void (async () => {
      const session = await beginCanvasEdit()
      if (!session) return
      const workflow = session.base.workflow
      const snapshot = await editor.sources.openPrompt(workflow.workflow_id, nodeId, workflow)
      if (request !== promptOpenRevision.current) return
      setPrompt({ nodeId, snapshot, workflow, session })
    })().catch(reason => { if (request === promptOpenRevision.current) setPromptOpenError({ nodeId, message: workspaceErrorMessage(reason) }) })
  }, [beginCanvasEdit])
  const openModuleEditor = useCallback(async (nodeId: string) => {
    const request = ++moduleOpenRevision.current
    const generation = projectGeneration.current
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const session = await beginCanvasEdit()
    if (!session) return
    const member = session.base.workflow.nodes.find(node => node.node_id === nodeId)!
    const registration = nodeEditor(moduleUi, member.node_type_id)
    if (!registration) throw new Error(`节点 ${nodeId} 没有已启用的模块编辑器`)
    const Component = await loadNodeEditor(registration)
    if (results.getSnapshot().phase !== 'idle' && !await results.ensureCandidates({ all: true })) return
    if (request !== moduleOpenRevision.current || generation !== projectGeneration.current || editor.getSnapshot().readOnly) return
    if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true })
    setModuleEdit({ nodeId, title: registration.definition.title, Component, workflow: session.base.workflow, session })
  }, [beginCanvasEdit, results, moduleUi, editor])
  const nodeLabels = useMemo(() => Object.fromEntries((draft?.workflow.nodes ?? []).map(node => [node.node_id, catalog ? nodeTypePresentation(catalog, node.node_type_id).title : node.node_type_id])), [draft?.workflow.nodes, catalog])
  const resultNodeLabels = useMemo(() => {
    const canvas = canvasFromUi(editing.desired?.ui_state ?? {})
    const entries = Object.entries(nodeLabels).map(([id, title]) => {
      const owner = canvas.groups?.find(group => group.nodeIds.includes(id))
      const path = groupPath(canvas, owner?.id ?? null).map(group => group.label)
      return { id, label: [...path, title].join(' › ') }
    })
    return Object.fromEntries(entries.map(entry => [entry.id, entries.filter(other => other.label === entry.label).length > 1 ? `${entry.label} · ${entry.id}` : entry.label]))
  }, [nodeLabels, editing.desired?.ui_state])
  const displayed = useMemo<FlowNode[]>(() => currentFlowNodes.map((node): FlowNode => {
    const sourceNode = draft?.workflow.nodes.find(item => item.node_id === node.id)
    const stageControls: StageControlView[] | undefined = node.data.stage?.controls.flatMap((control): StageControlView[] => {
      const member = draft!.workflow.nodes.find(item => item.node_id === control.nodeId)!
      if (missingNodeContracts(catalog!, member).length) return []
      if (control.kind !== 'parameter') return [control]
      const parameter = parameterPresentations(catalog!, member).find(item => item.scope === 'node' && item.key === control.key)!
      const raw = activeParameterEdits.current.get(`${control.nodeId}:${parameter.scope}:${parameter.key}`)
      return [{ kind: 'parameter', nodeId: control.nodeId, parameter: { ...parameter, label: control.label, ...(raw ? { value: raw.raw } : {}) }, choices: parameterChoices?.workflow === draft!.workflow ? parameterChoices.values[control.nodeId] : undefined }]
    })
    const members = node.data.kind === 'group' ? [...groupNodes(canvasFromUi(editor.getSnapshot().desired!.ui_state), node.id)] : []
    const states = members.map(id => runProgress?.nodeStates[id]?.status)
    const completed = states.filter(status => status === 'succeeded' || status === 'reused').length
    const status = (['failed', 'running', 'interrupted', 'cancelled', 'blocked', 'waiting'] as const).find(status => states.includes(status)) ?? (states.every(status => status === 'outside') ? 'outside' : completed === members.length && members.length ? 'succeeded' : 'idle')
    const labels = { idle: '未运行', waiting: '等待运行', running: '运行中', failed: '阶段失败', interrupted: '已中断', cancelled: '已取消', blocked: '存在未执行节点', outside: '本次运行范围外', succeeded: '阶段完成' }
    return { ...node, data: { ...node.data, readOnly: editing.readOnly,
      resultCollections: node.data.kind !== 'boundary' ? resultIndex.collections.filter(collection => node.data.kind === 'group' ? members.includes(collection.source.node_id) : collection.source.node_id === node.id) : undefined,
      onOpenResult: openResultSource,
      stageControls,
      stageState: node.data.stage ? { status, label: labels[status], completed, total: members.length } : undefined,
      onStageAction: (kind, nodeId) => { if (kind === 'prompt') openPromptEditor(nodeId); else void openModuleEditor(nodeId).catch(reportSaveError) },
      onEnter: () => { void navigateCanvas(node.id).catch(reportSaveError) },
      onRename: label => { void editor.edit(current => { const canvas = canvasFromUi(current.ui_state); return { ui_state: { ...current.ui_state, canvas: { ...canvas, groups: canvas.groups!.map(group => group.id === node.id ? { ...group, label } : group) } } } }).catch(reportSaveError) },
      groupErrors: node.data.kind === 'group' ? [...groupNodes(canvasFromUi(editor.getSnapshot().desired!.ui_state), node.id)].filter(id => runProgress?.nodeStates[id]?.status === 'failed').length : 0,
      onFocusError: () => { const failed = [...groupNodes(canvasFromUi(editor.getSnapshot().desired!.ui_state), node.id)].find(id => runProgress?.nodeStates[id]?.status === 'failed'); if (failed) focusCanvasNode(failed) },
      onCancelParameter: (nodeId, parameter) => { activeParameterEdits.current.delete(`${nodeId}:${parameter.scope}:${parameter.key}`); setRawEditCount(activeParameterEdits.current.size); setInputError(''); const value = parameterPresentations(catalog!, draft!.workflow.nodes.find(item => item.node_id === nodeId)!).find(item => item.key === parameter.key && item.scope === parameter.scope)!; setNodes(current => { const next = current.map(item => item.id === nodeId ? { ...item, data: { ...item.data, parameters: item.data.parameters.map(item => item.key === parameter.key && item.scope === parameter.scope ? value : item) } } : item); nodesRef.current = next; return next }) },
      parameterChoices: parameterChoices && parameterChoices.workflow === draft?.workflow && !parameterChoicesError ? parameterChoices.values[node.id] : { choices: {}, ...(parameterChoicesError ? { notice: `参数来源读取失败：${parameterChoicesError}` } : {}) },
      bindingOptions: catalog && sourceNode ? bindingOptions(catalog, sourceNode.node_type_id) : [],
      runState: runProgress?.nodeStates[node.data.sourceNodeId],
      scopeState: scopePreview?.reused_node_ids.includes(node.id) ? 'reuse' : scopePreview?.execution_node_ids.includes(node.id) ? 'execute' : undefined,
      moduleEditorTitle: sourceNode ? nodeEditor(moduleUi, sourceNode.node_type_id)?.definition.title : undefined,
      onEditModule: sourceNode && nodeEditor(moduleUi, sourceNode.node_type_id) ? () => { void openModuleEditor(node.id).catch(reportSaveError) } : undefined,
      onToggle: id => { const next = nodesRef.current.map(item => item.id === id ? { ...item, data: { ...item.data, collapsed: !item.data.collapsed } } : item); nodesRef.current = next; setNodes(next); void persistCanvas(next).catch(reportSaveError) },
      onEditPrompt: () => openPromptEditor(node.id),
      onParameter: (nodeId, parameter, raw, commit) => {
        if (editor.getSnapshot().readOnly) return
        const key = `${nodeId}:${parameter.scope}:${parameter.key}`
        if (commit && !activeParameterEdits.current.has(key)) return
        if (!commit) { activeParameterEdits.current.set(key, { nodeId, parameter, raw }); setRawEditCount(activeParameterEdits.current.size) }
        const next = nodesRef.current.map(item => item.id === nodeId ? { ...item, data: { ...item.data, parameters: item.data.parameters.map(value => value.key === parameter.key && value.scope === parameter.scope ? { ...value, value: raw } : value) } } : item)
        nodesRef.current = next; setNodes(next)
        if (commit) { try { void saveParameter(nodeId, parameter, raw).catch(reportSaveError) } catch (reason) { reportSaveError(reason) } }
      },
      onBinding: (nodeId, bindingId) => { void saveBinding(nodeId, bindingId).catch(reportSaveError) },
    } }
  }), [moduleUi, editing.readOnly, resultIndex.collections, openResultSource, navigateCanvas, editor, focusCanvasNode, currentFlowNodes, parameterChoices, parameterChoicesError, draft, catalog, runProgress?.nodeStates, scopePreview, openModuleEditor, openPromptEditor, persistCanvas, reportSaveError, saveBinding, saveParameter])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (event.isComposing || unsavedChoice || view !== 'workflow' || canvasPicker || pendingNodeDrop || runOpen || prompt || inputSource || projectsOpen || moduleEdit || event.defaultPrevented || target?.closest('input, textarea, select, [contenteditable="true"]')) return
      const modifier = event.metaKey || event.ctrlKey
      if (modifier && event.key.toLowerCase() === 'c') { event.preventDefault(); copySelection() }
      if (modifier && event.key.toLowerCase() === 'v') { event.preventDefault(); void pasteSelection().catch(reportSaveError) }
      if (modifier && event.key.toLowerCase() === 'z') { event.preventDefault(); if (event.shiftKey) redo(); else undo() }
      if (modifier && event.key.toLowerCase() === 'g') { event.preventDefault(); void (event.altKey ? ungroupSelection() : makeGroup()).catch(reportSaveError) }
      if (event.key === 'Tab' && !event.shiftKey && target?.closest('.flow-canvas') && !target.closest('button, [role="menu"], [role="menuitem"], [role="dialog"]')) {
        const canvas = canvasFromUi(editor.getSnapshot().desired!.ui_state)
        const selected = nodesRef.current.find(node => node.selected && node.data.kind === 'group')
        if (selected && !event.ctrlKey) { event.preventDefault(); void navigateCanvas(selected.id).catch(reportSaveError) }
        else if (currentCanvasGroup(canvas)) { event.preventDefault(); void navigateCanvas(canvas.groups!.find(group => group.id === currentCanvasGroup(canvas))!.parentId).catch(reportSaveError) }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [unsavedChoice, canvasPicker, pendingNodeDrop, copySelection, pasteSelection, redo, makeGroup, ungroupSelection, navigateCanvas, inputSource, projectsOpen, prompt, moduleEdit, editor, reportSaveError, runOpen, undo, view])
  const openInputSource = useCallback(async () => {
    const session = await beginCanvasEdit()
    if (!session) return
    setInputSource({ projectId: session.base.workflow.workflow_id, workflow: session.base.workflow, session })
  }, [beginCanvasEdit])
  const addMergeSource = useCallback(async (document: PromptAuthoringDocument) => {
    const projectId = prompt!.session.base.workflow.workflow_id
    const staged = { ...prompt!.workflow, workflow_id: projectId, nodes: prompt!.workflow.nodes.map(node => node.node_id === prompt!.nodeId ? { ...node, node_parameters: { ...node.node_parameters, [promptAuthorDocumentParameter]: document } } : node) }
    return new Promise<PromptSnapshot | undefined>(resolve => {
      mergeSourceCompletion.current = resolve
      setInputSource({ projectId, workflow: staged, session: prompt!.session, mergeTargetNodeId: prompt!.nodeId })
    })
  }, [prompt])
  const prepareSourcePrompt = useCallback(async (plan: PromptSourcePlan) => {
    const snapshot = await editor.sources.openPrompt(plan.workflow.workflow_id, plan.nodeId, plan.workflow)
    setPrompt({ nodeId: plan.nodeId, snapshot, workflow: plan.workflow, session: inputSource!.session })
    setInputSource(undefined)
    mergeSourceCompletion.current?.(snapshot); mergeSourceCompletion.current = undefined
  }, [inputSource])
  const importSourceCandidates = useCallback(async (plan: CandidateInputPlan) => {
    await commitSession(inputSource!.session, plan.workflow)
    setInputSource(undefined)
  }, [commitSession, inputSource])
  const closeInputSource = useCallback(() => { setInputSource(undefined); mergeSourceCompletion.current?.(undefined); mergeSourceCompletion.current = undefined }, [])
  const validConnection = useCallback((connection: Connection | Edge) => {
    const source = displayed.find((node) => node.id === connection.source)!
    const target = displayed.find((node) => node.id === connection.target)!
    const sourcePort = connection.sourceHandle!.slice(4)
    const targetPort = connection.targetHandle!.slice(3)
    if (source.data.collapsed || target.data.collapsed || source.data.kind === 'boundary' || target.data.kind === 'boundary') return false
    return workflowPortsMatch(source.data.outputs.find(port => port.name === sourcePort)!, target.data.inputs.find(port => port.name === targetPort)!)
  }, [displayed])
  const palette = useMemo(() => catalog && capabilities ? projectPalette(catalog, capabilities, paletteTaxonomy, search) : [], [catalog, capabilities, paletteTaxonomy, search])
  const progressNodeTitle = useMemo(() => {
    if (!runProgress?.currentNodeId || !draft || !catalog) return ''
    const node = draft.workflow.nodes.find((item) => item.node_id === runProgress.currentNodeId)
    const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'node_type' && contract.reference.contract_id === node?.node_type_id)?.descriptor
    return String(descriptor?.title ?? node?.node_type_id ?? runProgress.currentNodeId)
  }, [catalog, draft, runProgress?.currentNodeId])
  const runActive = (run?.project_id === project?.id || !run) && resultSnapshot.connection !== undefined && (!run || ['admitted', 'running'].includes(run.status))
  useLayoutEffect(() => { editor.setReadOnly(runActive) }, [editor, runActive])
  const pendingNodeTitle = pendingNodeDrop && catalog ? nodeTypePresentation(catalog, pendingNodeDrop.nodeTypeId).title : ''
  const inputSourceDialog = inputSource && catalog && <InputSourceDialog projectId={inputSource.projectId} workflow={inputSource.workflow} catalog={catalog} client={editor.sources} saveAccepted={inputSource.session.submitted} saveError={editing.error !== undefined ? workspaceErrorMessage(editing.error) : undefined} onRetrySave={async () => { await editor.retry(); if (inputSource.session.submitted) setInputSource(current => current?.session === inputSource.session ? undefined : current) }} preparePublication={async () => {
    const personal = await inputSource.session.writableProject()
    const scope = { projectId: personal.id, workflow: { ...inputSource.workflow, workflow_id: personal.id } }
    setInputSource(current => current?.session === inputSource.session ? { ...current, ...scope } : current)
    return scope
  }} mergeTargetNodeId={inputSource.mergeTargetNodeId} onPreparePrompt={prepareSourcePrompt} onImportCandidates={importSourceCandidates} onClose={closeInputSource} />

  const projectDialog = projectsOpen && <ProjectWorkspaceDialog api={client} currentProjectId={project?.id} beforeAction={beforeWorkspaceAction} onOpenProject={openProject} onViewVersion={(selected, version) => openProject(selected, version.workspace, version)} onBeforeRemove={async selected => selected.id !== editor.getSnapshot().project?.id || await askUnsaved('leave')} onSaveVersion={async selected => { if (selected.id === editor.getSnapshot().project?.id) await saveProject() }} onReturnWorkspace={async (selected) => { if (editor.getSnapshot().project?.id !== selected.id) { await openProject(selected); if (editor.getSnapshot().project?.id !== selected.id) return undefined } else if (!await askUnsaved('leave')) return undefined; return editor.returnToSavedWork() }} onProjectChanged={(updated, deletedId) => {
      if (updated && updated.id === project?.id) editor.updateProject(updated)
      if (deletedId && deletedId === project?.id) {
        results.openRun(undefined)
        editor.close()
        void client.projects().then(async available => {
          const next = available.projects.find(item => item.project_kind === 'default_example') ?? available.projects.find(item => !item.seed)
          if (next) await openProject(next)
        }).catch(reportSaveError)
      }
    }} onCreateProject={createProject} onClose={() => setProjectsOpen(false)} />
  if (!project || !draft) return <div className="loading-screen">
    {runError ? <p role="alert">{runError}</p> : !catalog ? '正在加载工作区…' : <>
      <h1>Protein Workbench</h1><p>创建项目，或打开已保存的项目。</p>
      <button className="secondary-button" onClick={() => void createProject().catch(reportSaveError)}>创建项目</button>
      <button className="secondary-button" onClick={() => setProjectsOpen(true)}>打开项目</button>
      {inputError && <p role="alert">{inputError}</p>}{projectDialog}
    </>}
  </div>
  const runControls = <>
    {runProgress && <RunProgressBar progress={runProgress} nodeTitle={progressNodeTitle} resultsLoading={resultsLoading} resultsAvailable={resultsAvailable} onResults={showResults} onCancel={() => { void client.cancelRun(runProgress.projectId!, runProgress.runId!).catch((reason) => setRunError(JSON.stringify(reason))) }} />}
    {runActive && resultSnapshot.connection === 'disconnected' && <div className="run-connection-error" role="status">运行状态连接已断开；Run 仍可能在执行。<button onClick={() => results.reconnect()}>从已接收位置重新连接</button></div>}
    {runError && <pre role="alert">{runError}</pre>}
    {resultLoadError && <div role="alert"><pre>{resultLoadError}</pre><button onClick={() => void results.refresh()}>重试读取 Run 结果</button></div>}
    {promptOpenError && <div className="workspace-error" role="alert">无法打开节点 {promptOpenError.nodeId} 的 Prompt：{promptOpenError.message}<button onClick={() => openPromptEditor(promptOpenError.nodeId)}>重新打开</button><button onClick={() => setPromptOpenError(undefined)}>关闭提示</button></div>}
    {run && <RunDiagnostics errors={resultSnapshot.diagnostics} onFocus={focusCanvasNode} />}
  </>
  const promptCanvas = canvasFromUi(editing.desired!.ui_state)
  const promptOwner = prompt && promptCanvas.groups?.find(group => group.nodeIds.includes(prompt.nodeId))
  const promptView = prompt && <>{<div className="prompt-context" aria-label="Prompt 所属流程"><span>{project.name}</span>{groupPath(promptCanvas, promptOwner?.id ?? null).map(group => <span key={group.id}>› {group.label}</span>)}<strong>› {nodeLabels[prompt.nodeId] ?? prompt.nodeId}</strong><code>{prompt.nodeId}</code><span>确认后采用至当前流程；持久保存请使用“保存项目”</span></div>}<PromptStudio snapshot={prompt.snapshot} onCancel={closePromptEditor} onAddMergeSource={addMergeSource} saveError={editing.error !== undefined ? workspaceErrorMessage(editing.error) : undefined} saveAccepted={prompt.session.submitted} onRetrySave={async () => { const saved = await editor.retry(); if (saved && prompt.session.submitted) { setNotice({ workspace: saved, message: 'Prompt 修改已采用，尚未保存项目' }); setBlockedMergeNodes([]); closePromptEditor() } }} onPreview={async document => {
    const projectId = prompt.session.base.workflow.workflow_id
    return editor.sources.previewPrompt(projectId, prompt.nodeId, document, { ...prompt.workflow, workflow_id: projectId }, prompt.session.versionContext())
  }} onApply={async preview => {
    const workflow = { ...prompt.workflow, nodes: prompt.workflow.nodes.map(node => node.node_id === prompt.nodeId ? { ...node, node_parameters: { ...node.node_parameters, [promptAuthorDocumentParameter]: preview.normalized_document } } : node) }
    const saved = await commitSession(prompt.session, workflow)
    if (saved) { setNotice({ workspace: saved, message: 'Prompt 修改已采用，尚未保存项目' }); setBlockedMergeNodes([]); closePromptEditor() }
  }} />{inputSourceDialog}</>

  return <>{unsavedChoice && <InteractionDialog title={unsavedChoice.mode === 'run' ? '保存后运行' : '尚未保存的修改'} className="run-dialog" busy={choiceBusy} onClose={() => resolveUnsaved(false)}><h2>{unsavedChoice.mode === 'run' ? '请先保存项目再运行' : '当前项目有尚未保存的修改'}</h2><p>{project.seed ? '保存将创建你自己的项目，教学原件保持不变。' : '流程内容与画布布局将一起保存。'}</p>{choiceError && <p role="alert">{choiceError}</p>}<footer><button disabled={choiceBusy} onClick={() => resolveUnsaved(false)}>{unsavedChoice.mode === 'run' ? '取消' : '取消退出，继续编辑'}</button>{unsavedChoice.mode === 'leave' && <button disabled={choiceBusy} onClick={() => { editor.discard(); resolveUnsaved(true) }}>放弃修改退出</button>}<button disabled={choiceBusy} onClick={() => { setChoiceBusy(true); setChoiceError(''); void saveProject().then(saved => { if (saved) resolveUnsaved(true) }, reason => setChoiceError(workspaceErrorMessage(reason))).finally(() => setChoiceBusy(false)) }}>{unsavedChoice.mode === 'run' ? '保存并运行' : '保存后退出'}</button></footer></InteractionDialog>}{promptView}{run && catalog && resultsIdentity && visitedResults.has(resultsIdentity) && <div hidden={view !== 'results' || !!prompt} className="persistent-results"><ResultsWorkbench key={resultsIdentity} workspaceProjectId={project.id} viewStateStore={resultsViewStateStore} runControls={runControls} results={results} run={run} index={resultIndex} loading={resultsLoading} loadError={resultLoadError} catalog={{ contracts: resultIndex.definitions, availability: [] }} scienceStatus={scienceStatus} onBack={() => setView('workflow')} active={view === 'results' && !prompt} requestedSource={requestedResultSource} nodeLabels={resultNodeLabels} onLocateNode={(nodeId: string) => locateResultNodes([nodeId])} /></div>}<div hidden={view === 'results' || !!prompt} className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark"><Braces size={16} /></span><div><strong>Protein</strong><span>Workbench</span></div></div><div className="project-identity"><div><span className="page-kicker">{project.project_kind.replace('_', ' ')}</span><strong>{project.name}</strong></div>{project.seed && <span className="immutable-pill">只读示例</span>}</div><nav className="view-tabs"><button className="active"><Network size={14} /> Workflow</button><button disabled={!run || run.outputs.length === 0 && run.artifact_index.length === 0} onClick={showResults}><Activity size={14} /> Results <span>{resultIndex.collections.reduce((sum, item) => sum + item.total, 0)}</span></button></nav><div className="top-actions"><span className="save-state" aria-label="流程保存状态"><span />{saveState}</span><span className="save-state" aria-label="布局保存状态"><span />{uiSaveState}</span><button className="icon-button" aria-label="撤销画布修改" title={editing.undoLabel ? `撤销：${editing.undoLabel}` : '没有可撤销的操作'} disabled={!editing.canUndo} onClick={undo}><RotateCcw size={16} /></button><button className="icon-button" aria-label="重做画布修改" title={editing.redoLabel ? `重做：${editing.redoLabel}` : '没有可重做的操作'} disabled={!editing.canRedo} onClick={redo}>↪</button><button className="secondary-button" onClick={() => { void beforeWorkspaceAction().then(() => setProjectsOpen(true)).catch(reportSaveError) }}><FolderOpen size={14} /> 项目</button><button className="secondary-button" disabled={runActive || editing.phase === 'saving'} onClick={() => void saveProject().catch(reportSaveError)}>保存项目</button><button className="run-button" disabled={runActive} onClick={() => void askUnsaved('run').then(proceed => { if (proceed) setRunOpen(true) }).catch(reportSaveError)}>{runActive ? <LoaderCircle size={14} /> : <Play size={14} />} {runActive ? '运行中' : '运行流程'}</button></div></header>
    {(viewedVersion || workspace?.return_workspace_revision !== null && workspace?.return_workspace_revision !== undefined) && <div className="version-work-banner" role="status"><span>{viewedVersion ? `正在查看版本“${viewedVersion.version.name}”；首次修改将另存为当前工作。` : '当前工作由旧版本继续，原工作仍然保留。'}</span><button onClick={() => void returnOriginalWork().catch(reportSaveError)}>返回原工作</button></div>}
    {saveError && <div className="workspace-error" role="alert">{saveError}<button onClick={() => void finishInputs().then(() => editor.retry()).then(() => { setInputError(''); if (moduleEdit?.session.submitted) setModuleEdit(undefined); if (inputSource?.session.submitted) setInputSource(undefined) }).catch(reportSaveError)}>重试保存</button></div>}
    {blockedMergeNodes.length > 0 && <div className="workspace-error" role="alert">现有合并来源受保护；请先在 Prompt Studio 调整并保存合并操作。{blockedMergeNodes.map(nodeId => <button key={nodeId} onClick={() => openPromptEditor(nodeId)}>打开 Prompt Studio：{nodeId}</button>)}</div>}
    {runControls}
    <nav className="canvas-breadcrumb" aria-label="节点组路径"><button onClick={() => void navigateCanvas(null).catch(reportSaveError)}>{project.name}</button>{groupPath(canvasFromUi(editing.desired!.ui_state), currentCanvasGroup(canvasFromUi(editing.desired!.ui_state))).map(group => <button key={group.id} onClick={() => void navigateCanvas(group.id).catch(reportSaveError)}>› {group.label}</button>)}{currentCanvasGroup(canvasFromUi(editing.desired!.ui_state)) && <button onClick={() => { const canvas = canvasFromUi(editing.desired!.ui_state); void navigateCanvas(canvas.groups!.find(group => group.id === currentCanvasGroup(canvas))!.parentId).catch(reportSaveError) }}>返回上层 · Tab</button>}</nav>
    {!!canvasFromUi(editing.desired!.ui_state).groups?.some(group => group.stage && group.parentId === null) && <nav className="canvas-stage-navigation" aria-label="流程阶段">{canvasFromUi(editing.desired!.ui_state).groups!.filter(group => group.stage && group.parentId === null).sort((left, right) => left.stage!.order - right.stage!.order).map(group => <button key={group.id} aria-label={`阶段 ${group.stage!.order} ${group.label}`} aria-current={groupPath(canvasFromUi(editing.desired!.ui_state), currentCanvasGroup(canvasFromUi(editing.desired!.ui_state))).some(parent => parent.id === group.id) || nodes.some(node => node.id === group.id && node.selected) ? 'step' : undefined} onClick={() => void navigateCanvas(null, group.id).catch(reportSaveError)}><span>{String(group.stage!.order).padStart(2, '0')}</span>{group.label}</button>)}</nav>}
    {currentCanvasGroup(canvasFromUi(editing.desired!.ui_state)) && catalog && <GroupInterfaceEditor canvas={canvasFromUi(editing.desired!.ui_state)} workflow={draft.workflow} catalog={catalog} groupId={currentCanvasGroup(canvasFromUi(editing.desired!.ui_state))!} onChange={ports => { void editor.edit(current => { const canvas = canvasFromUi(current.ui_state), id = currentCanvasGroup(canvas); return { ui_state: { ...current.ui_state, canvas: { ...canvas, groups: canvas.groups!.map(group => group.id === id ? { ...group, ports } : group) } } } }).catch(reportSaveError) }} />}
    {<div className="canvas-toolbar"><button aria-label={sidebarOpen ? '收起研究操作面板' : '展开研究操作面板'} aria-pressed={sidebarOpen} onClick={() => setSidebarOpen(open => !open)}><PanelLeftClose size={14} />研究操作</button><span>在节点上查看输出；进入阶段编辑完整流程</span></div>}
    <div className="workspace-shell"><aside className={`palette ${sidebarOpen ? '' : 'closed'}`}><header><div><span className="page-kicker">OPERATION PALETTE</span><h2>研究操作</h2></div><button className="icon-button" aria-label="收起研究操作面板" onClick={() => setSidebarOpen(false)}><PanelLeftClose size={16} /></button></header><div className="palette-search"><Search size={15} /><input placeholder="搜索 active Catalog…" value={search} onChange={(event) => setSearch(event.target.value)} /></div><div className="taxonomy-switch"><button className={paletteTaxonomy === 'purpose' ? 'active' : ''} onClick={() => setPaletteTaxonomy('purpose')}>按研究目的</button><button className={paletteTaxonomy === 'provider' ? 'active' : ''} onClick={() => setPaletteTaxonomy('provider')}>按包 / 模型</button></div><div className="palette-section"><span className="section-label">ACTIVE CATALOG</span>{palette.map((group) => <section className="palette-group" key={group.label}><span className="palette-group-title">{group.label}</span>{group.entries.map((item) => <button disabled={editing.readOnly} className="palette-item" key={`${group.label}-${item.id}`} onClick={() => addPaletteNode(item.id)} draggable={!editing.readOnly} onDragStart={(event) => { event.dataTransfer.setData('application/protein-workbench-node-type', item.id); event.dataTransfer.effectAllowed = 'move' }}><span className="palette-icon"><Atom size={16} /></span><span><strong>{item.title}</strong><small>{paletteTaxonomy === 'purpose' ? item.purpose : group.label}</small></span><Plus size={14} /></button>)}</section>)}</div><div className="catalog-status"><span className="status-light" /><div><strong>Active Catalog</strong><small>{catalog?.contracts.length} contracts</small></div><CircleHelp size={14} /></div></aside>
      <ContextMenu.Root><ContextMenu.Trigger asChild><main className="flow-canvas" tabIndex={0} onPointerMove={event => { canvasPointer.current = { x: event.clientX, y: event.clientY } }}>{!sidebarOpen && <button className="floating-open" aria-label="展开研究操作面板" onClick={() => setSidebarOpen(true)}><ChevronRight size={16} /></button>}<ReactFlow nodes={displayed} edges={currentFlowEdges} elevateEdgesOnSelect nodesDraggable={!editing.readOnly} nodesConnectable={!editing.readOnly} edgesReconnectable={!editing.readOnly} nodeTypes={{ workflow: WorkflowCard }} isValidConnection={validConnection} onInit={(instance) => { flowInstance.current = instance; const canvas = canvasFromUi(editor.getSnapshot().desired!.ui_state); const viewport = canvas.views?.[currentCanvasGroup(canvas) ?? 'root'] ?? canvas.viewport; if (viewport) requestAnimationFrame(() => void instance.setViewport(viewport)) }} onMoveEnd={(event, viewport) => { if (event) void persistCanvas(nodesRef.current, viewport).catch(reportSaveError) }} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move' }} onDrop={dropPaletteNode} onPaneClick={event => (event.currentTarget.closest('main') as HTMLElement | null)?.focus()} onNodeClick={event => { if (event.target instanceof Element && !event.target.closest('button, input, textarea, select, summary, a, [contenteditable="true"]')) (event.currentTarget as HTMLElement).focus({ preventScroll: true }) }} onNodeContextMenu={(_event, node) => { if (!node.selected && node.data.kind !== 'boundary') { const next = nodesRef.current.map(item => ({ ...item, selected: item.id === node.id })); nodesRef.current = next; setNodes(next) } }} onBeforeDelete={async ({ nodes: deletedNodes, edges: deletedEdges }) => { try { await deleteWorkflowElements(deletedNodes, deletedEdges) } catch (reason) { reportConnectionError(reason) }; return false }} onNodesChange={(changes: NodeChange<FlowNode>[]) => { const next = applyNodeChanges(changes.filter(change => change.type !== 'remove'), nodesRef.current); nodesRef.current = next; setNodes(next); if (changes.some((change) => change.type === 'position' && change.dragging === false)) void persistCanvas(next).catch(reportSaveError) }} onEdgesChange={(changes: EdgeChange<Edge>[]) => { const next = applyEdgeChanges(changes.filter(change => change.type !== 'remove'), edgesRef.current); edgesRef.current = next; setEdges(next) }} onConnectStart={() => { reconnectGesture.current = false }} onReconnectStart={() => { reconnectGesture.current = true }} onConnectEnd={(event, state) => {
        if (state.isValid || reconnectGesture.current || state.fromHandle?.type !== 'source' || !state.fromNode || !(event.target instanceof Element) || !event.target.classList.contains('react-flow__pane')) return
        const current = editor.getSnapshot().desired!
        const port = resolveCanvasPort(canvasFromUi(current.ui_state), current.workflow, state.fromNode.id, state.fromHandle.id!.slice(4), 'output')
        if (!port) return
        const source = current.workflow.nodes.find(node => node.node_id === port.nodeId)!
        if (nodeTypePresentation(catalog!, source.node_type_id).missing) return
        const presented = nodeTypePresentation(catalog!, source.node_type_id).outputs.find(item => item.name === port.portName)!
        if (presented.missing) return
        const point = 'changedTouches' in event ? event.changedTouches[0] : event
        setCanvasPicker({ x: point.clientX, y: point.clientY, from: { nodeId: port.nodeId, portName: port.portName, portTypeId: presented.portTypeId, multiplicity: presented.multiplicity } })
      }} onConnect={(connection: Connection) => { void connectPorts(connection).catch(reportConnectionError) }} onReconnect={(edge, connection) => { void connectPorts(connection, edge.data!.workflowEdge as Workflow['edges'][number]).catch(reportConnectionError) }} fitView={!canvasFromUi(editing.desired!.ui_state).viewport && !canvasFromUi(editing.desired!.ui_state).views?.[currentCanvasGroup(canvasFromUi(editing.desired!.ui_state)) ?? 'root']} defaultViewport={canvasFromUi(editing.desired!.ui_state).views?.[currentCanvasGroup(canvasFromUi(editing.desired!.ui_state)) ?? 'root'] ?? canvasFromUi(editing.desired!.ui_state).viewport} fitViewOptions={{ padding: 0.16 }} minZoom={0.01} maxZoom={1.5} deleteKeyCode={['Backspace', 'Delete']} selectionOnDrag><Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#39413b" /><MiniMap nodeColor={(node) => String(node.data.accent)} maskColor="rgba(14,16,14,.72)" /><Controls showInteractive={false} position="top-right" orientation="horizontal" style={{ top: 60 }} /><Panel position="top-left" className="canvas-heading"><span className="page-kicker">WORKFLOW DRAFT · {draft.workflow.nodes.length} GRAPH NODES</span><h1>{project.name}</h1><p>{draft.workflow.edges.length} 条草稿连线 · 按端口类型与数量匹配</p></Panel><Panel position="top-right" className="canvas-tools"><button disabled={editing.readOnly} onClick={() => void openInputSource().catch(reportSaveError)}><Plus size={14} /> 添加来源</button><button disabled={editing.readOnly} onClick={() => setCanvasPicker({ x: 350, y: 160 })}><Search size={14} /> 添加节点</button><button aria-label="100% 实际大小" onClick={() => { void (async () => { await finishInputs(); const flow = flowInstance.current!; await flow.zoomTo(1); await persistCanvas(nodesRef.current, flow.getViewport()) })().catch(reportSaveError) }}>100%</button><button onClick={() => void flowInstance.current?.fitView({ padding: 0.16 })}><Layers3 size={14} /> 适合视图</button></Panel></ReactFlow><div className="canvas-selection-tools canvas-footer"><span>{nodes.filter(node => node.selected).length} 项已选</span><button onClick={copySelection} disabled={!nodes.some(node => node.selected)}>复制</button><button onClick={() => void pasteSelection().catch(reportSaveError)}>粘贴</button><button onClick={() => void makeGroup().catch(reportSaveError)} disabled={!nodes.some(node => node.selected)}>组合 Ctrl/⌘G</button><button onClick={() => void ungroupSelection().catch(reportSaveError)} disabled={!nodes.some(node => node.selected && node.data.kind === 'group')}>解组</button><span className="canvas-footer-hint">拖动端口连接 · Delete 删除 · Ctrl/⌘Z 撤销</span></div></main></ContextMenu.Trigger><ContextMenu.Portal><ContextMenu.Content className="canvas-context-menu" onCloseAutoFocus={event => event.preventDefault()}>
        <ContextMenu.Item onSelect={() => setCanvasPicker({ ...canvasPointer.current })}>添加节点</ContextMenu.Item>
        <ContextMenu.Item disabled={!nodes.some(node => node.selected)} onSelect={copySelection}>复制 Ctrl/⌘C</ContextMenu.Item>
        <ContextMenu.Item onSelect={() => void pasteSelection().catch(reportSaveError)}>粘贴 Ctrl/⌘V</ContextMenu.Item>
        <ContextMenu.Item disabled={!nodes.some(node => node.selected)} onSelect={() => void makeGroup().catch(reportSaveError)}>组合 Ctrl/⌘G</ContextMenu.Item>
        <ContextMenu.Item disabled={!nodes.some(node => node.selected && node.data.kind === 'group')} onSelect={() => void ungroupSelection().catch(reportSaveError)}>解组 Ctrl/⌘Alt G</ContextMenu.Item>
        <ContextMenu.Item disabled={!nodes.some(node => node.selected) && !edges.some(edge => edge.selected)} onSelect={() => void deleteWorkflowElements(nodes.filter(node => node.selected), edges.filter(edge => edge.selected)).catch(reportConnectionError)}>删除所选（组包含所有成员）</ContextMenu.Item>
      </ContextMenu.Content></ContextMenu.Portal></ContextMenu.Root>
      </div>
    {!prompt && inputSourceDialog}
    {moduleEdit && catalog && <InteractionDialog title={moduleEdit.title} className="run-dialog module-editor-dialog" onClose={() => setModuleEdit(undefined)}>{saveError && <p role="alert">{saveError}{editing.error !== undefined && <button onClick={() => void editor.retry().then(() => { if (moduleEdit.session.submitted) setModuleEdit(undefined) }).catch(reportSaveError)}>重试保存</button>}</p>}<div inert={moduleEdit.session.submitted || editing.readOnly} style={{ display: 'contents' }}><moduleEdit.Component key={moduleEdit.nodeId} catalog={catalog} workflow={moduleEdit.workflow} nodeId={moduleEdit.nodeId} candidateCollections={resultIndex.collections} onCancel={() => setModuleEdit(undefined)} onApply={(next) => { void commitSession(moduleEdit.session, next).then(() => setModuleEdit(undefined)).catch(reportSaveError) }} /></div>{moduleEdit.session.submitted && <button onClick={() => setModuleEdit(undefined)}>关闭查看</button>}</InteractionDialog>}
    {canvasPicker && catalog && capabilities && <CanvasOperationPicker catalog={catalog} capabilities={capabilities} position={canvasPicker} requiredPort={canvasPicker.from ? { ...canvasPicker.from, direction: 'input' } : undefined} onClose={() => setCanvasPicker(undefined)} onChoose={(nodeTypeId) => { const position = flowInstance.current!.screenToFlowPosition(canvasPicker); const inputs = canvasPicker.from ? nodeTypePresentation(catalog, nodeTypeId).inputs.filter(port => workflowPortsMatch(canvasPicker.from!, port)) : []; const drop: PendingNodeDrop = { nodeTypeId, position, bindings: bindingOptions(catalog, nodeTypeId), connectionFrom: canvasPicker.from, connectionPort: inputs.length === 1 ? inputs[0].name : undefined }; setCanvasPicker(undefined); if (drop.bindings.length === 1 && (!drop.connectionFrom || drop.connectionPort)) void addDroppedNode(drop, drop.bindings[0].id).catch(reportSaveError); else setPendingNodeDrop(drop) }} />}
    {runOpen && <RunDialog selectedNodeIds={[...selectedLeafNodes(canvasFromUi(editing.desired!.ui_state), new Set(nodes.filter((node) => node.selected).map((node) => node.id)))]} sourceRunId={run && run.project_id === project.id && !['admitted', 'running'].includes(run.status) ? run.run_id : undefined} onClose={() => { setRunOpen(false); setScopePreview(undefined) }} onFocus={focusCanvasNode} onPrepare={async (request) => {
      const personal = editor.getSnapshot().project!
      const commit = await editor.commitWorkflow()
      if (!commit) throw new Error('项目已切换')
      const preview = await client.previewRunScope(personal.id, commit.workflow_commit_id, request)
      setScopePreview(preview.scope)
      return { projectId: personal.id, request, preview }
    }} onStart={async ({ projectId, request, preview }) => {
      const receipt = await client.startRun(projectId, preview.workflow_commit_id, request)
      results.openRun({ project_id: receipt.project_id, run_id: receipt.run_id }, receipt.event_cursor)
      const current = editor.getSnapshot().project
      if (current?.id === receipt.project_id) editor.updateProject({ ...current, latest_run_id: receipt.run_id })
      setRunError(''); setModuleEdit(undefined)
      setRunOpen(false); setScopePreview(undefined)
    }} />}
    {pendingNodeDrop && <InteractionDialog title={`为 ${pendingNodeTitle} 选择执行模型${pendingNodeDrop.connectionFrom ? '与连接端口' : ''}`} className="run-dialog binding-dialog" onClose={() => setPendingNodeDrop(undefined)}><header><span className="dialog-icon"><Atom size={18} /></span><div><span className="page-kicker">EXECUTION BINDING</span><h2 id="binding-dialog-title">为 {pendingNodeTitle} 选择执行模型</h2></div><button className="icon-button" onClick={() => setPendingNodeDrop(undefined)}><X size={18} /></button></header>{pendingNodeDrop.connectionFrom && !pendingNodeDrop.connectionPort && <p>有多个兼容输入，请先选择目标端口。</p>}{pendingNodeDrop.connectionFrom && <label>目标输入<select aria-label="新节点目标输入" value={pendingNodeDrop.connectionPort ?? ''} onChange={event => setPendingNodeDrop({ ...pendingNodeDrop, connectionPort: event.target.value || undefined })}><option value="">选择输入…</option>{nodeTypePresentation(catalog!, pendingNodeDrop.nodeTypeId).inputs.filter(port => { const source = draft.workflow.nodes.find(node => node.node_id === pendingNodeDrop.connectionFrom!.nodeId)!; return workflowPortsMatch(nodeTypePresentation(catalog!, source.node_type_id).outputs.find(port => port.name === pendingNodeDrop.connectionFrom!.portName)!, port) }).map(port => <option value={port.name} key={port.name}>{port.name}</option>)}</select></label>}<div className="binding-choice-list">{pendingNodeDrop.bindings.map((binding) => <button disabled={!!pendingNodeDrop.connectionFrom && !pendingNodeDrop.connectionPort} key={binding.id} title={binding.availabilityReason?.message} onClick={() => void addDroppedNode(pendingNodeDrop, binding.id).catch(reportSaveError)}><strong>{binding.label}{binding.available ? '' : '（不可用）'}</strong><small>{binding.id}</small>{binding.availabilityReason?.message && <p>{binding.availabilityReason.message}</p>}</button>)}</div><footer><button className="secondary-button" onClick={() => setPendingNodeDrop(undefined)}>取消</button></footer></InteractionDialog>}
    {projectDialog}

  </div></>
}

export default App
