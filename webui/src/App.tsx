import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Edge, Flow, FlowNode, Scope, ModuleHost, PackageInfo, EditorContext, EditorUpdate } from '@protein-workbench/module-ui'
import { client, type Catalog, type Project, type Run } from './host-client'
import { loadExtensions, type LoadedExtensions } from './host-ui'
import { ModuleManagement } from './ModuleManagement'
import { WorkflowCanvas } from './WorkflowCanvas'
import { ScopeEditor } from './ScopeEditor'
import { callLabel, callPath, copyNode, declarationFor, flowAt, replaceFlow } from './flow-model'

class ExtensionBoundary extends Component<{ children: ReactNode }, { error: string }> {
  state = { error: '' }
  static getDerivedStateFromError(error: Error) { return { error: error.message } }
  render() { return this.state.error ? <p role="alert">Module interface failed: {this.state.error}</p> : this.props.children }
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

function JsonEditor({ value, disabled, onChange, onDraftChange }: { value: Record<string, unknown>; disabled: boolean; onChange(value: Record<string, unknown>): void; onDraftChange?(): void }) {
  return <textarea key={JSON.stringify(value)} defaultValue={JSON.stringify(value, null, 2)} disabled={disabled} onInput={onDraftChange} onBlur={event => {
    try {
      const parsed = JSON.parse(event.target.value)
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('Enter a JSON object')
      event.target.setCustomValidity(''); onChange(parsed)
    } catch { event.target.setCustomValidity('Enter a valid JSON object'); event.target.reportValidity() }
  }} />
}

export default function App() {
  const [{ catalog, extensions, projects }, setSnapshot] = useState<{ catalog: Catalog; extensions: LoadedExtensions; projects: Project[] }>({ catalog: { nodes: [], modules: [] }, extensions: {}, projects: [] })
  const moduleEpoch = useRef(0)
  const projectEpoch = useRef(0)
  const projectRead = useRef<object | null>(null)
  const projectReadQueued = useRef(false)
  const invalidateRefresh = () => { moduleEpoch.current += 1 }
  const [project, setProject] = useState<Project | null>(null)
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
  const [projectName, setProjectName] = useState('Research project')
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
  const [locatedCall, setLocatedCall] = useState<{run:string;call:string}|null>(null)
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
      void discardDraftInputs()
    }
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirtyNow.current) { event.preventDefault(); event.returnValue = '' } }
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
    currentProject.current = update(currentProject.current)
    setProject(currentProject.current); markDirty(true); setNotice('')
  }
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
    projectSession.current += 1; setInputTransfers(0); currentProject.current = next; setProject(next); markDirty(false); setNotice('')
    runningNow.current = !!next.running || history.some(run => run.status === 'running'); setRunning(runningNow.current)
    scopePathNow.current = []; setScopePath([]); setConnection({source:'',source_port:'',target:'',target_port:''}); setPackages(files); setRuns(history); setSelectedPackage(''); setViewer(''); setAdoptionTarget(''); if (!preserveError) setError('')
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
      const result = await client.adopt(adoptionTarget, selectedPackage)
      if (session !== projectSession.current) return
      setNotice(`Package ${result.id} adopted into ${targetName}`)
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
  function editorContext(node: FlowNode): EditorContext {
    const session = projectSession.current, revision = draftRevision.current, projectId = project!.id
    const path = scopePath
    const declaration = declarationFor(node, catalog)
    function currentTarget() {
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
    return {
      projectId, nodeId: node.id, revision, parameters, bindings: structuredClone(node.inputs), edges: structuredClone(edges), host,
      inputs: Object.fromEntries(Object.entries(declaration?.inputs ?? {}).map(([port, input]) => {
        const ids = node.inputs[port] ?? []
        const selected = ids.flatMap(id => packagesNow.current.filter(item => item.id === id))
        const missing = ids.filter(id => !selected.some(item => item.id === id))
        const connected = edges.some(edge => edge.target === node.id && edge.target_port === port) || boundaryBindings.some(binding=>binding.port===port)
        const unavailable = missing.length ? `Selected packages are unavailable: ${missing.join(', ')}` : connected ? 'Connected input requires a delivered package selected explicitly; prepare and run the source group first' : !ids.length ? `No delivered package is selected for ${port}${input.required ? ' (required)' : ''}` : undefined
        return [port, {packages: structuredClone(selected), ...(unavailable ? {unavailable} : {})}]
      })),
      async update(update: EditorUpdate) {
        const parameters = update.parameters ? structuredClone(update.parameters) : undefined
        currentTarget()
        if ((await client.project(projectId)).running) throw new Error('Project is running; wait before accepting edits')
        currentTarget()
        let inputs = { ...node.inputs, ...update.inputs }
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
        if (update.delivery) {
          const delivery = update.delivery
          if ('interaction' in delivery && !temporaryInteractions.current.has(delivery.interaction)) throw new Error('Preview has ended; create a new preview')
          if (!declaration?.inputs[delivery.port]) throw new Error('Unknown delivery input port')
          // Validate connection replacement before committing any files.
          validateBindings({...inputs, [delivery.port]: []})
          const transfer = project!.tutorial ? {session} : null
          if (transfer) { pendingInputTransfers.current.add(transfer); setInputTransfers(count => count + 1) }
          try {
            const received = 'interaction' in delivery ? await client.acceptInteraction(delivery.interaction, delivery.output) : await client.createInput(projectId, delivery.input)
            if ('interaction' in delivery) temporaryInteractions.current.delete(delivery.interaction)
            try {
              if ((await client.project(projectId)).running) throw new Error('Project is running; wait before accepting edits')
              currentTarget()
            } catch (failure) {
              if (received.project_id === 'tutorial') await client.discardDraftInput(received.id)
              throw failure
            }
            inputs = {...inputs, [delivery.port]: [received.id]}
            validateBindings(inputs, received)
            if (project!.tutorial) draftInputs.current.push(received)
            packagesNow.current = [...packagesNow.current, received]; setPackages(packagesNow.current)
          } finally {
            if (transfer) { pendingInputTransfers.current.delete(transfer); if (session === projectSession.current) setInputTransfers([...pendingInputTransfers.current].filter(item => item.session === session).length) }
          }
        } else validateBindings(inputs)
        currentTarget()
        changeFlow(flow => ({...flow,
          nodes: flow.nodes.map(item => item.id === node.id ? {...item, ...(parameters ? {parameters} : {}), inputs} : item),
          edges: [...flow.edges.filter(edge => !(edge.target === node.id && replace.includes(edge.target_port))), ...additions],
        }), path)
      },
    }
  }
  const selected = packages.find(item => item.id === selectedPackage)
  const viewers = extensions.viewers?.filter(item => item.formats.includes(selected?.format ?? '')) ?? []
  const activeViewer = viewers.find(item => item.id === viewer) ?? viewers[0]
  const Viewer = activeViewer?.component
  function packageDescription(pkg: PackageInfo) {
    for (const [index, run] of runs.entries()) {
      for (const [node, result] of Object.entries(run.nodes)) {
        for (const [port, values] of Object.entries(result.outputs)) {
          if (values.includes(pkg.id)) return `Run ${index + 1} · ${callLabel(run,node)}.${port} · ${pkg.format} · ${pkg.id}`
        }
      }
    }
    return `${pkg.format} · ${pkg.id}`
  }
  const source = activeFlow?.nodes.find(node => node.id === connection.source)
  const target = activeFlow?.nodes.find(node => node.id === connection.target)
  const sourcePorts = declarationFor(source, catalog)?.outputs ?? {}
  const targetPorts = declarationFor(target, catalog)?.inputs ?? {}
  function updateNode(id: string, update: Partial<FlowNode>) {
    const ownedUpdate = update.parameters ? {...update, parameters: structuredClone(update.parameters)} : update
    changeFlow(flow => ({...flow,nodes:flow.nodes.map(node=>node.id===id?{...node,...ownedUpdate}:node)}))
  }

  function removeNode(id: string) {
    change(current => {
      let flow = replaceFlow(current.flow, scopePath, body => ({...body, nodes:body.nodes.filter(node=>node.id!==id), edges:body.edges.filter(edge=>edge.source!==id&&edge.target!==id)}))
      if (scopePath.length) flow=replaceFlow(flow,scopePath.slice(0,-1),body=>({...body,nodes:body.nodes.map(node=>node.id===scopePath.at(-1)&&node.scope?{...node,scope:{...node.scope,input_bindings:node.scope.input_bindings.filter(binding=>binding.node!==id),output_bindings:node.scope.output_bindings.filter(binding=>binding.node!==id)}}:node)}))
      return {...current,flow}
    })
  }
  function disconnect(index: number) { changeFlow(flow=>({...flow,edges:flow.edges.filter((_,i)=>i!==index)})) }
  function locateCall(run: Run, id: string) {
    const original = run.nodes[id]?.location?.node_id ?? id
    const path = callPath(run,id)
    if (!currentProject.current || !flowAt(currentProject.current.flow,path)?.nodes.some(node=>node.id===original)) { setNotice('This historical node is absent from the current draft. Its recorded results remain available here.'); return }
    setLocatedCall({run:run.id,call:id})
    navigateScope(path)
    window.requestAnimationFrame?.(()=>[...document.querySelectorAll<HTMLElement>('[data-canvas-node]')].find(element=>element.dataset.canvasNode===original)?.scrollIntoView?.({block:'center',inline:'center',behavior:'smooth'}))
  }
  function renderRunNode(run: Run, runIndex: number, id: string): ReactNode {
    const result=run.nodes[id]
    if(!result)return null
    const scope=run.scopes?.[id]
    return <section className="run-node" key={id} aria-label={`Run ${runIndex + 1} node ${id}`}>
      <p><strong>{callLabel(run,id)}</strong>: {result.status === 'configuration_blocked' ? 'Configuration prevents group startup' : result.status === 'blocked' ? 'Not executed' : result.status} {result.diagnostics?.join('; ')}</p>
      <button onClick={()=>locateCall(run,id)}>Locate node {result.location?.node_id??id}</button>
      {result.status !== 'succeeded' && Object.values(result.outputs).some(values => values.length) && <p>Partial results · batch incomplete</p>}
      {Object.entries(result.outputs).flatMap(([port, values]) => values.map((packageId, index) => <button key={`${port}-${index}`} onClick={() => { setSelectedPackage(packageId); setViewer('') }}>View {port} result {index + 1}</button>))}
      {result.kind!=='scope' && (result.status === 'failed' || result.status === 'cancelled') && run.calls?.[id] !== undefined && <button disabled={locked || saving} onClick={() => void continueRun(run.id, id)}>Continue {id} with original inputs and parameters</button>}
      {result.kind==='scope' && result.status==='cancelled' && scope && <button disabled={locked || saving} onClick={()=>void continueRun(run.id,id)}>Continue scheduling {id}</button>}
      {scope?.iterations.map(iteration=><details key={iteration.index} open={Object.values(iteration.nodes).some(child=>['failed','cancelled','blocked'].includes(run.nodes[child]?.status))}><summary>Iteration {iteration.index}</summary>{Object.values(iteration.nodes).map(child=>renderRunNode(run,runIndex,child))}</details>)}
    </section>
  }

  return <div className="workbench"><header><h1>Protein Workbench</h1><span>Public module host</span></header>
    {([{ message: error, dismiss: setError }, { message: moduleError, dismiss: setModuleError }, { message: projectListError, dismiss: setProjectListError }]).map(({ message, dismiss }, index) => message && <div key={index} role="alert" className="error">{message}<button onClick={() => dismiss('')}>Dismiss</button></div>)}
    {notice && <p role="status">{notice}</p>}
    <aside><h2>Projects</h2><button disabled={projectBusy} onClick={() => openTutorial().catch(fail)}>Teaching example</button><label>Project name<input value={projectName} onChange={event => setProjectName(event.target.value)} /></label><button disabled={projectBusy} onClick={() => createProject().catch(fail)}>Create project</button>
      <ul>{projects.map(item => <li key={item.id}><button disabled={running || (deleting && deletingProject.current === item.id)} onClick={() => open(item.id).catch(fail)}>{item.name}</button></li>)}</ul>
      <ModuleManagement modules={catalog.modules} disabled={locked} refresh={refresh} invalidateRefresh={invalidateRefresh} fail={fail} />
    </aside>
    <main>{waitingForTeachingInputs && <p role="status">Receiving teaching input files; wait before saving.</p>}<div className="toolbar"><h2>{project?.name ?? 'Open or create a project'}{dirty ? ' · unsaved' : ''}</h2><button disabled={!project || locked || saving || waitingForTeachingInputs} onClick={() => save().catch(fail)}>Save project</button><button disabled={!project || locked || saving || waitingForTeachingInputs} onClick={() => copyProject().catch(fail)}>Copy project</button><button disabled={!project || locked || saving || waitingForTeachingInputs} onClick={() => run().catch(fail)}>{dirty || project?.tutorial ? 'Save and run' : 'Run'}</button>{running && <button disabled={submittingRun.current || !cancellableRuns.length} onClick={() => void cancelRun()}>Cancel run</button>}<button disabled={!project || project.tutorial || running || saving || deleting} onClick={() => void deleteProject()}>Delete project</button></div>
      {project && <><section className="module-actions">{extensions.actions?.map(action => <div key={action.id + action.installation_id}><ExtensionBoundary><action.component host={host} /></ExtensionBoundary></div>)}</section>
        <label>Add node<select disabled={locked} value="" onChange={event => { if(event.target.value) void host.addNode({ type: event.target.value, parameters: {}, inputs: {} }).catch(fail) }}><option value="">Choose operation</option>{catalog.nodes.map(node => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label>
        <div className="scope-add"><button disabled={locked} onClick={()=>void host.addNode({type:'host.map',parameters:{},inputs:{},scope:{inputs:{},outputs:{},body:{nodes:[],edges:[]},input_bindings:[],output_bindings:[],item_input:''}}).catch(fail)}>Add Map subflow</button><button disabled={locked} onClick={()=>void host.addNode({type:'host.repeat',parameters:{},inputs:{},scope:{inputs:{},outputs:{},body:{nodes:[],edges:[]},input_bindings:[],output_bindings:[],rounds:2,feedback:{}}}).catch(fail)}>Add Repeat subflow</button></div>
        <section key={projectSession.current} className="canvas" aria-label="Workflow canvas" ref={canvas}>
          <nav className="scope-navigation" aria-label="Subflow navigation"><button onClick={()=>navigateScope([])} disabled={!scopePath.length}>Root canvas</button>{scopePath.map((id,index)=><button key={id} disabled={index===scopePath.length-1} onClick={()=>navigateScope(scopePath.slice(0,index+1))}>{index+1}: {declarationFor(flowAt(project.flow,scopePath.slice(0,index))?.nodes.find(node=>node.id===id),catalog)?.name??id}</button>)}</nav>
          {activeScope?.scope && <ScopeEditor key={activeScope.id} node={activeScope} catalog={catalog} disabled={locked} onChange={changeScope} />}
          <WorkflowCanvas key={`canvas:${scopePath.join('/')}`} flow={activeFlow!} catalog={catalog} layout={project.layout} disabled={locked} selectedSource={connection}
            onSource={(source,source_port)=>setConnection({source,source_port,target:'',target_port:''})}
            onTarget={(target,target_port)=>{const edge={...connection,target,target_port};setConnection(edge);if(edge.source&&edge.source_port)void host.connect(edge).then(()=>setConnection({source:'',source_port:'',target:'',target_port:''})).catch(fail)}}
            onMove={(id,position)=>change(current=>({...current,layout:{...current.layout,[id]:{...current.layout[id],...position}}}))} onDisconnect={disconnect}
            renderNode={(node, index) => {
            const declaration = declarationFor(node, catalog)
            const editor = extensions.editors?.find(item => item.node === node.type)
            const Editor = editor?.component
            const context = editorContext(node)
            const editorSession = projectSession.current
            const latestRun=runs.at(-1)
            const recorded=latestRun ? Object.entries(latestRun.nodes).filter(([id,result])=>(result.location?.node_id??id)===node.id&&callPath(latestRun,id).join('/')===scopePath.join('/')) : []
            const focusedRun=runs.find(run=>run.id===locatedCall?.run), focused=locatedCall&&focusedRun?.nodes[locatedCall.call]
            const isFocused=!!focused && (focused.location?.node_id??locatedCall?.call)===node.id && callPath(focusedRun!,locatedCall!.call).join('/')===scopePath.join('/')
            function currentEditorTarget() {
              if (!liveProject.current || editorSession !== projectSession.current || context.projectId !== currentProject.current?.id || context.revision !== draftRevision.current || scopePathNow.current.join('/')!==scopePath.join('/') || !flowAt(currentProject.current.flow, scopePath)?.nodes.some(item => item.id === node.id && item.type === node.type)) throw new Error('Editor draft changed; reopen the current node')
              if (runningNow.current || deletingProject.current === context.projectId || (savingNow.current && currentProject.current.tutorial)) throw new Error('Project is running, saving or being deleted')
            }
            return <article className={isFocused?'node located':'node'} key={node.id}><h4>{declaration?.name ?? `Missing module: ${node.type}`}</h4><small>Node {index + 1} · {node.id}</small>{!declaration && <p role="status">Cannot run: install and enable the module that provides {node.type}.</p>}
              {!!recorded.length && <details className="node-results"><summary>Latest run: {recorded.length} call{recorded.length===1?'':'s'} · {[...new Set(recorded.map(([,result])=>result.status))].join(', ')}</summary>{recorded.map(([id,result])=><p key={id}>{callLabel(latestRun!,id)} · {result.status}{result.diagnostics?.length?` · ${result.diagnostics.join('; ')}`:''}</p>)}</details>}
              {isFocused&&<p className="located-call">Located call: {callLabel(focusedRun!,locatedCall!.call)} · {focused.status}</p>}
              {node.scope ? <><p>{node.scope.body.nodes.length} child nodes · {node.type==='host.map' ? `each package on ${node.scope.item_input||'an unselected input'}` : `${node.scope.rounds??1} rounds`}</p><button onClick={()=>navigateScope([...scopePath,node.id])}>Open subflow</button></> : Editor ? <ExtensionBoundary key={node.id + editor?.installation_id}><Editor context={context} parameters={context.parameters} readOnly={locked} onChange={(parameters: Record<string, unknown>) => {
                try {
                  currentEditorTarget()
                  updateNode(node.id, {parameters})
                } catch (failure) { fail(failure) }
              }} onDraftChange={() => {
                try { currentEditorTarget(); markDirty(true); setNotice('') }
                catch (failure) { fail(failure) }
              }} /></ExtensionBoundary> : <label>Parameters<JsonEditor value={node.parameters} disabled={locked} onDraftChange={() => { markDirty(true); setNotice('') }} onChange={parameters => updateNode(node.id, { parameters })} /></label>}
              {Object.entries(declaration?.tools ?? {}).map(([slot, contract]) => {
                const available = (catalog.tools ?? []).filter(tool => tool.slot === contract.id)
                const selectedId = node.tools?.[slot] ?? ''
                const tool = available.find(item => item.id === selectedId)
                return <fieldset key={slot} disabled={locked}><legend>{contract.name}</legend>
                  <label>Tool<select value={selectedId} onChange={event => updateNode(node.id, {
                    tools: { ...node.tools, [slot]: event.target.value },
                    tool_parameters: { ...node.tool_parameters, [slot]: {} },
                  })}><option value="">Choose tool</option>{selectedId && !tool && <option value={selectedId}>Missing tool: {selectedId}</option>}{available.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                  {tool && <><p>Capabilities</p><pre>{JSON.stringify(tool.capabilities, null, 2)}</pre>
                    <details><summary>Tool parameter schema and defaults</summary><pre>{JSON.stringify(tool.parameters, null, 2)}</pre></details>
                    <label>Tool parameters (JSON)<JsonEditor value={node.tool_parameters?.[slot] ?? {}} disabled={locked} onDraftChange={() => { markDirty(true); setNotice('') }} onChange={parameters => updateNode(node.id, { tool_parameters: { ...node.tool_parameters, [slot]: parameters } })} /></label></>}
                </fieldset>
              })}
              {Object.entries(declaration?.inputs ?? {}).map(([port, input]) => <label key={port}>{port} · {input.accepts.join(', ')}{input.required ? ' · required' : ''}<select disabled={locked} multiple={input.cardinality === 'many'} value={input.cardinality === 'many' ? node.inputs[port] ?? [] : node.inputs[port]?.[0] ?? ''} onChange={event => updateNode(node.id, { inputs: { ...node.inputs, [port]: Array.from(event.target.selectedOptions).map(option => option.value).filter(Boolean) } })}><option value="">Use connection / no input</option>{packages.filter(pkg => input.accepts.includes(pkg.format)).map(pkg => <option key={pkg.id} value={pkg.id}>{packageDescription(pkg)}</option>)}</select></label>)}
              {Object.entries(declaration?.outputs ?? {}).map(([port, output]) => <p key={port}>Output {port} → {output.format}</p>)}
              <button disabled={locked} onClick={() => { void host.addNode(copyNode(node)).catch(fail) }}>Copy node</button>
              <button disabled={locked} onClick={() => removeNode(node.id)}>Remove node</button>
            </article>
          }} />
          <ul>{activeFlow!.edges.map((edge, index) => <li key={index}>{activeFlow!.nodes.findIndex(node => node.id === edge.source) + 1}:{edge.source_port} → {activeFlow!.nodes.findIndex(node => node.id === edge.target) + 1}:{edge.target_port} <button disabled={locked} onClick={() => disconnect(index)}>Disconnect</button></li>)}</ul>
        </section>
        <fieldset disabled={locked}><legend>Connect declared ports</legend><select aria-label="Source node" value={connection.source} onChange={event => setConnection({ ...connection, source: event.target.value, source_port: '' })}><option value="">Source node</option>{activeFlow!.nodes.map((node, index) => <option key={node.id} value={node.id}>{index + 1}: {node.type}</option>)}</select><select aria-label="Source port" value={connection.source_port} onChange={event => setConnection({ ...connection, source_port: event.target.value })}><option value="">Output port</option>{Object.keys(sourcePorts).map(port => <option key={port}>{port}</option>)}</select><select aria-label="Target node" value={connection.target} onChange={event => setConnection({ ...connection, target: event.target.value, target_port: '' })}><option value="">Target node</option>{activeFlow!.nodes.map((node, index) => <option key={node.id} value={node.id}>{index + 1}: {node.type}</option>)}</select><select aria-label="Target port" value={connection.target_port} onChange={event => setConnection({ ...connection, target_port: event.target.value })}><option value="">Input port</option>{Object.keys(targetPorts).map(port => <option key={port}>{port}</option>)}</select><button onClick={() => host.connect(connection).catch(fail)}>Connect</button></fieldset>
        <h3>Runs</h3>{runs.map((run, runIndex) => <details key={run.id}><summary>Run {runIndex + 1} · {run.status} · {run.id}</summary>{run.diagnostics.map((message, index) => <p key={index}>{message}</p>)}{Object.keys(run.nodes).filter(id=>!run.nodes[id].location).map(id=>renderRunNode(run,runIndex,id))}</details>)}
        <h3>Data packages</h3>{extensions.resultActions?.map(action => <ExtensionBoundary key={projectSession.current + action.id + action.installation_id}><action.component host={host} packages={packages} /></ExtensionBoundary>)}<select aria-label="Data package" value={selectedPackage} onChange={event => { setSelectedPackage(event.target.value); setViewer('') }}><option value="">Choose package</option>{packages.map(pkg => <option key={pkg.id} value={pkg.id}>{packageDescription(pkg)}</option>)}</select>
        {selected && <section className="package"><a href={client.exportUrl(selected.id)} download>Download ZIP</a><p>Format: {selected.format} · Entry: {selected.entry}</p>{!!viewers.length && <label>Viewer<select value={activeViewer?.id ?? ''} onChange={event => setViewer(event.target.value)}>{viewers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}<label>Adopt into project<select aria-label="Adoption target" value={adoptionTarget} disabled={adopting} onChange={event => setAdoptionTarget(event.target.value)}><option value="">Choose target project</option>{projects.filter(item => item.id !== project.id).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button disabled={!adoptionTarget || adopting} onClick={() => void adopt()}>{adopting ? 'Adopting…' : 'Adopt package'}</button>{Viewer && <ExtensionBoundary key={selected.id + activeViewer?.id + activeViewer?.installation_id}><Viewer package={selected} host={host} /></ExtensionBoundary>}<ul>{selected.files.map(key => <li key={key}><a href={client.fileUrl(selected.id, key)} download>{key}</a></li>)}</ul></section>}
      </>}
    </main></div>
}
