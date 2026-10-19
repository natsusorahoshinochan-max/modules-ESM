import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Edge, FlowNode, ModuleHost, PackageInfo } from '@protein-workbench/module-ui'
import { client, type Catalog, type Project, type Run } from './host-client'
import { loadExtensions, type LoadedExtensions } from './host-ui'
import { ModuleManagement } from './ModuleManagement'

class ExtensionBoundary extends Component<{ children: ReactNode }, { error: string }> {
  state = { error: '' }
  static getDerivedStateFromError(error: Error) { return { error: error.message } }
  render() { return this.state.error ? <p role="alert">Module interface failed: {this.state.error}</p> : this.props.children }
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
  const refreshGeneration = useRef(0)
  const invalidateRefresh = () => { refreshGeneration.current += 1 }
  const [project, setProject] = useState<Project | null>(null)
  const currentProject = useRef<Project | null>(null)
  const projectSession = useRef(0)
  const opening = useRef(0)
  const runningNow = useRef(false)
  const submittingRun = useRef(false)
  const runOperationEpoch = useRef(0)
  const [dirty, setDirty] = useState(false)
  const dirtyNow = useRef(false)
  const draftRevision = useRef(0)
  function markDirty(value: boolean) { if (value) draftRevision.current += 1; dirtyNow.current = value; setDirty(value) }
  const canvas = useRef<HTMLElement>(null)
  const [saving, setSaving] = useState(false)
  const savingNow = useRef(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [projectName, setProjectName] = useState('Research project')
  const draftInputs = useRef<PackageInfo[]>([])
  async function discardDraftInputs() {
    const inputs = draftInputs.current; draftInputs.current = []
    await Promise.all(inputs.map(input => client.discardDraftInput(input.id).catch(fail)))
  }
  const [packages, setPackages] = useState<PackageInfo[]>([])
  const [selectedPackage, setSelectedPackage] = useState('')
  const [viewer, setViewer] = useState('')
  const [adoptionTarget, setAdoptionTarget] = useState('')
  const [adopting, setAdopting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const deletingProject = useRef('')
  const locked = running || (deleting && deletingProject.current === project?.id)
  const [runs, setRuns] = useState<Run[]>([])
  const cancellableRuns = runs.filter(item => item.status === 'running')
  const [connection, setConnection] = useState<Edge>({ source: '', source_port: '', target: '', target_port: '' })
  const fail = (failure: unknown) => setError(failure instanceof Error ? failure.message : String(failure))
  async function refresh() {
    const request = ++refreshGeneration.current
    const current = () => request === refreshGeneration.current
    let next: Catalog | undefined
    try {
      next = await client.catalog()
      if (!current()) return
      let nextExtensions: LoadedExtensions = {}, extensionError: unknown, extensionFailed = false
      try { nextExtensions = await loadExtensions(next.modules) } catch (failure) { extensionError = failure; extensionFailed = true }
      if (!current()) return
      const nextProjects = await client.projects()
      if (!current()) return
      setSnapshot({ catalog: next, extensions: nextExtensions, projects: nextProjects })
      if (extensionFailed) fail(extensionError)
    } catch (failure) {
      if (!current()) return
      setSnapshot(previous => ({ catalog: next ?? previous.catalog, extensions: {}, projects: previous.projects }))
      fail(failure)
    }
  }
  useEffect(() => { refresh().then(() => openTutorial(true)).catch(fail) }, [])
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirtyNow.current) { event.preventDefault(); event.returnValue = '' } }
    const pageHide = (event: PageTransitionEvent) => { if (!event.persisted) void discardDraftInputs() }
    window.addEventListener('beforeunload', beforeUnload)
    window.addEventListener('pagehide', pageHide)
    return () => { window.removeEventListener('beforeunload', beforeUnload); window.removeEventListener('pagehide', pageHide); void discardDraftInputs() }
  }, [])
  function change(update: (current: Project) => Project) {
    if (runningNow.current || deletingProject.current === currentProject.current?.id) throw new Error('Project is running or being deleted')
    if (!currentProject.current) throw new Error('Open a project first')
    currentProject.current = update(currentProject.current)
    setProject(currentProject.current); markDirty(true); setNotice('')
  }
  async function openTutorial(automatic = false) {
    const request = opening.current
    const example = await client.tutorial()
    if (automatic && (request !== opening.current || currentProject.current)) return
    await open(example.id, undefined, automatic)
  }
  async function open(id: string, approvedRevision?: number, preserveError = false) {
    if (runningNow.current || (dirtyNow.current && draftRevision.current !== approvedRevision && !window.confirm('Discard unsaved changes and open this project?'))) return
    const leavingRevision = draftRevision.current
    const request = ++opening.current
    const [next, files, history] = await Promise.all([client.project(id), client.packages(id), client.runs(id)])
    if (request !== opening.current) return
    if (dirtyNow.current && draftRevision.current !== leavingRevision && !window.confirm('Discard unsaved changes and open this project?')) return
    void discardDraftInputs()
    projectSession.current += 1; currentProject.current = next; setProject(next); markDirty(false); setNotice('')
    runningNow.current = !!next.running || history.some(run => run.status === 'running'); setRunning(runningNow.current)
    setPackages(files); setRuns(history); setSelectedPackage(''); setViewer(''); setAdoptionTarget(''); if (!preserveError) setError('')
    return true
  }
  async function createProject() {
    if (dirtyNow.current && !window.confirm('Discard unsaved changes and create a project?')) return
    const approvedRevision = draftRevision.current
    setError('')
    const next = await client.createProject(projectName); await refresh(); await open(next.id, approvedRevision, true)
  }
  async function save() {
    if (document.activeElement instanceof HTMLElement && canvas.current?.contains(document.activeElement)) document.activeElement.blur()
    const invalid = canvas.current?.querySelector<HTMLTextAreaElement>('textarea:invalid')
    if (invalid) { invalid.reportValidity(); throw new Error('Enter valid parameter JSON before saving') }
    const snapshot = currentProject.current
    if (!snapshot) throw new Error('Open a project first')
    if (savingNow.current) throw new Error('Project save is already in progress')
    const session = projectSession.current
    const revision = draftRevision.current
    savingNow.current = true; setSaving(true); setError('')
    try {
      const saved = snapshot.tutorial ? await client.copy(snapshot, projectName) : await client.save(snapshot)
      if (snapshot.tutorial) setSnapshot(previous => ({ ...previous, projects: [...previous.projects, saved] }))
      if (currentProject.current !== snapshot || draftRevision.current !== revision) return false
      if (snapshot.tutorial) {
        const files = await client.packages(saved.id)
        if (currentProject.current !== snapshot || draftRevision.current !== revision) return false
        projectSession.current += 1; setPackages(files); setRuns([]); setSelectedPackage(''); setViewer('')
        void discardDraftInputs()
      }
      currentProject.current = saved; setProject(saved); markDirty(false); setNotice('Project and layout saved')
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
    const session = projectSession.current
    const revision = draftRevision.current
    savingNow.current = true; setSaving(true); setError('')
    try {
      const copied = await client.copy(snapshot, projectName)
      setSnapshot(previous => ({ ...previous, projects: [...previous.projects, copied] }))
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
      setSnapshot(previous => ({ ...previous, projects: previous.projects.filter(item => item.id !== current.id) }))
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
    function activeProject() {
      if (origin !== projectSession.current) throw new Error('Project changed; start the operation again')
      if (!currentProject.current || runningNow.current || deletingProject.current === currentProject.current.id) throw new Error('Open an idle project first')
      return currentProject.current
    }
    return {
      readOnly: locked || !project,
      async createInput(input) {
        const current = activeProject()
        const result = await client.createInput(current.id, input)
        if (current.tutorial) {
          try { activeProject() } catch (failure) { await client.discardDraftInput(result.id); throw failure }
          draftInputs.current.push(result)
        }
        activeProject()
        const files = await client.packages(current.id)
        activeProject(); setPackages([...files, ...draftInputs.current]); return result
      },
      async addNode(node) {
        activeProject()
        const id = crypto.randomUUID(); change(current => ({ ...current, flow: { ...current.flow, nodes: [...current.flow.nodes, { ...node, id }] } })); return id
      },
      async connect(edge) {
        const current = activeProject()
        const source = current.flow.nodes.find(node => node.id === edge.source)
        const target = current.flow.nodes.find(node => node.id === edge.target)
        const output = catalog.nodes.find(node => node.id === source?.type)?.outputs[edge.source_port]
        const input = catalog.nodes.find(node => node.id === target?.type)?.inputs[edge.target_port]
        if (!output || !input || !input.accepts.includes(output.format)) throw new Error('Port formats do not match; select an explicit conversion node')
        if (input.cardinality === 'one' && output.cardinality === 'many') throw new Error('Cardinality mismatch: a many output requires a many input')
        if (input.cardinality === 'one' && (target?.inputs[edge.target_port]?.length || current.flow.edges.some(item => item.target === edge.target && item.target_port === edge.target_port))) throw new Error('Input accepts only one package')
        change(current => ({ ...current, flow: { ...current.flow, edges: [...current.flow.edges, edge] } }))
      },
      readFile: client.readFile,
    }
  }, [project, locked, catalog])
  const selected = packages.find(item => item.id === selectedPackage)
  const viewers = extensions.viewers?.filter(item => item.formats.includes(selected?.format ?? '')) ?? []
  const activeViewer = viewers.find(item => item.id === viewer) ?? viewers[0]
  const Viewer = activeViewer?.component
  function packageDescription(pkg: PackageInfo) {
    for (const [index, run] of runs.entries()) {
      for (const [node, result] of Object.entries(run.nodes)) {
        for (const [port, values] of Object.entries(result.outputs)) {
          if (values.includes(pkg.id)) return `Run ${index + 1} · ${node}.${port} · ${pkg.format} · ${pkg.id}`
        }
      }
    }
    return `${pkg.format} · ${pkg.id}`
  }
  const source = project?.flow.nodes.find(node => node.id === connection.source)
  const target = project?.flow.nodes.find(node => node.id === connection.target)
  const sourcePorts = catalog.nodes.find(node => node.id === source?.type)?.outputs ?? {}
  const targetPorts = catalog.nodes.find(node => node.id === target?.type)?.inputs ?? {}
  function updateNode(id: string, update: Partial<FlowNode>) { change(current => ({ ...current, flow: { ...current.flow, nodes: current.flow.nodes.map(node => node.id === id ? { ...node, ...update } : node) } })) }

  return <div className="workbench"><header><h1>Protein Workbench</h1><span>Public module host</span></header>
    {error && <div role="alert" className="error">{error}<button onClick={() => setError('')}>Dismiss</button></div>}
    {notice && <p role="status">{notice}</p>}
    <aside><h2>Projects</h2><button disabled={locked} onClick={() => openTutorial().catch(fail)}>Teaching example</button><label>Project name<input value={projectName} onChange={event => setProjectName(event.target.value)} /></label><button disabled={locked} onClick={() => createProject().catch(fail)}>Create project</button>
      <ul>{projects.map(item => <li key={item.id}><button disabled={running || (deleting && deletingProject.current === item.id)} onClick={() => open(item.id).catch(fail)}>{item.name}</button></li>)}</ul>
      <ModuleManagement modules={catalog.modules} disabled={locked} refresh={refresh} invalidateRefresh={invalidateRefresh} fail={fail} />
    </aside>
    <main><div className="toolbar"><h2>{project?.name ?? 'Open or create a project'}{dirty ? ' · unsaved' : ''}</h2><button disabled={!project || locked || saving} onClick={() => save().catch(fail)}>Save project</button><button disabled={!project || locked || saving} onClick={() => copyProject().catch(fail)}>Copy project</button><button disabled={!project || locked || saving} onClick={() => run().catch(fail)}>{dirty || project?.tutorial ? 'Save and run' : 'Run'}</button>{running && <button disabled={submittingRun.current || !cancellableRuns.length} onClick={() => void cancelRun()}>Cancel run</button>}<button disabled={!project || project.tutorial || running || saving || deleting} onClick={() => void deleteProject()}>Delete project</button></div>
      {project && <><section className="module-actions">{extensions.actions?.map(action => <div key={action.id + action.installation_id}><ExtensionBoundary><action.component host={host} /></ExtensionBoundary></div>)}</section>
        <label>Add node<select disabled={locked} value="" onChange={event => { host.addNode({ type: event.target.value, parameters: {}, inputs: {} }).catch(fail) }}><option value="">Choose operation</option>{catalog.nodes.map(node => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label>
        <section key={projectSession.current} className="canvas" aria-label="Workflow canvas" ref={canvas}><h3>Canvas</h3>{!project.flow.nodes.length && <p>Empty canvas. Add a module operation to begin.</p>}
          {project.flow.nodes.map((node, index) => {
            const declaration = catalog.nodes.find(item => item.id === node.type)
            const editor = extensions.editors?.find(item => item.node === node.type)
            const Editor = editor?.component
            return <article className="node" key={node.id} style={{ marginLeft: project.layout[node.id]?.x ?? 0 }}><h4>{declaration?.name ?? `Missing module: ${node.type}`}</h4><small>Node {index + 1} · {node.id}</small>{!declaration && <p role="status">Cannot run: install and enable the module that provides {node.type}.</p>}
              <label>Horizontal position<input type="range" min="0" max="240" disabled={locked} value={project.layout[node.id]?.x ?? 0} onChange={event => { const x = Number(event.target.value); change(current => ({ ...current, layout: { ...current.layout, [node.id]: { ...(current.layout[node.id] ?? { y: 0 }), x } } })) }} /></label>
              {Editor ? <ExtensionBoundary key={node.id + editor?.installation_id}><Editor parameters={node.parameters} readOnly={locked} onChange={parameters => updateNode(node.id, { parameters })} /></ExtensionBoundary> : <label>Parameters<JsonEditor value={node.parameters} disabled={locked} onDraftChange={() => { markDirty(true); setNotice('') }} onChange={parameters => updateNode(node.id, { parameters })} /></label>}
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
              {Object.entries(declaration?.inputs ?? {}).map(([port, input]) => <label key={port}>{port} · {input.accepts.join(', ')}{input.required ? ' · required' : ''}<select disabled={locked} value={node.inputs[port]?.[0] ?? ''} onChange={event => updateNode(node.id, { inputs: { ...node.inputs, [port]: event.target.value ? [event.target.value] : [] } })}><option value="">Use connection / no input</option>{packages.filter(pkg => input.accepts.includes(pkg.format)).map(pkg => <option key={pkg.id} value={pkg.id}>{packageDescription(pkg)}</option>)}</select></label>)}
              {Object.entries(declaration?.outputs ?? {}).map(([port, output]) => <p key={port}>Output {port} → {output.format}</p>)}
              <button disabled={locked} onClick={() => change(current => ({ ...current, flow: { ...current.flow, nodes: current.flow.nodes.filter(item => item.id !== node.id), edges: current.flow.edges.filter(edge => edge.source !== node.id && edge.target !== node.id) } }))}>Remove node</button>
            </article>
          })}
          <ul>{project.flow.edges.map((edge, index) => <li key={index}>{project.flow.nodes.findIndex(node => node.id === edge.source) + 1}:{edge.source_port} → {project.flow.nodes.findIndex(node => node.id === edge.target) + 1}:{edge.target_port} <button disabled={locked} onClick={() => change(current => ({ ...current, flow: { ...current.flow, edges: current.flow.edges.filter((_, i) => i !== index) } }))}>Disconnect</button></li>)}</ul>
        </section>
        <fieldset disabled={locked}><legend>Connect declared ports</legend><select aria-label="Source node" value={connection.source} onChange={event => setConnection({ ...connection, source: event.target.value, source_port: '' })}><option value="">Source node</option>{project.flow.nodes.map((node, index) => <option key={node.id} value={node.id}>{index + 1}: {node.type}</option>)}</select><select aria-label="Source port" value={connection.source_port} onChange={event => setConnection({ ...connection, source_port: event.target.value })}><option value="">Output port</option>{Object.keys(sourcePorts).map(port => <option key={port}>{port}</option>)}</select><select aria-label="Target node" value={connection.target} onChange={event => setConnection({ ...connection, target: event.target.value, target_port: '' })}><option value="">Target node</option>{project.flow.nodes.map((node, index) => <option key={node.id} value={node.id}>{index + 1}: {node.type}</option>)}</select><select aria-label="Target port" value={connection.target_port} onChange={event => setConnection({ ...connection, target_port: event.target.value })}><option value="">Input port</option>{Object.keys(targetPorts).map(port => <option key={port}>{port}</option>)}</select><button onClick={() => host.connect(connection).catch(fail)}>Connect</button></fieldset>
        <h3>Runs</h3>{runs.map((run, runIndex) => <details key={run.id}><summary>Run {runIndex + 1} · {run.status} · {run.id}</summary>{run.diagnostics.map((message, index) => <p key={index}>{message}</p>)}{Object.entries(run.nodes).map(([id, result]) => <section key={id} aria-label={`Run ${runIndex + 1} node ${id}`}>
          <p>{id}: {result.status === 'configuration_blocked' ? 'Configuration prevents group startup' : result.status === 'blocked' ? 'Not executed' : result.status} {result.diagnostics?.join('; ')}</p>
          {result.status !== 'succeeded' && Object.values(result.outputs).some(values => values.length) && <p>Partial results · batch incomplete</p>}
          {Object.entries(result.outputs).flatMap(([port, values]) => values.map((packageId, index) => <button key={`${port}-${index}`} onClick={() => { setSelectedPackage(packageId); setViewer('') }}>View {port} result {index + 1}</button>))}
          {(result.status === 'failed' || result.status === 'cancelled') && run.calls?.[id] !== undefined && <button disabled={locked || saving} onClick={() => void continueRun(run.id, id)}>Continue {id} with original inputs and parameters</button>}
        </section>)}</details>)}
        <h3>Data packages</h3><select aria-label="Data package" value={selectedPackage} onChange={event => { setSelectedPackage(event.target.value); setViewer('') }}><option value="">Choose package</option>{packages.map(pkg => <option key={pkg.id} value={pkg.id}>{packageDescription(pkg)}</option>)}</select>
        {selected && <section className="package"><a href={client.exportUrl(selected.id)} download>Download ZIP</a><p>Format: {selected.format} · Entry: {selected.entry}</p>{!!viewers.length && <label>Viewer<select value={activeViewer?.id ?? ''} onChange={event => setViewer(event.target.value)}>{viewers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}<label>Adopt into project<select aria-label="Adoption target" value={adoptionTarget} disabled={adopting} onChange={event => setAdoptionTarget(event.target.value)}><option value="">Choose target project</option>{projects.filter(item => item.id !== project.id).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button disabled={!adoptionTarget || adopting} onClick={() => void adopt()}>{adopting ? 'Adopting…' : 'Adopt package'}</button>{Viewer && <ExtensionBoundary key={selected.id + activeViewer?.id + activeViewer?.installation_id}><Viewer package={selected} host={host} /></ExtensionBoundary>}<ul>{selected.files.map(key => <li key={key}><a href={client.fileUrl(selected.id, key)} download>{key}</a></li>)}</ul></section>}
      </>}
    </main></div>
}
