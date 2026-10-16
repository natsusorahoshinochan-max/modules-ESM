import { useCallback, useEffect, useState } from 'react'
import type { PublicV2Client, ProjectExecutionState, ProjectRunSummary, RunEventEnvelope } from './protocol/client'
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

/** History availability does not determine project execution ownership. */
export function useProjectRunHistory(client: PublicV2Client, projectId?: string, latestRunId?: string | null) {
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision(value => value + 1), [])
  const [state, setState] = useState<{ projectId?: string; runs: ProjectRunSummary[]; error?: string }>({ runs: [] })
  useEffect(() => {
    let current = true
    if (projectId) {
      void client.projectRuns(projectId).then(({ runs }) => {
        if (current) setState({ projectId, runs })
      }).catch(reason => { if (current) setState({ projectId, runs: [], error: workspaceErrorMessage(reason) }) })
    }
    return () => { current = false }
  }, [client, projectId, latestRunId, revision])
  return {
    runs: state.projectId === projectId ? state.runs : [],
    loading: !!projectId && state.projectId !== projectId,
    error: state.projectId === projectId ? state.error : undefined,
    refresh,
  }
}

/** Keep actual execution ownership separate from the Run selected for viewing. */
export function useProjectExecution(client: PublicV2Client, projectId: string | undefined, latestRunId: string | null | undefined, onTerminal: () => void) {
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision(value => value + 1), [])
  const [state, setState] = useState<{ projectId?: string; execution?: ProjectExecutionState; error?: string }>({})
  useEffect(() => {
    let current = true
    const sockets: WebSocket[] = []
    if (projectId) {
      void client.projectExecutionState(projectId).then(execution => {
        if (!current) return
        setState({ projectId, execution })
        for (const runId of execution.active_run_ids) {
          const socket = client.runEvents(projectId, runId)
          sockets.push(socket)
          let terminal = false
          socket.onmessage = message => {
            const envelope = JSON.parse(String(message.data)) as RunEventEnvelope
            if (envelope.event.type === 'run_terminal') {
              terminal = true
              if (current) { refresh(); onTerminal() }
            }
          }
          socket.onclose = () => {
            if (current && !terminal) setState(value => ({ ...value, error: '项目运行状态连接已断开，请重新读取。' }))
          }
        }
      }).catch(reason => {
        if (current) setState(value => ({
          projectId,
          execution: value.projectId === projectId ? value.execution : undefined,
          error: workspaceErrorMessage(reason),
        }))
      })
    }
    return () => { current = false; sockets.forEach(socket => socket.close()) }
  }, [client, projectId, latestRunId, revision, refresh, onTerminal])
  const started = useCallback((owner: string, runId: string) => {
    if (owner !== projectId) return
    setState({ projectId: owner, execution: { project_id: owner, active_run_ids: [runId], reserved: false } })
    refresh()
  }, [projectId, refresh])
  const execution = state.projectId === projectId ? state.execution : undefined
  return {
    active: !!execution && (execution.reserved || execution.active_run_ids.length > 0),
    editable: !!execution && !execution.reserved && execution.active_run_ids.length === 0,
    reserved: execution?.reserved ?? false,
    started,
    loading: !!projectId && !execution && !(state.projectId === projectId && state.error),
    error: state.projectId === projectId ? state.error : undefined,
    refresh,
  }
}
