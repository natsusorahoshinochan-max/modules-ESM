import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Background, BackgroundVariant, Controls, Handle, MiniMap, Panel, Position, ReactFlow, addEdge, applyEdgeChanges, applyNodeChanges, reconnectEdge, type Connection, type Edge, type EdgeChange, type Node, type NodeChange, type NodeProps } from '@xyflow/react'
import { Activity, Atom, Braces, Check, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Download, FolderOpen, GitBranch, Info, Layers3, LoaderCircle, Menu, MoreHorizontal, Network, PanelLeftClose, Play, Plus, RotateCcw, Search, SlidersHorizontal, Sparkles, Target, TestTubeDiagonal, X, Zap } from 'lucide-react'
import { strToU8, zipSync } from 'fflate'
import { PromptStudio } from './PromptStudio'
import { PublicV2Client, type CatalogSnapshot, type JsonObject, type ProjectMetadata, type PromptSnapshot, type RunEventEnvelope, type RunProjection, type RunStatus, type Workflow, type WorkflowDraft, type WorkflowNode } from './protocol/client'
import { StructureViewer } from './StructureViewer'

const client = new PublicV2Client()
type Parameter = { key: string; label: string; value: string; suffix?: string }
type WorkflowNodeData = Record<string, unknown> & { kind: 'prompt' | 'generate' | 'select' | 'fold' | 'design'; eyebrow: string; title: string; subtitle: string; index: string; inputs: string[]; outputs: string[]; parameters: Parameter[]; accent: string; count: string; collapsed?: boolean; onToggle?: (id: string) => void; onEditPrompt?: () => void; onParameter?: (id: string, key: string, value: string, commit: boolean) => void }
type FlowNode = Node<WorkflowNodeData>
type CandidateView = { id: string; parent: string; pdb: string; sequence: string; metadata: JsonObject }
type ScoreView = { candidateId: string; metricId: string; methodId: string; context: JsonObject; value: number }
type RunProgress = { status: 'committing' | 'starting' | RunStatus; totalNodes: number; completedNodeIds: string[]; currentNodeId?: string; lastNodeId?: string; projectId?: string; runId?: string; workflowCommitId?: string; eventCursor?: string; resultsReady?: boolean }

const visibleSteps = [
  { id: 'prompt-composition-webui-3gb1', source: '', kind: 'prompt', eyebrow: 'SPECIALIZED COMPOSITION', title: '编写 ProteinPrompt', subtitle: '3GB1 · chain A', accent: '#ae9cff', count: '56 → 57 aa', inputs: [], outputs: ['protein.prompt'] },
  { id: 'generate-paired', source: 'generate-paired', kind: 'generate', eyebrow: 'GENERATE', title: '生成候选蛋白质', subtitle: 'ESM-3', accent: '#55c8b7', count: '7 candidates', inputs: ['protein.prompt'], outputs: ['candidate.collection'] },
  { id: 'take-top-four', source: 'take-top-four', kind: 'select', eyebrow: 'SELECTION', title: '保留高置信候选', subtitle: 'mean-residue pLDDT', accent: '#e7b75f', count: 'Top 4', inputs: ['Candidates', 'Scores'], outputs: ['Selected'] },
  { id: 'fold-stage-one', source: 'fold-stage-one', kind: 'fold', eyebrow: 'STRUCTURE PREDICTION', title: '预测蛋白质结构', subtitle: 'ESMFold2', accent: '#71a8ff', count: '4 structures', inputs: ['Selected'], outputs: ['Structures', 'pLDDT'] },
  { id: 'take-top-two', source: 'take-top-two', kind: 'select', eyebrow: 'MULTI-OBJECTIVE', title: '选择折叠候选', subtitle: 'parent-normalized', accent: '#e7b75f', count: 'Top 2', inputs: ['Structures', 'Scores'], outputs: ['Selected'] },
  { id: 'design-children', source: 'design-children', kind: 'design', eyebrow: 'SEQUENCE DESIGN', title: '设计蛋白质序列', subtitle: 'ProteinMPNN', accent: '#ec8fb0', count: '2 × 3 = 6', inputs: ['Parents'], outputs: ['Sequences'] },
  { id: 'fold-final', source: 'fold-final', kind: 'fold', eyebrow: 'STRUCTURE PREDICTION', title: '重折叠子序列', subtitle: 'ESMFold2', accent: '#71a8ff', count: '6 structures', inputs: ['Sequences'], outputs: ['Structures', 'pLDDT'] },
  { id: 'take-top-three', source: 'take-top-three', kind: 'select', eyebrow: 'FINAL SELECTION', title: '最终候选', subtitle: 'direct-ancestor comparison', accent: '#e7b75f', count: 'Top 3', inputs: ['Structures', 'Scores'], outputs: ['Final candidates'] },
] as const
const positions = [{ x: 60, y: 170 }, { x: 390, y: 170 }, { x: 720, y: 70 }, { x: 1050, y: 170 }, { x: 60, y: 520 }, { x: 390, y: 520 }, { x: 720, y: 420 }, { x: 1050, y: 520 }]

function nodeParameters(stepId: string, workflow: Workflow): Parameter[] {
  const node = workflow.nodes.find((item) => item.node_id === stepId)
  if (!node) return []
  const labels: Record<string, string> = { effective_seed: '有效种子', num_samples: '生成数量', k: '保留数量', num_sequences: '每个父结构', temperature: '温度', backbone_noise: '骨架噪声' }
  return Object.entries(node.node_parameters).filter(([key]) => key !== 'objective_ids' && key !== 'tie_policy').map(([key, value]) => ({ key, label: labels[key] ?? key, value: String(value) }))
}

function flowFromDraft(draft: WorkflowDraft): { nodes: FlowNode[]; edges: Edge[] } {
  if (draft.workflow.nodes.length === 0) return { nodes: [], edges: [] }
  const nodes = visibleSteps.map((step, index): FlowNode => ({ id: step.id, type: 'workflow', position: positions[index], data: { kind: step.kind, eyebrow: step.eyebrow, title: step.title, subtitle: step.subtitle, index: String(index + 1).padStart(2, '0'), inputs: [...step.inputs], outputs: [...step.outputs], parameters: nodeParameters(step.source, draft.workflow), accent: step.accent, count: step.count } }))
  const edges = visibleSteps.slice(0, -1).map((step, index): Edge => ({ id: `visible-edge-${index}`, source: step.id, target: visibleSteps[index + 1].id, type: 'smoothstep', style: { stroke: '#637168', strokeWidth: 1.6 } }))
  return { nodes, edges }
}

function WorkflowCard({ id, data, selected }: NodeProps<FlowNode>) {
  const Icon = data.kind === 'prompt' ? Braces : data.kind === 'generate' ? Sparkles : data.kind === 'select' ? Target : data.kind === 'fold' ? Atom : TestTubeDiagonal
  return <article className={`workflow-node ${selected ? 'is-selected' : ''} ${data.collapsed ? 'is-collapsed' : ''}`} style={{ '--node-accent': data.accent } as React.CSSProperties}>
    {data.inputs.map((port, index) => <Handle key={port} id={`in-${index}`} type="target" position={Position.Left} style={{ top: data.collapsed ? 31 : 112 + index * 26 }} className="node-handle input-handle" />)}
    {data.outputs.map((port, index) => <Handle key={port} id={`out-${index}`} type="source" position={Position.Right} style={{ top: data.collapsed ? 31 : 112 + index * 26 }} className="node-handle output-handle" />)}
    <header className="node-header"><span className="node-icon"><Icon size={15} /></span><div><span className="node-eyebrow">{data.eyebrow}</span><h3>{data.title}</h3></div><span className="node-index">{data.index}</span><button className="icon-button nodrag" onClick={() => data.onToggle?.(id)}><ChevronDown size={15} /></button></header>
    {!data.collapsed && <><div className="node-meta"><span>{data.subtitle}</span><strong>{data.count}</strong></div><div className="ports-block"><div>{data.inputs.map((port) => <span key={port} className="port input-port">{port}</span>)}</div><div>{data.outputs.map((port) => <span key={port} className="port output-port">{port}</span>)}</div></div>
      {data.kind === 'prompt' ? <button className="prompt-edit-button nodrag" onClick={data.onEditPrompt}><Braces size={14} /> 打开 Prompt Studio <ChevronRight size={14} /></button> : <details className="parameter-group nodrag"><summary aria-label="编辑参数"><SlidersHorizontal size={13} /> 参数 <span>{data.parameters.length}</span></summary><div className="parameter-fields">{data.parameters.map((parameter) => <label key={parameter.key}><span>{parameter.label}</span><span className="field-control"><input value={parameter.value} onChange={(event) => data.onParameter?.(id, parameter.key, event.target.value, false)} onBlur={(event) => data.onParameter?.(id, parameter.key, event.target.value, true)} />{parameter.suffix && <em>{parameter.suffix}</em>}</span></label>)}</div></details>}
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
  files['manifest.json'] = strToU8(JSON.stringify({ schema_namespace: 'protein-workbench-webui-export/v1', run_id: run.run_id, workflow_commit_id: run.workflow_commit_id, candidates: candidates.map(({ id, parent }) => ({ candidate_id: id, parent_id: parent })), selection: run.selection_results?.find((item) => item.selection_node_id === 'rank-final') }, null, 2))
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
  return <div className="results-page"><aside className="results-sidebar"><button className="back-to-workflow" onClick={onBack}><ChevronLeft size={15} /> 返回 Workflow</button><div className="results-title"><span className="page-kicker">LATEST RUN</span><h2>3GB1 局部重设计</h2><span className="success-pill"><Check size={12} /> {run.status}</span><small>{run.workflow_commit_id}</small></div><nav className="result-steps">{(run.selection_results ?? []).map((item) => <button key={item.selection_node_id} className={item.selection_node_id === 'rank-final' ? 'active' : ''}><span><Target size={14} /></span><strong>{item.selection_node_id}</strong><em>{item.selected_candidate_ids.length}</em></button>)}</nav><div className="run-meta"><span>Run provenance</span><code>{run.run_id}</code></div></aside>
    <main className="results-main"><header className="results-header"><div><span className="page-kicker">RESULTS WORKBENCH</span><h1>最终候选 <span>{candidates.length}</span></h1></div><div className="results-actions"><button className="secondary-button"><GitBranch size={14} /> 谱系证据</button><button className="primary-button" onClick={() => exportCandidates(candidates.filter((candidate) => selected.has(candidate.id)), scores, run)}><Download size={14} /> 导出所选 · ZIP</button></div></header><section className="lineage-strip"><div className="lineage-heading"><span className="page-kicker">CANDIDATE LINEAGE</span><span>精确 Candidate parent IDs</span></div><div className="lineage-graph"><div className="lineage-stage"><span>ProteinMPNN parents</span>{[...new Set(candidates.map((item) => item.parent))].map((id) => <button key={id}><TestTubeDiagonal size={14} /> {id.slice(-10)}</button>)}</div><ChevronRight className="lineage-arrow" /><div className="lineage-stage final"><span>Refolded final</span>{candidates.map((candidate) => <button key={candidate.id} className={focused.id === candidate.id ? 'active' : ''} onClick={() => setFocused(candidate)}><Atom size={14} /> {candidate.id.slice(-10)}</button>)}</div></div></section>
      <div className="results-grid"><section className="candidate-table-card"><header><div><span className="page-kicker">CANDIDATES</span><h3>Final Top 3</h3></div></header><div className="candidate-table-head"><span /><span>Candidate</span><span>Direct parent</span><span>Stage</span><span /></div>{candidates.map((candidate) => <button className={`candidate-row ${focused.id === candidate.id ? 'active' : ''}`} key={candidate.id} onClick={() => setFocused(candidate)}><span className={`checkbox ${selected.has(candidate.id) ? 'checked' : ''}`} onClick={(event) => { event.stopPropagation(); setSelected((current) => { const next = new Set(current); if (next.has(candidate.id)) next.delete(candidate.id); else next.add(candidate.id); return next }) }}>{selected.has(candidate.id) && <Check size={11} />}</span><strong>{candidate.id.slice(-12)}</strong><code>{candidate.parent.slice(-10)}</code><em>Final Top 3</em><ChevronRight size={14} /></button>)}<footer>{selected.size} selected for comparison and export</footer></section>
        <section className="focused-candidate-card"><header><div><span className="page-kicker">FOCUSED CANDIDATE</span><h3>{focused.id.slice(-16)}</h3></div></header><div className="focused-body"><div className="mini-viewer"><StructureViewer pdb={focused.pdb} /><span>ESMFold2 structure</span></div><div className="candidate-details"><span className="section-label">SEQUENCE</span><code className="sequence-block">{focused.sequence}</code>{scores.filter((score) => score.candidateId === focused.id && ['structure.plddt.mean_residue', 'structure_comparison.tm_score'].includes(score.metricId)).map((score) => { const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'metric' && contract.reference.contract_id === score.metricId)?.descriptor; return <div className="metric-placeholder" key={`${score.metricId}-${score.context.kind}`}><Activity size={16} /><span><strong>{String(descriptor?.title)}</strong><small>{score.value.toFixed(4)} {String(descriptor?.unit)} · {score.methodId} · {String(score.context.pairing_mode ?? score.context.kind)} · {String(descriptor?.direction)}</small></span><Info size={14} /></div> })}<div className="provenance-list"><span>Direct parent</span><strong>{focused.parent}</strong><span>Comparison context</span><strong>per_subject_direct_ancestor</strong></div></div></div></section></div></main></div>
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

function App() {
  const [catalog, setCatalog] = useState<CatalogSnapshot>()
  const [capabilities, setCapabilities] = useState<JsonObject>()
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
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [saveState, setSaveState] = useState('加载中…')
  const history = useRef<Array<{ nodes: FlowNode[]; edges: Edge[] }>>([])
  const personalization = useRef<Promise<{ project: ProjectMetadata; draft: WorkflowDraft }> | undefined>(undefined)
  const reconnectSucceeded = useRef(false)
  const activeRunKey = useRef<string | undefined>(undefined)

  const loadCompletedRun = useCallback(async (projectId: string, runId: string) => {
    const projection = await client.runProjection(projectId, runId)
    let nextCandidates: CandidateView[] = []
    let nextScores: ScoreView[] = []
    if (projection.status === 'succeeded') {
      const [typed, scoreValue] = await Promise.all([client.typedValue(projectId, runId, 'take-top-three', 'candidates'), client.typedValue(projectId, runId, 'scores-final', 'scores')])
      nextCandidates = decodeCandidates(typed.value)
      nextScores = decodeScores(scoreValue.value)
    }
    const runKey = `${projectId}/${runId}`
    if (activeRunKey.current !== runKey) return
    if (projection.status === 'succeeded') {
      setRun(projection)
      setCandidates(nextCandidates)
      setScores(nextScores)
    }
    setProject((current) => current?.id === projectId ? { ...current, latest_run_id: runId } : current)
    setRunProgress((current) => current?.projectId === projectId && current.runId === runId ? { ...current, resultsReady: true } : current)
  }, [])

  useEffect(() => {
    if (!runProgress?.projectId || !runProgress.runId || !runProgress.eventCursor) return
    const projectId = runProgress.projectId
    const runId = runProgress.runId
    const socket = client.runEvents(projectId, runId, runProgress.eventCursor)
    socket.onmessage = (message) => {
      const envelope = JSON.parse(message.data as string) as RunEventEnvelope
      const event = envelope.event
      if (event.type === 'run_started') setRunProgress((current) => current?.runId === runId ? { ...current, status: 'running' } : current)
      if (event.type === 'node_attempt_started') setRunProgress((current) => current?.runId === runId ? { ...current, status: 'running', currentNodeId: event.node_id } : current)
      if (event.type === 'node_disposition') setRunProgress((current) => {
        if (current?.runId !== runId) return current
        const completedNodeIds = current.completedNodeIds.includes(event.disposition.node_id) ? current.completedNodeIds : [...current.completedNodeIds, event.disposition.node_id]
        return { ...current, completedNodeIds, lastNodeId: event.disposition.node_id, currentNodeId: current.currentNodeId === event.disposition.node_id ? undefined : current.currentNodeId }
      })
      if (event.type === 'run_terminal') {
        setRunProgress((current) => current?.runId === runId ? { ...current, status: event.status, currentNodeId: undefined } : current)
        void loadCompletedRun(projectId, runId)
      }
    }
    return () => socket.close()
  }, [loadCompletedRun, runProgress?.eventCursor, runProgress?.projectId, runProgress?.runId])

  useEffect(() => { void (async () => { const [catalogValue, capabilityValue, projects] = await Promise.all([client.catalog(), client.authoringCapabilities(), client.projects()]); const example = projects.projects.find((item) => item.project_kind === 'default_example'); if (!example) throw new Error('Default example Project is absent'); const draftValue = await client.workflowDraft(example.id); const flow = flowFromDraft(draftValue); setCatalog(catalogValue); setCapabilities(capabilityValue); setProject(example); setDraft(draftValue); setNodes(flow.nodes); setEdges(flow.edges); if (example.latest_run_id) { const runValue = await client.runProjection(example.id, example.latest_run_id); if (runValue.status === 'succeeded') { const [typed, scoreValue] = await Promise.all([client.typedValue(example.id, example.latest_run_id, 'take-top-three', 'candidates'), client.typedValue(example.id, example.latest_run_id, 'scores-final', 'scores')]); setRun(runValue); setCandidates(decodeCandidates(typed.value)); setScores(decodeScores(scoreValue.value)) } } setSaveState('示例已加载') })() }, [])

  const ensurePersonal = useCallback(async () => { if (!project || !draft) throw new Error('Project is not loaded'); if (project.project_kind === 'personal') return { project, draft }; if (!personalization.current) { setSaveState('正在创建个人副本…'); personalization.current = client.copyExample(project.id, `${project.name} · 我的副本`).then(async (copy) => { const copyDraft = await client.workflowDraft(copy.id); setProject(copy); setDraft(copyDraft); setSaveState('个人副本已保存'); return { project: copy, draft: copyDraft } }) } return personalization.current }, [project, draft])
  const openProject = useCallback(async (selected: ProjectMetadata) => { activeRunKey.current = undefined; setRunProgress(undefined); setRun(undefined); setCandidates([]); setScores([]); const selectedDraft = await client.workflowDraft(selected.id); const flow = flowFromDraft(selectedDraft); setProject(selected); setDraft(selectedDraft); setNodes(flow.nodes); setEdges(flow.edges); setProjectsOpen(false); setSaveState('项目已打开'); if (selected.latest_run_id) { const selectedRun = await client.runProjection(selected.id, selected.latest_run_id); if (selectedRun.status === 'succeeded') { const [typed, scoreValue] = await Promise.all([client.typedValue(selected.id, selected.latest_run_id, 'take-top-three', 'candidates'), client.typedValue(selected.id, selected.latest_run_id, 'scores-final', 'scores')]); setRun(selectedRun); setCandidates(decodeCandidates(typed.value)); setScores(decodeScores(scoreValue.value)) } } }, [])
  const saveParameter = useCallback(async (nodeId: string, key: string, raw: string) => { const personal = await ensurePersonal(); const source = personal.draft.workflow.nodes.find((item) => item.node_id === nodeId); if (!source) return; const current = source.node_parameters[key]; const value = typeof current === 'number' ? Number(raw) : typeof current === 'boolean' ? raw === 'true' : raw; const workflow = { ...personal.draft.workflow, nodes: personal.draft.workflow.nodes.map((item): WorkflowNode => item.node_id === nodeId ? { ...item, node_parameters: { ...item.node_parameters, [key]: value } } : item) }; setSaveState('自动保存中…'); const saved = await client.saveWorkflowDraft(personal.project.id, workflow); setDraft(saved); const flow = flowFromDraft(saved); setNodes(flow.nodes); setSaveState('已自动保存') }, [ensurePersonal])
  const undo = useCallback(() => { const previous = history.current.pop(); if (previous) { setNodes(previous.nodes); setEdges(previous.edges); setSaveState('已撤销画布修改') } }, [])
  const remember = useCallback(() => history.current.push({ nodes: structuredClone(nodes), edges: structuredClone(edges) }), [nodes, edges])
  const displayed = useMemo(() => nodes.map((node) => ({ ...node, data: { ...node.data, onToggle: (id: string) => setNodes((current) => current.map((item) => item.id === id ? { ...item, data: { ...item.data, collapsed: !item.data.collapsed } } : item)), onEditPrompt: async () => { if (!project || !draft) return; const composition = draft.authoring_compositions[0]; setPrompt(await client.openPrompt(project.id, composition.composition_id)) }, onParameter: (id: string, key: string, value: string, commit: boolean) => { setNodes((current) => current.map((item) => item.id === id ? { ...item, data: { ...item.data, parameters: item.data.parameters.map((parameter) => parameter.key === key ? { ...parameter, value } : parameter) } } : item)); if (commit) void saveParameter(id, key, value) } } })), [nodes, project, draft, saveParameter])
  const palette = useMemo(() => { if (!catalog || !capabilities) return []; const roles = capabilities.node_roles as Array<{ node_type: { contract_id: string }; role: string }>; const ordinary = new Set(roles.filter((item) => item.role === 'ordinary_node').map((item) => item.node_type.contract_id)); return catalog.contracts.filter((item) => item.reference.contract_kind === 'node_type' && ordinary.has(item.reference.contract_id)).map((item) => ({ id: item.reference.contract_id, title: String(item.descriptor.title), category: String(item.descriptor.category) })).filter((item) => `${item.title}${item.id}`.toLowerCase().includes(search.toLowerCase())).slice(0, 12) }, [catalog, capabilities, search])
  const progressNodeTitle = useMemo(() => {
    if (!runProgress?.currentNodeId || !draft || !catalog) return ''
    const node = draft.workflow.nodes.find((item) => item.node_id === runProgress.currentNodeId)
    const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'node_type' && contract.reference.contract_id === node?.node_type_id)?.descriptor
    return String(descriptor?.title ?? node?.node_type_id ?? runProgress.currentNodeId)
  }, [catalog, draft, runProgress?.currentNodeId])
  const runActive = runProgress ? ['committing', 'starting', 'admitted', 'running'].includes(runProgress.status) : false

  if (!project || !draft) return <div className="loading-screen">正在从 public v2 protocol 加载 WebUI 示例…</div>
  if (prompt) return <PromptStudio snapshot={prompt} onCancel={() => setPrompt(undefined)} onPreview={async (document) => { const personal = await ensurePersonal(); const composition = personal.draft.authoring_compositions[0]; return client.previewPrompt(personal.project.id, composition.composition_id, document) }} onApply={async (preview) => { const personal = await ensurePersonal(); const composition = personal.draft.authoring_compositions[0]; const applied = await client.applyPrompt(personal.project.id, composition.composition_id, preview); setDraft(applied.draft); setPrompt(undefined); setSaveState('Prompt 已保存') }} />
  if (view === 'results' && run && catalog) return <ResultsWorkbench run={run} candidates={candidates} scores={scores} catalog={catalog} onBack={() => setView('workflow')} />
  return <div className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark"><Braces size={16} /></span><div><strong>Protein</strong><span>Workbench</span></div></div><div className="project-identity"><button className="icon-button" aria-label="主菜单"><Menu size={16} /></button><div><span className="page-kicker">{project.project_kind.replace('_', ' ')}</span><strong>{project.name}</strong></div>{project.seed && <span className="immutable-pill">只读示例</span>}</div><nav className="view-tabs"><button className="active"><Network size={14} /> Workflow</button><button disabled={!run || candidates.length === 0} onClick={() => setView('results')}><Activity size={14} /> Results <span>{candidates.length}</span></button></nav><div className="top-actions"><span className="save-state"><span />{saveState}</span><button className="icon-button" aria-label="撤销画布修改" onClick={undo}><RotateCcw size={16} /></button><button className="secondary-button" onClick={() => { void client.projects().then((value) => { setProjectChoices(value.projects); setProjectsOpen(true) }) }}><FolderOpen size={14} /> 项目</button><button className="run-button" disabled={runActive} onClick={() => setRunOpen(true)}>{runActive ? <LoaderCircle size={14} /> : <Play size={14} />} {runActive ? '运行中' : '运行完整流程'}</button><button className="icon-button" aria-label="更多操作"><MoreHorizontal size={17} /></button></div></header>
    {runProgress && <RunProgressBar progress={runProgress} nodeTitle={progressNodeTitle} onResults={() => setView('results')} />}
    <div className="workspace-shell"><aside className={`palette ${sidebarOpen ? '' : 'closed'}`}><header><div><span className="page-kicker">OPERATION PALETTE</span><h2>研究操作</h2></div><button className="icon-button" onClick={() => setSidebarOpen(false)}><PanelLeftClose size={16} /></button></header><div className="palette-search"><Search size={15} /><input placeholder="搜索 active Catalog…" value={search} onChange={(event) => setSearch(event.target.value)} /></div><div className="taxonomy-switch"><button className="active">按研究目的</button><button>按包 / 模型</button></div><div className="palette-section"><span className="section-label">ACTIVE CATALOG</span>{palette.map((item) => <button className="palette-item" key={item.id} draggable><span className="palette-icon"><Atom size={16} /></span><span><strong>{item.title}</strong><small>{item.category}</small></span><Plus size={14} /></button>)}</div><div className="catalog-status"><span className="status-light" /><div><strong>Active Catalog</strong><small>{catalog?.contracts.length} contracts</small></div><CircleHelp size={14} /></div></aside>
      <main className="flow-canvas">{!sidebarOpen && <button className="floating-open" onClick={() => setSidebarOpen(true)}><ChevronRight size={16} /></button>}<ReactFlow nodes={displayed} edges={edges} nodeTypes={{ workflow: WorkflowCard }} onNodesChange={(changes: NodeChange<FlowNode>[]) => { if (changes.some((change) => change.type === 'position' && change.dragging === false)) { remember(); void ensurePersonal(); setSaveState('画布位置已保存') } setNodes((current) => applyNodeChanges(changes, current)) }} onEdgesChange={(changes: EdgeChange<Edge>[]) => { if (changes.some((change) => change.type === 'remove')) { remember(); void ensurePersonal(); setSaveState('画布连接已修改') } setEdges((current) => applyEdgeChanges(changes, current)) }} onConnect={(connection: Connection) => { remember(); void ensurePersonal(); setSaveState('画布连接已修改'); setEdges((current) => addEdge({ ...connection, type: 'smoothstep' }, current)) }} onReconnectStart={() => { reconnectSucceeded.current = false }} onReconnect={(edge, connection) => { reconnectSucceeded.current = true; remember(); void ensurePersonal(); setSaveState('画布连接已修改'); setEdges((current) => reconnectEdge(edge, connection, current)) }} onReconnectEnd={(_, edge) => { if (!reconnectSucceeded.current) { remember(); void ensurePersonal(); setSaveState('画布连接已修改'); setEdges((current) => current.filter((item) => item.id !== edge.id)) } reconnectSucceeded.current = false }} fitView fitViewOptions={{ padding: 0.16 }} minZoom={0.28} maxZoom={1.5} deleteKeyCode={['Backspace', 'Delete']} selectionOnDrag><Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#39413b" /><MiniMap nodeColor={(node) => String(node.data.accent)} maskColor="rgba(14,16,14,.72)" /><Controls showInteractive={false} /><Panel position="top-left" className="canvas-heading"><span className="page-kicker">WORKFLOW DRAFT · 8 VISIBLE STEPS / {draft.workflow.nodes.length} MATERIALIZED NODES</span><h1>{project.name}</h1><p>A37–A41 sequence + coordinates redesign · 7 → 4 → 4 → 2 → 6 → 6 → 3</p></Panel><Panel position="top-right" className="canvas-tools"><button><Search size={14} /> 搜索画布</button><button><Layers3 size={14} /> 适合视图</button></Panel><Panel position="bottom-center" className="canvas-hint"><Zap size={13} /> 拖动端口以重新连接 · Delete 删除 · ⌘Z 撤销</Panel></ReactFlow></main>
      <aside className="run-peek"><header><div><span className="page-kicker">BUNDLED RESULT</span><h3>最近结果</h3></div><span className="success-dot"><Check size={11} /></span></header><div className="run-peek-visual"><StructureViewer pdb={candidates[0]?.pdb} /><span>{run?.run_id}</span></div><div className="run-funnel"><span>ESM-3<strong>7</strong></span><ChevronRight size={13} /><span>Fold<strong>4</strong></span><ChevronRight size={13} /><span>MPNN<strong>6</strong></span><ChevronRight size={13} /><span>Final<strong>{candidates.length}</strong></span></div>{project.copied_from_project_id && <div className="old-result-note"><Info size={14} /><span>来自修改前的流程</span></div>}<button className="view-results-button" disabled={!run || candidates.length === 0} onClick={() => setView('results')}><Activity size={14} /> 打开 Results Workbench <ChevronRight size={14} /></button></aside></div>
    {runOpen && <RunDialog draft={draft} onClose={() => setRunOpen(false)} onStart={async () => { const personal = await ensurePersonal(); const commit = await client.commitWorkflow(personal.project.id, personal.draft.workflow); const receipt = await client.startRun(personal.project.id, commit.workflow_commit_id); activeRunKey.current = `${receipt.project_id}/${receipt.run_id}`; setRunProgress({ status: 'admitted', totalNodes: personal.draft.workflow.nodes.length, completedNodeIds: [], projectId: receipt.project_id, runId: receipt.run_id, workflowCommitId: receipt.workflow_commit_id, eventCursor: receipt.event_cursor, resultsReady: false }); setRunOpen(false) }} />}
    {projectsOpen && <ProjectDialog projects={projectChoices} query={projectQuery} onQuery={setProjectQuery} onSearch={async () => setProjectChoices((await client.projects(projectQuery)).projects)} onOpen={openProject} onCreate={async () => { activeRunKey.current = undefined; const created = await client.createProject(`Untitled Project ${new Date().toLocaleString()}`); const empty: Workflow = { schema_version: draft.workflow.schema_version, workflow_id: created.id, nodes: [], edges: [], observation_selectors: [], selection_objectives: [] }; const saved = await client.saveWorkflowDraft(created.id, empty); const flow = flowFromDraft(saved); setProject(created); setDraft(saved); setNodes(flow.nodes); setEdges(flow.edges); setRun(undefined); setRunProgress(undefined); setCandidates([]); setScores([]); setProjectsOpen(false); setSaveState('空白项目已创建') }} onClose={() => setProjectsOpen(false)} />}
  </div>
}

export default App
