import { useState } from 'react'
import type { RunScopePreview, RunScopeRequest } from './protocol/client'
import './run-session.css'
import { InteractionDialog } from './InteractionDialog'

export type PreparedRun = { projectId: string; request: RunScopeRequest; preview: RunScopePreview }

export function RunDialog({ selectedNodeIds, sourceRunId, onClose, onPrepare, onStart, onFocus }: {
  selectedNodeIds: string[]
  sourceRunId?: string
  onClose: () => void
  onPrepare: (request: RunScopeRequest) => Promise<PreparedRun>
  onStart: (prepared: PreparedRun) => Promise<void>
  onFocus: (nodeId: string) => void
}) {
  const [mode, setMode] = useState<RunScopeRequest['mode']>('full')
  const [prepared, setPrepared] = useState<PreparedRun>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const labels = { full: '完整流程', to_node: '运行到所选节点', from_node: '从所选节点继续' }
  const request: RunScopeRequest = { mode, node_ids: mode === 'full' ? [] : selectedNodeIds, ...(mode === 'from_node' ? { source_run_id: sourceRunId } : {}) }
  const unavailable = (mode !== 'full' && selectedNodeIds.length === 0) || (mode === 'from_node' && !sourceRunId)
  const perform = async (work: () => Promise<void>) => { setBusy(true); setError(''); try { await work() } catch (reason) { setError(reason instanceof Error ? reason.message : JSON.stringify(reason)) } finally { setBusy(false) } }
  return <InteractionDialog className="run-dialog run-scope-dialog" title="确认运行范围" busy={busy} onClose={onClose}>
    <header><h2>确认运行范围</h2><button onClick={onClose} disabled={busy}>关闭</button></header>
    <div className="run-mode-choices">{(['full', 'to_node', 'from_node'] as const).map((value) => <label key={value}><input type="radio" name="run-scope" value={value} checked={mode === value} disabled={busy} onChange={() => { setMode(value); setPrepared(undefined) }} />{labels[value]}</label>)}</div>
    {mode !== 'full' && <p>画布选中：{selectedNodeIds.join('、') || '请先选择节点'}</p>}
    {mode === 'from_node' && <p>仅执行选中节点及其后代，全部强制重算；范围外上游只复用。缺少匹配的上游结果会拒绝启动。{!sourceRunId && '当前项目尚无可用的结束 Run。'}</p>}
    <button disabled={busy || unavailable} onClick={() => void perform(async () => setPrepared(await onPrepare(request)))}>{busy ? '处理中…' : '准备并查看范围'}</button>
    {error && <pre role="alert">{error}</pre>}
    {prepared && <div className="run-scope-preview"><p>固定流程版本：<code>{prepared.preview.workflow_commit_id}</code></p><div className="scope-counts"><span>执行 {prepared.preview.scope.execution_node_ids.length}</span><span>强制重算 {prepared.preview.scope.forced_node_ids.length}</span><span>仅复用 {prepared.preview.scope.reused_node_ids.length}</span><span>范围外 {prepared.preview.scope.out_of_scope_node_ids.length}</span></div>
      <p>以下为实际执行配置；模型是否可调用将在执行时检查。</p>
      {prepared.preview.blockers.map((blocker, index) => <p className="scope-blocker" role="alert" key={index}>{blocker.node_id && <button onClick={() => { onFocus(blocker.node_id!); onClose() }}>{blocker.node_id}</button>}{blocker.message}</p>)}
      {prepared.preview.nodes.map((node) => <details key={node.node_id}><summary>{node.action === 'reuse' ? '仅复用' : prepared.preview.scope.forced_node_ids.includes(node.node_id) ? '强制重算' : '执行'} · {node.node_id} · {node.method.contract_id}</summary><dl><dt>执行模型</dt><dd>{node.binding.contract_id}</dd><dt>节点参数</dt><dd><pre>{JSON.stringify(node.node_parameters, null, 2)}</pre></dd><dt>模型参数</dt><dd><pre>{JSON.stringify(node.binding_parameters, null, 2)}</pre></dd><dt>实际随机参数</dt><dd>{node.randomness_status === 'resolved' ? <pre>{JSON.stringify(node.effective_randomness, null, 2)}</pre> : '待上游输出后确定；不会隐式更换 seed'}</dd></dl></details>)}
      <footer><button onClick={onClose} disabled={busy}>取消</button><button className="primary-button" disabled={busy || prepared.preview.blockers.length > 0} onClick={() => void perform(() => onStart(prepared))}>开始运行已确认范围</button></footer>
    </div>}
  </InteractionDialog>
}
