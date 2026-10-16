import type { RunDiagnostic } from './protocol/client'

export function RunDiagnostics({ errors, runDiagnostic, onFocus }: { errors: Record<string, RunDiagnostic>; runDiagnostic?: RunDiagnostic; onFocus: (nodeId: string) => void }) {
  const entries = Object.entries(errors)
  if (entries.length === 0 && !runDiagnostic) return null
  return <section className="run-diagnostics" aria-label="运行失败诊断">{runDiagnostic && <article>
    <h3>运行失败原因</h3><p role="alert">{runDiagnostic.message}</p>
    <details><summary>原始失败诊断</summary><pre>{JSON.stringify({ code: runDiagnostic.code, correlation_id: runDiagnostic.correlation_id, ...runDiagnostic.details }, null, 2)}</pre></details>
  </article>}{entries.map(([nodeId, error]) => <article key={nodeId}>
    <button onClick={() => onFocus(nodeId)}>定位节点 {nodeId}</button><p role="alert">{error.message}</p>
    <details><summary>失败来源与科学诊断</summary><pre>{JSON.stringify({ code: error.code, correlation_id: error.correlation_id, ...error.details }, null, 2)}</pre></details>
  </article>)}</section>
}
