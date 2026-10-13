import type { RunDiagnostic } from './protocol/client'

export function RunDiagnostics({ errors, onFocus }: { errors: Record<string, RunDiagnostic>; onFocus: (nodeId: string) => void }) {
  const entries = Object.entries(errors)
  if (entries.length === 0) return null
  return <section className="run-diagnostics" aria-label="运行失败诊断">{entries.map(([nodeId, error]) => <article key={nodeId}>
    <button onClick={() => onFocus(nodeId)}>定位节点 {nodeId}</button><p role="alert">{error.message}</p>
    <details><summary>失败来源与科学诊断</summary><pre>{JSON.stringify({ code: error.code, correlation_id: error.correlation_id, ...error.details }, null, 2)}</pre></details>
  </article>)}</section>
}
