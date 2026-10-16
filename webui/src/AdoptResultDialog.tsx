import { useEffect, useState } from 'react'
import { InteractionDialog } from './InteractionDialog'
import { workspaceErrorMessage } from './project-workspace'
import type { AdoptedResult, ProjectMetadata, ProjectRunSummary, PublicV2Client, PublishedOutput } from './protocol/client'

export function AdoptResultDialog({ client, projectId, readOnly, onAdopt, onClose }: {
  client: PublicV2Client
  projectId: string
  readOnly: boolean
  onAdopt: (result: AdoptedResult) => Promise<void>
  onClose: () => void
}) {
  const [projects, setProjects] = useState<ProjectMetadata[]>([])
  const [sourceProject, setSourceProject] = useState(projectId)
  const [runs, setRuns] = useState<ProjectRunSummary[]>([])
  const [runId, setRunId] = useState('')
  const [outputs, setOutputs] = useState<PublishedOutput[]>([])
  const [types, setTypes] = useState<string[]>([])
  const [selection, setSelection] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let current = true
    void Promise.all([client.projects(), client.resultSources()]).then(([listed, registered]) => {
      if (current) { setProjects(listed.projects); setTypes(registered.sources.map(source => source.port_type_id)) }
    }).catch(reason => { if (current) setError(workspaceErrorMessage(reason)) })
    return () => { current = false }
  }, [client])
  useEffect(() => {
    let current = true
    void client.projectRuns(sourceProject).then(result => {
      if (current) { setRuns(result.runs); setLoading(false) }
    }).catch(reason => { if (current) { setError(workspaceErrorMessage(reason)); setLoading(false) } })
    return () => { current = false }
  }, [client, sourceProject])
  useEffect(() => {
    if (!runId) return
    let current = true
    void client.runProjection(sourceProject, runId).then(result => {
      if (current) { setOutputs(result.outputs); setLoading(false) }
    }).catch(reason => { if (current) { setError(workspaceErrorMessage(reason)); setLoading(false) } })
    return () => { current = false }
  }, [client, sourceProject, runId])
  const values = outputs.filter(output => types.includes(output.port_type.contract_id)).flatMap(output =>
    Array.from({ length: output.value_count }, (_, value_index) => ({ node_id: output.node_id, output_port: output.output_port, value_index })))
  const selected = values.find(value => JSON.stringify(value) === selection)
  async function adopt() {
    if (!selected || readOnly) return
    setBusy(true)
    setError('')
    try {
      const adopted = await client.adoptResult(projectId, { source_project_id: sourceProject, source_run_id: runId, ...selected })
      await onAdopt(adopted)
      onClose()
    } catch (reason) { setError(workspaceErrorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <InteractionDialog title="采用历史结果" className="run-dialog" onClose={onClose} busy={busy}>
    <h2>采用历史结果</h2>
    <p>将结果复制为本项目的独立输入，并添加来源节点。请手动连接后续节点和保存项目。</p>
    <label>来源项目<select aria-label="来源项目" disabled={busy} value={sourceProject} onChange={event => {
      setSourceProject(event.target.value); setRunId(''); setRuns([]); setOutputs([]); setSelection(''); setError(''); setLoading(true)
    }}>{projects.map(project => <option key={project.id} value={project.id}>{project.name}{project.id === projectId ? '（当前项目）' : ''}</option>)}</select></label>
    <label>历史运行<select aria-label="历史运行" disabled={busy || loading} value={runId} onChange={event => {
      setRunId(event.target.value); setOutputs([]); setSelection(''); setError(''); setLoading(Boolean(event.target.value))
    }}><option value="">选择运行…</option>{runs.map(run => <option key={run.run_id} value={run.run_id} disabled={run.availability !== 'readable'}>{run.run_id} · {run.availability === 'readable' ? run.status : '记录不可用'}</option>)}</select></label>
    <label>结果值<select aria-label="结果值" disabled={busy || loading || !runId} value={selection} onChange={event => setSelection(event.target.value)}><option value="">选择结果…</option>{values.map(value => <option key={JSON.stringify(value)} value={JSON.stringify(value)}>{value.node_id} / {value.output_port} · 值 {value.value_index + 1}</option>)}</select></label>
    {loading && <p role="status">读取历史结果…</p>}
    {!loading && runId && values.length === 0 && <p>此运行没有当前模块支持采用的结果值。</p>}
    {readOnly && <p role="status">项目正在运行，结束后才能采用输入。</p>}
    {error && <p role="alert">{error}</p>}
    <footer><button disabled={busy} onClick={onClose}>取消</button><button disabled={busy || readOnly || loading || !selected} onClick={() => void adopt()}>采用为输入</button></footer>
  </InteractionDialog>
}
