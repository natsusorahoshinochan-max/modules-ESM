import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from 'react'
import { PublishedOutputs } from './PublishedOutputs'
import { loadRunViewer, runViewers, type ModuleRunViewerProps, type ModuleUiManifest } from './module-ui'
import './results.css'

export type ResultsViewStateStore = Map<string, unknown>
type Props = Omit<ModuleRunViewerProps, 'viewStateStore' | 'active'> & {
  viewStateStore?: ResultsViewStateStore; active?: boolean; onBack: () => void
  runControls?: ReactNode; loading?: boolean; loadError?: string
}

/** Generic Run shell: module packages own all cross-output interpretation. */
export function ResultsWorkbench({ runControls, onBack, loading, loadError, viewStateStore, active = true, ...props }: Props) {
  const [manifest, setManifest] = useState<ModuleUiManifest>()
  const [choice, setChoice] = useState('')
  const [Component, setComponent] = useState<ComponentType<ModuleRunViewerProps>>()
  const [manifestError, setManifestError] = useState('')
  const [viewerError, setViewerError] = useState('')
  const [localState] = useState(() => new Map<string, unknown>())
  useEffect(() => {
    let current = true
    void props.client.moduleUi().then(value => { if (current) setManifest(value) }, reason => { if (current) setManifestError(String(reason)) })
    return () => { current = false }
  }, [props.client])
  const viewers = useMemo(() => manifest ? runViewers(manifest, props.run) : [], [manifest, props.run])
  const selected = viewers.find(viewer => viewer.definition.viewer_id === choice) ?? viewers[0]
  useEffect(() => {
    let current = true
    setComponent(undefined)
    setViewerError('')
    if (selected) void loadRunViewer(selected).then(component => { if (current) setComponent(() => component) }, reason => { if (current) setViewerError(String(reason)) })
    return () => { current = false }
  }, [selected?.extension.entry_url, selected?.definition.component])
  return <section className="run-results-shell" aria-label="运行结果">
    <header><button onClick={onBack}>返回 Workflow</button><div className="result-run-controls">{runControls}</div><p>{props.run.status} · Run {props.run.run_id} · Commit {props.run.workflow_commit_id}</p></header>
    {loadError && <p role="alert">{loadError}</p>}{manifestError && <p role="alert">{manifestError}</p>}{viewerError && <p role="alert">{viewerError}</p>}
    {loading && <p role="status">正在读取 Run…</p>}
    <details className="run-results-outputs"><summary>全部已发布类型值与附件</summary><PublishedOutputs run={props.run} results={props.results} /></details>
    {selected && <label>结果面板<select aria-label="结果面板" value={selected.definition.viewer_id} onChange={event => setChoice(event.target.value)}>{viewers.map(viewer => <option key={viewer.definition.viewer_id} value={viewer.definition.viewer_id}>{viewer.definition.title}</option>)}</select></label>}
    <div className="run-results-panel">{Component && <Component {...props} active={active} viewStateStore={viewStateStore ?? localState} />}</div>
  </section>
}
