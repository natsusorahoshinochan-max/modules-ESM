import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Edge, Flow, FlowNode, Scope, ModuleHost, PackageInfo, EditorContext, EditorUpdate } from '@protein-workbench/module-ui'
import { client, type Catalog, type Project, type Run } from './host-client'
import { loadExtensions, type LoadedExtensions } from './host-ui'
import { ParameterFields } from './ParameterFields'
import { ModuleManagement } from './ModuleManagement'
import { WorkflowCanvas, connectionProblem, CanvasToolPicker } from './WorkflowCanvas'
import { ScopeEditor } from './ScopeEditor'
import { callLabel, callPath, copyNode, declarationFor, flowAt, replaceFlow } from './flow-model'

class ExtensionBoundary extends Component<{ children: ReactNode; onReturn?: () => void }, { error: string }> {
  state = { error: '' }
  static getDerivedStateFromError(error: Error) { return { error: error.message } }
  render() { return this.state.error ? <div role="alert">Module interface failed: {this.state.error}{this.props.onReturn && <button onClick={this.props.onReturn}>返回画布</button>}</div> : this.props.children }
}

function frozenParameterCopy(parameters: Record<string, unknown>) {
  const snapshot = structuredClone(parameters)
  function freeze(value: unknown) {
    if (value && typeof value === 'object') {
      Object.values(value).forEach(freeze)
      Object.freeze(value)
    }
  }
  freeze(snapshot)
  return snapshot
}

const statusLabel = (status: string) => ({succeeded:'已完成',failed:'失败',cancelled:'已取消',running:'运行中',pending:'等待中',blocked:'未执行',configuration_blocked:'配置未完成'}[status] ?? status)

export default function App() {
  const [{ catalog, extensions, projects }, setSnapshot] = useState<{ catalog: Catalog; extensions: LoadedExtensions; projects: Project[] }>({ catalog: { nodes: [], modules: [] }, extensions: {}, projects: [] })
  const moduleEpoch = useRef(0)
  const projectEpoch = useRef(0)
  const projectRead = useRef<object | null>(null)
  const projectReadQueued = useRef(false)
  const invalidateRefresh = () => { moduleEpoch.current += 1 }
  const [project, setProject] = useState<Project | null>(null)
  const [managementOpen, setManagementOpen] = useState(false)
  const [resultsOpen, setResultsOpen] = useState(false)
  const [focusRequest,setFocusRequest]=useState<{id:string;token:number}>()
  const [projectMenu, setProjectMenu] = useState(false)
  const [modulesOpen, setModulesOpen] = useState(false)
  const [importAction, setImportAction] = useState('')
  const [resultRun, setResultRun] = useState('')
  const [resultCall, setResultCall] = useState('')
  const [useTarget, setUseTarget] = useState('')
  const [usePort, setUsePort] = useState('')
  const [workspace, setWorkspace] = useState<{ editor: NonNullable<LoadedExtensions['editors']>[number]; context: EditorContext } | null>(null)
  const workspaceDirty = useRef(false)
  const workspaceToken = useRef<symbol | null>(null)
  const workspaceInteractions = useRef(new Set<string>())
  const workspaceRequests = useRef(new Set<AbortController>())
  const undoStack = useRef<Project[]>([])
  const redoStack = useRef<Project[]>([])
  function releaseWorkspaceOperations() {
    workspaceToken.current = null
    for (const request of workspaceRequests.current) request.abort()
    workspaceRequests.current.clear()
    for (const id of workspaceInteractions.current) { temporaryInteractions.current.delete(id); void client.cancelInteraction(id).catch(()=>{}) }
    workspaceInteractions.current.clear()
  }
  function closeWorkspace() {
    releaseWorkspaceOperations(); workspaceDirty.current = false; setWorkspace(null)
  }
  function openWorkspace(node: FlowNode, editor: NonNullable<LoadedExtensions['editors']>[number]) {
    const token = Symbol('editor workspace');workspaceToken.current=token;workspaceDirty.current=false
    setWorkspace({editor,context:editorContext(node,token)})
  }

  const currentProject = useRef<Project | null>(null)
  const [scopePath, setScopePath] = useState<string[]>([])
  const scopePathNow = useRef<string[]>([])
  const activeFlow = project ? flowAt(project.flow, scopePath) ?? project.flow : undefined
  const activeScope = project && scopePath.length ? flowAt(project.flow, scopePath.slice(0, -1))?.nodes.find(node => node.id === scopePath.at(-1)) : undefined
  const liveProject = useRef(true)
  const projectSession = useRef(0)
  const opening = useRef(0)
  const runningNow = useRef(false)
  const submittingRun = useRef(false)
  const runOperationEpoch = useRef(0)
  const [{dirty}, setDirty] = useState({dirty: false, revision: 0})
  const dirtyNow = useRef(false)
  const draftRevision = useRef(0)
  const parameterSnapshots = useRef(new WeakMap<Record<string, unknown>, Record<string, unknown>>())
  function markDirty(value: boolean) { if (value) draftRevision.current += 1; dirtyNow.current = value; setDirty({dirty: value, revision: draftRevision.current}) }
  const canvas = useRef<HTMLElement>(null)
  const [saving, setSaving] = useState(false)
  const savingNow = useRef(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [moduleError, setModuleError] = useState('')
  const [projectListError, setProjectListError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(''),3200);return()=>clearTimeout(timer)},[notice])
  const [projectName, setProjectName] = useState('新项目')
  const draftInputs = useRef<PackageInfo[]>([])
  const pendingInputTransfers = useRef(new Set<{ session: number }>())
  const [inputTransfers, setInputTransfers] = useState(0)
  function ensureInputsTransferred(current: Project) {
    if (current.tutorial && [...pendingInputTransfers.current].some(transfer => transfer.session === projectSession.current)) throw new Error('Wait for teaching input transfers to finish before saving')
  }
  async function discardDraftInputs() {
    for (const token of temporaryInteractions.current) void client.cancelInteraction(token).catch(() => {})
    temporaryInteractions.current.clear()
    const inputs = draftInputs.current; draftInputs.current = []
    await Promise.all(inputs.map(input => client.discardDraftInput(input.id).catch(fail)))
  }
  const temporaryInteractions = useRef(new Set<string>())
  const packagesNow = useRef<PackageInfo[]>([])
  const [packages, setPackages] = useState<PackageInfo[]>([])
  packagesNow.current = packages
  const [selectedPackage, setSelectedPackage] = useState('')
  const [viewer, setViewer] = useState('')
  const [adoptionTarget, setAdoptionTarget] = useState('')
  const [adopting, setAdopting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const deletingProject = useRef('')
  const projectBusy = running || (deleting && deletingProject.current === project?.id)
  const locked = projectBusy || (saving && !!project?.tutorial)
  const waitingForTeachingInputs = !!project?.tutorial && inputTransfers > 0
  const [runs, setRuns] = useState<Run[]>([])
  const cancellableRuns = runs.filter(item => item.status === 'running')
  const [connection, setConnection] = useState<Edge>({ source: '', source_port: '', target: '', target_port: '' })
  const fail = (failure: unknown) => { if (liveProject.current) setError(failure instanceof Error ? failure.message : String(failure)) }
  const errorText = (failure: unknown) => failure instanceof Error ? failure.message : String(failure)
  async function refreshProjects() {
    const epoch = ++projectEpoch.current
    const current = () => liveProject.current && epoch === projectEpoch.current
    const read = {}
    projectRead.current = read
    try {
      const nextProjects = await client.projects()
      if (!current()) return
      setSnapshot(previous => current() ? { ...previous, projects: nextProjects } : previous)
      setProjectListError('')
    } catch (failure) { if (current()) setProjectListError(`Project list refresh failed: ${errorText(failure)}`) }
    finally { if (projectRead.current === read) projectRead.current = null }
  }
  function projectChanged() {
    projectEpoch.current += 1
    if (!projectRead.current) return
    // A confirmed write supersedes this read immediately, even if it never settles.
    projectRead.current = null
    if (projectReadQueued.current) return
    projectReadQueued.current = true
    queueMicrotask(() => {
      projectReadQueued.current = false
      if (liveProject.current && !projectRead.current) void refreshProjects()
    })
  }
  function commitProject(saved: Project) {
    if (!liveProject.current) return
    projectChanged()
    setSnapshot(previous => ({ ...previous, projects: previous.projects.some(item => item.id === saved.id) ? previous.projects.map(item => item.id === saved.id ? saved : item) : [...previous.projects, saved] }))
  }
  function removeProject(id: string) {
    if (!liveProject.current) return
    projectChanged()
    setSnapshot(previous => ({ ...previous, projects: previous.projects.filter(item => item.id !== id) }))
  }
  async function refresh() {
    void refreshProjects()
    const request = ++moduleEpoch.current
    const current = () => liveProject.current && request === moduleEpoch.current
    let next: Catalog | undefined
    try {
      next = await client.catalog()
      if (!current()) return
      const nextExtensions = await loadExtensions(next.modules)
      if (!current()) return
      const loaded = next
      setSnapshot(previous => current() ? { ...previous, catalog: loaded, extensions: nextExtensions } : previous)
      setModuleError('')
    } catch (failure) {
      if (!current()) return
      const loaded = next
      setSnapshot(previous => current() ? { ...previous, catalog: loaded ?? previous.catalog, extensions: {} } : previous)
      setModuleError(`Module refresh failed: ${errorText(failure)}`)
    }
  }
  useEffect(() => { refresh().then(() => openTutorial(true)).catch(fail) }, [])
  useEffect(() => {
    liveProject.current = true
    function dispose() {
      if (!liveProject.current) return
      liveProject.current = false; projectSession.current += 1; opening.current += 1; currentProject.current = null
      releaseWorkspaceOperations()
      void discardDraftInputs()
    }
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirtyNow.current || workspaceDirty.current) { event.preventDefault(); event.returnValue = '' } }
    const pageHide = (event: PageTransitionEvent) => { if (!event.persisted) dispose() }
    window.addEventListener('beforeunload', beforeUnload)
    window.addEventListener('pagehide', pageHide)
    return () => { window.removeEventListener('beforeunload', beforeUnload); window.removeEventListener('pagehide', pageHide); dispose() }
  }, [])
  function change(update: (current: Project) => Project) {
    if (!liveProject.current) throw new Error('Project changed; start the operation again')
    if (savingNow.current && currentProject.current?.tutorial) throw new Error('Teaching draft is saving; wait for the user project')
    if (runningNow.current || deletingProject.current === currentProject.current?.id) throw new Error('Project is running or being deleted')
    if (!currentProject.current) throw new Error('Open a project first')
    const previous = currentProject.current
    currentProject.current = update(previous)
    undoStack.current.push(previous); redoStack.current = []
    setProject(currentProject.current); markDirty(true); setNotice('')
  }
  function restoreHistory(redo = false) {
    if (locked || saving || workspace || !currentProject.current) return
    const source = redo ? redoStack.current : undoStack.current
    const target = redo ? undoStack.current : redoStack.current
    const previous = source.pop()
    if (!previous || previous.id !== currentProject.current.id) return
    target.push(currentProject.current); currentProject.current = previous
    let path = scopePathNow.current
    while (path.length && !flowAt(previous.flow, path)) path = path.slice(0, -1)
    if (path.length !== scopePathNow.current.length) {
      scopePathNow.current = path; setScopePath(path)
      setConnection({source:'',source_port:'',target:'',target_port:''})
    }
    setProject(previous); markDirty(true); setNotice(redo ? '已重做' : '已撤销')
  }
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z' || (event.target instanceof HTMLElement && event.target.closest('input,textarea,select,[contenteditable=true]'))) return
      if (workspace) return
      event.preventDefault(); restoreHistory(event.shiftKey)
    }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [locked, saving, workspace])
  function changeFlow(update: (flow: Flow) => Flow, path = scopePathNow.current) {
    change(current => ({...current, flow: replaceFlow(current.flow, path, update)}))
  }
  function changeScope(scope: Scope) {
    if (!activeScope) return
    const id = activeScope.id, parentPath = scopePath.slice(0, -1)
    change(current => {
      let flow = replaceFlow(current.flow, parentPath, body => ({
        ...body,
        nodes: body.nodes.map(node => node.id === id ? {...node, scope, inputs: Object.fromEntries(Object.entries(node.inputs).filter(([port]) => scope.inputs[port]))} : node),
        edges: body.edges.filter(edge => (edge.source !== id || scope.outputs[edge.source_port]) && (edge.target !== id || scope.inputs[edge.target_port])),
      }))
      if (parentPath.length) flow = replaceFlow(flow, parentPath.slice(0, -1), body => ({...body, nodes: body.nodes.map(node => node.id === parentPath.at(-1) && node.scope ? {
        ...node, scope: {...node.scope,
          input_bindings: node.scope.input_bindings.filter(binding => binding.node !== id || scope.inputs[binding.port]),
          output_bindings: node.scope.output_bindings.filter(binding => binding.node !== id || scope.outputs[binding.port]),
        },
      } : node)}))
      return {...current, flow}
    })
  }
  function navigateScope(path: string[]) {
    if (document.activeElement instanceof HTMLElement && canvas.current?.contains(document.activeElement)) document.activeElement.blur()
    const invalid = canvas.current?.querySelector<HTMLTextAreaElement>('textarea:invalid')
    if (invalid) { invalid.reportValidity(); fail(new Error('Enter valid parameter JSON before leaving this subflow')); return }
    if (!currentProject.current || !flowAt(currentProject.current.flow, path)) return
    scopePathNow.current = path; setScopePath(path); setConnection({source:'',source_port:'',target:'',target_port:''})
  }
  async function openTutorial(automatic = false) {
    if (!liveProject.current) return
    const request = opening.current
    const example = await client.tutorial()
    if (!liveProject.current) return
    if (automatic && (request !== opening.current || currentProject.current)) return
    await open(example.id, undefined, automatic)
  }
  async function open(id: string, approvedRevision?: number, preserveError = false) {
    if (!liveProject.current) return
    if (runningNow.current || (dirtyNow.current && draftRevision.current !== approvedRevision && !window.confirm('Discard unsaved changes and open this project?'))) return
    const leavingRevision = draftRevision.current
    const request = ++opening.current
    const [next, files, history] = await Promise.all([client.project(id), client.packages(id), client.runs(id)])
    if (!liveProject.current || request !== opening.current) return
    if (dirtyNow.current && draftRevision.current !== leavingRevision && !window.confirm('Discard unsaved changes and open this project?')) return
    void discardDraftInputs()
    closeWorkspace(); undoStack.current = []; redoStack.current = []
    projectSession.current += 1; setInputTransfers(0); currentProject.current = next; setProject(next); markDirty(false); setNotice('')
    runningNow.current = !!next.running || history.some(run => run.status === 'running'); setRunning(runningNow.current)
    scopePathNow.current = []; setScopePath([]); setConnection({source:'',source_port:'',target:'',target_port:''}); setPackages(files); setRuns(history); setResultRun(''); setResultCall(''); setUseTarget(''); setUsePort(''); setSelectedPackage(''); setViewer(''); setAdoptionTarget(''); if (!preserveError) setError('')
    return true
  }
  async function createProject() {
    if (dirtyNow.current && !window.confirm('Discard unsaved changes and create a project?')) return
    const approvedRevision = draftRevision.current
    const session = projectSession.current, openedAt = opening.current
    setError('')
    const next = await client.createProject(projectName)
    commitProject(next)
    if (session === projectSession.current && openedAt === opening.current) await open(next.id, approvedRevision, true)
  }
  async function save() {
    if (document.activeElement instanceof HTMLElement && canvas.current?.contains(document.activeElement)) document.activeElement.blur()
    const invalid = canvas.current?.querySelector<HTMLTextAreaElement>('textarea:invalid')
    if (invalid) { invalid.reportValidity(); throw new Error('Enter valid parameter JSON before saving') }
    const snapshot = currentProject.current
    if (!snapshot) throw new Error('Open a project first')
    if (savingNow.current) throw new Error('Project save is already in progress')
    ensureInputsTransferred(snapshot)
    const session = projectSession.current
    const revision = draftRevision.current
    savingNow.current = true; setSaving(true); setError('')
    try {
      const saved = snapshot.tutorial ? await client.copy(snapshot, projectName, draftInputs.current.map(input => input.id)) : await client.save(snapshot)
      if (!liveProject.current) return false
      commitProject(saved)
      if (currentProject.current !== snapshot || draftRevision.current !== revision) return false
      if (snapshot.tutorial) {
        projectSession.current += 1; setPackages([]); setRuns([]); setSelectedPackage(''); setViewer('')
        void discardDraftInputs()
      }
      currentProject.current = saved; setProject(saved); markDirty(false); setNotice('Project and layout saved')
      if (snapshot.tutorial) {
        const target = { projectId: saved.id, session: projectSession.current, epoch: runOperationEpoch.current }
        const openedAt = opening.current
        const current = () => liveProject.current && currentProject.current === saved && currentRunOperation(target) && opening.current === openedAt
        void client.packages(saved.id).then(files => { if (current()) setPackages(files) }).catch(failure => {
          if (current()) fail(new Error(`Project saved; package list refresh failed: ${failure instanceof Error ? failure.message : String(failure)}`))
        })
      }
      return true
    } catch (failure) {
      if (session !== projectSession.current) return false
      throw failure
    } finally { savingNow.current = false; setSaving(false) }
  }
  async function copyProject() {
    if (savingNow.current || runningNow.current || !currentProject.current) return
    if (document.activeElement instanceof HTMLElement && canvas.current?.contains(document.activeElement)) document.activeElement.blur()
    const invalid = canvas.current?.querySelector<HTMLTextAreaElement>('textarea:invalid')
    if (invalid) { invalid.reportValidity(); throw new Error('Enter valid parameter JSON before copying') }
    const snapshot = currentProject.current
    ensureInputsTransferred(snapshot)
    const session = projectSession.current
    const revision = draftRevision.current
    savingNow.current = true; setSaving(true); setError('')
    try {
      const copied = await client.copy(snapshot, projectName, snapshot.tutorial ? draftInputs.current.map(input => input.id) : [])
      if (!liveProject.current) return
      commitProject(copied)
      if (session !== projectSession.current || draftRevision.current !== revision) return
      if (await open(copied.id, revision)) setNotice('Project copied with independent inputs and no runs')
    } catch (failure) { if (session === projectSession.current) throw failure }
    finally { savingNow.current = false; setSaving(false) }
  }
  function currentRunOperation(target: { projectId: string; session: number; epoch: number }) {
    return currentProject.current?.id === target.projectId && projectSession.current === target.session && runOperationEpoch.current === target.epoch
  }
  async function run() {
    if (!project) return
    const epoch = ++runOperationEpoch.current
    const session = projectSession.current
    if (dirtyNow.current || currentProject.current?.tutorial) {
      if (!window.confirm('Save changes and run?')) return
      const saved = await save()
      if (!saved && session !== projectSession.current) return
      if (!saved) throw new Error('Project changed while saving; save again before running')
    }
    const runProject = currentProject.current
    if (!runProject || epoch !== runOperationEpoch.current) return
    const target = { projectId: runProject.id, session: projectSession.current, epoch }
    opening.current += 1; submittingRun.current = true
    runningNow.current = true; setRunning(true); setError(''); setNotice('Running on the backend…')
    try {
      const result = await client.run(target.projectId)
      if (!currentRunOperation(target)) return
      if (result.status !== 'running') {
        const files = await client.packages(target.projectId)
        if (!currentRunOperation(target)) return
        setPackages(files)
      }
      setRuns(items => [...items.filter(item => item.id !== result.id), result])
      runningNow.current = result.status === 'running'; setRunning(runningNow.current)
      setNotice(`Run ${result.status}`)
    } catch (failure) {
      // A lost submission response leaves the lock until a current poll confirms state.
      if (currentRunOperation(target)) fail(failure)
    } finally { if (currentRunOperation(target)) submittingRun.current = false }
  }
  async function continueRun(runId: string, nodeId: string) {
    const current = currentProject.current
    if (!current || runningNow.current || savingNow.current || submittingRun.current) return
    const target = { projectId: current.id, session: projectSession.current, epoch: ++runOperationEpoch.current }
    opening.current += 1; submittingRun.current = true
    runningNow.current = true; setRunning(true); setError(''); setNotice('Continuing the original call on the backend…')
    try {
      const result = await client.continueRun(runId, nodeId)
      if (!currentRunOperation(target)) return
      if (result.status !== 'running') {
        const files = await client.packages(target.projectId)
        if (!currentRunOperation(target)) return
        setPackages(files)
      }
      setRuns(items => [...items.filter(item => item.id !== result.id), result])
      runningNow.current = result.status === 'running'; setRunning(runningNow.current)
      setNotice(`Run ${result.status}`)
    } catch (failure) { if (currentRunOperation(target)) fail(failure) }
    finally { if (currentRunOperation(target)) submittingRun.current = false }
  }
  async function cancelRun() {
    const current = currentProject.current
    if (!current || submittingRun.current || !cancellableRuns.length) return
    const target = { projectId: current.id, session: projectSession.current, epoch: ++runOperationEpoch.current }
    submittingRun.current = true; runningNow.current = true; setRunning(true)
    try {
      await Promise.all(cancellableRuns.map(item => client.cancelRun(item.id)))
      if (!currentRunOperation(target)) return
      setNotice('Cancellation requested; waiting for the backend…')
    } catch (failure) { if (currentRunOperation(target)) fail(failure) }
    finally { if (currentRunOperation(target)) submittingRun.current = false }
  }
  useEffect(() => {
    if (!project) return
    const projectId = project.id
    const session = projectSession.current
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      const target = { projectId, session, epoch: runOperationEpoch.current }
      const current = () => !stopped && currentRunOperation(target)
      try {
        if (submittingRun.current) return
        const history = await client.runs(projectId)
        if (!current()) return
        const active = history.some(item => item.status === 'running')
        const wasRunning = runningNow.current
        let files: PackageInfo[] | undefined
        if (active || wasRunning) {
          files = await client.packages(projectId)
          if (!current()) return
        }
        setRuns(history); runningNow.current = active; setRunning(active)
        if (files) {
          setPackages(files)
          if (!active) setNotice(`Run ${history.at(-1)?.status ?? 'finished'}`)
        }
      } catch (failure) { if (current()) fail(failure) }
      finally { if (!stopped) timer = setTimeout(poll, 500) }
    }
    timer = setTimeout(poll, 500)
    return () => { stopped = true; clearTimeout(timer) }
  }, [project?.id, projectSession.current])

  async function deleteProject() {
    const current = currentProject.current
    if (!current || runningNow.current || savingNow.current || deletingProject.current) return
    const message = `Delete project "${current.name}" and its stored packages and runs?${dirty ? ' Unsaved changes will be discarded.' : ''} This cannot be undone.`
    if (!window.confirm(message)) return
    const session = projectSession.current
    deletingProject.current = current.id; setDeleting(true); setError('')
    opening.current += 1
    try {
      await client.deleteProject(current.id)
      removeProject(current.id)
      if (session !== projectSession.current) return
      projectSession.current += 1; currentProject.current = null
      setProject(null); markDirty(false); setPackages([]); setRuns([]); setSelectedPackage(''); setViewer(''); setAdoptionTarget('')
      setConnection({ source: '', source_port: '', target: '', target_port: '' })
      setNotice(`Project "${current.name}" deleted`)
    } catch (failure) { if (session === projectSession.current) fail(failure) }
    finally { deletingProject.current = ''; setDeleting(false) }
  }
  async function adopt() {
    if (!selectedPackage || !adoptionTarget || adopting) return
    const session = projectSession.current
    const targetName = projects.find(item => item.id === adoptionTarget)?.name ?? adoptionTarget
    setAdopting(true); setError('')
    try {
      await client.adopt(adoptionTarget, selectedPackage)
      if (session !== projectSession.current) return
      setNotice(`已采用到 ${targetName}`)
    } catch (failure) { if (session === projectSession.current) fail(failure) }
    finally { setAdopting(false) }
  }
  const host = useMemo<ModuleHost>(() => {
    const origin = projectSession.current
    const path = scopePath
    function activeProject() {
      if (!liveProject.current || origin !== projectSession.current) throw new Error('Project changed; start the operation again')
      if (scopePathNow.current.join('/') !== path.join('/')) throw new Error('Subflow changed; start the operation again')
      if (savingNow.current && currentProject.current?.tutorial) throw new Error('Teaching draft is saving; wait for the user project')
      if (!currentProject.current || runningNow.current || deletingProject.current === currentProject.current.id) throw new Error('Open an idle project first')
      return currentProject.current
    }
    return {
      readOnly: locked || !project,
      async createInput(input) {
        const current = activeProject()
        const transfer = current.tutorial ? { session: origin } : null
        if (transfer) { pendingInputTransfers.current.add(transfer); setInputTransfers(count => count + 1) }
        try {
          const result = await client.createInput(current.id, input)
          if (current.tutorial) {
            try { activeProject() } catch (failure) { await client.discardDraftInput(result.id); throw failure }
            draftInputs.current.push(result)
            markDirty(true)
          }
          activeProject()
          const files = await client.packages(current.id)
          activeProject(); setPackages([...files, ...draftInputs.current]); return result
        } finally {
          if (transfer) {
            pendingInputTransfers.current.delete(transfer)
            if (origin === projectSession.current) setInputTransfers([...pendingInputTransfers.current].filter(item => item.session === origin).length)
          }
        }
      },
      async addNode(node) {
        activeProject()
        const id = crypto.randomUUID(), ownedNode = structuredClone(node)
        changeFlow(flow => ({...flow, nodes:[...flow.nodes,{...ownedNode,id}]}), path); return id
      },
      async connect(edge) {
        const current = activeProject()
        const flow = flowAt(current.flow, path)!
        const source = flow.nodes.find(node => node.id === edge.source)
        const target = flow.nodes.find(node => node.id === edge.target)
        const output = declarationFor(source, catalog)?.outputs[edge.source_port]
        const input = declarationFor(target, catalog)?.inputs[edge.target_port]
        const boundary = path.length ? flowAt(current.flow,path.slice(0,-1))?.nodes.find(node=>node.id===path.at(-1))?.scope : undefined
        if (edge.source === edge.target) throw new Error('Connect different nodes; use explicit subflow feedback for repetition')
        if (flow.edges.some(item => JSON.stringify(item) === JSON.stringify(edge))) throw new Error('This connection already exists')
        if (!output || !input || !input.accepts.includes(output.format)) throw new Error('Port formats do not match; select an explicit conversion node')
        if (input.cardinality === 'one' && output.cardinality === 'many') throw new Error('Cardinality mismatch: a many output requires a many input')
        if (input.cardinality === 'one' && (target?.inputs[edge.target_port]?.length || flow.edges.some(item => item.target === edge.target && item.target_port === edge.target_port) || boundary?.input_bindings.some(item=>item.node===edge.target&&item.port===edge.target_port))) throw new Error('Input accepts only one package')
        changeFlow(flow => ({...flow, edges:[...flow.edges,structuredClone(edge)]}), path)
      },
      async preview(interaction, inputs, parameters, options) {
        // The session survives harmless React renders, but never project changes.
        const current = currentProject.current
        if (!current || !liveProject.current || origin !== projectSession.current) throw new Error('Project changed; start the operation again')
        const { id } = await client.beginInteraction(current.id, interaction, inputs, parameters)
        if (!liveProject.current || origin !== projectSession.current) { await client.cancelInteraction(id); throw new Error('Project changed; start the operation again') }
        if (options?.signal?.aborted) { await client.cancelInteraction(id); throw new Error('Preview cancelled') }
        temporaryInteractions.current.add(id)
        const cancel = () => { temporaryInteractions.current.delete(id); void client.cancelInteraction(id).catch(() => {}) }
        options?.signal?.addEventListener('abort', cancel, {once:true})
        try {
          const result = await client.executeInteraction(id)
          if (options?.signal?.aborted) throw new Error('Preview cancelled')
          if (!liveProject.current || origin !== projectSession.current) throw new Error('Project changed; start the operation again')
          return result
        } catch (failure) {
          temporaryInteractions.current.delete(id); await client.cancelInteraction(id).catch(() => {}); throw failure
        } finally { options?.signal?.removeEventListener('abort', cancel) }
      },
      async cancelPreview(id) { temporaryInteractions.current.delete(id); await client.cancelInteraction(id) },
      readPreviewFile: client.readPreviewFile,
      readFile: client.readFile,
    }
  }, [project, locked, catalog, scopePath])
  function editorContext(node: FlowNode, workspaceSession?: symbol): EditorContext {
    const session = projectSession.current, revision = draftRevision.current, projectId = project!.id
    const path = scopePath
    const declaration = declarationFor(node, catalog)
    function currentTarget() {
      if (workspaceSession && workspaceToken.current !== workspaceSession) throw new Error('Editor workspace closed; reopen it to apply changes')
      const current = currentProject.current
      if (!liveProject.current || session !== projectSession.current || current?.id !== projectId) throw new Error('Project changed; reopen this editor')
      if (revision !== draftRevision.current || scopePathNow.current.join('/') !== path.join('/') || !flowAt(current.flow, path)?.nodes.some(item => item.id === node.id && item.type === node.type)) throw new Error('Editor draft changed; preview the current node again')
      if (runningNow.current || deletingProject.current === projectId || (savingNow.current && current.tutorial)) throw new Error('Project is running, saving or being deleted')
      return current
    }
    const edges = activeFlow!.edges.filter(edge => edge.source === node.id || edge.target === node.id)
    const boundaryBindings = activeScope?.scope?.input_bindings.filter(binding=>binding.node===node.id) ?? []
    let parameters = parameterSnapshots.current.get(node.parameters)
    if (!parameters) {
      parameters = frozenParameterCopy(node.parameters)
      parameterSnapshots.current.set(node.parameters, parameters)
    }
    async function workspaceRequest<T>(operation: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
      if (workspaceToken.current !== workspaceSession) throw new Error('Editor workspace closed')
      const controller = new AbortController()
      workspaceRequests.current.add(controller)
      const abort = () => controller.abort(signal?.reason)
      signal?.addEventListener('abort', abort, {once:true})
      if (signal?.aborted) abort()
      try { return await operation(controller.signal) }
      finally { signal?.removeEventListener('abort', abort); workspaceRequests.current.delete(controller) }
    }
    const editorHost: ModuleHost = workspaceSession ? {...host,
      async preview(interaction, inputs, parameters, options) {
        currentTarget()
        const result=await workspaceRequest(signal=>host.preview(interaction,inputs,parameters,{signal}),options?.signal)
        if(workspaceToken.current!==workspaceSession){await host.cancelPreview(result.id);throw new Error('Editor workspace closed')}
        workspaceInteractions.current.add(result.id);return result
      },
      readPreviewFile(id, output, key, options) {
        return workspaceRequest(signal=>host.readPreviewFile(id,output,key,{signal}),options?.signal)
      },
      async cancelPreview(id) {workspaceInteractions.current.delete(id);await host.cancelPreview(id)},
    } : host
    return {
      projectId, nodeId: node.id, revision, parameters, bindings: structuredClone(node.inputs), edges: structuredClone(edges), host: editorHost,
      document: packagesNow.current.find(item => item.id === node.document),
      inputs: Object.fromEntries(Object.entries(declaration?.inputs ?? {}).map(([port, input]) => {
        const ids = node.inputs[port] ?? []
        const selected = ids.flatMap(id => packagesNow.current.filter(item => item.id === id))
        const missing = ids.filter(id => !selected.some(item => item.id === id))
        const connected = edges.some(edge => edge.target === node.id && edge.target_port === port) || boundaryBindings.some(binding=>binding.port===port)
        const unavailable = missing.length ? `Selected packages are unavailable: ${missing.join(', ')}` : connected ? 'Connected input requires a delivered package selected explicitly; prepare and run the source group first' : !ids.length ? `No delivered package is selected for ${port}${input.required ? ' (required)' : ''}` : undefined
        const available = runs.flatMap((run, runIndex) => Object.entries(run.nodes).flatMap(([callId, result]) => {
          const sourceId = result.location?.node_id ?? callId
          if (result.status !== 'succeeded' || JSON.stringify(callPath(run, callId)) !== JSON.stringify(path)) return []
          return edges.filter(edge => edge.target === node.id && edge.target_port === port && edge.source === sourceId).flatMap(edge =>
            (result.outputs[edge.source_port] ?? []).flatMap(id => {
              const pkg = packagesNow.current.find(item => item.id === id && input.accepts.includes(item.format))
              return pkg ? [{package: structuredClone(pkg), label: `运行 ${runIndex + 1} · ${callLabel(run, callId)} · ${edge.source_port}`}] : []
            }))
        }))
        return [port, {packages: structuredClone(selected), available, ...(unavailable ? {unavailable} : {})}]
      })),
      async update(update: EditorUpdate) {
        const parameters = update.parameters ? structuredClone(update.parameters) : undefined
        currentTarget()
        if ((await client.project(projectId)).running) throw new Error('Project is running; wait before accepting edits')
        currentTarget()
        let inputs = { ...node.inputs, ...update.inputs }
        let document = node.document
        if (update.document && update.delivery) throw new Error('Accept one editor document or input at a time')
        const replace = update.replaceConnections ?? []
        const additions = update.connections ?? []
        const changedPorts = new Set([...Object.keys(update.inputs ?? {}), ...(update.delivery ? [update.delivery.port] : [])])
        if (replace.some(port => !changedPorts.has(port))) throw new Error('Connection replacement requires an explicit input update')
        const current = currentTarget()
        for (const edge of additions) {
          const source = flowAt(current.flow, path)?.nodes.find(item => item.id === edge.source)
          const output = declarationFor(source, catalog)?.outputs[edge.source_port]
          const input = declaration?.inputs[edge.target_port]
          if (edge.target !== node.id || !replace.includes(edge.target_port) || !input || !output || !input.accepts.includes(output.format) || (input.cardinality === 'one' && output.cardinality === 'many')) throw new Error('Replacement connection does not match the current target declaration')
        }
        if (new Set(additions.map(edge => JSON.stringify(edge))).size !== additions.length) throw new Error('Duplicate replacement connection')
        function validateBindings(values: Record<string, string[]>, extra?: PackageInfo) {
          for (const port of changedPorts) {
            const input = declaration?.inputs[port]
            if (!input) throw new Error(`Unknown input port: ${port}`)
            const ids = values[port] ?? []
            const incoming = [...edges.filter(edge => !replace.includes(edge.target_port)), ...additions].filter(edge => edge.target === node.id && edge.target_port === port).length + boundaryBindings.filter(binding=>binding.port===port).length
            if (input.cardinality === 'one' && ids.length + incoming > 1) throw new Error('Input accepts only one package; explicitly replace its connection')
            for (const id of ids) {
              const pkg = extra?.id === id ? extra : packagesNow.current.find(item => item.id === id)
              if (!pkg || pkg.project_id !== projectId || !input.accepts.includes(pkg.format)) throw new Error(`Input package is unavailable or has an unaccepted format: ${port}`)
            }
          }
        }
        if (update.delivery || update.document) {
          const delivery = update.delivery ?? update.document!
          if ('interaction' in delivery && !temporaryInteractions.current.has(delivery.interaction)) throw new Error('Preview has ended; create a new preview')
          if ('port' in delivery) {
            if (!declaration?.inputs[delivery.port]) throw new Error('Unknown delivery input port')
            validateBindings({...inputs, [delivery.port]: []})
          } else if (!declaration?.document_format) throw new Error('This node does not accept editor documents')
          const transfer = project!.tutorial ? {session} : null
          if (transfer) { pendingInputTransfers.current.add(transfer); setInputTransfers(count => count + 1) }
          try {
            const received = 'interaction' in delivery ? await client.acceptInteraction(delivery.interaction, delivery.output) : await client.createInput(projectId, delivery.input)
            try {
              if ((await client.project(projectId)).running) throw new Error('Project is running; wait before accepting edits')
              currentTarget()
            } catch (failure) {
              if (received.project_id === 'tutorial') await client.discardDraftInput(received.id)
              throw failure
            }
            if ('port' in delivery) {
              inputs = {...inputs, [delivery.port]: [received.id]}
              validateBindings(inputs, received)
            } else {
              if (received.project_id !== projectId || received.format !== declaration?.document_format) throw new Error('Editor document format does not match this node')
              document = received.id
              validateBindings(inputs)
            }
            if (project!.tutorial) draftInputs.current.push(received)
            packagesNow.current = [...packagesNow.current, received]; setPackages(packagesNow.current)
          } finally {
            if (transfer) { pendingInputTransfers.current.delete(transfer); if (session === projectSession.current) setInputTransfers([...pendingInputTransfers.current].filter(item => item.session === session).length) }
          }
        } else validateBindings(inputs)
        currentTarget()
        changeFlow(flow => ({...flow,
          nodes: flow.nodes.map(item => item.id === node.id ? {...item, ...(parameters ? {parameters} : {}), inputs, ...(document ? {document} : {})} : item),
          edges: [...flow.edges.filter(edge => !(edge.target === node.id && replace.includes(edge.target_port))), ...additions],
        }), path)
        const accepted = update.document ?? update.delivery
        if (accepted && 'interaction' in accepted) {
          const token = accepted.interaction
          temporaryInteractions.current.delete(token)
          void client.cancelInteraction(token).catch(() => {})
        }
      },
    }
  }
  const selected = packages.find(item => item.id === selectedPackage)
  const viewers = extensions.viewers?.filter(item => item.formats.includes(selected?.format ?? '')) ?? []
  const activeViewer = viewers.find(item => item.id === viewer) ?? viewers.find(item => item.defaultFor?.includes(selected?.format ?? '')) ?? [...viewers].sort((a,b)=>a.id.localeCompare(b.id))[0]
  const Viewer = activeViewer?.component
  function resultName(run: Run, id: string) {
    const result=run.nodes[id], path=callPath(run,id), original=result?.location?.node_id??id
    const flow=run.flow?flowAt(run.flow,path):project?flowAt(project.flow,path):undefined
    const node=flow?.nodes.find(item=>item.id===original)
    const index=flow?.nodes.findIndex(item=>item.id===original)??-1
    return `${index>=0?String(index+1).padStart(2,'0')+' ':''}${declarationFor(node,catalog)?.name??'历史节点'}${result?.location?.round?' · 第 '+result.location.round+' 轮':''}${result?.location?.item?' · 第 '+result.location.item+' 项':''}`
  }
  function packageDescription(pkg: PackageInfo) {
    for (const [index, run] of runs.entries()) for (const [id, result] of Object.entries(run.nodes)) {
      for (const values of Object.values(result.outputs)) if(values.includes(pkg.id))return `第 ${index+1} 次 · ${resultName(run,id)}${values.length>1?' · '+(values.indexOf(pkg.id)+1):''}`
    }
    function inputName(flow: Flow):string|undefined {
      for(const node of flow.nodes){if(node.document===pkg.id||Object.values(node.inputs).some(ids=>ids.includes(pkg.id)))return declarationFor(node,catalog)?.name;if(node.scope){const found=inputName(node.scope.body);if(found)return found}}
    }
    return `${project?inputName(project.flow)??'输入文件':'输入文件'} · ${packages.indexOf(pkg)+1}`
  }
  const viewedRun=runs.find(run=>run.id===resultRun)??(resultRun==='inputs'?undefined:runs.at(-1))
  const viewedCalls=viewedRun?Object.keys(viewedRun.nodes):[]
  const viewedCall=viewedRun?.nodes[resultCall]?resultCall:viewedCalls[0]??''
  const viewedNode=viewedRun?.nodes[viewedCall]
  const resultPackages=viewedRun?Object.entries(viewedNode?.outputs??{}).flatMap(([port,ids])=>ids.flatMap((id,index)=>{const pkg=packages.find(item=>item.id===id);return pkg?[{pkg,port,index}]:[]})):packages.filter(pkg=>!runs.some(run=>Object.values(run.nodes).some(node=>Object.values(node.outputs).some(ids=>ids.includes(pkg.id))))).map((pkg,index)=>({pkg,port:'',index}))
  useEffect(()=>{if(!resultsOpen)return;if(!resultPackages.some(item=>item.pkg.id===selectedPackage)){setSelectedPackage(resultPackages[0]?.pkg.id??'');setViewer('')}},[resultsOpen,viewedRun?.id,viewedCall,packages,selectedPackage])
  function openNodeResults(node: FlowNode) {
    const match=[...runs].reverse().flatMap(run=>Object.entries(run.nodes).filter(([id,result])=>(result.location?.node_id??id)===node.id&&callPath(run,id).join('/')===scopePath.join('/')).map(([id])=>({run,id})))[0]
    setResultRun(match?.run.id??'inputs');setResultCall(match?.id??'');setSelectedPackage(match?Object.values(match.run.nodes[match.id].outputs).flat()[0]??'':node.document??Object.values(node.inputs).flat()[0]??'');setViewer('');setResultsOpen(true)
  }
  async function useResult() {
    const node=activeFlow?.nodes.find(item=>item.id===useTarget)
    if(!node||!selected||!usePort)return
    await editorContext(node).update({inputs:{[usePort]:[selected.id]},replaceConnections:[usePort]})
    setNotice('已用于 '+(declarationFor(node,catalog)?.name??'节点'));setUseTarget('');setUsePort('')
  }
  function updateNode(id: string, update: Partial<FlowNode>) {
    const ownedUpdate = update.parameters ? {...update, parameters: structuredClone(update.parameters)} : update
    changeFlow(flow => ({...flow,nodes:flow.nodes.map(node=>node.id===id?{...node,...ownedUpdate}:node)}))
  }

  async function connectCanvas(edge: Edge, replacingIndex?: number) {
    const flow = activeFlow!
    const problem = connectionProblem(flow, catalog, edge, replacingIndex)
    if (problem) throw new Error(problem)
    const input = declarationFor(flow.nodes.find(node => node.id === edge.target), catalog)?.inputs[edge.target_port]
    if (input?.cardinality === 'one' && activeScope?.scope?.input_bindings.some(binding => binding.node === edge.target && binding.port === edge.target_port)) throw new Error('此输入已有子流程边界连接')
    changeFlow(current => ({...current, edges: [...current.edges.filter((_, index) => index !== replacingIndex), structuredClone(edge)]}))
  }
  function addCanvasNode(type: string, position: {x:number;y:number}) {
    const id = crypto.randomUUID()
    const scope = type==='host.map'||type==='host.repeat'?{inputs:{},outputs:{},body:{nodes:[],edges:[]},input_bindings:[],output_bindings:[],...(type==='host.map'?{item_input:''}:{rounds:2,feedback:{}})}:undefined
    change(current => ({...current, flow: replaceFlow(current.flow, scopePath, flow => ({...flow, nodes: [...flow.nodes, {id,type,parameters:{},inputs:{},...(scope?{scope}:{})}]})), layout: {...current.layout, [id]:position}}))
  }
  function copyCanvasNodes(ids: string[]) {
    const copies = activeFlow!.nodes.filter(node => ids.includes(node.id)).map(node => ({original:node.id, node:{...copyNode(node),id:crypto.randomUUID()}}))
    change(current => ({...current, flow: replaceFlow(current.flow, scopePath, flow => ({...flow, nodes:[...flow.nodes,...copies.map(item=>item.node)]})), layout:{...current.layout,...Object.fromEntries(copies.map(item=>[item.node.id,{x:(current.layout[item.original]?.x??(28+activeFlow!.nodes.findIndex(node=>node.id===item.original)%3*380))+36,y:(current.layout[item.original]?.y??(24+Math.floor(activeFlow!.nodes.findIndex(node=>node.id===item.original)/3)*280))+36}]))}}))
  }
  function removeCanvasNodes(ids: string[]) {
    change(current => {
      let flow = replaceFlow(current.flow, scopePath, body => ({...body,nodes:body.nodes.filter(node=>!ids.includes(node.id)),edges:body.edges.filter(edge=>!ids.includes(edge.source)&&!ids.includes(edge.target))}))
      if (scopePath.length) flow = replaceFlow(flow,scopePath.slice(0,-1),body=>({...body,nodes:body.nodes.map(node=>node.id===scopePath.at(-1)&&node.scope?{...node,scope:{...node.scope,input_bindings:node.scope.input_bindings.filter(binding=>!ids.includes(binding.node)),output_bindings:node.scope.output_bindings.filter(binding=>!ids.includes(binding.node))}}:node)}))
      return {...current,flow,layout:Object.fromEntries(Object.entries(current.layout).filter(([id])=>!ids.includes(id)))}
    })
  }
  function disconnect(index: number) { changeFlow(flow=>({...flow,edges:flow.edges.filter((_,i)=>i!==index)})) }
  function locateCall(run: Run, id: string) {
    const original = run.nodes[id]?.location?.node_id ?? id
    const path = callPath(run,id)
    if (!currentProject.current || !flowAt(currentProject.current.flow,path)?.nodes.some(node=>node.id===original)) { setNotice('当前画布中已删除此节点'); return }
    navigateScope(path)
    setFocusRequest({id:original,token:Date.now()})
  }
  const canvasCatalog={...catalog,nodes:[...catalog.nodes,...(['host.map','host.repeat'].map(id=>({id,name:id==='host.map'?'逐项处理':'循环',module_id:'host',inputs:{},outputs:{},parameters:{}})))]}
  const WorkspaceEditor = workspace?.editor.component
  return <div className="workbench workbench-fullscreen"><div className="workbench-base" inert={!!workspace}>
    <header><div className="project-menu-anchor"><button className="project-trigger" aria-expanded={projectMenu} onClick={()=>setProjectMenu(!projectMenu)}>{project?.name??'项目'} ▾</button>{projectMenu&&<div className="project-menu"><button onClick={()=>{setManagementOpen(true);setProjectMenu(false)}}>新建 / 打开</button><button disabled={!project||locked||saving} onClick={()=>{setProjectMenu(false);void copyProject().catch(fail)}}>复制项目</button><button onClick={()=>{setModulesOpen(true);setProjectMenu(false)}}>模块管理</button><details><summary>更多导入</summary>{extensions.actions?.map(action=><button key={action.id} onClick={()=>{setImportAction(action.id);setProjectMenu(false)}}>{action.name}</button>)}</details><button disabled={!project||project.tutorial||locked||saving} onClick={()=>{setProjectMenu(false);void deleteProject()}}>删除项目</button></div>}</div>
    {dirty&&<span className="unsaved-dot" title="未保存" aria-label="未保存"/>}<div className="header-spacer"/>
    <button aria-label="撤销" title="撤销" disabled={locked||!undoStack.current.length} onClick={()=>restoreHistory()}>↶</button><button aria-label="重做" title="重做" disabled={locked||!redoStack.current.length} onClick={()=>restoreHistory(true)}>↷</button>
    <button aria-expanded={resultsOpen} onClick={()=>setResultsOpen(!resultsOpen)}>结果</button><button disabled={!project||locked||saving||waitingForTeachingInputs} onClick={()=>save().catch(fail)}>{saving?'保存中…':'保存'}</button><button className="primary" disabled={!project||locked||saving||waitingForTeachingInputs} onClick={()=>run().catch(fail)}>▷ 运行</button>{running&&<button disabled={submittingRun.current||!cancellableRuns.length} onClick={()=>void cancelRun()}>停止</button>}</header>
    {([{ message: error, dismiss: setError }, { message: moduleError, dismiss: setModuleError }, { message: projectListError, dismiss: setProjectListError }]).map(({ message, dismiss }, index) => message && <div key={index} role="alert" className="error">{message}<button aria-label="关闭提示" onClick={() => dismiss('')}>×</button></div>)}
    {notice&&<p role="status">{notice}</p>}
    {managementOpen&&<aside className="workbench-management" aria-label="项目"><div className="panel-heading"><h2>项目</h2><button aria-label="关闭项目" onClick={()=>setManagementOpen(false)}>×</button></div><button disabled={projectBusy} onClick={()=>{void openTutorial().then(()=>setManagementOpen(false)).catch(fail)}}>打开示例</button><form onSubmit={e=>{e.preventDefault();void createProject().then(()=>setManagementOpen(false)).catch(fail)}}><label>项目名称<input value={projectName} onChange={e=>setProjectName(e.target.value)}/></label><button disabled={projectBusy}>新建</button></form><ul>{projects.map(item=><li key={item.id}><button disabled={projectBusy} onClick={()=>open(item.id).then(()=>setManagementOpen(false)).catch(fail)}>{item.name}</button></li>)}</ul></aside>}
    {modulesOpen&&<aside className="workbench-management" aria-label="模块管理"><div className="panel-heading"><h2>模块管理</h2><button aria-label="关闭模块管理" onClick={()=>setModulesOpen(false)}>×</button></div><ModuleManagement modules={catalog.modules} disabled={locked} refresh={refresh} invalidateRefresh={invalidateRefresh} fail={fail}/></aside>}
    {importAction&&<aside className="workbench-management"><div className="panel-heading"><h2>{extensions.actions?.find(action=>action.id===importAction)?.name}</h2><button aria-label="关闭导入" onClick={()=>setImportAction('')}>×</button></div>{extensions.actions?.filter(action=>action.id===importAction).map(action=><ExtensionBoundary key={action.id}><action.component host={host}/></ExtensionBoundary>)}</aside>}
    <main>{waitingForTeachingInputs&&<p role="status">正在载入输入文件…</p>}{project&&<>
        <section key={projectSession.current} className="canvas" aria-label="节点画布" ref={canvas}>
          <nav hidden={!scopePath.length} className="scope-navigation" aria-label="Subflow navigation"><button onClick={()=>navigateScope([])} disabled={!scopePath.length}>主画布</button>{scopePath.map((id,index)=><button key={id} disabled={index===scopePath.length-1} onClick={()=>navigateScope(scopePath.slice(0,index+1))}>{index+1}: {declarationFor(flowAt(project.flow,scopePath.slice(0,index))?.nodes.find(node=>node.id===id),catalog)?.name??id}</button>)}</nav>
          {activeScope?.scope && <ScopeEditor key={activeScope.id} node={activeScope} catalog={catalog} disabled={locked} onChange={changeScope} />}
          <WorkflowCanvas key={`canvas:${scopePath.join('/')}`} focusRequest={focusRequest} flow={activeFlow!} catalog={canvasCatalog} layout={project.layout} disabled={locked} selectedSource={connection}
            onSource={(source,source_port)=>setConnection({source,source_port,target:'',target_port:''})}
            onTarget={(target,target_port)=>{const edge={...connection,target,target_port};setConnection(edge);if(edge.source&&edge.source_port)void host.connect(edge).then(()=>setConnection({source:'',source_port:'',target:'',target_port:''})).catch(fail)}}
            onMove={(id,position)=>change(current=>({...current,layout:{...current.layout,[id]:{...current.layout[id],...position}}}))} onDisconnect={disconnect}
            onConnect={connectCanvas} onAdd={addCanvasNode} onCopy={copyCanvasNodes} onDelete={removeCanvasNodes}
            onMoveMany={positions=>change(current=>({...current,layout:{...current.layout,...positions}}))}
            renderNodeResult={node=>{const record=[...runs].reverse().find(run=>Object.entries(run.nodes).some(([id,r])=>(r.location?.node_id??id)===node.id&&callPath(run,id).join('/')===scopePath.join('/')));const calls=record?Object.entries(record.nodes).filter(([id,r])=>(r.location?.node_id??id)===node.id&&callPath(record,id).join('/')===scopePath.join('/')):[];return calls.length||node.document||Object.values(node.inputs).some(ids=>ids.length)?<button onClick={()=>openNodeResults(node)}>{calls.some(([,r])=>r.status==='failed')?'失败 · 查看':calls.some(([,r])=>r.status==='running')?'运行中':'结果 ↗'}</button>:null}}
            renderNodeSummary={node=> {
              const editor = extensions.editors?.find(item=>item.node===node.type)
              const declaration = declarationFor(node,catalog)
              const InlineEditor=editor?.inline?editor.component:null
              return <>
                {InlineEditor&&<ExtensionBoundary key={node.id+editor?.installation_id}><InlineEditor context={editorContext(node)} parameters={node.parameters} readOnly={locked} onChange={(parameters: Record<string,unknown>)=>updateNode(node.id,{parameters})}/></ExtensionBoundary>}
                {editor?.workspace && <button disabled={locked} onClick={()=>openWorkspace(node,editor)}>{editor.workspace.openLabel ?? `打开 ${editor.workspace.title}`}</button>}
                {Object.entries(declaration?.tools??{}).map(([slot,contract])=><label key={slot}>工具<CanvasToolPicker label={`${declaration?.name} 工具`} disabled={locked} value={node.tools?.[slot]??''} options={[{id:'',name:'选择工具'},...(catalog.tools??[]).filter(tool=>tool.slot===contract.id)]} onChange={value=>updateNode(node.id,{tools:{...node.tools,[slot]:value},tool_parameters:{...node.tool_parameters,[slot]:{}}})} /></label>)}
              </>
            }}
            renderNode={(node) => {
            const declaration = declarationFor(node, catalog)
            const editor = extensions.editors?.find(item => item.node === node.type)
            const Editor = editor?.component
            const context = editorContext(node)
            const editorSession = projectSession.current
            function currentEditorTarget() {
              if (!liveProject.current || editorSession !== projectSession.current || context.projectId !== currentProject.current?.id || context.revision !== draftRevision.current || scopePathNow.current.join('/')!==scopePath.join('/') || !flowAt(currentProject.current.flow, scopePath)?.nodes.some(item => item.id === node.id && item.type === node.type)) throw new Error('Editor draft changed; reopen the current node')
              if (runningNow.current || deletingProject.current === context.projectId || (savingNow.current && currentProject.current.tutorial)) throw new Error('Project is running, saving or being deleted')
            }
            return <article className="node" key={node.id}>
              {!declaration&&<p role="alert">此节点所需模块未安装。</p>}
              {node.scope ? <button onClick={()=>navigateScope([...scopePath,node.id])}>打开子流程</button> : editor?.workspace || editor?.inline ? null : Editor ? <ExtensionBoundary key={node.id + editor?.installation_id}><Editor context={context} parameters={context.parameters} readOnly={locked} onChange={(parameters: Record<string, unknown>) => {
                try {
                  currentEditorTarget()
                  updateNode(node.id, {parameters})
                } catch (failure) { fail(failure) }
              }} onDraftChange={() => {
                try { currentEditorTarget(); markDirty(true); setNotice('') }
                catch (failure) { fail(failure) }
              }} /></ExtensionBoundary> : <ParameterFields schema={declaration?.parameters??{}} value={node.parameters} disabled={locked} onChange={(parameters: Record<string,unknown>)=>updateNode(node.id,{parameters})}/> }
              {Object.entries(declaration?.tools ?? {}).map(([slot, contract]) => {
                const tool=catalog.tools?.find(item=>item.id===node.tools?.[slot]&&item.slot===contract.id)
                return tool&&<fieldset key={slot} disabled={locked}><legend>计算参数</legend><ParameterFields schema={tool.parameters} value={node.tool_parameters?.[slot]??{}} disabled={locked} onChange={parameters=>updateNode(node.id,{tool_parameters:{...node.tool_parameters,[slot]:parameters}})}/></fieldset>
              })}
              {!!Object.keys(declaration?.inputs??{}).length&&<details className="node-inputs"><summary>输入来源</summary>{Object.entries(declaration?.inputs??{}).map(([port,input])=>{const connected=activeFlow!.edges.find(edge=>edge.target===node.id&&edge.target_port===port);return <label key={port}>{input.name??port}{connected&&<small>已连接：{declarationFor(activeFlow!.nodes.find(item=>item.id===connected.source),catalog)?.name??'上游节点'}</small>}<select disabled={locked} multiple={input.cardinality==='many'} value={input.cardinality==='many'?node.inputs[port]??[]:node.inputs[port]?.[0]??''} onChange={e=>{const ids=Array.from(e.target.selectedOptions).map(option=>option.value).filter(Boolean);void editorContext(node).update({inputs:{[port]:ids},...(ids.length?{replaceConnections:[port]}:{})}).catch(fail)}}><option value="">{connected?'使用连线':'未选择'}</option>{packages.filter(pkg=>input.accepts.includes(pkg.format)).map(pkg=><option key={pkg.id} value={pkg.id}>{packageDescription(pkg)}</option>)}</select></label>})}</details>}

            </article>
          }} />
        </section>
        {resultsOpen&&<aside className="workbench-results" aria-label="结果"><div className="panel-heading"><h2>结果</h2><button aria-label="关闭结果" onClick={()=>setResultsOpen(false)}>×</button></div>
          <div className="result-selectors"><select aria-label="选择运行" value={viewedRun?.id??'inputs'} onChange={e=>{setResultRun(e.target.value);setResultCall('');setSelectedPackage('');setViewer('')}}><option value="inputs">输入文件</option>{runs.map((run,index)=><option key={run.id} value={run.id}>第 {index+1} 次运行 · {statusLabel(run.status)}</option>)}</select>{viewedRun&&<select aria-label="选择结果节点" value={viewedCall} onChange={e=>{setResultCall(e.target.value);setSelectedPackage('');setViewer('')}}>{viewedCalls.map(id=><option key={id} value={id}>{resultName(viewedRun,id)} · {statusLabel(viewedRun.nodes[id].status)}</option>)}</select>}</div>
          {viewedRun?.diagnostics.map((message,i)=><p role="status" key={i}>{message}</p>)}
          {viewedNode&&<div className="result-status"><button onClick={()=>locateCall(viewedRun!,viewedCall)}>定位节点</button>{['failed','cancelled'].includes(viewedNode.status)&&(viewedRun?.calls?.[viewedCall]!==undefined||viewedRun?.scopes?.[viewedCall]!==undefined)&&<button disabled={locked||saving} onClick={()=>void continueRun(viewedRun!.id,viewedCall)}>继续运行</button>}{viewedNode.diagnostics?.map((message,i)=><p role="alert" key={i}>{message}</p>)}</div>}
          {resultPackages.length>1&&<select aria-label="选择输出" value={selectedPackage} onChange={e=>{setSelectedPackage(e.target.value);setViewer('')}}>{resultPackages.map(({pkg,index,port})=><option key={pkg.id} value={pkg.id}>{viewedRun?`${declarationFor(viewedRun.flow&&flowAt(viewedRun.flow,callPath(viewedRun,viewedCall))?.nodes.find(node=>node.id===(viewedNode?.location?.node_id??viewedCall)),catalog)?.outputs[port]?.name??'输出'} ${index+1}`:packageDescription(pkg)}</option>)}</select>}
          {!resultPackages.length&&<p className="empty-result">暂无结果</p>}
          {selected&&resultPackages.some(item=>item.pkg.id===selected.id)&&<section className="package">

            {Viewer&&<ExtensionBoundary key={selected.id+activeViewer?.id+activeViewer?.installation_id}><Viewer package={selected} host={host}/></ExtensionBoundary>}
            {viewers.length>1&&<details><summary>查看方式</summary><select aria-label="查看方式" value={activeViewer?.id??''} onChange={e=>setViewer(e.target.value)}>{viewers.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></details>}
            <div className="result-actions"><a href={client.exportUrl(selected.id)} download>下载 ZIP</a><details><summary>用于后续节点</summary><select aria-label="接收节点" value={useTarget} onChange={e=>{setUseTarget(e.target.value);setUsePort('')}}><option value="">选择节点</option>{activeFlow!.nodes.filter(node=>Object.values(declarationFor(node,catalog)?.inputs??{}).some(input=>input.accepts.includes(selected.format))).map(node=><option key={node.id} value={node.id}>{String(activeFlow!.nodes.indexOf(node)+1).padStart(2,'0')} {declarationFor(node,catalog)?.name}</option>)}</select><select aria-label="接收端口" value={usePort} onChange={e=>setUsePort(e.target.value)}><option value="">选择输入</option>{Object.entries(declarationFor(activeFlow?.nodes.find(node=>node.id===useTarget),catalog)?.inputs??{}).filter(([,input])=>input.accepts.includes(selected.format)).map(([port,input])=><option key={port} value={port}>{input.name??port}</option>)}</select>{useTarget&&usePort&&<small>采用后替换此输入的现有来源。</small>}<button disabled={locked||!useTarget||!usePort} onClick={()=>void useResult().catch(fail)}>采用</button></details></div>
            {extensions.resultActions?.map(action=><details key={action.id}><summary>{action.name}</summary><ExtensionBoundary><action.component host={host} packages={[selected]}/></ExtensionBoundary></details>)}
            <details><summary>采用到其他项目</summary><select aria-label="目标项目" value={adoptionTarget} disabled={adopting} onChange={e=>setAdoptionTarget(e.target.value)}><option value="">选择项目</option>{projects.filter(item=>item.id!==project.id).map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select><button disabled={!adoptionTarget||adopting} onClick={()=>void adopt()}>{adopting?'采用中…':'采用'}</button></details>
            <details><summary>文件</summary><ul>{selected.files.map(key=><li key={key}><a href={client.fileUrl(selected.id,key)} download>{key}</a></li>)}</ul></details>
          </section>}
        </aside>}

      </>}
    </main></div>
    {workspace && WorkspaceEditor && <section className="editor-workspace-overlay" role="dialog" aria-modal="true" aria-label={workspace.editor.workspace?.title}><ExtensionBoundary onReturn={closeWorkspace} key={workspace.context.projectId+workspace.context.nodeId+workspace.editor.installation_id}><WorkspaceEditor context={workspace.context} parameters={workspace.context.parameters} readOnly={locked} onClose={closeWorkspace} onDraftChange={()=>{workspaceDirty.current=true}} onChange={(parameters: Record<string, unknown>)=>{void workspace.context.update({parameters}).catch(fail)}} /></ExtensionBoundary></section>}
    </div>
}
