import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Background, BackgroundVariant, Controls, Handle, MiniMap, Panel, Position, ReactFlow, addEdge, applyEdgeChanges, applyNodeChanges, reconnectEdge, type Connection, type Edge, type EdgeChange, type Node, type NodeChange, type NodeProps, type ReactFlowInstance } from '@xyflow/react'
import { Activity, Atom, Braces, Check, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Download, FolderOpen, GitBranch, Info, Layers3, LoaderCircle, Menu, MoreHorizontal, Network, PanelLeftClose, Play, Plus, RotateCcw, Search, SlidersHorizontal, Target, TestTubeDiagonal, X, Zap } from 'lucide-react'
import { strToU8, zipSync } from 'fflate'
import { PromptStudio } from './PromptStudio'
import { PublicV2Client, type AuthoringCapabilities, type CatalogSnapshot, type ContractReference, type JsonObject, type NodeDisposition, type ProjectMetadata, type PromptSnapshot, type RunEventEnvelope, type RunProjection, type RunStatus, type Workflow, type WorkflowDraft, type WorkflowNode } from './protocol/client'
import { StructureViewer } from './StructureViewer'
import { bindingOptions, insertOrdinaryNode, nodeTypePresentation, parameterPresentations, projectPalette, selectNodeBinding, type BindingOption, type PaletteTaxonomy, type ParameterPresentation } from './workflow-authoring'

const client = new PublicV2Client()
type Parameter = ParameterPresentation & { suffix?: string }
type NodeRunStatus = 'waiting' | 'running' | 'succeeded' | 'failed' | 'blocked' | 'cancelled' | 'interrupted'
type NodeRunState = { status: NodeRunStatus; blockedBy?: string[]; resolution?: 'executed' | 'cache_replayed' }
type WorkflowNodeData = Record<string, unknown> & { kind: 'prompt' | 'ordinary'; eyebrow: string; title: string; subtitle: string; index: string; inputs: string[]; outputs: string[]; inputPortTypes: Record<string, string>; inputMultiplicities: Record<string, string>; outputPortTypes: Record<string, string>; parameters: Parameter[]; accent: string; count: string; sourceNodeId: string; bindingId?: string; bindingOptions?: BindingOption[]; runMemberNodeIds: string[]; managedMembers?: string[]; collapsed?: boolean; runState?: NodeRunState; onToggle?: (id: string) => void; onEditPrompt?: () => void; onParameter?: (id: string, parameter: Parameter, value: string, commit: boolean) => void; onBinding?: (nodeId: string, bindingId: string) => void }
type FlowNode = Node<WorkflowNodeData>
type CandidateView = { id: string; parent: string; pdb: string; sequence: string; metadata: JsonObject }
type ScoreView = { candidateId: string; metricId: string; methodId: string; context: JsonObject; value: number }
type RunProgress = { status: 'committing' | 'starting' | RunStatus; totalNodes: number; completedNodeIds: string[]; nodeStates: Record<string, NodeRunState>; currentNodeId?: string; lastNodeId?: string; projectId?: string; runId?: string; workflowCommitId?: string; eventCursor?: string; resultsReady?: boolean }
type PendingNodeDrop = { nodeTypeId: string; position: { x: number; y: number }; bindings: BindingOption[] }
type HistoryEntry = { workflow: Workflow; nodes: FlowNode[]; edges: Edge[] }

type CanvasState = { positions: Record<string, { x: number; y: number }>; collapsed: string[] }
const categoryColors: Record<string, string> = { generation: '#55c8b7', selection: '#e7b75f', structure_comparison: '#71a8ff', structure_prediction: '#71a8ff', collection_ops: '#92a79a' }

function canvasState(projectId: string): CanvasState {
  return JSON.parse(localStorage.getItem(`protein-workbench.canvas.${projectId}`) ?? '{"positions":{},"collapsed":[]}') as CanvasState
}

function storeCanvasState(projectId: string, flowNodes: FlowNode[]) {
  localStorage.setItem(`protein-workbench.canvas.${projectId}`, JSON.stringify({
    positions: Object.fromEntries(flowNodes.map((node) => [node.id, node.position])),
    collapsed: flowNodes.filter((node) => node.data.collapsed).map((node) => node.id),
  } satisfies CanvasState))
}

function nodeParameters(stepId: string, workflow: Workflow, catalog?: CatalogSnapshot): Parameter[] {
  const node = workflow.nodes.find((item) => item.node_id === stepId)
  return node && catalog ? parameterPresentations(catalog, node) : []
}

function parameterInputValue(raw: string, valueType: string): unknown {
  if (valueType === 'integer' || valueType === 'number') return Number(raw)
  if (valueType === 'boolean') return raw === 'true'
  if (valueType === 'array' || valueType === 'object') return JSON.parse(raw)
  return raw
}

function flowFromDraft(draft: WorkflowDraft, catalog?: CatalogSnapshot, positionOverrides: Record<string, { x: number; y: number }> = {}): { nodes: FlowNode[]; edges: Edge[] } {
  if (!catalog) return { nodes: [], edges: [] }
  const stored = canvasState(draft.project_id)
  const managedOwner = new Map(draft.authoring_compositions.flatMap((composition) => composition.managed_node_ids.map((nodeId) => [nodeId, composition.composition_id] as const)))
  const managedNode = new Map(draft.workflow.nodes.map((node) => [node.node_id, node]))
  const compositionNodes = draft.authoring_compositions.map((composition, index): FlowNode => {
    const outputPortTypes = Object.fromEntries(composition.exposed_outputs.map((output) => {
      const source = managedNode.get(output.node_id)!
      return [output.port_name, nodeTypePresentation(catalog, source.node_type_id).outputPortTypes[output.port_name]]
    }))
    return { id: composition.composition_id, type: 'workflow', deletable: false, position: positionOverrides[composition.composition_id] ?? stored.positions[composition.composition_id] ?? { x: 60, y: 120 + index * 260 }, data: { kind: 'prompt', eyebrow: 'SPECIALIZED COMPOSITION', title: composition.capability_id, subtitle: 'managed graph', index: String(index + 1).padStart(2, '0'), inputs: [], outputs: composition.exposed_outputs.map((output) => output.port_name), inputPortTypes: {}, inputMultiplicities: {}, outputPortTypes, parameters: [], accent: '#ae9cff', count: `${composition.managed_node_ids.length} managed`, sourceNodeId: '', runMemberNodeIds: composition.managed_node_ids, managedMembers: composition.managed_node_ids, collapsed: stored.collapsed.includes(composition.composition_id) } }
  })
  const ordinaryNodes = draft.workflow.nodes.filter((node) => !managedOwner.has(node.node_id)).map((node, index): FlowNode => {
    const presentation = nodeTypePresentation(catalog, node.node_type_id)
    return { id: node.node_id, type: 'workflow', position: positionOverrides[node.node_id] ?? stored.positions[node.node_id] ?? { x: 390 + index % 5 * 320, y: 100 + Math.floor(index / 5) * 270 }, data: { kind: 'ordinary', eyebrow: presentation.category.toUpperCase(), title: presentation.title, subtitle: node.node_type_id, index: String(compositionNodes.length + index + 1).padStart(2, '0'), inputs: presentation.inputs, outputs: presentation.outputs, inputPortTypes: presentation.inputPortTypes, inputMultiplicities: presentation.inputMultiplicities, outputPortTypes: presentation.outputPortTypes, parameters: nodeParameters(node.node_id, draft.workflow, catalog), accent: categoryColors[presentation.category] ?? '#9aa69b', count: '', sourceNodeId: node.node_id, bindingId: node.binding_id, runMemberNodeIds: [node.node_id], collapsed: stored.collapsed.includes(node.node_id) } }
  })
  const nodes = [...compositionNodes, ...ordinaryNodes]
  const edges = draft.workflow.edges.flatMap((edge, index): Edge[] => {
    const source = managedOwner.get(edge.source_node_id) ?? edge.source_node_id
    if (managedOwner.has(edge.target_node_id)) return []
    const sourcePort = managedOwner.has(edge.source_node_id)
      ? draft.authoring_compositions.find((composition) => composition.composition_id === source)!.exposed_outputs.find((output) => output.node_id === edge.source_node_id && output.port_name === edge.source_port)?.port_name
      : edge.source_port
    if (!sourcePort) return []
    return [{ id: `workflow-edge-${index}`, source, sourceHandle: `out-${sourcePort}`, target: edge.target_node_id, targetHandle: `in-${edge.target_port}`, type: 'default', style: { stroke: '#637168', strokeWidth: 1.6 } }]
  })
  return { nodes, edges }
}

function workflowEdgesFromFlow(draft: WorkflowDraft, flowEdges: Edge[]): Workflow['edges'] {
  const managed = new Set(draft.authoring_compositions.flatMap((composition) => composition.managed_node_ids))
  const internalEdges = draft.workflow.edges.filter((edge) => managed.has(edge.target_node_id))
  const visibleEdges = flowEdges.map((edge) => {
    const composition = draft.authoring_compositions.find((item) => item.composition_id === edge.source)
    const sourcePort = edge.sourceHandle!.slice(4)
    const exposed = composition?.exposed_outputs.find((output) => output.port_name === sourcePort)
    return {
      source_node_id: exposed?.node_id ?? edge.source,
      source_port: exposed?.port_name ?? sourcePort,
      target_node_id: edge.target,
      target_port: edge.targetHandle!.slice(3),
    }
  })
  return [...internalEdges, ...visibleEdges]
}

function nodeRunStateFromDisposition(disposition: NodeDisposition): NodeRunState {
  if (disposition.outcome === 'succeeded') return { status: 'succeeded', resolution: disposition.resolution }
  if (disposition.outcome === 'blocked') return { status: 'blocked', blockedBy: disposition.blocked_by }
  return { status: disposition.outcome }
}

function nodeStatesFromProjection(projection: RunProjection, workflowNodeIds: string[] = []): Record<string, NodeRunState> {
  return Object.fromEntries([
    ...workflowNodeIds.map((nodeId): [string, NodeRunState] => [nodeId, { status: 'waiting' }]),
    ...projection.node_dispositions.map((disposition): [string, NodeRunState] => [disposition.node_id, nodeRunStateFromDisposition(disposition)]),
  ])
}

function aggregateNodeRunState(memberNodeIds: string[], nodeStates: Record<string, NodeRunState> | undefined): NodeRunState | undefined {
  if (!nodeStates) return undefined
  const states = memberNodeIds.flatMap((nodeId) => nodeStates[nodeId] ? [nodeStates[nodeId]] : [])
  if (states.length === 0) return undefined
  for (const status of ['running', 'failed', 'interrupted', 'cancelled'] as const) {
    const state = states.find((item) => item.status === status)
    if (state) return state
  }
  if (states.every((state) => state.status === 'succeeded')) return { status: 'succeeded' }
  const blocked = states.find((state) => state.status === 'blocked')
  if (blocked) return blocked
  return { status: 'waiting' }
}

function WorkflowCard({ id, data, selected }: NodeProps<FlowNode>) {
  const Icon = data.kind === 'prompt' ? Braces : Atom
  const runStatusLabel: Record<NodeRunStatus, string> = { waiting: '等待', running: '运行中', succeeded: '成功', failed: '失败', blocked: '未执行', cancelled: '已取消', interrupted: '已中断' }
  return <article className={`workflow-node ${selected ? 'is-selected' : ''} ${data.collapsed ? 'is-collapsed' : ''} ${data.runState ? `run-status-${data.runState.status}` : ''}`} style={{ '--node-accent': data.accent } as React.CSSProperties}>
    {data.inputs.map((port, index) => <Handle key={port} id={`in-${port}`} type="target" position={Position.Left} style={{ top: data.collapsed ? 31 : 112 + index * 26 }} className="node-handle input-handle" />)}
    {data.outputs.map((port, index) => <Handle key={port} id={`out-${port}`} type="source" position={Position.Right} style={{ top: data.collapsed ? 31 : 112 + index * 26 }} className="node-handle output-handle" />)}
    <header className="node-header"><span className="node-icon"><Icon size={15} /></span><div><span className="node-eyebrow">{data.eyebrow}</span><h3>{data.title}</h3></div>{data.runState && <span className={`node-run-status ${data.runState.status}`} aria-label={`${data.title}：${runStatusLabel[data.runState.status]}`}>{data.runState.status === 'running' ? <LoaderCircle size={11} /> : data.runState.status === 'succeeded' ? <Check size={11} /> : data.runState.status === 'failed' ? <X size={11} /> : <span />}{runStatusLabel[data.runState.status]}</span>}<span className="node-index">{data.index}</span><button className="icon-button nodrag" onClick={() => data.onToggle?.(id)}><ChevronDown size={15} /></button></header>
    {!data.collapsed && <><div className="node-meta">{data.bindingOptions && data.bindingOptions.length > 1 ? <select className="node-binding-select nodrag" aria-label={`${data.title}的执行模型`} value={data.bindingId} onChange={(event) => data.onBinding?.(data.sourceNodeId, event.target.value)}>{data.bindingOptions.map((option) => <option value={option.id} key={option.id} disabled={!option.available && option.id !== data.bindingId}>{option.label}{option.available ? '' : '（不可用）'}</option>)}</select> : <span>{data.bindingOptions?.find((option) => option.id === data.bindingId)?.label ?? data.subtitle}{data.bindingOptions?.some((option) => option.id === data.bindingId && !option.available) ? '（不可用）' : ''}</span>}<strong>{data.count}</strong></div><div className="ports-block"><div>{data.inputs.map((port) => <span key={port} className="port input-port">{port}</span>)}</div><div>{data.outputs.map((port) => <span key={port} className="port output-port">{port}</span>)}</div></div>
      {data.kind === 'prompt' ? <><button className="prompt-edit-button nodrag" onClick={data.onEditPrompt}><Braces size={14} /> 打开 Prompt Studio <ChevronRight size={14} /></button><details className="parameter-group managed-members nodrag"><summary>Managed Members <span>{data.managedMembers?.length}</span></summary><div className="managed-member-list">{data.managedMembers?.map((member) => <code key={member}>{member}</code>)}</div></details></> : <details className="parameter-group nodrag"><summary aria-label="编辑参数"><SlidersHorizontal size={13} /> 参数 <span>{data.parameters.length}</span></summary><div className="parameter-fields">{data.parameters.map((parameter) => <label key={`${parameter.scope}-${parameter.key}`}><span>{parameter.label}{parameter.required ? ' *' : ''}</span><span className="field-control"><input aria-label={parameter.label} value={parameter.value} onChange={(event) => data.onParameter?.(data.sourceNodeId, parameter, event.target.value, false)} onBlur={(event) => data.onParameter?.(data.sourceNodeId, parameter, event.target.value, true)} />{parameter.suffix && <em>{parameter.suffix}</em>}</span></label>)}</div></details>}
    </>}
  </article>
}

const amino: Record<string, string> = { ALA: 'A', ARG: 'R', ASN: 'N', ASP: 'D', CYS: 'C', GLN: 'Q', GLU: 'E', GLY: 'G', HIS: 'H', ILE: 'I', LEU: 'L', LYS: 'K', MET: 'M', PHE: 'F', PRO: 'P', SER: 'S', THR: 'T', TRP: 'W', TYR: 'Y', VAL: 'V' }
function pdbSequence(pdb: string) { const seen = new Set<string>(); const letters: string[] = []; for (const line of pdb.split('\n')) if (line.startsWith('ATOM') && line.slice(12, 16).trim() === 'CA') { const key = `${line.slice(21, 22)}:${line.slice(22, 27).trim()}`; if (!seen.has(key)) { seen.add(key); letters.push(amino[line.slice(17, 20).trim()] ?? 'X') } } return letters.join('') }
function decodeCandidates(value: unknown): CandidateView[] { const root = value as { fields?: { items?: Array<{ fields?: Record<string, unknown> }> } }; return (root.fields?.items ?? []).map((item) => { const fields = item.fields ?? {}; const data = fields.data as { fields?: { pdb_string?: string } }; const pdb = data.fields?.pdb_string ?? ''; return { id: String(fields.candidate_id), parent: String((fields.parent_ids as string[] | undefined)?.[0] ?? ''), pdb, sequence: pdbSequence(pdb), metadata: (fields.metadata ?? {}) as JsonObject } }) }

function decodeScores(value: unknown): ScoreView[] {
  const root = value as { fields?: { entries?: Array<{ fields?: Record<string, unknown> }> } }
  return (root.fields?.entries ?? []).flatMap((entry) => {
    const fields = entry.fields ?? {}
    if (typeof fields.value !== 'number') return []
    const subject = fields.subject as { fields: { candidate_id: string } }
    const metric = fields.metric as { fields: { contract_id: string } }
    const method = fields.method as { fields: { contract_id: string } }
    const context = fields.context as { fields: JsonObject }
    return [{ candidateId: subject.fields.candidate_id, metricId: metric.fields.contract_id, methodId: method.fields.contract_id, context: context.fields, value: fields.value }]
  })
}

function exportCandidates(candidates: CandidateView[], scores: ScoreView[], run: RunProjection) {
  const files: Record<string, Uint8Array> = {}
  for (const candidate of candidates) files[`structures/${candidate.id}.pdb`] = strToU8(candidate.pdb)
  files['candidates.fasta'] = strToU8(candidates.map((candidate) => `>${candidate.id} parent=${candidate.parent}\n${candidate.sequence}`).join('\n'))
  const scoreRows = scores.filter((score) => candidates.some((candidate) => candidate.id === score.candidateId)).map((score) => [score.candidateId, score.metricId, score.methodId, score.context.kind, score.context.pairing_mode ?? '', score.value].join(','))
  files['scores.csv'] = strToU8(['candidate_id,metric_id,method_id,context_kind,pairing_mode,value', ...scoreRows].join('\n'))
  files['manifest.json'] = strToU8(JSON.stringify({ schema_namespace: 'protein-workbench-webui-export/v1', run_id: run.run_id, workflow_commit_id: run.workflow_commit_id, candidates: candidates.map(({ id, parent }) => ({ candidate_id: id, parent_id: parent })), selection: run.selection_results?.at(-1) }, null, 2))
  const bytes = zipSync(files)
  const url = URL.createObjectURL(new Blob([bytes.buffer as ArrayBuffer], { type: 'application/zip' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${run.run_id}-candidates.zip`
  link.click()
  URL.revokeObjectURL(url)
}

function ResultsWorkbench({ run, candidates, scores, catalog, onBack }: { run: RunProjection; candidates: CandidateView[]; scores: ScoreView[]; catalog: CatalogSnapshot; onBack: () => void }) {
  const [focused, setFocused] = useState(candidates[0])
  const [selected, setSelected] = useState(new Set(candidates[0] ? [candidates[0].id] : []))
  useEffect(() => { setFocused(candidates[0]); setSelected(new Set(candidates[0] ? [candidates[0].id] : [])) }, [candidates])
  if (!focused) return null
  const comparisonContexts = [...new Set(scores.filter((score) => score.candidateId === focused.id && score.context.kind === 'pairwise').map((score) => String(score.context.pairing_mode)))]
  return <div className="results-page"><aside className="results-sidebar"><button className="back-to-workflow" onClick={onBack}><ChevronLeft size={15} /> 返回 Workflow</button><div className="results-title"><span className="page-kicker">LATEST RUN</span><h2>3GB1 局部重设计</h2><span className="success-pill"><Check size={12} /> {run.status}</span><small>{run.workflow_commit_id}</small></div><nav className="result-steps">{(run.selection_results ?? []).map((item, index, all) => <button key={item.selection_node_id} className={index === all.length - 1 ? 'active' : ''}><span><Target size={14} /></span><strong>{item.selection_node_id}</strong><em>{item.selected_candidate_ids.length}</em></button>)}</nav><div className="run-meta"><span>Run provenance</span><code>{run.run_id}</code></div></aside>
    <main className="results-main"><header className="results-header"><div><span className="page-kicker">RESULTS WORKBENCH</span><h1>最终候选 <span>{candidates.length}</span></h1></div><div className="results-actions"><button className="secondary-button"><GitBranch size={14} /> 谱系证据</button><button className="primary-button" onClick={() => exportCandidates(candidates.filter((candidate) => selected.has(candidate.id)), scores, run)}><Download size={14} /> 导出所选 · ZIP</button></div></header><section className="lineage-strip"><div className="lineage-heading"><span className="page-kicker">CANDIDATE LINEAGE</span><span>精确 Candidate parent IDs</span></div><div className="lineage-graph"><div className="lineage-stage"><span>ProteinMPNN parents</span>{[...new Set(candidates.map((item) => item.parent))].map((id) => <button key={id}><TestTubeDiagonal size={14} /> {id.slice(-10)}</button>)}</div><ChevronRight className="lineage-arrow" /><div className="lineage-stage final"><span>Refolded final</span>{candidates.map((candidate) => <button key={candidate.id} className={focused.id === candidate.id ? 'active' : ''} onClick={() => setFocused(candidate)}><Atom size={14} /> {candidate.id.slice(-10)}</button>)}</div></div></section>
      <div className="results-grid"><section className="candidate-table-card"><header><div><span className="page-kicker">CANDIDATES</span><h3>Final Top 3</h3></div></header><div className="candidate-table-head"><span /><span>Candidate</span><span>Direct parent</span><span>Stage</span><span /></div>{candidates.map((candidate) => <button className={`candidate-row ${focused.id === candidate.id ? 'active' : ''}`} key={candidate.id} onClick={() => setFocused(candidate)}><span className={`checkbox ${selected.has(candidate.id) ? 'checked' : ''}`} onClick={(event) => { event.stopPropagation(); setSelected((current) => { const next = new Set(current); if (next.has(candidate.id)) next.delete(candidate.id); else next.add(candidate.id); return next }) }}>{selected.has(candidate.id) && <Check size={11} />}</span><strong>{candidate.id.slice(-12)}</strong><code>{candidate.parent.slice(-10)}</code><em>Final Top 3</em><ChevronRight size={14} /></button>)}<footer>{selected.size} selected for comparison and export</footer></section>
        <section className="focused-candidate-card"><header><div><span className="page-kicker">FOCUSED CANDIDATE</span><h3>{focused.id.slice(-16)}</h3></div></header><div className="focused-body"><div className="mini-viewer"><StructureViewer pdb={focused.pdb} /><span>ESMFold2 structure</span></div><div className="candidate-details"><span className="section-label">SEQUENCE</span><code className="sequence-block">{focused.sequence}</code>{scores.filter((score) => score.candidateId === focused.id && ['structure.plddt.mean_residue', 'structure_comparison.tm_score'].includes(score.metricId)).map((score) => { const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'metric' && contract.reference.contract_id === score.metricId)?.descriptor; return <div className="metric-placeholder" key={`${score.metricId}-${score.context.kind}`}><Activity size={16} /><span><strong>{String(descriptor?.title)}</strong><small>{score.value.toFixed(4)} {String(descriptor?.unit)} · {score.methodId} · {String(score.context.pairing_mode ?? score.context.kind)} · {String(descriptor?.direction)}</small></span><Info size={14} /></div> })}<div className="provenance-list"><span>Direct parent</span><strong>{focused.parent}</strong><span>Comparison context</span><strong>{comparisonContexts.join(', ')}</strong></div></div></div></section></div></main></div>
}

function RunDialog({ draft, onClose, onStart }: { draft: WorkflowDraft; onClose: () => void; onStart: () => Promise<void> }) { const [running, setRunning] = useState(false); return <div className="modal-backdrop" onMouseDown={onClose}><section className="run-dialog" onMouseDown={(event) => event.stopPropagation()}><header><span className="dialog-icon"><Play size={18} /></span><div><span className="page-kicker">RUN WORKFLOW</span><h2>确认运行完整流程</h2></div><button className="icon-button" onClick={onClose}><X size={18} /></button></header><div className="run-scope"><span className="section-label">EXECUTION SCOPE</span><div><GitBranch size={17} /><span><strong>{draft.workflow.nodes.length} 个 materialized Node Instances</strong><small>7 → 4 → 4 → 2 → 6 → 6 → 3</small></span><span className="ready-pill"><Check size={12} /> Ready</span></div></div><div className="run-note"><Info size={15} /><span>先提交当前 Draft，再用不可变 Workflow Commit 启动 Run。</span></div><footer><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={running} onClick={() => { setRunning(true); void onStart().finally(() => setRunning(false)) }}><Play size={14} /> {running ? '启动中…' : '开始运行'}</button></footer></section></div> }

function runProgressTitle(status: RunProgress['status']) {
  if (status === 'committing') return '正在准备运行'
  if (status === 'starting' || status === 'admitted') return '正在启动'
  if (status === 'running') return '正在运行'
  if (status === 'succeeded') return '运行完成'
  if (status === 'failed') return '运行失败'
  if (status === 'cancelled') return '运行已取消'
  return '运行已中断'
}

function RunProgressBar({ progress, nodeTitle, onResults }: { progress: RunProgress; nodeTitle: string; onResults: () => void }) {
  const terminal = ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(progress.status)
  const percent = progress.totalNodes === 0 ? 0 : Math.round(progress.completedNodeIds.length / progress.totalNodes * 100)
  const stage = progress.status === 'committing' ? '提交 Workflow Commit' : progress.status === 'starting' ? '等待 Run 接纳' : progress.status === 'admitted' ? '已接纳，等待执行开始' : progress.currentNodeId ? nodeTitle : progress.status === 'running' ? '等待下一个 Node Instance' : progress.status === 'succeeded' && !progress.resultsReady ? '加载 Run 结果' : 'Run Closure'
  return <section className={`run-progress-bar ${terminal ? 'terminal' : 'active'} status-${progress.status}`} role="status" aria-live="polite">
    <span className="run-progress-icon">{terminal && progress.status === 'succeeded' ? <Check size={15} /> : terminal ? <Info size={15} /> : <LoaderCircle size={16} />}</span>
    <div className="run-progress-state"><span className="page-kicker">LIVE RUN</span><strong>{progress.status === 'succeeded' && !progress.resultsReady ? '运行完成 · 正在加载结果' : runProgressTitle(progress.status)}</strong></div>
    <div className="run-progress-stage"><span>当前阶段</span><strong>{stage}</strong>{progress.currentNodeId && <code>{progress.currentNodeId}</code>}</div>
    <div className="run-progress-meter" role="progressbar" aria-label="Run Node 进度" aria-valuemin={0} aria-valuemax={progress.totalNodes} aria-valuenow={progress.completedNodeIds.length}><div><span style={{ width: `${percent}%` }} /></div><small>{progress.completedNodeIds.length} / {progress.totalNodes} Nodes · {percent}%</small></div>
    {progress.runId && <code className="run-progress-id">{progress.runId}</code>}
    {progress.status === 'succeeded' && progress.resultsReady && <button className="secondary-button" onClick={onResults}>查看结果</button>}
  </section>
}

function ProjectDialog({ projects, query, onQuery, onSearch, onOpen, onCreate, onClose }: { projects: ProjectMetadata[]; query: string; onQuery: (value: string) => void; onSearch: () => Promise<void>; onOpen: (project: ProjectMetadata) => Promise<void>; onCreate: () => Promise<void>; onClose: () => void }) {
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="run-dialog project-dialog" onMouseDown={(event) => event.stopPropagation()}><header><span className="dialog-icon"><FolderOpen size={18} /></span><div><span className="page-kicker">PROJECTS</span><h2>打开个人项目</h2></div><button className="icon-button" onClick={onClose}><X size={18} /></button></header><div className="palette-search"><Search size={15} /><input aria-label="按名称搜索项目" value={query} onChange={(event) => onQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void onSearch() }} /><button onClick={() => void onSearch()}>搜索</button></div><div className="project-list">{projects.map((item) => <button key={item.id} onClick={() => void onOpen(item)}><span><strong>{item.name}</strong><small>{item.project_kind}{item.latest_run_id ? ' · 有结果' : ''}</small></span><ChevronRight size={15} /></button>)}</div><footer><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" onClick={() => void onCreate()}><Plus size={14} /> 新建空白画布</button></footer></section></div>
}

function resultEndpoints(projection: RunProjection) {
  const selection = projection.selection_results!.at(-1)!
  const candidateOutput = projection.outputs.filter((output) => {
    const portType = output.port_type as ContractReference
    return portType.contract_id === 'candidate.collection'
  }).at(-1)!
  const scoreInputs = [...new Map(selection.objectives.map((objective) => {
    const input = objective.score_collection_input
    return [`${input.node_id}/${input.output_port}`, { nodeId: input.node_id, port: input.output_port }]
  })).values()]
  return {
    candidates: { nodeId: String(candidateOutput.node_id), port: String(candidateOutput.output_port) },
    scores: scoreInputs,
  }
}

async function resultValues(projectId: string, runId: string, projection: RunProjection) {
  const endpoints = resultEndpoints(projection)
  const [candidateValue, ...scoreValues] = await Promise.all([
    client.typedValue(projectId, runId, endpoints.candidates.nodeId, endpoints.candidates.port),
    ...endpoints.scores.map((input) => client.typedValue(projectId, runId, input.nodeId, input.port)),
  ])
  return {
    candidates: decodeCandidates(candidateValue.value),
    scores: scoreValues.flatMap((value) => decodeScores(value.value)),
  }
}

function App() {
  const [catalog, setCatalog] = useState<CatalogSnapshot>()
  const [capabilities, setCapabilities] = useState<AuthoringCapabilities>()
  const [project, setProject] = useState<ProjectMetadata>()
  const [draft, setDraft] = useState<WorkflowDraft>()
  const [run, setRun] = useState<RunProjection>()
  const [runProgress, setRunProgress] = useState<RunProgress>()
  const [candidates, setCandidates] = useState<CandidateView[]>([])
  const [scores, setScores] = useState<ScoreView[]>([])
  const [nodes, setNodes] = useState<FlowNode[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [prompt, setPrompt] = useState<PromptSnapshot>()
  const [view, setView] = useState<'workflow' | 'results'>('workflow')
  const [runOpen, setRunOpen] = useState(false)
  const [projectsOpen, setProjectsOpen] = useState(false)
  const [projectChoices, setProjectChoices] = useState<ProjectMetadata[]>([])
  const [projectQuery, setProjectQuery] = useState('')
  const [search, setSearch] = useState('')
  const [paletteTaxonomy, setPaletteTaxonomy] = useState<PaletteTaxonomy>('purpose')
  const [pendingNodeDrop, setPendingNodeDrop] = useState<PendingNodeDrop>()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [saveState, setSaveState] = useState('加载中…')
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
  const activeRunKey = useRef<string | undefined>(undefined)
  const flowInstance = useRef<ReactFlowInstance<FlowNode, Edge> | null>(null)
  const bindingParameterMemory = useRef<Record<string, Record<string, Record<string, Record<string, unknown>>>>>({})
  const activeParameterEdits = useRef(new Set<string>())

  useEffect(() => { draftRef.current = draft }, [draft])
  useEffect(() => { nodesRef.current = nodes }, [nodes])
  useEffect(() => { edgesRef.current = edges }, [edges])

  const loadCompletedRun = useCallback(async (projectId: string, runId: string) => {
    const projection = await client.runProjection(projectId, runId)
    let nextCandidates: CandidateView[] = []
    let nextScores: ScoreView[] = []
    if (projection.status === 'succeeded') {
      const values = await resultValues(projectId, runId, projection)
      nextCandidates = values.candidates
      nextScores = values.scores
    }
    const runKey = `${projectId}/${runId}`
    if (activeRunKey.current !== runKey) return
    if (projection.status === 'succeeded') {
      setRun(projection)
      setCandidates(nextCandidates)
      setScores(nextScores)
    }
    setProject((current) => current?.id === projectId ? { ...current, latest_run_id: runId } : current)
    setRunProgress((current) => current?.projectId === projectId && current.runId === runId ? { ...current, status: projection.status, completedNodeIds: projection.node_dispositions.map((disposition) => disposition.node_id), nodeStates: nodeStatesFromProjection(projection, Object.keys(current.nodeStates)), resultsReady: projection.status === 'succeeded' } : current)
  }, [])

  useEffect(() => {
    if (!runProgress?.projectId || !runProgress.runId || (runProgress.status !== 'admitted' && runProgress.status !== 'running')) return
    const projectId = runProgress.projectId
    const runId = runProgress.runId
    const socket = client.runEvents(projectId, runId, runProgress.eventCursor || undefined)
    socket.onmessage = (message) => {
      const envelope = JSON.parse(message.data as string) as RunEventEnvelope
      const event = envelope.event
      if (event.type === 'run_started') setRunProgress((current) => current?.runId === runId ? { ...current, status: 'running' } : current)
      if (event.type === 'node_attempt_started') setRunProgress((current) => current?.runId === runId ? { ...current, status: 'running', currentNodeId: event.node_id, nodeStates: { ...current.nodeStates, [event.node_id]: { status: 'running' } } } : current)
      if (event.type === 'node_disposition') setRunProgress((current) => {
        if (current?.runId !== runId) return current
        const completedNodeIds = current.completedNodeIds.includes(event.disposition.node_id) ? current.completedNodeIds : [...current.completedNodeIds, event.disposition.node_id]
        const nodeState = nodeRunStateFromDisposition(event.disposition)
        return { ...current, completedNodeIds, nodeStates: { ...current.nodeStates, [event.disposition.node_id]: nodeState }, lastNodeId: event.disposition.node_id, currentNodeId: current.currentNodeId === event.disposition.node_id ? undefined : current.currentNodeId }
      })
      if (event.type === 'run_terminal') {
        setRunProgress((current) => current?.runId === runId ? { ...current, status: event.status, currentNodeId: undefined } : current)
        void loadCompletedRun(projectId, runId)
      }
    }
    return () => socket.close()
  }, [loadCompletedRun, runProgress?.eventCursor, runProgress?.projectId, runProgress?.runId, runProgress?.status])

  useEffect(() => { void (async () => {
    const [catalogValue, capabilityValue, projects] = await Promise.all([client.catalog(), client.authoringCapabilities(), client.projects()])
    const example = projects.projects.find((item) => item.project_kind === 'default_example')
    if (!example) throw new Error('Default example Project is absent')
    const draftValue = await client.workflowDraft(example.id)
    const flow = flowFromDraft(draftValue, catalogValue)
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
    if (example.latest_run_id) {
      const runValue = await client.runProjection(example.id, example.latest_run_id)
      activeRunKey.current = `${example.id}/${example.latest_run_id}`
      setRunProgress({ status: runValue.status, totalNodes: draftValue.workflow.nodes.length, completedNodeIds: runValue.node_dispositions.map((disposition) => disposition.node_id), nodeStates: nodeStatesFromProjection(runValue, draftValue.workflow.nodes.map((node) => node.node_id)), projectId: example.id, runId: example.latest_run_id, workflowCommitId: runValue.workflow_commit_id, eventCursor: runValue.status === 'admitted' || runValue.status === 'running' ? '' : undefined, resultsReady: runValue.status === 'succeeded' })
      if (runValue.status === 'succeeded') {
        const values = await resultValues(example.id, example.latest_run_id, runValue)
        setRun(runValue)
        setCandidates(values.candidates)
        setScores(values.scores)
      }
    }
    setSaveState('示例已加载')
  })() }, [])

  const ensurePersonal = useCallback(async () => { if (!project || !draftRef.current) throw new Error('Project is not loaded'); if (project.project_kind === 'personal') return { project, draft: projectDrafts.current[project.id] ?? draftRef.current }; if (!personalization.current) { const generation = projectGeneration.current; setSaveState('正在创建个人副本…'); personalization.current = client.copyExample(project.id, `${project.name} · 我的副本`).then(async (copy) => { const copyDraft = await client.workflowDraft(copy.id); storeCanvasState(copy.id, nodesRef.current); projectDrafts.current[copy.id] = copyDraft; if (generation === projectGeneration.current) { const workflow = { ...(workflowRef.current ?? copyDraft.workflow), workflow_id: copyDraft.workflow.workflow_id }; const activeDraft = { ...copyDraft, workflow }; workflowRef.current = workflow; draftRef.current = activeDraft; setProject(copy); setDraft(activeDraft); setSaveState('个人副本已保存') } return { project: copy, draft: copyDraft } }) } return personalization.current }, [project])

  const saveWorkflow = useCallback((change: (base: WorkflowDraft) => Workflow) => {
    const generation = projectGeneration.current
    const revision = ++workflowRevision.current
    const activeDraft = draftRef.current!
    const workflow = change({
      ...activeDraft,
      workflow: workflowRef.current ?? activeDraft.workflow,
    })
    workflowRef.current = workflow
    const optimisticDraft = { ...activeDraft, workflow }
    draftRef.current = optimisticDraft
    setDraft(optimisticDraft)
    return ensurePersonal().then((personal) => {
      const previous = projectSaveQueues.current[personal.project.id] ?? Promise.resolve()
      const operation = previous.then(async () => {
        const base = projectDrafts.current[personal.project.id] ?? personal.draft
        if (generation === projectGeneration.current) setSaveState('自动保存中…')
        const changed = change(base)
        const saved = await client.saveWorkflowDraft(personal.project.id, {
          ...changed,
          workflow_id: base.workflow.workflow_id,
        })
        projectDrafts.current[personal.project.id] = saved
        const current = generation === projectGeneration.current && revision === workflowRevision.current
        if (current) {
          workflowRef.current = saved.workflow
          draftRef.current = saved
          setDraft(saved)
          setSaveState('已自动保存')
        }
        return { project: personal.project, draft: saved, current }
      })
      projectSaveQueues.current[personal.project.id] = operation
      return operation
    })
  }, [ensurePersonal])
  const savedPersonalDraft = useCallback(async () => {
    const personal = await ensurePersonal()
    const pending = projectSaveQueues.current[personal.project.id]
    if (pending) await pending
    return {
      project: personal.project,
      draft: projectDrafts.current[personal.project.id] ?? personal.draft,
    }
  }, [ensurePersonal])

  const installSavedFlow = useCallback((saved: WorkflowDraft, positionOverrides: Record<string, { x: number; y: number }> = {}) => {
    const flow = flowFromDraft(saved, catalog, positionOverrides)
    workflowRef.current = saved.workflow
    nodesRef.current = flow.nodes
    edgesRef.current = flow.edges
    setNodes(flow.nodes)
    setEdges(flow.edges)
    return flow
  }, [catalog])
  const openProject = useCallback(async (selected: ProjectMetadata) => {
    const generation = ++projectGeneration.current
    workflowRevision.current += 1
    activeRunKey.current = undefined
    personalization.current = undefined
    history.current = []
    activeParameterEdits.current.clear()
    setRunProgress(undefined)
    setRun(undefined)
    setCandidates([])
    setScores([])
    setProject(undefined)
    setDraft(undefined)
    draftRef.current = undefined
    workflowRef.current = undefined
    nodesRef.current = []
    edgesRef.current = []
    setNodes([])
    setEdges([])
    setProjectsOpen(false)
    const selectedDraft = await client.workflowDraft(selected.id)
    if (generation !== projectGeneration.current) return
    const flow = flowFromDraft(selectedDraft, catalog)
    setProject(selected)
    draftRef.current = selectedDraft
    workflowRef.current = selectedDraft.workflow
    projectDrafts.current[selectedDraft.project_id] = selectedDraft
    nodesRef.current = flow.nodes
    edgesRef.current = flow.edges
    setDraft(selectedDraft)
    setNodes(flow.nodes)
    setEdges(flow.edges)
    setSaveState('项目已打开')
    let resultProject = selected
    if (!resultProject.latest_run_id && selected.copied_from_project_id) {
      resultProject = (await client.projects()).projects.find((item) => item.id === selected.copied_from_project_id)!
      if (generation !== projectGeneration.current) return
    }
    if (resultProject.latest_run_id) {
      const selectedRun = await client.runProjection(resultProject.id, resultProject.latest_run_id)
      if (generation !== projectGeneration.current) return
      activeRunKey.current = `${resultProject.id}/${resultProject.latest_run_id}`
      setRunProgress({ status: selectedRun.status, totalNodes: selectedDraft.workflow.nodes.length, completedNodeIds: selectedRun.node_dispositions.map((disposition) => disposition.node_id), nodeStates: nodeStatesFromProjection(selectedRun, selectedDraft.workflow.nodes.map((node) => node.node_id)), projectId: resultProject.id, runId: resultProject.latest_run_id, workflowCommitId: selectedRun.workflow_commit_id, eventCursor: selectedRun.status === 'admitted' || selectedRun.status === 'running' ? '' : undefined, resultsReady: selectedRun.status === 'succeeded' })
      if (selectedRun.status === 'succeeded') {
        const values = await resultValues(resultProject.id, resultProject.latest_run_id, selectedRun)
        if (generation !== projectGeneration.current) return
        setRun(selectedRun)
        setCandidates(values.candidates)
        setScores(values.scores)
      }
    }
  }, [catalog])
  const remember = useCallback(() => { const currentWorkflow = workflowRef.current!; history.current.push({ workflow: structuredClone(currentWorkflow), nodes: structuredClone(nodesRef.current), edges: structuredClone(edgesRef.current) }) }, [])
  const saveParameter = useCallback(async (nodeId: string, parameter: Parameter, raw: string) => { if (!catalog) return; const result = await saveWorkflow((base) => { const source = base.workflow.nodes.find((item) => item.node_id === nodeId)!; const field = parameter.scope === 'node' ? 'node_parameters' : 'binding_parameters'; const values = { ...source[field] }; if (raw === '') delete values[parameter.key]; else values[parameter.key] = parameterInputValue(raw, parameter.valueType); if (parameter.scope === 'binding') { const projectMemory = bindingParameterMemory.current[base.project_id] ??= {}; const nodeMemory = projectMemory[nodeId] ??= {}; nodeMemory[source.binding_id] = values } return { ...base.workflow, nodes: base.workflow.nodes.map((item): WorkflowNode => item.node_id === nodeId ? { ...item, [field]: values } : item) } }); if (result.current) installSavedFlow(result.draft) }, [catalog, installSavedFlow, saveWorkflow])
  const saveBinding = useCallback(async (nodeId: string, bindingId: string) => { if (!catalog) return; remember(); const result = await saveWorkflow((base) => { const source = base.workflow.nodes.find((item) => item.node_id === nodeId)!; const projectMemory = bindingParameterMemory.current[base.project_id] ??= {}; const nodeMemory = projectMemory[nodeId] ??= {}; nodeMemory[source.binding_id] = source.binding_parameters; return selectNodeBinding(base.workflow, nodeId, bindingId, catalog, nodeMemory[bindingId]) }); const selected = result.draft.workflow.nodes.find((item) => item.node_id === nodeId)!; const projectMemory = bindingParameterMemory.current[result.project.id] ??= {}; const nodeMemory = projectMemory[nodeId] ??= {}; nodeMemory[bindingId] = selected.binding_parameters; if (result.current) installSavedFlow(result.draft) }, [catalog, installSavedFlow, remember, saveWorkflow])
  const addDroppedNode = useCallback(async (drop: PendingNodeDrop, bindingId: string) => { if (!catalog) return; remember(); const nodeId = `${drop.nodeTypeId.replaceAll('.', '-')}-${crypto.randomUUID().slice(0, 8)}`; const result = await saveWorkflow((base) => insertOrdinaryNode(base.workflow, nodeId, drop.nodeTypeId, bindingId, catalog)); if (result.current) { const flow = installSavedFlow(result.draft, { [nodeId]: drop.position }); storeCanvasState(result.project.id, flow.nodes); setPendingNodeDrop(undefined) } }, [catalog, installSavedFlow, remember, saveWorkflow])
  const saveFlowEdges = useCallback(async (nextEdges: Edge[]) => { if (!catalog) return; const result = await saveWorkflow((base) => ({ ...base.workflow, edges: workflowEdgesFromFlow(base, nextEdges) })); if (result.current) installSavedFlow(result.draft) }, [catalog, installSavedFlow, saveWorkflow])
  const deleteWorkflowElements = useCallback(async (deletedNodes: FlowNode[], deletedEdges: Edge[]) => {
    if (!catalog || (deletedNodes.length === 0 && deletedEdges.length === 0)) return
    const removedNodeIds = new Set(deletedNodes.map((node) => node.id))
    const removedEdgeIds = new Set(deletedEdges.map((edge) => edge.id))
    const remainingEdges = edgesRef.current.filter((edge) => !removedEdgeIds.has(edge.id) && !removedNodeIds.has(edge.source) && !removedNodeIds.has(edge.target))
    const result = await saveWorkflow((base) => ({
      ...base.workflow,
      nodes: base.workflow.nodes.filter((node) => !removedNodeIds.has(node.node_id)),
      edges: workflowEdgesFromFlow(base, remainingEdges),
    }))
    if (result.current) installSavedFlow(result.draft)
  }, [catalog, installSavedFlow, saveWorkflow])
  const dropPaletteNode = useCallback((event: React.DragEvent) => { if (!catalog || !flowInstance.current) return; event.preventDefault(); const nodeTypeId = event.dataTransfer.getData('application/protein-workbench-node-type'); if (!nodeTypeId) return; const point = flowInstance.current.screenToFlowPosition({ x: event.clientX, y: event.clientY }); const drop = { nodeTypeId, position: { x: point.x - 137, y: point.y - 30 }, bindings: bindingOptions(catalog, nodeTypeId) }; const availableBindings = drop.bindings.filter((binding) => binding.available); if (availableBindings.length === 1) void addDroppedNode(drop, availableBindings[0].id); else setPendingNodeDrop(drop) }, [addDroppedNode, catalog])
  const undo = useCallback(() => { const previous = history.current.pop(); if (!previous) return; nodesRef.current = previous.nodes; edgesRef.current = previous.edges; setNodes(previous.nodes); setEdges(previous.edges); void saveWorkflow(() => previous.workflow).then((result) => { if (result.current) { nodesRef.current = previous.nodes; edgesRef.current = previous.edges; setNodes(previous.nodes); setEdges(previous.edges); storeCanvasState(result.project.id, previous.nodes); setSaveState('已撤销画布修改') } }) }, [saveWorkflow])
  const persistCanvas = useCallback(async (nextNodes: FlowNode[]) => { const generation = projectGeneration.current; const personal = await ensurePersonal(); storeCanvasState(personal.project.id, nextNodes); if (generation === projectGeneration.current) setSaveState('画布位置已保存') }, [ensurePersonal])
  const displayed = useMemo<FlowNode[]>(() => nodes.map((node) => {
    const sourceNode = draft?.workflow.nodes.find((item) => item.node_id === node.data.sourceNodeId)
    return { ...node, data: { ...node.data, bindingOptions: catalog && sourceNode ? bindingOptions(catalog, sourceNode.node_type_id) : [], runState: aggregateNodeRunState(node.data.runMemberNodeIds, runProgress?.nodeStates), onToggle: (id: string) => { remember(); const next = nodesRef.current.map((item) => item.id === id ? { ...item, data: { ...item.data, collapsed: !item.data.collapsed } } : item); nodesRef.current = next; setNodes(next); void persistCanvas(next) }, onEditPrompt: async () => { if (!project || !draft) return; const composition = draft.authoring_compositions.find((item) => item.composition_id === node.id)!; setPrompt(await client.openPrompt(project.id, composition.composition_id)) }, onParameter: (nodeId: string, changed: Parameter, value: string, commit: boolean) => { const editKey = `${nodeId}:${changed.scope}:${changed.key}`; if (!commit && !activeParameterEdits.current.has(editKey)) { remember(); workflowRevision.current += 1; activeParameterEdits.current.add(editKey) } const next = nodesRef.current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, parameters: item.data.parameters.map((parameter) => parameter.key === changed.key && parameter.scope === changed.scope ? { ...parameter, value } : parameter) } } : item); nodesRef.current = next; setNodes(next); if (commit && activeParameterEdits.current.delete(editKey)) void saveParameter(nodeId, changed, value) }, onBinding: (nodeId: string, bindingId: string) => { void saveBinding(nodeId, bindingId) } } }
  }), [nodes, project, draft, catalog, runProgress?.nodeStates, persistCanvas, remember, saveBinding, saveParameter])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (prompt || event.defaultPrevented || target?.closest('input, textarea, select, [contenteditable="true"]')) return
      if ((event.metaKey || event.ctrlKey) && !event.shiftKey && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        undo()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [prompt, undo])
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

  if (!project || !draft) return <div className="loading-screen">正在从 public v2 protocol 加载 WebUI 示例…</div>
  if (prompt) return <PromptStudio snapshot={prompt} onCancel={() => setPrompt(undefined)} onPreview={async (document) => { const personal = await ensurePersonal(); const composition = personal.draft.authoring_compositions[0]; return client.previewPrompt(personal.project.id, composition.composition_id, document) }} onApply={async (preview) => { const personal = await ensurePersonal(); const composition = personal.draft.authoring_compositions[0]; const applied = await client.applyPrompt(personal.project.id, composition.composition_id, preview); projectDrafts.current[personal.project.id] = applied.draft; draftRef.current = applied.draft; setDraft(applied.draft); installSavedFlow(applied.draft); setPrompt(undefined); setSaveState('Prompt 已保存') }} />
  if (view === 'results' && run && catalog) return <ResultsWorkbench run={run} candidates={candidates} scores={scores} catalog={catalog} onBack={() => setView('workflow')} />
  return <div className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark"><Braces size={16} /></span><div><strong>Protein</strong><span>Workbench</span></div></div><div className="project-identity"><button className="icon-button" aria-label="主菜单"><Menu size={16} /></button><div><span className="page-kicker">{project.project_kind.replace('_', ' ')}</span><strong>{project.name}</strong></div>{project.seed && <span className="immutable-pill">只读示例</span>}</div><nav className="view-tabs"><button className="active"><Network size={14} /> Workflow</button><button disabled={!run || candidates.length === 0} onClick={() => setView('results')}><Activity size={14} /> Results <span>{candidates.length}</span></button></nav><div className="top-actions"><span className="save-state"><span />{saveState}</span><button className="icon-button" aria-label="撤销画布修改" onClick={undo}><RotateCcw size={16} /></button><button className="secondary-button" onClick={() => { void client.projects().then((value) => { setProjectChoices(value.projects); setProjectsOpen(true) }) }}><FolderOpen size={14} /> 项目</button><button className="run-button" disabled={runActive} onClick={() => setRunOpen(true)}>{runActive ? <LoaderCircle size={14} /> : <Play size={14} />} {runActive ? '运行中' : '运行完整流程'}</button><button className="icon-button" aria-label="更多操作"><MoreHorizontal size={17} /></button></div></header>
    {runProgress && <RunProgressBar progress={runProgress} nodeTitle={progressNodeTitle} onResults={() => setView('results')} />}
    <div className="workspace-shell"><aside className={`palette ${sidebarOpen ? '' : 'closed'}`}><header><div><span className="page-kicker">OPERATION PALETTE</span><h2>研究操作</h2></div><button className="icon-button" onClick={() => setSidebarOpen(false)}><PanelLeftClose size={16} /></button></header><div className="palette-search"><Search size={15} /><input placeholder="搜索 active Catalog…" value={search} onChange={(event) => setSearch(event.target.value)} /></div><div className="taxonomy-switch"><button className={paletteTaxonomy === 'purpose' ? 'active' : ''} onClick={() => setPaletteTaxonomy('purpose')}>按研究目的</button><button className={paletteTaxonomy === 'provider' ? 'active' : ''} onClick={() => setPaletteTaxonomy('provider')}>按包 / 模型</button></div><div className="palette-section"><span className="section-label">ACTIVE CATALOG</span>{palette.map((group) => <section className="palette-group" key={group.label}><span className="palette-group-title">{group.label}</span>{group.entries.map((item) => <button className="palette-item" key={`${group.label}-${item.id}`} draggable onDragStart={(event) => { event.dataTransfer.setData('application/protein-workbench-node-type', item.id); event.dataTransfer.effectAllowed = 'move' }}><span className="palette-icon"><Atom size={16} /></span><span><strong>{item.title}</strong><small>{paletteTaxonomy === 'purpose' ? item.purpose : group.label}</small></span><Plus size={14} /></button>)}</section>)}</div><div className="catalog-status"><span className="status-light" /><div><strong>Active Catalog</strong><small>{catalog?.contracts.length} contracts</small></div><CircleHelp size={14} /></div></aside>
      <main className="flow-canvas">{!sidebarOpen && <button className="floating-open" onClick={() => setSidebarOpen(true)}><ChevronRight size={16} /></button>}<ReactFlow nodes={displayed} edges={edges} nodeTypes={{ workflow: WorkflowCard }} isValidConnection={validConnection} onInit={(instance) => { flowInstance.current = instance }} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move' }} onDrop={dropPaletteNode} onNodeDragStart={remember} onBeforeDelete={async () => { remember(); return true }} onDelete={({ nodes: deletedNodes, edges: deletedEdges }) => { void deleteWorkflowElements(deletedNodes, deletedEdges) }} onNodesChange={(changes: NodeChange<FlowNode>[]) => { const next = applyNodeChanges(changes, nodesRef.current); nodesRef.current = next; setNodes(next); if (changes.some((change) => change.type === 'position' && change.dragging === false)) void persistCanvas(next) }} onEdgesChange={(changes: EdgeChange<Edge>[]) => { const next = applyEdgeChanges(changes, edgesRef.current); edgesRef.current = next; setEdges(next) }} onConnect={(connection: Connection) => { remember(); const target = nodesRef.current.find((node) => node.id === connection.target)!; const targetPort = connection.targetHandle!.slice(3); const available = target.data.inputMultiplicities[targetPort] === 'many' ? edgesRef.current : edgesRef.current.filter((edge) => edge.target !== connection.target || edge.targetHandle !== connection.targetHandle); const next = addEdge({ ...connection, type: 'default' }, available); edgesRef.current = next; setEdges(next); void saveFlowEdges(next) }} onReconnectStart={() => { reconnectSucceeded.current = false }} onReconnect={(edge, connection) => { reconnectSucceeded.current = true; remember(); const next = reconnectEdge(edge, connection, edgesRef.current); edgesRef.current = next; setEdges(next); void saveFlowEdges(next) }} onReconnectEnd={(_, edge) => { if (!reconnectSucceeded.current) { remember(); const next = edgesRef.current.filter((item) => item.id !== edge.id); edgesRef.current = next; setEdges(next); void saveFlowEdges(next) } reconnectSucceeded.current = false }} fitView fitViewOptions={{ padding: 0.16 }} minZoom={0.28} maxZoom={1.5} deleteKeyCode={['Backspace', 'Delete']} selectionOnDrag><Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#39413b" /><MiniMap nodeColor={(node) => String(node.data.accent)} maskColor="rgba(14,16,14,.72)" /><Controls showInteractive={false} /><Panel position="top-left" className="canvas-heading"><span className="page-kicker">WORKFLOW DRAFT · {nodes.length} GRAPH NODES · {draft.authoring_compositions.length} SPECIALIZED COMPOSITIONS</span><h1>{project.name}</h1><p>{draft.workflow.edges.length} persisted edges · exact Catalog Port compatibility</p></Panel><Panel position="top-right" className="canvas-tools"><button><Search size={14} /> 搜索画布</button><button><Layers3 size={14} /> 适合视图</button></Panel><Panel position="bottom-center" className="canvas-hint"><Zap size={13} /> 拖动端口以重新连接 · Delete 删除 · ⌘Z 撤销</Panel></ReactFlow></main>
      <aside className="run-peek"><header><div><span className="page-kicker">LATEST RUN</span><h3>最近结果</h3></div><span className="success-dot"><Check size={11} /></span></header><div className="run-peek-visual"><StructureViewer pdb={candidates[0]?.pdb} /><span>{run?.run_id}</span></div><div className="run-funnel">{(run?.selection_results ?? []).map((selection, index, all) => <span key={selection.selection_node_id}>{selection.selection_node_id}<strong>{selection.selected_candidate_ids.length}</strong>{index < all.length - 1 && <ChevronRight size={13} />}</span>)}</div>{project.copied_from_project_id && <div className="old-result-note"><Info size={14} /><span>来自修改前的流程</span></div>}<button className="view-results-button" disabled={!run || candidates.length === 0} onClick={() => setView('results')}><Activity size={14} /> 打开 Results Workbench <ChevronRight size={14} /></button></aside></div>
    {runOpen && <RunDialog draft={draft} onClose={() => setRunOpen(false)} onStart={async () => { const personal = await savedPersonalDraft(); const commit = await client.commitWorkflow(personal.project.id, personal.draft.workflow); const receipt = await client.startRun(personal.project.id, commit.workflow_commit_id); activeRunKey.current = `${receipt.project_id}/${receipt.run_id}`; setRunProgress({ status: 'admitted', totalNodes: personal.draft.workflow.nodes.length, completedNodeIds: [], nodeStates: Object.fromEntries(personal.draft.workflow.nodes.map((node) => [node.node_id, { status: 'waiting' as const }])), projectId: receipt.project_id, runId: receipt.run_id, workflowCommitId: receipt.workflow_commit_id, eventCursor: receipt.event_cursor, resultsReady: false }); setRunOpen(false) }} />}
    {pendingNodeDrop && <div className="modal-backdrop"><section className="run-dialog binding-dialog" role="dialog" aria-modal="true" aria-labelledby="binding-dialog-title"><header><span className="dialog-icon"><Atom size={18} /></span><div><span className="page-kicker">EXECUTION BINDING</span><h2 id="binding-dialog-title">为 {pendingNodeTitle} 选择执行模型</h2></div><button className="icon-button" onClick={() => setPendingNodeDrop(undefined)}><X size={18} /></button></header><div className="binding-choice-list">{pendingNodeDrop.bindings.map((binding) => <button key={binding.id} disabled={!binding.available} onClick={() => void addDroppedNode(pendingNodeDrop, binding.id)}><strong>{binding.label}{binding.available ? '' : '（不可用）'}</strong><small>{binding.id}</small></button>)}</div><footer><button className="secondary-button" onClick={() => setPendingNodeDrop(undefined)}>取消</button></footer></section></div>}
    {projectsOpen && <ProjectDialog projects={projectChoices} query={projectQuery} onQuery={setProjectQuery} onSearch={async () => setProjectChoices((await client.projects(projectQuery)).projects)} onOpen={openProject} onCreate={async () => { const schemaVersion = draft.workflow.schema_version; projectGeneration.current += 1; workflowRevision.current += 1; activeRunKey.current = undefined; personalization.current = undefined; history.current = []; activeParameterEdits.current.clear(); setProject(undefined); setDraft(undefined); draftRef.current = undefined; workflowRef.current = undefined; nodesRef.current = []; edgesRef.current = []; setNodes([]); setEdges([]); setProjectsOpen(false); const created = await client.createProject(`Untitled Project ${new Date().toLocaleString()}`); const empty: Workflow = { schema_version: schemaVersion, workflow_id: created.id, nodes: [], edges: [], observation_selectors: [], selection_objectives: [] }; const saved = await client.saveWorkflowDraft(created.id, empty); const flow = flowFromDraft(saved, catalog); projectDrafts.current[created.id] = saved; draftRef.current = saved; workflowRef.current = saved.workflow; nodesRef.current = flow.nodes; edgesRef.current = flow.edges; setProject(created); setDraft(saved); setNodes(flow.nodes); setEdges(flow.edges); setRun(undefined); setRunProgress(undefined); setCandidates([]); setScores([]); setSaveState('空白项目已创建') }} onClose={() => setProjectsOpen(false)} />}
  </div>
}

export default App
