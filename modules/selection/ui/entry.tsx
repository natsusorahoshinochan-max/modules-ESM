import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { workspaceErrorMessage } from '../../../webui/src/project-workspace'
import { SelectionEditor } from './SelectionEditor'
import { candidateResults } from '../../protein_io/ui/candidate-results'
import type { ModuleEditorProps } from '../../../webui/src/module-ui'
import type { RunProjection } from '../../../webui/src/protocol/client'

function Editor({ onApply, results, client, ...props }: ModuleEditorProps) {
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [load, setLoad] = useState<{ run?: RunProjection; phase: 'loading' | 'ready' | 'error'; error?: string }>({ phase: 'loading' })
  const reading = useMemo(() => candidateResults(results, client), [results, client])
  const published = useSyncExternalStore(results.subscribe, results.getSnapshot)
  const snapshot = useSyncExternalStore(reading.subscribe, reading.getSnapshot)
  const run = snapshot.run
  useEffect(() => {
    if (!run) return
    let cancelled = false
    setLoad({ run, phase: 'loading' })
    void (async () => {
      try {
        if (retry > 0) await reading.refresh()
        const complete = await reading.ensureCandidates({ all: true })
        if (!cancelled && complete) setLoad({ run, phase: 'ready' })
      } catch (reason) {
        if (!cancelled) setLoad({ run, phase: 'error', error: workspaceErrorMessage(reason) })
      }
    })()
    return () => { cancelled = true }
  }, [reading, run, retry])
  const readError = published.phase === 'error' ? workspaceErrorMessage(published.error) : load.run === run && load.phase === 'error' ? load.error : undefined
  if (readError) return <div role="alert">候选读取失败：{readError}<button onClick={() => { if (published.phase === 'error') void results.refresh(); setRetry(value => value + 1) }}>重新读取</button><button onClick={props.onCancel}>取消</button></div>
  if (published.phase !== 'idle' && (!run || load.run !== run || load.phase !== 'ready')) return <div role="status">正在读取候选…<button onClick={props.onCancel}>取消</button></div>
  return <>{error && <p role="alert">{error}</p>}<SelectionEditor {...props} candidateCollections={snapshot.index.collections} onChange={next => { setError(''); void onApply(next).catch(reason => setError(workspaceErrorMessage(reason))) }} /></>
}

export function register() {
  return { SelectionEditor: Editor }
}
