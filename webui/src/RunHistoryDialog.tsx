import './run-history.css'
import { InteractionDialog } from './InteractionDialog'
import type { ProjectRunSummary, RunProjection } from './protocol/client'

export function RunHistoryDialog({ runs, loading, error, selected, onOpen, onRefresh, onClose }: {
  runs: ProjectRunSummary[]; loading: boolean; error?: string; selected?: RunProjection
  onOpen: (runId: string) => void; onRefresh: () => void; onClose: () => void
}) {
  return <InteractionDialog title="项目运行历史" className="run-dialog run-history-dialog" onClose={onClose}>
    <header><h2>项目运行历史</h2><button onClick={onClose}>关闭</button></header>
    <p>选择一次运行，查看该次运行的状态与已保留结果。</p>
    <button onClick={onRefresh}>刷新运行列表</button>
    {loading && <p role="status">正在读取运行历史…</p>}
    {error && <p role="alert">{error}</p>}
    {!loading && !error && runs.length === 0 && <p>此项目尚无运行。</p>}
    <ul className="run-history-list">{runs.map(run => <li key={run.run_id}>
      <code>{run.run_id}</code>{run.availability === 'unavailable' ? <p role="status">运行记录不可读取；无法确定其状态及保留结果。</p> : <><p>{run.status} · {run.has_results ? '有保留结果' : '无保留结果'}</p>
      <small>流程提交：{run.workflow_commit_id}</small></>}
      <button aria-current={selected?.run_id === run.run_id ? 'true' : undefined} onClick={() => onOpen(run.run_id)}>打开运行</button>
    </li>)}</ul>
    {selected && <section aria-label="选中运行状态"><h3>{selected.run_id}</h3><p>{selected.status}</p>
      <ul>{selected.node_dispositions.map(item => <li key={item.node_id}>{item.node_id} · {item.outcome}</li>)}</ul>
    </section>}
  </InteractionDialog>
}
