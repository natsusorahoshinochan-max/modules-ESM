import { useCallback, useEffect, useState } from 'react'
import type { PublicV2Client, ProjectRunSummary, RunEventEnvelope } from './protocol/client'
import type { RunReference } from './published-results'
import { workspaceErrorMessage } from './project-workspace'

export function rememberedRun(projectId: string): RunReference | undefined {
  const url = new URL(window.location.href)
  if (url.searchParams.get('project') === projectId && url.searchParams.has('run')) return { project_id: url.searchParams.get('result_project') ?? projectId, run_id: url.searchParams.get('run')! }
  const saved = sessionStorage.getItem(`project-run:${projectId}`)
  return saved ? JSON.parse(saved) as RunReference : undefined
}

export function rememberRun(projectId: string, run?: RunReference) {
  if (run) sessionStorage.setItem(`project-run:${projectId}`, JSON.stringify(run))
  else sessionStorage.removeItem(`project-run:${projectId}`)
  const url = new URL(window.location.href)
  url.searchParams.set('project', projectId)
  url.searchParams.delete('run')
  url.searchParams.delete('result_project')
  if (run) {
    url.searchParams.set('run', run.run_id)
    if (run.project_id !== projectId) url.searchParams.set('result_project', run.project_id)
  }
  window.history.replaceState(null, '', url)
}

/** Project execution ownership is independent of the selected historical result. */
export function useProjectRunHistory(client: PublicV2Client, projectId?: string, latestRunId?: string) {
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision(value => value + 1), [])
  const [state, setState] = useState<{ projectId?: string; runs: ProjectRunSummary[]; loading: boolean; error?: string }>({ runs: [], loading: true })
  useEffect(() => {
    let current = true
    const sockets: WebSocket[] = []
    if (projectId) {
      void client.projectRuns(projectId).then(({ runs }) => {
        if (!current) return
        setState({ projectId, runs, loading: false })
        for (const run of runs.filter(item => ['admitted', 'running'].includes(item.status))) {
          const socket = client.runEvents(projectId, run.run_id)
          sockets.push(socket)
          let terminal = false
          socket.onmessage = message => {
            const envelope = JSON.parse(String(message.data)) as RunEventEnvelope
            if (envelope.event.type === 'run_terminal') { terminal = true; if (current) refresh() }
          }
          socket.onclose = () => {
            if (current && !terminal) setState(value => ({ ...value, error: '项目运行状态连接已断开，请重新读取。' }))
          }
        }
      }).catch(reason => { if (current) setState({ projectId, runs: [], loading: false, error: workspaceErrorMessage(reason) }) })
    }
    return () => { current = false; sockets.forEach(socket => socket.close()) }
  }, [client, projectId, latestRunId, revision, refresh])
  const loading = !!projectId && (state.projectId !== projectId || state.loading)
  const runs = state.projectId === projectId ? state.runs : []
  const error = state.projectId === projectId ? state.error : undefined
  return { runs, loading, error, refresh, active: !!projectId && (loading || !!error || runs.some(run => ['admitted', 'running'].includes(run.status))) }
}
