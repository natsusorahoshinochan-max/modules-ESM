import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Edge, Extensions, FlowNode, ModuleHost, PackageInfo } from '@protein-workbench/module-ui'
import { client, type Catalog, type ModuleRecord, type Project, type Run } from './host-client'
import { loadExtensions } from './host-ui'

class ExtensionBoundary extends Component<{ children: ReactNode }, { error: string }> {
  state = { error: '' }
  static getDerivedStateFromError(error: Error) { return { error: error.message } }
  render() { return this.state.error ? <p role="alert">Module interface failed: {this.state.error}</p> : this.props.children }
}

function JsonEditor({ value, disabled, onChange }: { value: Record<string, unknown>; disabled: boolean; onChange(value: Record<string, unknown>): void }) {
  return <textarea key={JSON.stringify(value)} defaultValue={JSON.stringify(value, null, 2)} disabled={disabled} onBlur={event => {
    try {
      const parsed = JSON.parse(event.target.value)
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('Enter a JSON object')
      event.target.setCustomValidity(''); onChange(parsed)
    } catch { event.target.setCustomValidity('Enter a valid JSON object'); event.target.reportValidity() }
  }} />
}
function ModuleSettings({ module, disabled, refresh, fail }: { module: ModuleRecord; disabled: boolean; refresh(): Promise<void>; fail(error: unknown): void }) {
  const [settings, setSettings] = useState(module.settings)
  return <details><summary>{module.name} · {module.enabled ? 'enabled' : 'disabled'}</summary>
    <p>{module.entry_point}</p><label>Deployment settings<JsonEditor value={settings} disabled={disabled} onChange={setSettings} /></label>
    <pre>{JSON.stringify(module.settings_schema, null, 2)}</pre>
    <button disabled={disabled} onClick={() => client.configure(module.id, settings).then(refresh).catch(fail)}>Save settings</button>
    <button disabled={disabled} onClick={() => client.enable(module.id, !module.enabled).then(refresh).catch(fail)}>{module.enabled ? 'Disable' : 'Enable'}</button>
    <button disabled={disabled} onClick={() => client.uninstall(module.id).then(refresh).catch(fail)}>Unregister</button>
  </details>
}

export default function App() {
  const [catalog, setCatalog] = useState<Catalog>({ nodes: [], modules: [] })
  const [extensions, setExtensions] = useState<Extensions>({})
  const [projects, setProjects] = useState<Project[]>([])
  const [project, setProject] = useState<Project | null>(null)
  const currentProject = useRef<Project | null>(null)
  const projectSession = useRef(0)
  const opening = useRef(0)
  const runningNow = useRef(false)
  const submittingRun = useRef(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const savingNow = useRef(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [entry, setEntry] = useState('workbench_notes:module')
  const [projectName, setProjectName] = useState('Research project')
  const [packages, setPackages] = useState<PackageInfo[]>([])
  const [selectedPackage, setSelectedPackage] = useState('')
  const [viewer, setViewer] = useState('')
  const [adoptionTarget, setAdoptionTarget] = useState('')
  const [adopting, setAdopting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const deletingProject = useRef('')
  const locked = running || (deleting && deletingProject.current === project?.id)
  const [runs, setRuns] = useState<Run[]>([])
  const [connection, setConnection] = useState<Edge>({ source: '', source_port: '', target: '', target_port: '' })
  const fail = (failure: unknown) => setError(failure instanceof Error ? failure.message : String(failure))
  async function refresh() {
    const next = await client.catalog(); setCatalog(next)
    try { setExtensions(await loadExtensions(next.modules)) } catch (failure) { setExtensions({}); fail(failure) }
    setProjects(await client.projects())
  }
  useEffect(() => { refresh().catch(fail) }, [])
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [dirty])
  function change(update: (current: Project) => Project) {
    if (runningNow.current || deletingProject.current === currentProject.current?.id) throw new Error('Project is running or being deleted')
    if (!currentProject.current) throw new Error('Open a project first')
    currentProject.current = update(currentProject.current)
    setProject(currentProject.current); setDirty(true); setNotice('')
  }
  async function open(id: string) {
    if (runningNow.current || (dirty && !window.confirm('Discard unsaved changes and open this project?'))) return
    const request = ++opening.current
    const [next, files, history] = await Promise.all([client.project(id), client.packages(id), client.runs(id)])
    if (request !== opening.current) return
    projectSession.current += 1; currentProject.current = next; setProject(next); setDirty(false); setNotice('')
    runningNow.current = !!next.running || history.some(run => run.status === 'running'); setRunning(runningNow.current)
    setPackages(files); setRuns(history); setSelectedPackage(''); setViewer(''); setAdoptionTarget(''); setError('')
  }
  async function createProject() {
    if (dirty && !window.confirm('Discard unsaved changes and create a project?')) return
    const next = await client.createProject(projectName); await refresh(); await open(next.id)
  }
  async function save() {
    const snapshot = currentProject.current
    if (!snapshot) throw new Error('Open a project first')
    if (savingNow.current) throw new Error('Project save is already in progress')
    savingNow.current = true; setSaving(true)
    try {
      const saved = await client.save(snapshot)
      if (currentProject.current !== snapshot) return false
      currentProject.current = saved; setProject(saved); setDirty(false); setNotice('Project and layout saved')
      return true
    } finally { savingNow.current = false; setSaving(false) }
  }
  async function run() {
    if (!project) return
    if (dirty) { if (!window.confirm('Save changes and run?')) return; if (!await save()) throw new Error('Project changed while saving; save again before running') }
    opening.current += 1; runningNow.current = true; setRunning(true); setError(''); setNotice('Running on the backend…')
    try {
      submittingRun.current = true
      const result = await client.run(project.id)
      setRuns(items => [...items.filter(item => item.id !== result.id), result])
      runningNow.current = result.status === 'running'; setRunning(runningNow.current)
      if (!runningNow.current) setPackages(await client.packages(project.id))
      setNotice(`Run ${result.status}`)
    } catch (failure) {
      // Re-read the backend on the next poll if the submission response was lost.
      throw failure
    } finally { submittingRun.current = false }
  }
  useEffect(() => {
    if (!project) return
    const id = project.id
    const session = projectSession.current
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const history = await client.runs(id)
        if (stopped || session !== projectSession.current || submittingRun.current) return
        const active = history.some(item => item.status === 'running')
        const wasRunning = runningNow.current
        setRuns(history); runningNow.current = active; setRunning(active)
        if (active || wasRunning) {
          const files = await client.packages(id)
          if (stopped || session !== projectSession.current) return
          setPackages(files)
          if (!active) setNotice(`Run ${history.at(-1)?.status ?? 'finished'}`)
        }
      } catch (failure) { if (!stopped && session === projectSession.current) fail(failure) }
      finally { if (!stopped) timer = setTimeout(poll, 500) }
    }
    timer = setTimeout(poll, 500)
    return () => { stopped = true; clearTimeout(timer) }
  }, [project?.id])

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
      setProjects(items => items.filter(item => item.id !== current.id))
      if (session !== projectSession.current) return
      projectSession.current += 1; currentProject.current = null
      setProject(null); setDirty(false); setPackages([]); setRuns([]); setSelectedPackage(''); setViewer(''); setAdoptionTarget('')
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
        activeProject()
        const files = await client.packages(current.id)
        activeProject(); setPackages(files); return result
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
  const Viewer = viewers.find(item => item.id === viewer)?.component ?? viewers[0]?.component
  const source = project?.flow.nodes.find(node => node.id === connection.source)
  const target = project?.flow.nodes.find(node => node.id === connection.target)
  const sourcePorts = catalog.nodes.find(node => node.id === source?.type)?.outputs ?? {}
  const targetPorts = catalog.nodes.find(node => node.id === target?.type)?.inputs ?? {}
  function updateNode(id: string, update: Partial<FlowNode>) { change(current => ({ ...current, flow: { ...current.flow, nodes: current.flow.nodes.map(node => node.id === id ? { ...node, ...update } : node) } })) }

  return <div className="workbench"><header><h1>Protein Workbench</h1><span>Public module host</span></header>
    {error && <div role="alert" className="error">{error}<button onClick={() => setError('')}>Dismiss</button></div>}
    {notice && <p role="status">{notice}</p>}
    <aside><h2>Projects</h2><label>Project name<input value={projectName} onChange={event => setProjectName(event.target.value)} /></label><button disabled={locked} onClick={() => createProject().catch(fail)}>Create project</button>
      <ul>{projects.map(item => <li key={item.id}><button disabled={running || (deleting && deletingProject.current === item.id)} onClick={() => open(item.id).catch(fail)}>{item.name}</button></li>)}</ul>
      <h2>Modules</h2><p>Install a Python package in the server environment, then register its public factory.</p><label>Entry point<input value={entry} onChange={event => setEntry(event.target.value)} /></label>
      <button disabled={locked} onClick={() => client.install(entry).then(refresh).catch(fail)}>Register module</button>
      {catalog.modules.map(module => <ModuleSettings key={module.id} module={module} disabled={locked} refresh={refresh} fail={fail} />)}
      {!catalog.modules.length && <p>No modules enabled. Projects and canvas are available.</p>}
    </aside>
    <main><div className="toolbar"><h2>{project?.name ?? 'Open or create a project'}{dirty ? ' · unsaved' : ''}</h2><button disabled={!project || locked || saving} onClick={() => save().catch(fail)}>Save project</button><button disabled={!project || locked || saving} onClick={() => run().catch(fail)}>{dirty ? 'Save and run' : 'Run'}</button>{running && <button onClick={() => Promise.all(runs.filter(item => item.status === 'running').map(item => client.cancelRun(item.id))).then(() => setNotice('Cancellation requested; waiting for the backend…')).catch(fail)}>Cancel run</button>}<button disabled={!project || running || saving || deleting} onClick={() => void deleteProject()}>Delete project</button></div>
      {project && <><section className="module-actions">{extensions.actions?.map(action => <div key={action.id}><ExtensionBoundary><action.component host={host} /></ExtensionBoundary></div>)}</section>
        <label>Add node<select disabled={locked} value="" onChange={event => { host.addNode({ type: event.target.value, parameters: {}, inputs: {} }).catch(fail) }}><option value="">Choose operation</option>{catalog.nodes.map(node => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label>
        <section className="canvas" aria-label="Workflow canvas"><h3>Canvas</h3>{!project.flow.nodes.length && <p>Empty canvas. Add a module operation to begin.</p>}
          {project.flow.nodes.map((node, index) => {
            const declaration = catalog.nodes.find(item => item.id === node.type)
            const Editor = extensions.editors?.find(item => item.node === node.type)?.component
            return <article className="node" key={node.id} style={{ marginLeft: project.layout[node.id]?.x ?? 0 }}><h4>{declaration?.name ?? `Missing module: ${node.type}`}</h4><small>Node {index + 1} · {node.id}</small>
              <label>Horizontal position<input type="range" min="0" max="240" disabled={locked} value={project.layout[node.id]?.x ?? 0} onChange={event => { const x = Number(event.target.value); change(current => ({ ...current, layout: { ...current.layout, [node.id]: { ...(current.layout[node.id] ?? { y: 0 }), x } } })) }} /></label>
              {Editor ? <ExtensionBoundary><Editor parameters={node.parameters} readOnly={locked} onChange={parameters => updateNode(node.id, { parameters })} /></ExtensionBoundary> : <label>Parameters<JsonEditor value={node.parameters} disabled={locked} onChange={parameters => updateNode(node.id, { parameters })} /></label>}
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
                    <label>Tool parameters (JSON)<JsonEditor value={node.tool_parameters?.[slot] ?? {}} disabled={locked} onChange={parameters => updateNode(node.id, { tool_parameters: { ...node.tool_parameters, [slot]: parameters } })} /></label></>}
                </fieldset>
              })}
              {Object.entries(declaration?.inputs ?? {}).map(([port, input]) => <label key={port}>{port} · {input.accepts.join(', ')}{input.required ? ' · required' : ''}<select disabled={locked} value={node.inputs[port]?.[0] ?? ''} onChange={event => updateNode(node.id, { inputs: { ...node.inputs, [port]: event.target.value ? [event.target.value] : [] } })}><option value="">Use connection / no input</option>{packages.filter(pkg => input.accepts.includes(pkg.format)).map(pkg => <option key={pkg.id} value={pkg.id}>{pkg.format} · {pkg.id}</option>)}</select></label>)}
              {Object.entries(declaration?.outputs ?? {}).map(([port, output]) => <p key={port}>Output {port} → {output.format}</p>)}
              <button disabled={locked} onClick={() => change(current => ({ ...current, flow: { ...current.flow, nodes: current.flow.nodes.filter(item => item.id !== node.id), edges: current.flow.edges.filter(edge => edge.source !== node.id && edge.target !== node.id) } }))}>Remove node</button>
            </article>
          })}
          <ul>{project.flow.edges.map((edge, index) => <li key={index}>{project.flow.nodes.findIndex(node => node.id === edge.source) + 1}:{edge.source_port} → {project.flow.nodes.findIndex(node => node.id === edge.target) + 1}:{edge.target_port} <button disabled={locked} onClick={() => change(current => ({ ...current, flow: { ...current.flow, edges: current.flow.edges.filter((_, i) => i !== index) } }))}>Disconnect</button></li>)}</ul>
        </section>
        <fieldset disabled={locked}><legend>Connect declared ports</legend><select aria-label="Source node" value={connection.source} onChange={event => setConnection({ ...connection, source: event.target.value, source_port: '' })}><option value="">Source node</option>{project.flow.nodes.map((node, index) => <option key={node.id} value={node.id}>{index + 1}: {node.type}</option>)}</select><select aria-label="Source port" value={connection.source_port} onChange={event => setConnection({ ...connection, source_port: event.target.value })}><option value="">Output port</option>{Object.keys(sourcePorts).map(port => <option key={port}>{port}</option>)}</select><select aria-label="Target node" value={connection.target} onChange={event => setConnection({ ...connection, target: event.target.value, target_port: '' })}><option value="">Target node</option>{project.flow.nodes.map((node, index) => <option key={node.id} value={node.id}>{index + 1}: {node.type}</option>)}</select><select aria-label="Target port" value={connection.target_port} onChange={event => setConnection({ ...connection, target_port: event.target.value })}><option value="">Input port</option>{Object.keys(targetPorts).map(port => <option key={port}>{port}</option>)}</select><button onClick={() => host.connect(connection).catch(fail)}>Connect</button></fieldset>
        <h3>Runs</h3>{runs.map(run => <details key={run.id}><summary>{run.status} · {run.id}</summary>{run.diagnostics.map((message, index) => <p key={index}>{message}</p>)}{Object.entries(run.nodes).map(([id, result]) => <p key={id}>{id}: {result.status === 'configuration_blocked' ? 'Configuration prevents group startup' : result.status === 'blocked' ? 'Not executed: dependency failed' : result.status} {result.diagnostics?.join('; ')}</p>)}</details>)}
        <h3>Data packages</h3><select aria-label="Data package" value={selectedPackage} onChange={event => { setSelectedPackage(event.target.value); setViewer('') }}><option value="">Choose package</option>{packages.map(pkg => <option key={pkg.id} value={pkg.id}>{pkg.format} · {pkg.id}</option>)}</select>
        {selected && <section className="package"><a href={client.exportUrl(selected.id)} download>Download ZIP</a><p>Format: {selected.format} · Entry: {selected.entry}</p>{!!viewers.length && <label>Viewer<select value={viewers.find(item => item.id === viewer)?.id ?? viewers[0].id} onChange={event => setViewer(event.target.value)}>{viewers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}<label>Adopt into project<select aria-label="Adoption target" value={adoptionTarget} disabled={adopting} onChange={event => setAdoptionTarget(event.target.value)}><option value="">Choose target project</option>{projects.filter(item => item.id !== project.id).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button disabled={!adoptionTarget || adopting} onClick={() => void adopt()}>{adopting ? 'Adopting…' : 'Adopt package'}</button>{Viewer && <ExtensionBoundary key={selected.id + viewer}><Viewer package={selected} host={host} /></ExtensionBoundary>}<ul>{selected.files.map(key => <li key={key}><a href={client.fileUrl(selected.id, key)} download>{key}</a></li>)}</ul></section>}
      </>}
    </main></div>
}
