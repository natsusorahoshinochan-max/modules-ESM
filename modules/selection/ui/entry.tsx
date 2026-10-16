import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { workspaceErrorMessage } from '../../../webui/src/project-workspace'
import { SelectionEditor } from './SelectionEditor'
import { candidateResults } from '../../protein_io/ui/candidate-results'
import type { ModuleEditorProps } from '../../../webui/src/module-ui'

function Editor({ onApply, results, client, ...props }: ModuleEditorProps) {
  const [error, setError] = useState('')
  const reading = useMemo(() => candidateResults(results, client), [results, client])
  const snapshot = useSyncExternalStore(reading.subscribe, reading.getSnapshot)
  useEffect(() => {
    if (results.getSnapshot().phase !== 'idle') void reading.ensureCandidates({ all: true })
  }, [reading, results])
  if (snapshot.phase === 'error') return <div role="alert">候选读取失败。<button onClick={() => void reading.ensureCandidates({ all: true })}>重新读取</button><button onClick={props.onCancel}>取消</button></div>
  if (snapshot.phase === 'loading') return <div role="status">正在读取候选…<button onClick={props.onCancel}>取消</button></div>
  return <>{error && <p role="alert">{error}</p>}<SelectionEditor {...props} candidateCollections={snapshot.index.collections} onChange={next => { setError(''); void onApply(next).catch(reason => setError(workspaceErrorMessage(reason))) }} /></>
}

export function register() {
  return { SelectionEditor: Editor }
}
