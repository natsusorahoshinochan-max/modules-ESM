import { InteractionDialog } from './InteractionDialog'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { PromptDiagnostic, PromptDocumentFunctionAnnotation, PromptTrackAdoption, PromptMergeSource, PromptMergeTarget, PromptSnapshot, PromptTrackKey } from './protocol/client'
import { StructureViewer } from './StructureViewer'
import { promptStructurePdb } from './prompt-structure'

export type ManualMergeRow = { disposition: 'match' | 'insert' | 'source_gap' | 'target_gap'; source_residue_id: string; target_residue_id: string }
type Projection = Pick<PromptSnapshot, 'residues' | 'tracks' | 'function_annotations'>
type PickEvent = { toggle: boolean; range: boolean }
type Props = {
  source: PromptMergeSource
  target: PromptMergeTarget
  result: Projection
  rows: ManualMergeRow[]
  selectedSource: string[]
  selectedTarget: string[]
  selectedRow: number | undefined
  adoptions: (Omit<PromptTrackAdoption, 'mask_policy'> & { mask_policy: '' | 'adopt' | 'preserve' })[]
  adoptAnnotations: PromptDocumentFunctionAnnotation[]
  removeAnnotations: PromptDocumentFunctionAnnotation[]
  onSelection: (source: string[], target: string[], row?: number) => void
  onInsert: (rows: ManualMergeRow[], position: number) => void
  onRegion: (track: PromptTrackKey, adopt: boolean) => void
  onPreview: () => void
  onMaskPolicy: (track: PromptTrackKey, policy: 'adopt' | 'preserve') => void
  previewEnabled: boolean
  busy: boolean
  diagnostics: PromptDiagnostic[]
  onClose: () => void
}
const tracks: PromptTrackKey[] = ['sequence', 'coordinates', 'secondary_structure', 'sasa']

export function PromptMergeEvidence({ source, target, result, rows, selectedSource, selectedTarget, selectedRow, adoptions, adoptAnnotations, removeAnnotations, onSelection, onInsert, onRegion, onMaskPolicy, onPreview, previewEnabled, busy, diagnostics, onClose }: Props) {
  const [sourceAnchor, setSourceAnchor] = useState('')
  const [targetAnchor, setTargetAnchor] = useState('')
  const [insertAt, setInsertAt] = useState<'start' | 'selected' | 'end'>('end')
  const [showResult, setShowResult] = useState(false)
  const [newTargetId, setNewTargetId] = useState('')
  const dialog = useRef<HTMLElement>(null)
  useEffect(() => {
    for (const [attribute, ids] of [['data-merge-source', selectedSource], ['data-merge-target', selectedTarget]] as const) {
      const selected = Array.from(dialog.current?.querySelectorAll<HTMLElement>(`[${attribute}]`) ?? []).find(element => ids.includes(element.getAttribute(attribute)!))
      selected?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    }
  }, [selectedSource, selectedTarget])
  const sourcePdb = useMemo(() => promptStructurePdb(source), [source])
  const targetPdb = useMemo(() => promptStructurePdb(target), [target])
  const resultPdb = useMemo(() => promptStructurePdb(result), [result])
  const sourceResidues = source.residues.filter(item => item.state !== 'pending-delete')
  const targetResidues = target.residues.filter(item => item.state !== 'pending-delete')
  const resultResidues = result.residues.filter(item => item.state !== 'pending-delete')
  const insertPosition = insertAt === 'start' ? 0 : insertAt === 'selected' && selectedRow !== undefined ? selectedRow + 1 : rows.length
  const choose = (side: 'source' | 'target', id: string, event: PickEvent) => {
    const axis = side === 'source' ? sourceResidues : targetResidues
    const selected = side === 'source' ? selectedSource : selectedTarget
    const anchor = side === 'source' ? sourceAnchor : targetAnchor
    const from = axis.findIndex(item => item.residue_id === anchor), to = axis.findIndex(item => item.residue_id === id)
    const next = event.range && from >= 0 ? axis.slice(Math.min(from, to), Math.max(from, to) + 1).map(item => item.residue_id) : event.toggle ? selected.includes(id) ? selected.filter(item => item !== id) : [...selected, id] : [id]
    if (side === 'source') {
      if (!event.range) setSourceAnchor(id)
      const counterparts = rows.filter(row => next.includes(row.source_residue_id) && row.disposition === 'match').map(row => row.target_residue_id)
      const rowIndex = rows.findIndex(row => row.source_residue_id === id)
      const previouslyLinked = rows.filter(row => selectedSource.includes(row.source_residue_id) && row.disposition === 'match').map(row => row.target_residue_id)
      onSelection(next, counterparts.length ? counterparts : selectedTarget.filter(id => !previouslyLinked.includes(id)), next.length === 1 && rowIndex >= 0 ? rowIndex : undefined)
    } else {
      if (!event.range) setTargetAnchor(id)
      const counterparts = rows.filter(row => next.includes(row.target_residue_id) && row.disposition === 'match').map(row => row.source_residue_id)
      const rowIndex = rows.findIndex(row => row.target_residue_id === id)
      const previouslyLinked = rows.filter(row => selectedTarget.includes(row.target_residue_id) && row.disposition === 'match').map(row => row.source_residue_id)
      onSelection(counterparts.length ? counterparts : selectedSource.filter(id => !previouslyLinked.includes(id)), next, next.length === 1 && rowIndex >= 0 ? rowIndex : undefined)
    }
  }
  const positions = (projection: Projection, selected: string[]) => projection.residues.filter(item => item.state !== 'pending-delete' && selected.includes(item.residue_id)).map(item => ({ chain: item.chain_id, resi: item.position }))
  const sourceSequence = new Map(source.tracks.sequence.values.map(item => [item.residue_handle, typeof item.value === 'string' ? item.value : 'Mask']))
  const targetSequence = new Map(target.tracks.sequence.values.map(item => [item.residue_handle, typeof item.value === 'string' ? item.value : 'Mask']))
  const resultSequence = new Map(result.tracks.sequence.values.map(item => [item.residue_handle, typeof item.value === 'string' ? item.value : 'Mask']))
  const firstPair = rows.findIndex(row => row.disposition === 'match' || row.disposition === 'insert')
  const lastPair = rows.reduce((last, row, index) => row.disposition === 'match' || row.disposition === 'insert' ? index : last, -1)
  const leading = firstPair < 0 ? rows : rows.slice(0, firstPair)
  const trailing = lastPair < 0 ? [] : rows.slice(lastPair + 1)
  const gapCount = (list: ManualMergeRow[], disposition: ManualMergeRow['disposition']) => list.filter(row => row.disposition === disposition).length
  const valueAt = (projection: Projection, track: PromptTrackKey, id: string) => {
    const residue = projection.residues.find(item => item.residue_id === id && item.state !== 'pending-delete')
    return { present: Boolean(residue && projection.tracks[track].present), value: residue && projection.tracks[track].values.find(item => item.residue_handle === residue.residue_handle)?.value }
  }
  const shown = (cell: ReturnType<typeof valueAt>) => !cell.present ? 'Absent' : cell.value == null ? 'Mask' : typeof cell.value === 'object' ? JSON.stringify(cell.value) : String(cell.value)
  const impact = adoptions.flatMap(adoption => adoption.source_residue_ids.map(sourceId => {
    const row = rows.find(item => item.source_residue_id === sourceId && (item.disposition === 'match' || item.disposition === 'insert'))
    const from = valueAt(source, adoption.track, sourceId)
    const prior = valueAt(target, adoption.track, row?.target_residue_id ?? '')
    const action = !row ? '缺少明确对应' : !adoption.mask_policy ? '待明确 Mask 处理' : from.value == null && adoption.mask_policy === 'preserve' ? '来源 Mask：保留目标' : from.value == null ? '明确清除目标' : '采用来源值'
    return { track: adoption.track, sourceId, row, from, prior, action }
  }))
  return <InteractionDialog title="来源 / 目标证据分屏" className="ps-evidence-dialog" onClose={onClose}><section ref={dialog} onPaste={event => event.stopPropagation()}>
    <header><div><span className="ps-kicker">MANUAL CORRESPONDENCE</span><h2 id="merge-evidence-title">来源 / 目标证据分屏</h2></div><button aria-label="关闭合并分屏" onClick={onClose}>返回编辑</button></header>
    <p className="ps-help">点击残基或三维位置定位；Ctrl/⌘ 多选、Shift 选择范围。仅既有 Match 行同步对应高亮；新对应须点击明确匹配。镜头独立，不做自动对齐。</p>
    <div className="ps-evidence-panes">
      <section aria-label="合并来源证据"><h3>来源 {source.source_index + 1} · {String(source.source.node_id)}</h3><small>{String(source.source.content_digest)}</small><StructureViewer pdb={sourcePdb} selectedResidues={positions(source, selectedSource)} onSelectResidue={picked => { const residue = sourceResidues.find(item => item.chain_id === picked.chain && item.position === picked.resi); if (residue) choose('source', residue.residue_id, picked) }} /><div className="ps-evidence-sequence">{sourceResidues.map(item => <button key={item.residue_id} data-merge-source={item.residue_id} aria-label={`来源残基 ${item.residue_id}`} className={selectedSource.includes(item.residue_id) ? 'selected' : ''} onClick={event => choose('source', item.residue_id, { toggle: event.ctrlKey || event.metaKey, range: event.shiftKey })}><strong>{sourceSequence.get(item.residue_handle) ?? 'Mask'}</strong><small>{item.residue_id}</small></button>)}</div></section>
      <section aria-label="合并目标证据"><h3>{showResult ? '当前后端结果' : `合并 ${target.merge_index + 1} 前的目标基线`}</h3><label className="ps-evidence-result-toggle"><input type="checkbox" checked={showResult} onChange={event => setShowResult(event.target.checked)} />查看当前后端结果（编辑意图始终引用目标基线）</label><StructureViewer pdb={showResult ? resultPdb : targetPdb} selectedResidues={positions(showResult ? result : target, selectedTarget)} onSelectResidue={picked => { const residue = targetResidues.find(item => item.chain_id === picked.chain && item.position === picked.resi); if (!showResult && residue) choose('target', residue.residue_id, picked) }} /><div className="ps-evidence-sequence">{(showResult ? resultResidues : targetResidues).map(item => <button key={item.residue_id} data-merge-target={item.residue_id} aria-label={`目标残基 ${item.residue_id}`} disabled={showResult} className={selectedTarget.includes(item.residue_id) ? 'selected' : ''} onClick={event => choose('target', item.residue_id, { toggle: event.ctrlKey || event.metaKey, range: event.shiftKey })}><strong>{(showResult ? resultSequence : targetSequence).get(item.residue_handle) ?? 'Mask'}</strong><small>{item.residue_id}</small></button>)}</div></section>
    </div>
    <div className="ps-evidence-tools"><strong>来源选区 {selectedSource.length} · 目标选区 {selectedTarget.length}</strong><label>新增行位置<select aria-label="对应新增行位置" value={insertAt} onChange={event => setInsertAt(event.target.value as typeof insertAt)}><option value="start">最前（首端 gap）</option><option value="selected" disabled={selectedRow === undefined}>当前对应行之后</option><option value="end">最后（尾端 gap）</option></select></label><button disabled={selectedSource.length !== 1 || selectedTarget.length !== 1} onClick={() => onInsert([{ disposition: 'match', source_residue_id: selectedSource[0], target_residue_id: selectedTarget[0] }], insertPosition)}>明确匹配这两个残基</button><button disabled={!selectedSource.length} onClick={() => onInsert(sourceResidues.filter(item => selectedSource.includes(item.residue_id)).map(item => ({ disposition: 'source_gap', source_residue_id: item.residue_id, target_residue_id: '' })), insertPosition)}>所选来源设为 Source gap</button><button disabled={!selectedTarget.length} onClick={() => onInsert(targetResidues.filter(item => selectedTarget.includes(item.residue_id)).map(item => ({ disposition: 'target_gap', source_residue_id: '', target_residue_id: item.residue_id })), insertPosition)}>所选目标设为 Target gap</button><label>新增目标身份<input aria-label="分屏新增目标身份" placeholder="A:new.identity" value={newTargetId} onChange={event => setNewTargetId(event.target.value)} /></label><button disabled={selectedSource.length !== 1 || !newTargetId} onClick={() => onInsert([{ disposition: 'insert', source_residue_id: selectedSource[0], target_residue_id: newTargetId }], insertPosition)}>插入所选来源为新目标残基</button></div>
    <div className="ps-evidence-region"><strong>来源区域采用范围：{selectedSource.join(', ') || '未选择'}</strong>{tracks.map(track => <div key={track} data-merge-track={track}><span>{track}</span><button disabled={!selectedSource.length || !source.tracks[track].present} onClick={() => onRegion(track, true)}>采用所选区域</button><button disabled={!selectedSource.length} onClick={() => onRegion(track, false)}>保留目标区域</button></div>)}{adoptions.map(adoption => <label key={adoption.track}>{adoption.track} · Mask 处理<select aria-label={`分屏 ${adoption.track} Mask 处理`} value={adoption.mask_policy} onChange={event => onMaskPolicy(adoption.track, event.target.value as 'adopt' | 'preserve')}><option value="" disabled>明确选择</option><option value="preserve">保留目标值</option><option value="adopt">明确清除目标值</option></select></label>)}<p className="ps-help">采用范围精确到来源残基 × 轨道；gap 不自动采用。Mask 策略只影响选定轨道与区域。</p></div>
    <div className="ps-evidence-correspondence"><strong>明确对应表 · {rows.length} 行 · 首端 source / target gap {gapCount(leading, 'source_gap')} / {gapCount(leading, 'target_gap')} · 尾端 source / target gap {gapCount(trailing, 'source_gap')} / {gapCount(trailing, 'target_gap')}</strong><div>{rows.map((row, index) => <button key={index} className={selectedRow === index || Boolean(row.source_residue_id && selectedSource.includes(row.source_residue_id) || row.target_residue_id && selectedTarget.includes(row.target_residue_id)) ? 'selected' : ''} onClick={() => onSelection(row.source_residue_id ? [row.source_residue_id] : [], row.target_residue_id ? [row.target_residue_id] : [], index)}><span>{index + 1}</span><strong>{row.source_residue_id || '—'}</strong><span>{row.disposition}</span><strong>{row.target_residue_id || '—'}</strong></button>)}</div></div>
    <section className="ps-evidence-impact" aria-label="区域采用影响"><h3>区域采用影响 · {impact.length} 个残基轨道单元</h3><p className="ps-help">目标旧值来自后端该合并前的科学投影；下面列出当前编辑意图。点击预览后，完整结果还会包含后续合并、手动覆盖、变换和随机操作。</p><table><thead><tr><th>来源 → 目标</th><th>轨道</th><th>目标旧值</th><th>来源值</th><th>本次处理</th></tr></thead><tbody>{impact.map(item => <tr key={`${item.track}:${item.sourceId}`}><th>{item.sourceId} → {item.row?.target_residue_id ?? '未对应'}{item.row?.disposition === 'insert' && '（新增）'}</th><td>{item.track}</td><td>{shown(item.prior)}</td><td>{shown(item.from)}</td><td>{item.action}</td></tr>)}</tbody></table><p>明确新增残基 {rows.filter(row => row.disposition === 'insert').length}；采用完整注释 {adoptAnnotations.length}；移除目标注释 {removeAnnotations.length}。</p>{adoptAnnotations.map(item => <p key={`adopt:${item.label}:${item.start_residue_id}:${item.end_residue_id}`}>采用来源注释：{item.label} · {item.start_residue_id}–{item.end_residue_id}（后端须确认整个区间连续对应）</p>)}{removeAnnotations.map(item => <p key={`remove:${item.label}:${item.start_residue_id}:${item.end_residue_id}`}>移除目标注释：{item.label} · {item.start_residue_id}–{item.end_residue_id}</p>)}</section>
    {diagnostics.length > 0 && <ul role="alert">{diagnostics.map((item, index) => <li key={index}>{item.message}</li>)}</ul>}
    <footer><span>采用前后值在主编辑器逐轨显示。确认后的整组修改支持撤销。</span><button disabled={busy || !previewEnabled} onClick={onPreview}>预览全部合并意图</button><button onClick={onClose}>返回轨道决策与确认</button></footer>
  </section></InteractionDialog>
}
