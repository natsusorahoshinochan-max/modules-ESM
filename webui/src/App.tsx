import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { Background, BackgroundVariant, Controls, Handle, MiniMap, Panel, Position, ReactFlow, addEdge, applyEdgeChanges, applyNodeChanges, reconnectEdge, type Connection, type Edge, type EdgeChange, type Node, type NodeChange, type NodeProps, type ReactFlowInstance } from '@xyflow/react'
import { Activity, Atom, Braces, Check, ChevronDown, ChevronRight, CircleHelp, FolderOpen, Info, Layers3, LoaderCircle, Network, PanelLeftClose, Play, Plus, RotateCcw, Search, X, Zap } from 'lucide-react'
import { PromptStudio } from './PromptStudio'
import { InputSourceDialog } from './InputSourceDialog'
import type { CandidateInputPlan, PromptSourcePlan } from './input-sources'
import { ProjectWorkspaceDialog } from './ProjectWorkspaceDialog'
import { workspaceErrorMessage, type ProjectWorkspace, type WorkflowVersionView } from './project-workspace'
import { PublicV2Client, promptAuthorDocumentParameter, promptAuthorNodeTypeId, type AuthoringCapabilities, type CatalogSnapshot, type NodeDisposition, type ProjectMetadata, type PromptAuthoringDocument, type PromptSnapshot, type RunEventEnvelope, type RunProjection, type RunScope, type RunStatus, type Workflow, type WorkflowDraft, type WorkflowNode, type JsonObject, type PromptVersionContext } from './protocol/client'
import { RunDialog } from './RunDialog'
import { RunDiagnostics } from './RunDiagnostics'
import type { RunDiagnostic } from './protocol/client'
import { ResultsWorkbench } from './ResultsWorkbench'
import { PublishedResults } from './published-results'
import { WorkflowParameters } from './WorkflowParameters'
import { loadWorkflowParameterChoices, type NodeParameterChoices, type WorkflowParameterChoices } from './parameter-choices'
import { SelectionEditor } from './SelectionEditor'
import { selectionNodeTypes } from './selection-authoring'
import { CanvasOperationPicker } from './CanvasOperationPicker'
import { copyWorkflowFragment, pasteWorkflowFragment, removeWorkflowNodes, type WorkflowFragment } from './workflow-fragments'
import { bindingOptions, insertOrdinaryNode, nodeTypePresentation, parameterPresentations, projectPalette, selectNodeBinding, type BindingOption, type PaletteTaxonomy, type ParameterPresentation } from './workflow-authoring'

const client = new PublicV2Client()
type Parameter = ParameterPresentation & { suffix?: string }
type NodeRunStatus = 'waiting' | 'running' | 'succeeded' | 'failed' | 'blocked' | 'cancelled' | 'interrupted' | 'outside' | 'reused'
type NodeRunState = { status: NodeRunStatus; blockedBy?: string[]; resolution?: 'executed' | 'cache_replayed' }
type WorkflowNodeData = Record<string, unknown> & { kind: 'prompt' | 'ordinary'; eyebrow: string; title: string; subtitle: string; index: string; inputs: string[]; outputs: string[]; inputPortTypes: Record<string, string>; inputMultiplicities: Record<string, string>; outputPortTypes: Record<string, string>; parameters: Parameter[]; parameterChoices?: NodeParameterChoices; accent: string; count: string; sourceNodeId: string; bindingId?: string; bindingOptions?: BindingOption[]; collapsed?: boolean; runState?: NodeRunState; scopeState?: 'execute' | 'reuse'; onToggle?: (id: string) => void; onEditPrompt?: () => void; onEditSelection?: () => void; onParameter?: (id: string, parameter: Parameter, value: string, commit: boolean) => void; onBinding?: (nodeId: string, bindingId: string) => void }
type FlowNode = Node<WorkflowNodeData>
type RunProgress = { status: 'committing' | 'starting' | RunStatus; totalNodes: number; completedNodeIds: string[]; nodeStates: Record<string, NodeRunState>; currentNodeId?: string; lastNodeId?: string; projectId?: string; runId?: string; workflowCommitId?: string; eventCursor?: string; scope?: RunScope }
type PendingNodeDrop = { nodeTypeId: string; position: { x: number; y: number }; bindings: BindingOption[] }
type HistoryEntry = { workflow: Workflow; nodes: FlowNode[]; edges: Edge[] }

type CanvasState = { positions: Record<string, { x: number; y: number }>; collapsed: string[]; viewport?: { x: number; y: number; zoom: number } }
type VersionSession = { view: WorkflowVersionView; forked: boolean }
const emptyCanvas: CanvasState = { positions: {}, collapsed: [] }
const categoryColors: Record<string, string> = { generation: '#55c8b7', selection: '#e7b75f', structure_comparison: '#71a8ff', structure_prediction: '#71a8ff', collection_ops: '#92a79a', prompt_authoring: '#ae9cff' }

function canvasFromUi(uiState: JsonObject): CanvasState {
  return uiState.canvas as CanvasState | undefined ?? emptyCanvas
}

function canvasFromNodes(flowNodes: FlowNode[], previous: CanvasState): CanvasState {
  return {
    ...previous,
    positions: Object.fromEntries(flowNodes.map((node) => [node.id, node.position])),
    collapsed: flowNodes.filter((node) => node.data.collapsed).map((node) => node.id),
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
  if (valueType === 'integer' || valueType === 'number') return Number(raw)
  if (valueType === 'boolean') return raw === 'true'
  if (valueType === 'array' || valueType === 'object') return JSON.parse(raw)
  return raw
}

function flowFromDraft(draft: WorkflowDraft, catalog?: CatalogSnapshot, stored: CanvasState = emptyCanvas, positionOverrides: Record<string, { x: number; y: number }> = {}): { nodes: FlowNode[]; edges: Edge[] } {
  if (!catalog) return { nodes: [], edges: [] }
  const nodes = draft.workflow.nodes.map((node, index): FlowNode => {
    const presentation = nodeTypePresentation(catalog, node.node_type_id)
    return { id: node.node_id, type: 'workflow', position: positionOverrides[node.node_id] ?? stored.positions[node.node_id] ?? { x: 60 + index % 5 * 320, y: 100 + Math.floor(index / 5) * 270 }, data: { kind: node.node_type_id === promptAuthorNodeTypeId ? 'prompt' : 'ordinary', eyebrow: presentation.category.toUpperCase(), title: presentation.title, subtitle: node.node_type_id, index: String(index + 1).padStart(2, '0'), inputs: presentation.inputs, outputs: presentation.outputs, inputPortTypes: presentation.inputPortTypes, inputMultiplicities: presentation.inputMultiplicities, outputPortTypes: presentation.outputPortTypes, parameters: nodeParameters(node.node_id, draft.workflow, catalog), accent: categoryColors[presentation.category] ?? '#9aa69b', count: '', sourceNodeId: node.node_id, bindingId: node.binding_id, collapsed: stored.collapsed.includes(node.node_id) } }
  })
  const edges = draft.workflow.edges.map((edge, index): Edge => ({ id: `workflow-edge-${index}`, source: edge.source_node_id, sourceHandle: `out-${edge.source_port}`, target: edge.target_node_id, targetHandle: `in-${edge.target_port}`, type: 'default', style: { stroke: '#637168', strokeWidth: 1.6 } }))
  return { nodes, edges }
}

function workflowEdgesFromFlow(flowEdges: Edge[]): Workflow['edges'] {
  return flowEdges.map((edge) => ({
    source_node_id: edge.source,
    source_port: edge.sourceHandle!.slice(4),
    target_node_id: edge.target,
    target_port: edge.targetHandle!.slice(3),
  }))
}

function nodeRunStateFromDisposition(disposition: NodeDisposition): NodeRunState {
  if (disposition.outcome === 'succeeded') return { status: 'succeeded', resolution: disposition.resolution }
  if (disposition.outcome === 'blocked') return { status: 'blocked', blockedBy: disposition.blocked_by }
  return { status: disposition.outcome }
}

function nodeStatesFromProjection(projection: RunProjection, workflowNodeIds: string[] = []): Record<string, NodeRunState> {
  return Object.fromEntries([
    ...workflowNodeIds.map((nodeId): [string, NodeRunState] => [nodeId, { status: projection.scope.execution_node_ids.includes(nodeId) ? 'waiting' : 'outside' }]),
    ...projection.node_dispositions.map((disposition): [string, NodeRunState] => [disposition.node_id, projection.scope.reused_node_ids.includes(disposition.node_id) ? { status: 'reused' } : nodeRunStateFromDisposition(disposition)]),
  ])
}

function WorkflowCard({ id, data, selected }: NodeProps<FlowNode>) {
  const Icon = data.kind === 'prompt' ? Braces : Atom
  const runStatusLabel: Record<NodeRunStatus, string> = { waiting: '等待', running: '运行中', succeeded: '成功', failed: '失败', blocked: '未执行', cancelled: '已取消', interrupted: '已中断', outside: '范围外', reused: '仅复用' }
  return <article className={`workflow-node ${selected ? 'is-selected' : ''} ${data.collapsed ? 'is-collapsed' : ''} ${data.runState ? `run-status-${data.runState.status}` : ''} ${data.scopeState ? `scope-${data.scopeState}` : ''}`} style={{ '--node-accent': data.accent } as React.CSSProperties}>
    {data.inputs.map((port, index) => <Handle key={port} id={`in-${port}`} type="target" position={Position.Left} style={{ top: data.collapsed ? 31 : 112 + index * 26 }} className="node-handle input-handle" />)}
    {data.outputs.map((port, index) => <Handle key={port} id={`out-${port}`} type="source" position={Position.Right} style={{ top: data.collapsed ? 31 : 112 + index * 26 }} className="node-handle output-handle" />)}
    <header className="node-header"><span className="node-icon"><Icon size={15} /></span><div><span className="node-eyebrow">{data.eyebrow}</span><h3>{data.title}</h3></div>{data.runState && <span className={`node-run-status ${data.runState.status}`} aria-label={`${data.title}：${runStatusLabel[data.runState.status]}`}>{data.runState.status === 'running' ? <LoaderCircle size={11} /> : data.runState.status === 'succeeded' ? <Check size={11} /> : data.runState.status === 'failed' ? <X size={11} /> : <span />}{runStatusLabel[data.runState.status]}</span>}<span className="node-index">{data.index}</span><button className="icon-button nodrag" onClick={() => data.onToggle?.(id)}><ChevronDown size={15} /></button></header>
    {!data.collapsed && <><div className="node-meta">{data.bindingOptions && data.bindingOptions.length > 1 ? <select className="node-binding-select nodrag" aria-label={`${data.title}的执行模型`} value={data.bindingId} onChange={(event) => data.onBinding?.(data.sourceNodeId, event.target.value)}>{data.bindingOptions.map((option) => <option value={option.id} key={option.id} title={option.availabilityReason?.message}>{option.label}{option.available ? '' : '（不可用）'}</option>)}</select> : <span>{data.bindingOptions?.find((option) => option.id === data.bindingId)?.label ?? data.subtitle}{data.bindingOptions?.some((option) => option.id === data.bindingId && !option.available) ? '（不可用）' : ''}</span>}<strong>{data.count}</strong></div><div className="ports-block"><div>{data.inputs.map((port) => <span key={port} className="port input-port">{port}</span>)}</div><div>{data.outputs.map((port) => <span key={port} className="port output-port">{port}</span>)}</div></div>
      {data.bindingOptions?.find((option) => option.id === data.bindingId)?.availabilityReason?.message && <p className="parameter-empty-hint">{data.bindingOptions.find((option) => option.id === data.bindingId)!.availabilityReason!.message}</p>}
      {data.kind === 'prompt' ? <button className="prompt-edit-button nodrag" onClick={data.onEditPrompt}><Braces size={14} /> 打开 Prompt Studio <ChevronRight size={14} /></button> : data.onEditSelection ? <button className="prompt-edit-button nodrag" onClick={data.onEditSelection}>编辑筛选与排序 <ChevronRight size={14} /></button> : <><WorkflowParameters parameters={data.parameters} choices={data.parameterChoices?.choices} onParameter={(parameter, raw, commit) => data.onParameter?.(data.sourceNodeId, parameter, raw, commit)} />{data.parameterChoices?.source && <small className="parameter-description">选项来源：{data.parameterChoices.source}</small>}{data.parameterChoices?.notice && <p className="parameter-empty-hint" role="status">{data.parameterChoices.notice}</p>}</>}
    </>}
  </article>
}

function runProgressTitle(status: RunProgress['status']) {
  if (status === 'committing') return '正在准备运行'
  if (status === 'starting' || status === 'admitted') return '正在启动'
  if (status === 'running') return '正在运行'
  if (status === 'succeeded') return '运行完成'
  if (status === 'failed') return '运行失败'
  if (status === 'cancelled') return '运行已取消'
  return '运行已中断'
}

function RunProgressBar({ progress, nodeTitle, resultsLoading, resultsAvailable, onResults, onCancel }: { progress: RunProgress; nodeTitle: string; resultsLoading: boolean; resultsAvailable: boolean; onResults: () => void; onCancel: () => void }) {
  const terminal = ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(progress.status)
  const percent = progress.totalNodes === 0 ? 0 : Math.round(progress.completedNodeIds.length / progress.totalNodes * 100)
  const stage = progress.status === 'committing' ? '提交 Workflow Commit' : progress.status === 'starting' ? '等待 Run 接纳' : progress.status === 'admitted' ? '已接纳，等待执行开始' : progress.currentNodeId ? nodeTitle : progress.status === 'running' ? '等待下一个 Node Instance' : progress.status === 'succeeded' && resultsLoading ? '加载 Run 结果' : 'Run Closure'
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
  const [project, setProject] = useState<ProjectMetadata>()
  const [draft, setDraft] = useState<WorkflowDraft>()
  const [scienceStatus, setScienceStatus] = useState<'current' | 'stale' | 'unknown'>('unknown')
  const [results] = useState(() => new PublishedResults(client))
  const resultSnapshot = useSyncExternalStore(results.subscribe, results.getSnapshot)
  const { run, index: resultIndex } = resultSnapshot
  const resultsLoading = resultSnapshot.phase === 'loading'
  const resultLoadError = resultSnapshot.phase === 'error' ? workspaceErrorMessage(resultSnapshot.error) : ''
  const resultsAvailable = !!run && (run.outputs.length > 0 || run.artifact_index.length > 0)
  const [runProgress, setRunProgress] = useState<RunProgress>()
  const [runDiagnostics, setRunDiagnostics] = useState<Record<string, Record<string, RunDiagnostic>>>({})
  const attemptNodeIds = useRef<Record<string, Record<string, string>>>({})
  const candidates = resultIndex.collections.flatMap((collection) => collection.items)
  const [nodes, setNodes] = useState<FlowNode[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [prompt, setPrompt] = useState<{ nodeId: string; snapshot: PromptSnapshot; workflow: Workflow }>()
  const [promptOpenError, setPromptOpenError] = useState<{ nodeId: string; message: string }>()
  const promptOpenRevision = useRef(0)
  const [inputSource, setInputSource] = useState<{ projectId: string; workflow: Workflow; mergeTargetNodeId?: string }>()
  const mergeSourceCompletion = useRef<((snapshot: PromptSnapshot | undefined) => void) | undefined>(undefined)
  const [selectionEdit, setSelectionEdit] = useState<{ nodeId: string; workflow: Workflow }>()
  const [parameterChoices, setParameterChoices] = useState<{ workflow: Workflow; values: WorkflowParameterChoices }>()
  const [parameterChoicesError, setParameterChoicesError] = useState('')
  const [view, setView] = useState<'workflow' | 'results'>('workflow')
  const [scopePreview, setScopePreview] = useState<RunScope>()
  const [connection, setConnection] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const [reconnectVersion, setReconnectVersion] = useState(0)
  const [runError, setRunError] = useState('')
  const eventCursors = useRef<Record<string, string>>({})
  const [runOpen, setRunOpen] = useState(false)
  const [projectsOpen, setProjectsOpen] = useState(false)
  const [canvasPicker, setCanvasPicker] = useState<{ x: number; y: number }>()
  const clipboard = useRef<WorkflowFragment | undefined>(undefined)
  const [search, setSearch] = useState('')
  const [paletteTaxonomy, setPaletteTaxonomy] = useState<PaletteTaxonomy>('purpose')
  const [pendingNodeDrop, setPendingNodeDrop] = useState<PendingNodeDrop>()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [saveState, setSaveState] = useState('加载中…')
  const [uiSaveState, setUiSaveState] = useState('加载中…')
  const [saveError, setSaveError] = useState('')
  const [workspace, setWorkspace] = useState<ProjectWorkspace>()
  const [viewedVersion, setViewedVersion] = useState<WorkflowVersionView>()
  const uiStateRef = useRef<JsonObject>({})
  const versionSession = useRef<VersionSession | undefined>(undefined)
  const pendingEdits = useRef(new Set<Promise<unknown>>())
  const saveErrorRef = useRef('')
  const history = useRef<HistoryEntry[]>([])
  const draftRef = useRef<WorkflowDraft | undefined>(undefined)
  const workflowRef = useRef<Workflow | undefined>(undefined)
  const nodesRef = useRef<FlowNode[]>([])
  const edgesRef = useRef<Edge[]>([])
  const projectGeneration = useRef(0)
  const workflowRevision = useRef(0)
  const projectDrafts = useRef<Record<string, WorkflowDraft>>({})
  const projectSaveQueues = useRef<Record<string, Promise<unknown>>>({})
  const personalization = useRef<Promise<{ project: ProjectMetadata; draft: WorkflowDraft }> | undefined>(undefined)
  const reconnectSucceeded = useRef(false)
  const flowInstance = useRef<ReactFlowInstance<FlowNode, Edge> | null>(null)
  const bindingParameterMemory = useRef<Record<string, Record<string, Record<string, Record<string, unknown>>>>>({})
  const activeParameterEdits = useRef(new Set<string>())

  useEffect(() => { draftRef.current = draft }, [draft])
  useEffect(() => { nodesRef.current = nodes }, [nodes])
  useEffect(() => { edgesRef.current = edges }, [edges])

  const choicesProjectId = project?.id
  const choicesWorkflow = draft?.workflow
  useEffect(() => {
    if (!choicesProjectId || !choicesWorkflow || !catalog) return
    let current = true
    setParameterChoicesError('')
    void loadWorkflowParameterChoices(client, choicesProjectId, choicesWorkflow, catalog, run).then(values => {
      if (current) setParameterChoices({ workflow: choicesWorkflow, values })
    }, reason => { if (current) setParameterChoicesError(workspaceErrorMessage(reason)) })
    return () => { current = false }
  }, [choicesProjectId, choicesWorkflow, catalog, run, inputSource])

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
    if (!run) return
    setProject((current) => current?.id === run.project_id && current.latest_run_id !== run.run_id ? { ...current, latest_run_id: run.run_id } : current)
    setRunProgress((progress) => {
      const previous = progress?.projectId === run.project_id && progress.runId === run.run_id ? progress : undefined
      return {
        ...previous,
        status: run.status, scope: run.scope,
        totalNodes: run.scope.execution_node_ids.length,
        completedNodeIds: run.node_dispositions.filter((item) => run.scope.execution_node_ids.includes(item.node_id)).map((item) => item.node_id),
        nodeStates: nodeStatesFromProjection(run, previous ? Object.keys(previous.nodeStates) : workflowRef.current!.nodes.map((node) => node.node_id)),
        projectId: run.project_id, runId: run.run_id, workflowCommitId: run.workflow_commit_id,
        eventCursor: previous?.eventCursor ?? (run.status === 'admitted' || run.status === 'running' ? '' : undefined),
      }
    })
  }, [run])

  const subscribedRun = runProgress?.projectId && runProgress.runId ? `${runProgress.projectId}/${runProgress.runId}` : undefined
  useEffect(() => {
    if (!subscribedRun) return
    const [projectId, runId] = subscribedRun.split('/')
    let disposed = false
    let replaying = true
    let terminalSeen = false
    const socket = client.runEvents(projectId, runId, eventCursors.current[subscribedRun])
    socket.onopen = () => { if (!disposed) setConnection('connected') }
    socket.onclose = () => { if (!disposed && !terminalSeen) setConnection('disconnected') }
    socket.onerror = () => { if (!disposed) setConnection('disconnected') }
    socket.onmessage = (message) => {
      if (disposed) return
      const envelope = JSON.parse(message.data as string) as RunEventEnvelope
      eventCursors.current[subscribedRun] = envelope.cursor
      const event = envelope.event
      setRunProgress((current) => current?.runId === runId ? { ...current, eventCursor: envelope.cursor } : current)
      if (event.type === 'run_started' && !replaying) setRunProgress((current) => current?.runId === runId ? { ...current, status: 'running' } : current)
      if (event.type === 'node_attempt_started') {
        const attempts = attemptNodeIds.current[subscribedRun] ??= {}
        attempts[event.node_attempt_id] = event.node_id
        setRunProgress((current) => current?.runId === runId && ['admitted', 'running'].includes(current.status) ? { ...current, status: 'running', currentNodeId: event.node_id, nodeStates: { ...current.nodeStates, [event.node_id]: { status: 'running' } } } : current)
      }
      if (event.type === 'node_attempt_terminal' && event.error) {
        const nodeId = attemptNodeIds.current[subscribedRun][event.node_attempt_id]
        const diagnostic = event.error
        setRunDiagnostics((current) => ({ ...current, [subscribedRun]: { ...current[subscribedRun], [nodeId]: diagnostic } }))
      }
      if (event.type === 'replay_complete') {
        replaying = false
        void results.refresh()
      }
      if (event.type === 'node_disposition') {
        setRunProgress((current) => {
          if (current?.runId !== runId) return current
          const isExecution = current.scope?.execution_node_ids.includes(event.disposition.node_id) ?? true
          const completedNodeIds = !isExecution || current.completedNodeIds.includes(event.disposition.node_id) ? current.completedNodeIds : [...current.completedNodeIds, event.disposition.node_id]
          const nodeState: NodeRunState = current.scope?.reused_node_ids.includes(event.disposition.node_id) ? { status: 'reused' } : nodeRunStateFromDisposition(event.disposition)
          return { ...current, completedNodeIds, nodeStates: { ...current.nodeStates, [event.disposition.node_id]: nodeState }, lastNodeId: event.disposition.node_id, currentNodeId: current.currentNodeId === event.disposition.node_id ? undefined : current.currentNodeId }
        })
        if (!replaying) void results.refresh()
      }
      if (event.type === 'run_terminal') {
        terminalSeen = true
        setRunProgress((current) => current?.runId === runId ? { ...current, status: event.status, currentNodeId: undefined } : current)
        if (!replaying) void results.refresh()
      }
    }
    return () => { disposed = true; socket.close() }
  }, [results, reconnectVersion, subscribedRun])

  useEffect(() => {
    let current = true
    void (async () => {
      const [catalogValue, capabilityValue, projects] = await Promise.all([client.catalog(), client.authoringCapabilities(), client.projects()])
      const example = projects.projects.find((item) => item.project_kind === 'default_example')
      if (!example) throw new Error('Default example Project is absent')
      const initialWorkspace = await client.projectWorkspace(example.id)
      if (!current) return
      const draftValue = initialWorkspace.draft!
      uiStateRef.current = initialWorkspace.ui_state
      bindingParameterMemory.current[example.id] = initialWorkspace.ui_state.binding_parameter_memory as Record<string, Record<string, Record<string, unknown>>> | undefined ?? {}
      setWorkspace(initialWorkspace)
      const flow = flowFromDraft(draftValue, catalogValue, canvasFromUi(initialWorkspace.ui_state))
      setCatalog(catalogValue)
      setCapabilities(capabilityValue)
      setProject(example)
      draftRef.current = draftValue
      workflowRef.current = draftValue.workflow
      projectDrafts.current[draftValue.project_id] = draftValue
      nodesRef.current = flow.nodes
      edgesRef.current = flow.edges
      setDraft(draftValue)
      setNodes(flow.nodes)
      setEdges(flow.edges)
      if (example.latest_run_id) results.openRun({ project_id: example.id, run_id: example.latest_run_id })
      setSaveState('示例已加载')
      setUiSaveState(initialWorkspace.ui_state_revision ? '布局已保存' : '默认布局')
    })().catch(reason => { if (current) setRunError(workspaceErrorMessage(reason)) })
    return () => { current = false }
  }, [results])

  const reportSaveError = useCallback((reason: unknown) => {
    const message = workspaceErrorMessage(reason)
    saveErrorRef.current = message
    setSaveError(message)
  }, [])
  const trackEdit = useCallback(<T,>(operation: Promise<T>): Promise<T> => {
    pendingEdits.current.add(operation)
    void operation.then(() => pendingEdits.current.delete(operation), (reason) => { pendingEdits.current.delete(operation); reportSaveError(reason) })
    return operation
  }, [reportSaveError])
  const beforeWorkspaceAction = useCallback(async () => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
    while (pendingEdits.current.size) await Promise.all([...pendingEdits.current])
    if (saveErrorRef.current) throw new Error(`存在未保存的修改：${saveErrorRef.current}。请先重试保存。`)
    return true
  }, [])
  const ensurePersonal = useCallback(async () => {
    if (!project || !draftRef.current) throw new Error('Project is not loaded')
    if (project.project_kind === 'personal') return { project, draft: projectDrafts.current[project.id] ?? draftRef.current }
    if (!personalization.current) {
      const generation = projectGeneration.current
      setSaveState('正在创建个人副本…')
      personalization.current = client.copyExample(project.id, `${project.name} · 我的副本`).then(async (copy) => {
        const copiedWorkspace = await client.projectWorkspace(copy.id)
        const copyDraft = copiedWorkspace.draft!
        bindingParameterMemory.current[copy.id] = structuredClone(bindingParameterMemory.current[project.id] ?? copiedWorkspace.ui_state.binding_parameter_memory ?? {}) as Record<string, Record<string, Record<string, unknown>>>
        projectDrafts.current[copy.id] = copyDraft
        if (generation === projectGeneration.current) {
          const workflow = { ...(workflowRef.current ?? copyDraft.workflow), workflow_id: copy.id }
          const activeDraft = { ...copyDraft, workflow }
          workflowRef.current = workflow
          draftRef.current = activeDraft
          setProject(copy)
          setDraft(activeDraft)
          setWorkspace(copiedWorkspace)
          uiStateRef.current = { ...uiStateRef.current, binding_parameter_memory: bindingParameterMemory.current[copy.id] }
          setSaveState('个人副本已保存')
        }
        return { project: copy, draft: copyDraft }
      })
    }
    return personalization.current
  }, [project])

  const saveWorkflow = useCallback((change: (base: WorkflowDraft) => Workflow) => {
    const generation = projectGeneration.current
    const revision = ++workflowRevision.current
    const activeDraft = draftRef.current!
    const workflow = change({ ...activeDraft, workflow: workflowRef.current ?? activeDraft.workflow })
    const editingVersion = versionSession.current
    const editUiState = uiStateRef.current
    workflowRef.current = workflow
    const optimisticDraft = { ...activeDraft, workflow }
    draftRef.current = optimisticDraft
    setDraft(optimisticDraft)
    setSaveState('流程保存中…')
    return trackEdit(ensurePersonal().then((personal) => {
      const previous = projectSaveQueues.current[personal.project.id] ?? Promise.resolve()
      const operation = previous.then(async () => {
        const submitted = { ...workflow, workflow_id: personal.project.id }
        let saved: WorkflowDraft
        if (editingVersion && !editingVersion.forked) {
          const fork = await client.forkVersion(personal.project.id, editingVersion.view.version.version_id, submitted, editUiState, editingVersion.view.return_workspace_revision)
          editingVersion.forked = true
          saved = fork.draft!
          if (generation === projectGeneration.current) { setWorkspace(fork); setViewedVersion(undefined); setUiSaveState('布局已保存') }
        } else {
          saved = await client.saveWorkflowDraft(personal.project.id, submitted)
        }
        projectDrafts.current[personal.project.id] = saved
        const current = generation === projectGeneration.current && revision === workflowRevision.current
        if (current) {
          workflowRef.current = saved.workflow
          draftRef.current = saved
          setDraft(saved)
          setSaveState('已自动保存')
          setWorkspace((value) => value ? { ...value, draft: saved } : value)
        }
        return { project: personal.project, draft: saved, current }
      })
      projectSaveQueues.current[personal.project.id] = operation
      return operation.catch((reason) => { if (generation === projectGeneration.current) setSaveState('流程保存失败'); throw reason })
    }))
  }, [ensurePersonal, trackEdit])

  const persistCanvas = useCallback((nextNodes: FlowNode[], viewport?: CanvasState['viewport']) => {
    const generation = projectGeneration.current
    const editingVersion = versionSession.current
    const revision = workflowRevision.current
    const workflow = workflowRef.current!
    const previousCanvas = canvasFromUi(uiStateRef.current)
    const canvas = canvasFromNodes(nextNodes, viewport ? { ...previousCanvas, viewport } : previousCanvas)
    const uiState = { ...uiStateRef.current, canvas, binding_parameter_memory: bindingParameterMemory.current[project!.id] ?? {} }
    uiStateRef.current = uiState
    setUiSaveState('布局保存中…')
    return trackEdit(ensurePersonal().then((personal) => {
      const previous = projectSaveQueues.current[personal.project.id] ?? Promise.resolve()
      const operation = previous.then(async () => {
        const submittedUiState = { ...uiState, binding_parameter_memory: bindingParameterMemory.current[personal.project.id] ?? {} }
        if (uiStateRef.current === uiState) uiStateRef.current = submittedUiState
        let saved: ProjectWorkspace
        if (editingVersion && !editingVersion.forked) {
          saved = await client.forkVersion(personal.project.id, editingVersion.view.version.version_id, { ...workflow, workflow_id: personal.project.id }, submittedUiState, editingVersion.view.return_workspace_revision)
          editingVersion.forked = true
          projectDrafts.current[personal.project.id] = saved.draft!
          if (generation === projectGeneration.current) { if (revision === workflowRevision.current) { draftRef.current = saved.draft!; setDraft(saved.draft!); setSaveState('旧版修改已另存为当前工作') } setViewedVersion(undefined) }
        } else saved = await client.saveProjectUiState(personal.project.id, submittedUiState)
        if (generation === projectGeneration.current) { setWorkspace(saved); setUiSaveState('布局已保存') }
        return saved
      })
      projectSaveQueues.current[personal.project.id] = operation
      return operation.catch((reason) => { if (generation === projectGeneration.current) setUiSaveState('布局保存失败'); throw reason })
    }))
  }, [ensurePersonal, project, trackEdit])

  const savedPersonalDraft = useCallback(async () => {
    await beforeWorkspaceAction()
    if (versionSession.current && !versionSession.current.forked) await saveWorkflow((base) => base.workflow)
    const personal = await ensurePersonal()
    const pending = projectSaveQueues.current[personal.project.id]
    if (pending) await pending
    return { project: personal.project, draft: projectDrafts.current[personal.project.id] ?? personal.draft }
  }, [beforeWorkspaceAction, ensurePersonal, saveWorkflow])

  const installSavedFlow = useCallback((saved: WorkflowDraft, positionOverrides: Record<string, { x: number; y: number }> = {}) => {
    const canvas = canvasFromNodes(nodesRef.current, canvasFromUi(uiStateRef.current))
    const flow = flowFromDraft(saved, catalog, canvas, positionOverrides)
    const currentNodes = new Map(nodesRef.current.map(node => [node.id, node]))
    // Saving scientific values keeps the mounted canvas nodes and their measured sizes.
    flow.nodes = flow.nodes.map(node => ({ ...node, measured: currentNodes.get(node.id)?.measured }))
    workflowRef.current = saved.workflow
    nodesRef.current = flow.nodes
    edgesRef.current = flow.edges
    setNodes(flow.nodes)
    setEdges(flow.edges)
    uiStateRef.current = { ...uiStateRef.current, canvas: canvasFromNodes(flow.nodes, canvas) }
    return flow
  }, [catalog])
  const openProject = useCallback(async (selected: ProjectMetadata, suppliedWorkspace?: ProjectWorkspace, versionView?: WorkflowVersionView) => {
    await beforeWorkspaceAction()
    const generation = ++projectGeneration.current
    promptOpenRevision.current += 1
    const selectedWorkspace = suppliedWorkspace ?? await client.projectWorkspace(selected.id)
    if (generation !== projectGeneration.current) return
    const selectedDraft = selectedWorkspace.draft ?? { project_id: selected.id, draft_revision: 0, workflow: { schema_version: '2.1.0', workflow_id: selected.id, nodes: [], edges: [], observation_selectors: [], selection_objectives: [] } }
    workflowRevision.current += 1
    results.openRun(undefined)
    const openingResults = results.getSnapshot()
    personalization.current = undefined
    history.current = []
    activeParameterEdits.current.clear()
    versionSession.current = versionView ? { view: versionView, forked: false } : undefined
    setViewedVersion(versionView)
    setWorkspace(selectedWorkspace)
    uiStateRef.current = selectedWorkspace.ui_state
    bindingParameterMemory.current[selected.id] = selectedWorkspace.ui_state.binding_parameter_memory as Record<string, Record<string, Record<string, unknown>>> | undefined ?? {}
    setRunProgress(undefined)
    setPrompt(undefined)
    setPromptOpenError(undefined)
    setRunError('')
    setSelectionEdit(undefined)
    setView('workflow')
    setProjectsOpen(false)
    const canvas = canvasFromUi(selectedWorkspace.ui_state)
    const flow = flowFromDraft(selectedDraft, catalog, canvas)
    setProject(selected)
    draftRef.current = selectedDraft
    workflowRef.current = selectedDraft.workflow
    if (!versionView) projectDrafts.current[selected.id] = selectedDraft
    nodesRef.current = flow.nodes
    edgesRef.current = flow.edges
    setDraft(selectedDraft)
    setNodes(flow.nodes)
    setEdges(flow.edges)
    setSaveState(versionView ? '旧版只读查看' : selectedWorkspace.draft ? '流程已保存' : '空白流程尚未保存')
    setUiSaveState(selectedWorkspace.ui_state_revision ? '布局已保存' : '默认布局')
    requestAnimationFrame(() => { if (canvas.viewport) void flowInstance.current?.setViewport(canvas.viewport); else void flowInstance.current?.fitView({ padding: 0.16 }) })
    let resultProject = selected
    if (!resultProject.latest_run_id && selected.reference_results_project_id) {
      resultProject = (await client.projects()).projects.find((item) => item.id === selected.reference_results_project_id)!
      if (generation !== projectGeneration.current || results.getSnapshot() !== openingResults) return
    }
    if (resultProject.latest_run_id) {
      results.openRun({ project_id: resultProject.id, run_id: resultProject.latest_run_id })
    }
  }, [beforeWorkspaceAction, catalog, results])
  const returnOriginalWork = useCallback(async () => {
    await beforeWorkspaceAction()
    const target = viewedVersion?.return_workspace_revision ?? workspace!.return_workspace_revision!
    const returned = await client.returnWorkspace(project!.id, target)
    await openProject(project!, returned)
  }, [beforeWorkspaceAction, openProject, project, viewedVersion, workspace])
  const createProject = useCallback(async () => {
    await beforeWorkspaceAction()
    const created = await client.createProject(`Untitled Project ${new Date().toLocaleString()}`)
    await client.saveWorkflowDraft(created.id, { schema_version: draftRef.current!.workflow.schema_version, workflow_id: created.id, nodes: [], edges: [], observation_selectors: [], selection_objectives: [] })
    await openProject(created)
  }, [beforeWorkspaceAction, openProject])
  const remember = useCallback(() => { const currentWorkflow = workflowRef.current!; history.current.push({ workflow: structuredClone(currentWorkflow), nodes: structuredClone(nodesRef.current), edges: structuredClone(edgesRef.current) }) }, [])
  const saveParameter = useCallback(async (nodeId: string, parameter: Parameter, raw: string) => { if (!catalog) return; const result = await saveWorkflow((base) => { const source = base.workflow.nodes.find((item) => item.node_id === nodeId)!; const field = parameter.scope === 'node' ? 'node_parameters' : 'binding_parameters'; const values = { ...source[field] }; if (raw === '') delete values[parameter.key]; else values[parameter.key] = parameterInputValue(raw, parameter.valueType); if (parameter.scope === 'binding') { const projectMemory = bindingParameterMemory.current[base.project_id] ??= {}; const nodeMemory = projectMemory[nodeId] ??= {}; nodeMemory[source.binding_id] = values } return { ...base.workflow, nodes: base.workflow.nodes.map((item): WorkflowNode => item.node_id === nodeId ? { ...item, [field]: values } : item) } }); if (result.current) { const flow = installSavedFlow(result.draft); await persistCanvas(flow.nodes) } }, [catalog, installSavedFlow, persistCanvas, saveWorkflow])
  const saveBinding = useCallback(async (nodeId: string, bindingId: string) => { if (!catalog) return; remember(); const result = await saveWorkflow((base) => { const source = base.workflow.nodes.find((item) => item.node_id === nodeId)!; const projectMemory = bindingParameterMemory.current[base.project_id] ??= {}; const nodeMemory = projectMemory[nodeId] ??= {}; nodeMemory[source.binding_id] = source.binding_parameters; return selectNodeBinding(base.workflow, nodeId, bindingId, catalog, nodeMemory[bindingId]) }); const selected = result.draft.workflow.nodes.find((item) => item.node_id === nodeId)!; const projectMemory = bindingParameterMemory.current[result.project.id] ??= {}; const nodeMemory = projectMemory[nodeId] ??= {}; nodeMemory[bindingId] = selected.binding_parameters; if (result.current) { const flow = installSavedFlow(result.draft); await persistCanvas(flow.nodes) } }, [catalog, installSavedFlow, persistCanvas, remember, saveWorkflow])
  const addDroppedNode = useCallback(async (drop: PendingNodeDrop, bindingId: string) => { if (!catalog) return; remember(); const nodeId = `${drop.nodeTypeId.replaceAll('.', '-')}-${crypto.randomUUID().slice(0, 8)}`; const result = await saveWorkflow((base) => insertOrdinaryNode(base.workflow, nodeId, drop.nodeTypeId, bindingId, catalog)); if (result.current) { const flow = installSavedFlow(result.draft, { [nodeId]: drop.position }); await persistCanvas(flow.nodes); setPendingNodeDrop(undefined) } }, [catalog, installSavedFlow, persistCanvas, remember, saveWorkflow])
  const saveFlowEdges = useCallback(async (nextEdges: Edge[]) => { if (!catalog) return; const result = await saveWorkflow((base) => ({ ...base.workflow, edges: workflowEdgesFromFlow(nextEdges) })); if (result.current) { const flow = installSavedFlow(result.draft); await persistCanvas(flow.nodes) } }, [catalog, installSavedFlow, persistCanvas, saveWorkflow])
  const deleteWorkflowElements = useCallback(async (deletedNodes: FlowNode[], deletedEdges: Edge[]) => {
    if (!catalog || (deletedNodes.length === 0 && deletedEdges.length === 0)) return
    const removedNodeIds = new Set(deletedNodes.map((node) => node.id))
    const removedEdgeIds = new Set(deletedEdges.map((edge) => edge.id))
    const remainingEdges = edgesRef.current.filter((edge) => !removedEdgeIds.has(edge.id) && !removedNodeIds.has(edge.source) && !removedNodeIds.has(edge.target))
    const result = await saveWorkflow((base) => ({ ...removeWorkflowNodes(base.workflow, removedNodeIds, catalog).workflow, edges: workflowEdgesFromFlow(remainingEdges) }))
    if (result.current) { const flow = installSavedFlow(result.draft); await persistCanvas(flow.nodes) }
  }, [catalog, installSavedFlow, persistCanvas, saveWorkflow])
  const dropPaletteNode = useCallback((event: React.DragEvent) => { if (!catalog || !flowInstance.current) return; event.preventDefault(); const nodeTypeId = event.dataTransfer.getData('application/protein-workbench-node-type'); if (!nodeTypeId) return; const point = flowInstance.current.screenToFlowPosition({ x: event.clientX, y: event.clientY }); const drop = { nodeTypeId, position: { x: point.x - 137, y: point.y - 30 }, bindings: bindingOptions(catalog, nodeTypeId) }; if (drop.bindings.length === 1) void addDroppedNode(drop, drop.bindings[0].id).catch(reportSaveError); else setPendingNodeDrop(drop) }, [addDroppedNode, catalog, reportSaveError])
  const addPaletteNode = (nodeTypeId: string) => {
    const point = flowInstance.current!.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
    const drop = { nodeTypeId, position: { x: point.x - 137, y: point.y - 30 }, bindings: bindingOptions(catalog!, nodeTypeId) }
    if (drop.bindings.length === 1) void addDroppedNode(drop, drop.bindings[0].id).catch(reportSaveError)
    else setPendingNodeDrop(drop)
  }
  const undo = useCallback(() => { const previous = history.current.pop(); if (!previous) return; nodesRef.current = previous.nodes; edgesRef.current = previous.edges; setNodes(previous.nodes); setEdges(previous.edges); void saveWorkflow(() => previous.workflow).then((result) => { if (result.current) { nodesRef.current = previous.nodes; edgesRef.current = previous.edges; setNodes(previous.nodes); setEdges(previous.edges); void persistCanvas(previous.nodes).catch(reportSaveError); setSaveState('已撤销画布修改') } }).catch(reportSaveError) }, [persistCanvas, reportSaveError, saveWorkflow])
  const openPromptEditor = useCallback((nodeId: string) => {
    const generation = projectGeneration.current
    const revision = ++promptOpenRevision.current
    const current = () => generation === projectGeneration.current && revision === promptOpenRevision.current
    setPromptOpenError(undefined)
    void (async () => {
      await beforeWorkspaceAction()
      if (!current()) return
      const currentWorkflow = workflowRef.current!
      const currentWorkflowRevision = workflowRevision.current
      const snapshot = await client.openPrompt(draftRef.current!.project_id, nodeId, currentWorkflow)
      if (!current()) return
      if (currentWorkflowRevision !== workflowRevision.current) {
        setPromptOpenError({ nodeId, message: '流程已更改，请重新打开 Prompt Studio。' })
        return
      }
      setPrompt({ nodeId, snapshot, workflow: currentWorkflow })
    })().catch(reason => { if (current()) setPromptOpenError({ nodeId, message: workspaceErrorMessage(reason) }) })
  }, [beforeWorkspaceAction])
  const openSelectionEditor = useCallback(async (nodeId: string) => {
    const generation = projectGeneration.current
    await beforeWorkspaceAction()
    if (generation !== projectGeneration.current) return
    if (results.getSnapshot().phase !== 'idle') {
      const snapshot = await results.ensureCandidates({ all: true })
      if (!snapshot || generation !== projectGeneration.current) return
    }
    setSelectionEdit({ nodeId, workflow: workflowRef.current! })
  }, [beforeWorkspaceAction, results])
  const displayed = useMemo<FlowNode[]>(() => nodes.map((node) => {
    const sourceNode = draft?.workflow.nodes.find((item) => item.node_id === node.data.sourceNodeId)
    return { ...node, data: { ...node.data, parameterChoices: parameterChoices && parameterChoices.workflow === draft?.workflow && !parameterChoicesError ? parameterChoices.values[node.id] : { choices: {}, ...(parameterChoicesError ? { notice: `参数来源读取失败：${parameterChoicesError}` } : {}) }, bindingOptions: catalog && sourceNode ? bindingOptions(catalog, sourceNode.node_type_id) : [], runState: runProgress?.nodeStates[node.data.sourceNodeId], scopeState: scopePreview?.reused_node_ids.includes(node.id) ? 'reuse' : scopePreview?.execution_node_ids.includes(node.id) ? 'execute' : undefined, onEditSelection: sourceNode && selectionNodeTypes.has(sourceNode.node_type_id) ? () => { void openSelectionEditor(node.id).catch(reportSaveError) } : undefined, onToggle: (id: string) => { remember(); const next = nodesRef.current.map((item) => item.id === id ? { ...item, data: { ...item.data, collapsed: !item.data.collapsed } } : item); nodesRef.current = next; setNodes(next); void persistCanvas(next).catch(reportSaveError) }, onEditPrompt: () => openPromptEditor(node.id), onParameter: (nodeId: string, changed: Parameter, value: string, commit: boolean) => { const editKey = `${nodeId}:${changed.scope}:${changed.key}`; if (!commit && !activeParameterEdits.current.has(editKey)) { remember(); workflowRevision.current += 1; activeParameterEdits.current.add(editKey) } const next = nodesRef.current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, parameters: item.data.parameters.map((parameter) => parameter.key === changed.key && parameter.scope === changed.scope ? { ...parameter, value } : parameter) } } : item); nodesRef.current = next; setNodes(next); if (commit && activeParameterEdits.current.delete(editKey)) void saveParameter(nodeId, changed, value).catch(reportSaveError) }, onBinding: (nodeId: string, bindingId: string) => { void saveBinding(nodeId, bindingId).catch(reportSaveError) } } }
  }), [nodes, parameterChoices, parameterChoicesError, draft, catalog, runProgress?.nodeStates, scopePreview, openSelectionEditor, openPromptEditor, persistCanvas, remember, reportSaveError, saveBinding, saveParameter])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (view !== 'workflow' || runOpen || prompt || inputSource || projectsOpen || selectionEdit || event.defaultPrevented || target?.closest('input, textarea, select, [contenteditable="true"]')) return
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'c' && catalog) {
        const selected = new Set(nodesRef.current.filter((node) => node.selected).map((node) => node.id))
        if (selected.size) { event.preventDefault(); clipboard.current = copyWorkflowFragment(workflowRef.current!, selected, catalog, Object.fromEntries(nodesRef.current.map((node) => [node.id, node.position]))) }
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'v' && clipboard.current) {
        event.preventDefault(); remember()
        const pasted = pasteWorkflowFragment(workflowRef.current!, clipboard.current, { x: 120, y: 160 })
        void saveWorkflow(() => pasted.workflow).then((result) => { if (result.current) { const pastedFlow = installSavedFlow(result.draft, pasted.positions); void persistCanvas(pastedFlow.nodes).catch(reportSaveError); setSaveState(pasted.notices.length ? '片段已粘贴；外部来源的选择配置需要重新连接' : '片段已粘贴') } }).catch(reportSaveError)
      }
      if ((event.metaKey || event.ctrlKey) && !event.shiftKey && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        undo()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [catalog, inputSource, installSavedFlow, persistCanvas, projectsOpen, prompt, selectionEdit, remember, reportSaveError, runOpen, saveWorkflow, undo, view])
  const saveSelectionWorkflow = useCallback(async (nextWorkflow: Workflow) => {
    remember()
    const result = await saveWorkflow(() => nextWorkflow)
    if (result.current) { const flow = installSavedFlow(result.draft); await persistCanvas(flow.nodes) }
    setSaveState('筛选配置已保存为流程')
  }, [installSavedFlow, persistCanvas, remember, saveWorkflow])
  const openInputSource = useCallback(async () => {
    await beforeWorkspaceAction()
    const personal = await ensurePersonal()
    setInputSource({ projectId: personal.project.id, workflow: { ...workflowRef.current!, workflow_id: personal.project.id } })
  }, [beforeWorkspaceAction, ensurePersonal])
  const addMergeSource = useCallback(async (document: PromptAuthoringDocument) => {
    const personal = await ensurePersonal()
    const staged = {
      ...prompt!.workflow,
      workflow_id: personal.project.id,
      nodes: prompt!.workflow.nodes.map((node) => node.node_id === prompt!.nodeId ? { ...node, node_parameters: { ...node.node_parameters, [promptAuthorDocumentParameter]: document } } : node),
    }
    return new Promise<PromptSnapshot | undefined>((resolve) => {
      mergeSourceCompletion.current = resolve
      setInputSource({ projectId: personal.project.id, workflow: staged, mergeTargetNodeId: prompt!.nodeId })
    })
  }, [ensurePersonal, prompt])
  const prepareSourcePrompt = useCallback(async (plan: PromptSourcePlan) => {
    const snapshot = await client.openPrompt(inputSource!.projectId, plan.nodeId, plan.workflow)
    setPrompt({ nodeId: plan.nodeId, snapshot, workflow: plan.workflow })
    setInputSource(undefined)
    mergeSourceCompletion.current?.(snapshot)
    mergeSourceCompletion.current = undefined
  }, [inputSource])
  const importSourceCandidates = useCallback(async (plan: CandidateInputPlan) => {
    remember()
    const result = await saveWorkflow(() => plan.workflow)
    if (result.current) { const flow = installSavedFlow(result.draft); await persistCanvas(flow.nodes) }
    setInputSource(undefined)
  }, [installSavedFlow, persistCanvas, remember, saveWorkflow])
  const closeInputSource = useCallback(() => {
    setInputSource(undefined)
    mergeSourceCompletion.current?.(undefined)
    mergeSourceCompletion.current = undefined
  }, [])
  const validConnection = useCallback((connection: Connection | Edge) => {
    const source = displayed.find((node) => node.id === connection.source)!
    const target = displayed.find((node) => node.id === connection.target)!
    const sourcePort = connection.sourceHandle!.slice(4)
    const targetPort = connection.targetHandle!.slice(3)
    return source.data.outputPortTypes[sourcePort] === target.data.inputPortTypes[targetPort]
  }, [displayed])
  const palette = useMemo(() => catalog && capabilities ? projectPalette(catalog, capabilities, paletteTaxonomy, search) : [], [catalog, capabilities, paletteTaxonomy, search])
  const progressNodeTitle = useMemo(() => {
    if (!runProgress?.currentNodeId || !draft || !catalog) return ''
    const node = draft.workflow.nodes.find((item) => item.node_id === runProgress.currentNodeId)
    const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'node_type' && contract.reference.contract_id === node?.node_type_id)?.descriptor
    return String(descriptor?.title ?? node?.node_type_id ?? runProgress.currentNodeId)
  }, [catalog, draft, runProgress?.currentNodeId])
  const runActive = runProgress ? ['committing', 'starting', 'admitted', 'running'].includes(runProgress.status) : false
  const pendingNodeTitle = pendingNodeDrop && catalog ? nodeTypePresentation(catalog, pendingNodeDrop.nodeTypeId).title : ''
  const inputSourceDialog = inputSource && catalog && <InputSourceDialog projectId={inputSource.projectId} workflow={inputSource.workflow} catalog={catalog} client={client} mergeTargetNodeId={inputSource.mergeTargetNodeId} onPreparePrompt={prepareSourcePrompt} onImportCandidates={importSourceCandidates} onClose={closeInputSource} />

  if (!project || !draft) return <div className="loading-screen">{runError ? <p role="alert">{runError}</p> : '正在从 public v2 protocol 加载 WebUI 示例…'}</div>
  if (prompt) {
    const promptVersionContext = (): PromptVersionContext | undefined => {
      const session = versionSession.current
      return session && !session.forked ? { version_id: session.view.version.version_id, return_workspace_revision: session.view.return_workspace_revision, ui_state: uiStateRef.current } : undefined
    }
    return <><PromptStudio snapshot={prompt.snapshot} onCancel={() => setPrompt(undefined)} onAddMergeSource={addMergeSource} onPreview={async (document) => {
      const personal = await ensurePersonal()
      return client.previewPrompt(personal.project.id, prompt.nodeId, document, { ...prompt.workflow, workflow_id: personal.project.id }, promptVersionContext())
    }} onApply={async (preview) => {
      const personal = await ensurePersonal()
      const context = promptVersionContext()
      const applied = await client.applyPrompt(personal.project.id, prompt.nodeId, preview, prompt.snapshot.draft_revision, { ...prompt.workflow, workflow_id: personal.project.id }, context)
      remember()
      if (context) { versionSession.current!.forked = true; setViewedVersion(undefined) }
      const savedWorkspace = await client.projectWorkspace(personal.project.id)
      setWorkspace(savedWorkspace)
      projectDrafts.current[personal.project.id] = applied.draft
      draftRef.current = applied.draft
      setDraft(applied.draft)
      const flow = installSavedFlow(applied.draft)
      await persistCanvas(flow.nodes)
      setPrompt(undefined)
      setSaveState('Prompt 已保存')
      if (context) setUiSaveState('布局已保存')
    }} />{inputSourceDialog}</>
  }
  if (view === 'results' && run && catalog) return <ResultsWorkbench key={`${run.project_id}/${run.run_id}`} results={results} run={run} index={resultIndex} loading={resultsLoading} loadError={resultLoadError} catalog={{ contracts: resultIndex.definitions, availability: [] }} scienceStatus={scienceStatus} workflow={draft.workflow} authoringCatalog={catalog} onBack={() => setView('workflow')} onSaveWorkflow={saveSelectionWorkflow} />
  return <div className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark"><Braces size={16} /></span><div><strong>Protein</strong><span>Workbench</span></div></div><div className="project-identity"><div><span className="page-kicker">{project.project_kind.replace('_', ' ')}</span><strong>{project.name}</strong></div>{project.seed && <span className="immutable-pill">只读示例</span>}</div><nav className="view-tabs"><button className="active"><Network size={14} /> Workflow</button><button disabled={!run || run.outputs.length === 0 && run.artifact_index.length === 0} onClick={() => setView('results')}><Activity size={14} /> Results <span>{candidates.length}</span></button></nav><div className="top-actions"><span className="save-state" aria-label="流程保存状态"><span />{saveState}</span><span className="save-state" aria-label="布局保存状态"><span />{uiSaveState}</span><button className="icon-button" aria-label="撤销画布修改" onClick={undo}><RotateCcw size={16} /></button><button className="secondary-button" onClick={() => { void beforeWorkspaceAction().then(() => setProjectsOpen(true)).catch(reportSaveError) }}><FolderOpen size={14} /> 项目</button><button className="run-button" disabled={runActive} onClick={() => setRunOpen(true)}>{runActive ? <LoaderCircle size={14} /> : <Play size={14} />} {runActive ? '运行中' : '运行流程'}</button></div></header>
    {(viewedVersion || workspace?.return_workspace_revision !== null && workspace?.return_workspace_revision !== undefined) && <div className="version-work-banner" role="status"><span>{viewedVersion ? `正在查看版本“${viewedVersion.version.name}”；首次修改将另存为当前工作。` : '当前工作由旧版本继续，原工作仍然保留。'}</span><button onClick={() => void returnOriginalWork().catch(reportSaveError)}>返回原工作</button></div>}
    {saveError && <div className="workspace-error" role="alert">{saveError}<button onClick={() => {
      const currentWorkflow = workflowRef.current!
      const currentNodes = nodesRef.current
      delete projectSaveQueues.current[project.id]
      saveErrorRef.current = ''
      setSaveError('')
      void saveWorkflow(() => currentWorkflow).then(() => persistCanvas(currentNodes)).catch(reportSaveError)
    }}>重试保存</button></div>}
    {runProgress && <RunProgressBar progress={runProgress} nodeTitle={progressNodeTitle} resultsLoading={resultsLoading} resultsAvailable={resultsAvailable} onResults={() => setView('results')} onCancel={() => { void client.cancelRun(runProgress.projectId!, runProgress.runId!).catch((reason) => setRunError(JSON.stringify(reason))) }} />}
    {runActive && connection === 'disconnected' && <div className="run-connection-error" role="status">运行状态连接已断开；Run 仍可能在执行。<button onClick={() => { setConnection('connecting'); setReconnectVersion((value) => value + 1) }}>从已接收位置重新连接</button></div>}
    {runError && <pre role="alert">{runError}</pre>}
    {resultLoadError && <pre role="alert">{resultLoadError}</pre>}
    {promptOpenError && <div className="workspace-error" role="alert">无法打开节点 {promptOpenError.nodeId} 的 Prompt：{promptOpenError.message}<button onClick={() => openPromptEditor(promptOpenError.nodeId)}>重新打开</button><button onClick={() => setPromptOpenError(undefined)}>关闭提示</button></div>}
    {subscribedRun && <RunDiagnostics errors={runDiagnostics[subscribedRun] ?? {}} onFocus={(nodeId) => { setNodes((current) => current.map((node) => ({ ...node, selected: node.id === nodeId }))); void flowInstance.current?.fitView({ nodes: [{ id: nodeId }], duration: 250 }) }} />}
    <div className="workspace-shell"><aside className={`palette ${sidebarOpen ? '' : 'closed'}`}><header><div><span className="page-kicker">OPERATION PALETTE</span><h2>研究操作</h2></div><button className="icon-button" onClick={() => setSidebarOpen(false)}><PanelLeftClose size={16} /></button></header><div className="palette-search"><Search size={15} /><input placeholder="搜索 active Catalog…" value={search} onChange={(event) => setSearch(event.target.value)} /></div><div className="taxonomy-switch"><button className={paletteTaxonomy === 'purpose' ? 'active' : ''} onClick={() => setPaletteTaxonomy('purpose')}>按研究目的</button><button className={paletteTaxonomy === 'provider' ? 'active' : ''} onClick={() => setPaletteTaxonomy('provider')}>按包 / 模型</button></div><div className="palette-section"><span className="section-label">ACTIVE CATALOG</span>{palette.map((group) => <section className="palette-group" key={group.label}><span className="palette-group-title">{group.label}</span>{group.entries.map((item) => <button className="palette-item" key={`${group.label}-${item.id}`} onClick={() => addPaletteNode(item.id)} draggable onDragStart={(event) => { event.dataTransfer.setData('application/protein-workbench-node-type', item.id); event.dataTransfer.effectAllowed = 'move' }}><span className="palette-icon"><Atom size={16} /></span><span><strong>{item.title}</strong><small>{paletteTaxonomy === 'purpose' ? item.purpose : group.label}</small></span><Plus size={14} /></button>)}</section>)}</div><div className="catalog-status"><span className="status-light" /><div><strong>Active Catalog</strong><small>{catalog?.contracts.length} contracts</small></div><CircleHelp size={14} /></div></aside>
      <main className="flow-canvas">{!sidebarOpen && <button className="floating-open" onClick={() => setSidebarOpen(true)}><ChevronRight size={16} /></button>}<ReactFlow nodes={displayed} edges={edges} nodeTypes={{ workflow: WorkflowCard }} isValidConnection={validConnection} onInit={(instance) => { flowInstance.current = instance; const viewport = canvasFromUi(uiStateRef.current).viewport; if (viewport) requestAnimationFrame(() => void instance.setViewport(viewport)) }} onMoveEnd={(event, viewport) => { if (event) void persistCanvas(nodesRef.current, viewport).catch(reportSaveError) }} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move' }} onDrop={dropPaletteNode} onPaneContextMenu={(event) => { event.preventDefault(); setCanvasPicker({ x: event.clientX, y: event.clientY }) }} onNodeDragStart={remember} onBeforeDelete={async () => { remember(); return true }} onDelete={({ nodes: deletedNodes, edges: deletedEdges }) => { void deleteWorkflowElements(deletedNodes, deletedEdges).catch(reportSaveError) }} onNodesChange={(changes: NodeChange<FlowNode>[]) => { const next = applyNodeChanges(changes, nodesRef.current); nodesRef.current = next; setNodes(next); if (changes.some((change) => change.type === 'position' && change.dragging === false)) void persistCanvas(next).catch(reportSaveError) }} onEdgesChange={(changes: EdgeChange<Edge>[]) => { const next = applyEdgeChanges(changes, edgesRef.current); edgesRef.current = next; setEdges(next) }} onConnect={(connection: Connection) => { remember(); const target = nodesRef.current.find((node) => node.id === connection.target)!; const targetPort = connection.targetHandle!.slice(3); const available = target.data.inputMultiplicities[targetPort] === 'many' ? edgesRef.current : edgesRef.current.filter((edge) => edge.target !== connection.target || edge.targetHandle !== connection.targetHandle); const next = addEdge({ ...connection, type: 'default' }, available); edgesRef.current = next; setEdges(next); void saveFlowEdges(next).catch(reportSaveError) }} onReconnectStart={() => { reconnectSucceeded.current = false }} onReconnect={(edge, connection) => { reconnectSucceeded.current = true; remember(); const next = reconnectEdge(edge, connection, edgesRef.current); edgesRef.current = next; setEdges(next); void saveFlowEdges(next).catch(reportSaveError) }} onReconnectEnd={(_, edge) => { if (!reconnectSucceeded.current) { remember(); const next = edgesRef.current.filter((item) => item.id !== edge.id); edgesRef.current = next; setEdges(next); void saveFlowEdges(next).catch(reportSaveError) } reconnectSucceeded.current = false }} fitView fitViewOptions={{ padding: 0.16 }} minZoom={0.28} maxZoom={1.5} deleteKeyCode={['Backspace', 'Delete']} selectionOnDrag><Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#39413b" /><MiniMap nodeColor={(node) => String(node.data.accent)} maskColor="rgba(14,16,14,.72)" /><Controls showInteractive={false} /><Panel position="top-left" className="canvas-heading"><span className="page-kicker">WORKFLOW DRAFT · {nodes.length} GRAPH NODES</span><h1>{project.name}</h1><p>{draft.workflow.edges.length} persisted edges · exact Catalog Port compatibility</p></Panel><Panel position="top-right" className="canvas-tools"><button onClick={() => void openInputSource().catch(reportSaveError)}><Plus size={14} /> 添加来源</button><button onClick={() => setCanvasPicker({ x: 350, y: 160 })}><Search size={14} /> 添加节点</button><button onClick={() => void flowInstance.current?.fitView({ padding: 0.16 })}><Layers3 size={14} /> 适合视图</button></Panel><Panel position="bottom-center" className="canvas-hint"><Zap size={13} /> 拖动端口以重新连接 · Delete 删除 · ⌘Z 撤销</Panel></ReactFlow></main>
      <aside className="run-peek"><header><div><span className="page-kicker">LATEST RUN</span><h3>最近结果</h3></div>{run && <span className={run.status === 'succeeded' ? 'success-dot' : 'run-status-label'}>{run.status === 'succeeded' ? <Check size={11} /> : run.status}</span>}</header><div className="run-peek-visual"><div className="result-count-preview"><strong>{candidates.length}</strong><span>已发布候选 · 按需打开结构</span></div><span>{run?.run_id}</span></div><div className="run-funnel">{(run?.selection_results ?? []).map((selection, index, all) => <span key={selection.selection_node_id}>{selection.selection_node_id}<strong>{selection.selected_candidate_ids.length}</strong>{index < all.length - 1 && <ChevronRight size={13} />}</span>)}</div>{run && <div className="old-result-note"><Info size={14} /><span>{scienceStatus === 'current' ? '与当前科学流程一致' : scienceStatus === 'stale' ? '来自修改前的科学流程' : '结果一致性待确认'}</span><small>{run.workflow_commit_id}</small></div>}<button className="view-results-button" disabled={!run || run.outputs.length === 0 && run.artifact_index.length === 0} onClick={() => setView('results')}><Activity size={14} /> 打开 Results Workbench <ChevronRight size={14} /></button></aside></div>
    {inputSourceDialog}
    {selectionEdit && catalog && <div className="modal-backdrop"><section className="run-dialog" role="dialog" aria-modal="true" aria-label="编辑流程筛选" style={{ maxHeight: '90vh', overflow: 'auto', width: 'min(900px, 94vw)' }}>{saveError && <p role="alert">{saveError}</p>}<SelectionEditor key={selectionEdit.nodeId} catalog={catalog} workflow={selectionEdit.workflow} nodeId={selectionEdit.nodeId} candidateCollections={resultIndex.collections} onCancel={() => setSelectionEdit(undefined)} onChange={(next) => { void saveSelectionWorkflow(next).then(() => setSelectionEdit(undefined)).catch(reportSaveError) }} /></section></div>}
    {canvasPicker && catalog && capabilities && <CanvasOperationPicker catalog={catalog} capabilities={capabilities} position={canvasPicker} onClose={() => setCanvasPicker(undefined)} onChoose={(nodeTypeId) => { const position = flowInstance.current!.screenToFlowPosition(canvasPicker); const drop = { nodeTypeId, position, bindings: bindingOptions(catalog, nodeTypeId) }; setCanvasPicker(undefined); if (drop.bindings.length === 1) void addDroppedNode(drop, drop.bindings[0].id).catch(reportSaveError); else setPendingNodeDrop(drop) }} />}
    {runOpen && <RunDialog selectedNodeIds={nodes.filter((node) => node.selected).map((node) => node.id)} sourceRunId={run && run.project_id === project.id && !['admitted', 'running'].includes(run.status) ? run.run_id : undefined} onClose={() => { setRunOpen(false); setScopePreview(undefined) }} onFocus={(nodeId) => { void flowInstance.current?.fitView({ nodes: [{ id: nodeId }], duration: 250 }); setNodes((current) => current.map((node) => ({ ...node, selected: node.id === nodeId }))) }} onPrepare={async (request) => {
      const personal = await savedPersonalDraft()
      const commit = await client.commitWorkflow(personal.project.id, personal.draft.workflow)
      const preview = await client.previewRunScope(personal.project.id, commit.workflow_commit_id, request)
      setScopePreview(preview.scope)
      return { projectId: personal.project.id, request, preview }
    }} onStart={async ({ projectId, request, preview }) => {
      const receipt = await client.startRun(projectId, preview.workflow_commit_id, request)
      eventCursors.current[`${receipt.project_id}/${receipt.run_id}`] = receipt.event_cursor
      results.openRun({ project_id: receipt.project_id, run_id: receipt.run_id })
      setRunError(''); setConnection('connecting'); setSelectionEdit(undefined)
      setRunProgress({ status: 'admitted', scope: preview.scope, totalNodes: preview.scope.execution_node_ids.length, completedNodeIds: [], nodeStates: Object.fromEntries(draft.workflow.nodes.map((node) => [node.node_id, { status: preview.scope.execution_node_ids.includes(node.node_id) ? 'waiting' as const : preview.scope.reused_node_ids.includes(node.node_id) ? 'reused' as const : 'outside' as const }])), projectId: receipt.project_id, runId: receipt.run_id, workflowCommitId: receipt.workflow_commit_id, eventCursor: receipt.event_cursor })
      setRunOpen(false); setScopePreview(undefined)
    }} />}
    {pendingNodeDrop && <div className="modal-backdrop"><section className="run-dialog binding-dialog" role="dialog" aria-modal="true" aria-labelledby="binding-dialog-title"><header><span className="dialog-icon"><Atom size={18} /></span><div><span className="page-kicker">EXECUTION BINDING</span><h2 id="binding-dialog-title">为 {pendingNodeTitle} 选择执行模型</h2></div><button className="icon-button" onClick={() => setPendingNodeDrop(undefined)}><X size={18} /></button></header><div className="binding-choice-list">{pendingNodeDrop.bindings.map((binding) => <button key={binding.id} title={binding.availabilityReason?.message} onClick={() => void addDroppedNode(pendingNodeDrop, binding.id).catch(reportSaveError)}><strong>{binding.label}{binding.available ? '' : '（不可用）'}</strong><small>{binding.id}</small>{binding.availabilityReason?.message && <p>{binding.availabilityReason.message}</p>}</button>)}</div><footer><button className="secondary-button" onClick={() => setPendingNodeDrop(undefined)}>取消</button></footer></section></div>}
    {projectsOpen && <ProjectWorkspaceDialog api={client} currentProjectId={project.id} beforeAction={beforeWorkspaceAction} onOpenProject={openProject} onViewVersion={(selected, version) => openProject(selected, version.workspace, version)} onWorkspaceReturned={(selected, returned) => openProject(selected, returned)} onProjectChanged={(updated, deletedId) => {
      if (updated?.id === project.id) setProject(updated)
      if (deletedId === project.id) void client.projects().then((available) => openProject(available.projects.find((item) => item.project_kind === 'default_example')!)).catch(reportSaveError)
    }} onCreateProject={createProject} onClose={() => setProjectsOpen(false)} />}

  </div>
}

export default App
