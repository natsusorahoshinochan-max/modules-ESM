import { useEffect, useRef, useState } from 'react'
import type { PromptAuthoringDocument, PromptDocumentFunctionAnnotation, PromptMergeCorrespondence, PromptMergeSource, PromptMergeTarget, PromptDiagnostic, PromptSnapshot, PromptSourceMerge, PromptTrackAdoption, PromptTrackKey } from './protocol/client'

import { PromptMergeEvidence, type ManualMergeRow as Row } from './PromptMergeEvidence'

type DraftAdoption = Omit<PromptTrackAdoption, 'mask_policy'> & { mask_policy: '' | 'adopt' | 'preserve' }
export type PromptMergeDraft = {
  sourceIndex: number; editing?: number; rows: Row[]; adoptions: DraftAdoption[]
  adoptAnnotations: PromptDocumentFunctionAnnotation[]; removeAnnotations: PromptDocumentFunctionAnnotation[]
  submitted: string
}
type Props = {
  initialDraft?: PromptMergeDraft
  onDraftState: (draft: PromptMergeDraft) => void
  onDraftChange: (dirty: boolean) => void
  sources: PromptMergeSource[]
  projection: Pick<PromptSnapshot, 'residues' | 'tracks' | 'function_annotations' | 'merge_targets'>
  diagnostics: PromptDiagnostic[]
  onTargetSelection: (ids: string[]) => void
  document: PromptAuthoringDocument
  busy: boolean
  onPreview: (document: PromptAuthoringDocument, title: string) => void
}
const tracks: PromptTrackKey[] = ['sequence', 'coordinates', 'secondary_structure', 'sasa']
const tupleKey = (item: PromptDocumentFunctionAnnotation) => `${item.label}\u0000${item.start_residue_id}\u0000${item.end_residue_id}`

function annotationIntents(projection: Pick<PromptSnapshot, 'residues' | 'function_annotations'>) {
  const ids = new Map(projection.residues.map(item => [item.residue_handle, item.residue_id]))
  return projection.function_annotations.filter(item => item.state !== 'pending-delete').map(item => ({ label: item.label, start_residue_id: ids.get(item.start_residue_handle)!, end_residue_id: ids.get(item.end_residue_handle)! }))
}

export function PromptMergeEditor({ initialDraft, onDraftState, onDraftChange, sources, projection, document, busy, diagnostics, onTargetSelection, onPreview }: Props) {
  const [sourceIndex, setSourceIndex] = useState(initialDraft?.sourceIndex ?? 0)
  const [editing, setEditing] = useState<number | undefined>(initialDraft?.editing)
  const [rows, setRows] = useState<Row[]>(initialDraft?.rows ?? [])
  const [adoptions, setAdoptions] = useState<DraftAdoption[]>(initialDraft?.adoptions ?? [])
  const [adoptAnnotations, setAdoptAnnotations] = useState<PromptDocumentFunctionAnnotation[]>(initialDraft?.adoptAnnotations ?? [])
  const [removeAnnotations, setRemoveAnnotations] = useState<PromptDocumentFunctionAnnotation[]>(initialDraft?.removeAnnotations ?? [])
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [selectedSource, setSelectedSource] = useState<string[]>([])
  const [selectedTarget, setSelectedTarget] = useState<string[]>([])
  const [selectedRow, setSelectedRow] = useState<number>()
  const signature = JSON.stringify({ sourceIndex, editing, rows, adoptions, adoptAnnotations, removeAnnotations })
  const submitted = useRef(initialDraft?.submitted ?? signature)
  const callbacks = useRef({ onDraftState, onDraftChange })
  useEffect(() => { callbacks.current = { onDraftState, onDraftChange } })
  useEffect(() => {
    callbacks.current.onDraftState({ sourceIndex, editing, rows, adoptions, adoptAnnotations, removeAnnotations, submitted: submitted.current })
    callbacks.current.onDraftChange(signature !== submitted.current)
  }, [signature, sourceIndex, editing, rows, adoptions, adoptAnnotations, removeAnnotations])
  const [switchRequest, setSwitchRequest] = useState<(() => void) | null>(null)
  const switchDraft = (action: () => void) => { if (signature !== submitted.current) setSwitchRequest(() => action); else action() }
  const lastValidTargets = useRef<PromptMergeTarget[]>(projection.merge_targets)
  useEffect(() => { if (projection.merge_targets.length) lastValidTargets.current = projection.merge_targets }, [projection.merge_targets])
  const mergeIndex = editing === undefined || editing >= (document.source_merges?.length ?? 0) ? document.source_merges?.length ?? 0 : editing
  const targetStages = projection.merge_targets.length ? projection.merge_targets : lastValidTargets.current
  const targetStage = targetStages[mergeIndex]
  const source = sources[sourceIndex]
  const selectEvidence = (sourceIds: string[], targetIds: string[], row?: number) => {
    setSelectedSource(sourceIds); setSelectedTarget(targetIds); setSelectedRow(row)
    onTargetSelection(targetIds)
  }
  const adoptRegion = (track: PromptTrackKey, adopt: boolean) => setAdoptions(current => {
    const prior = current.find(item => item.track === track)
    const requested = new Set(adopt ? [...prior?.source_residue_ids ?? [], ...selectedSource] : (prior?.source_residue_ids ?? []).filter(id => !selectedSource.includes(id)))
    const ids = source.residues.filter(item => requested.has(item.residue_id)).map(item => item.residue_id)
    return [...current.filter(item => item.track !== track), ...(ids.length ? [{ track, source_residue_ids: ids, mask_policy: prior?.mask_policy ?? '' as const }] : [])]
  })
  const targetAnnotations = targetStage ? annotationIntents(targetStage) : []
  const targetResidues = targetStage?.residues.filter(item => item.state !== 'pending-delete') ?? []
  const updateRow = (index: number, value: Partial<Row>) => setRows(current => current.map((item, i) => i === index ? { ...item, ...value } : item))
  const load = (merge: PromptSourceMerge, index: number) => {
    submitted.current = JSON.stringify({ sourceIndex: merge.source_index, editing: index, rows: merge.correspondence.map(item => ({ source_residue_id: '', target_residue_id: '', ...item })), adoptions: merge.track_adoptions, adoptAnnotations: merge.adopt_annotations, removeAnnotations: merge.remove_annotations })
    setEditing(index); setSourceIndex(merge.source_index); selectEvidence([], [])
    setRows(merge.correspondence.map(item => ({ source_residue_id: '', target_residue_id: '', ...item })))
    setAdoptions(merge.track_adoptions); setAdoptAnnotations(merge.adopt_annotations); setRemoveAnnotations(merge.remove_annotations)
  }
  const newMerge = (index: number) => { submitted.current = JSON.stringify({ sourceIndex: index, rows: [], adoptions: [], adoptAnnotations: [], removeAnnotations: [] }); setSourceIndex(index); setEditing(undefined); setRows([]); setAdoptions([]); setAdoptAnnotations([]); setRemoveAnnotations([]); selectEvidence([], []) }
  const toggleTrack = (track: PromptTrackKey, residueId: string, selected: boolean) => setAdoptions(current => {
    const prior = current.find(item => item.track === track)
    const ids = selected ? [...prior?.source_residue_ids ?? [], residueId] : (prior?.source_residue_ids ?? []).filter(item => item !== residueId)
    return [...current.filter(item => item.track !== track), ...(ids.length ? [{ track, source_residue_ids: ids, mask_policy: prior?.mask_policy ?? '' as const }] : [])]
  })
  const toggleTuple = (items: PromptDocumentFunctionAnnotation[], tuple: PromptDocumentFunctionAnnotation, checked: boolean) => checked ? [...items, tuple] : items.filter(item => tupleKey(item) !== tupleKey(tuple))
  const preview = () => {
    const correspondence: PromptMergeCorrespondence[] = rows.map(item => item.disposition === 'source_gap' ? { disposition: item.disposition, source_residue_id: item.source_residue_id } : item.disposition === 'target_gap' ? { disposition: item.disposition, target_residue_id: item.target_residue_id } : { disposition: item.disposition, source_residue_id: item.source_residue_id, target_residue_id: item.target_residue_id })
    const merge: PromptSourceMerge = { source_index: sourceIndex, correspondence, track_adoptions: adoptions.map(item => ({ ...item, mask_policy: item.mask_policy as 'adopt' | 'preserve' })), adopt_annotations: adoptAnnotations, remove_annotations: removeAnnotations }
    const merges = [...document.source_merges ?? []]
    if (editing === undefined || editing >= merges.length) { setEditing(merges.length); merges.push(merge) } else merges[editing] = merge
    submitted.current = JSON.stringify({ sourceIndex, editing: editing === undefined || editing >= (document.source_merges?.length ?? 0) ? (document.source_merges?.length ?? 0) : editing, rows, adoptions, adoptAnnotations, removeAnnotations })
    onDraftChange(false)
    onDraftState({ sourceIndex, editing: editing ?? merges.length - 1, rows, adoptions, adoptAnnotations, removeAnnotations, submitted: submitted.current })
    onPreview({ ...document, source_merges: merges }, '手动来源合并 · 区域、Mask 与注释')
  }
  const previewEnabled = Boolean(targetStage) && rows.length > 0 && !adoptions.some(item => !item.mask_policy) && !rows.some(row => row.disposition !== 'target_gap' && !row.source_residue_id || row.disposition !== 'source_gap' && !row.target_residue_id)
  return <section className="ps-editor-section ps-merge-editor" aria-label="手动来源合并">
    {switchRequest && <div className="ps-help" role="alert">当前合并表尚未预览。<button onClick={() => setSwitchRequest(null)}>继续编辑当前表</button><button onClick={() => { switchRequest(); setSwitchRequest(null) }}>放弃表中修改并切换</button></div>}
    <span className="ps-kicker">MANUAL SOURCE MERGE</span>
    <p className="ps-help">添加来源后逐行明确对应；每个来源和原目标残基须按各自顺序出现一次。</p>
    {(document.source_merges ?? []).map((merge, index) => <div className="ps-action-row" key={index}><button onClick={() => switchDraft(() => load(merge, index))}>编辑合并 {index + 1} · Source {merge.source_index + 1}</button><button disabled={busy} onClick={() => { onPreview({ ...document, source_merges: document.source_merges!.filter((_, i) => i !== index) }, '移除合并意图'); newMerge(sourceIndex) }}>移除</button></div>)}
    {!sources.length ? <p className="ps-help">当前没有已连接的 ProteinPrompt 合并来源。</p> : <>
      <label>来源<select aria-label="合并来源" value={sourceIndex} onChange={event => { const index = Number(event.target.value); switchDraft(() => newMerge(index)) }}>{sources.map(item => <option key={item.source_index} value={item.source_index}>{item.source_index + 1} · {String(item.source.node_id)} / {String(item.source.port)}</option>)}</select></label>
      <button onClick={() => switchDraft(() => newMerge(sourceIndex))}>新建合并意图</button>
      <button disabled={!targetStage} onClick={() => setEvidenceOpen(true)}>打开来源 / 目标证据分屏</button>
      {!projection.merge_targets.length && <p role="status">当前预览无效；对应编辑显示上次有效预览的目标基线，修正后需重新预览。</p>}
      <small>Source digest: {String(source.source.content_digest)}</small>
      <div className="ps-merge-axis"><strong>来源有序残基</strong><p>{source.residues.map(item => `${item.residue_id} ${source.tracks.sequence.values.find(value => value.residue_handle === item.residue_handle)?.value ?? 'Mask'}`).join(' · ')}</p><strong>本次合并前目标残基</strong><p>{targetResidues.map(item => `${item.residue_id} ${targetStage?.tracks.sequence.values.find(value => value.residue_handle === item.residue_handle)?.value ?? 'Mask'}`).join(' · ')}</p></div>
      <ol className="ps-correspondence">{rows.map((row, index) => <li key={index} className={selectedRow === index ? 'selected' : ''}>
        <button aria-label={`定位对应 ${index + 1}`} onClick={() => selectEvidence(row.source_residue_id ? [row.source_residue_id] : [], row.target_residue_id ? [row.target_residue_id] : [], index)}>{index + 1}</button>
        <select aria-label={`对应 ${index + 1} 类型`} value={row.disposition} onChange={event => updateRow(index, { disposition: event.target.value as Row['disposition'] })}><option value="match">Match</option><option value="source_gap">Source gap</option><option value="target_gap">Target gap</option><option value="insert">Insert new target</option></select>
        {row.disposition !== 'target_gap' && <select aria-label={`对应 ${index + 1} 来源`} value={row.source_residue_id} onChange={event => updateRow(index, { source_residue_id: event.target.value })}><option value="">选择来源残基</option>{source.residues.map(item => <option key={item.residue_id}>{item.residue_id}</option>)}</select>}
        {row.disposition === 'insert' ? <input aria-label={`对应 ${index + 1} 新增目标`} placeholder="A:new.identity" value={row.target_residue_id} onChange={event => updateRow(index, { target_residue_id: event.target.value })} /> : row.disposition !== 'source_gap' && <select aria-label={`对应 ${index + 1} 目标`} value={row.target_residue_id} onChange={event => updateRow(index, { target_residue_id: event.target.value })}><option value="">选择目标残基</option>{targetResidues.map(item => <option key={item.residue_id}>{item.residue_id}</option>)}</select>}
        <button aria-label={`上移对应 ${index + 1}`} disabled={index === 0} onClick={() => setRows(current => { const next = [...current]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next })}>↑</button><button aria-label={`删除对应 ${index + 1}`} onClick={() => setRows(current => current.filter((_, i) => i !== index))}>×</button>
      </li>)}</ol>
      <button onClick={() => setRows(current => [...current, { disposition: 'match', source_residue_id: '', target_residue_id: '' }])}>添加手动对应行</button>
      <div className="ps-merge-track-table"><table><thead><tr><th>采用来源残基</th>{tracks.map(track => <th key={track}>{track}</th>)}</tr></thead><tbody>{source.residues.map(residue => <tr key={residue.residue_id}><th>{residue.residue_id}</th>{tracks.map(track => {
        const value = source.tracks[track].values.find(item => item.residue_handle === residue.residue_handle)?.value
        const mapping = rows.find(row => row.source_residue_id === residue.residue_id && (row.disposition === 'match' || row.disposition === 'insert'))
        const target = mapping && targetResidues.find(item => item.residue_id === mapping.target_residue_id)
        const previous = target && targetStage?.tracks[track].values.find(item => item.residue_handle === target.residue_handle)?.value
        const shown = (value: unknown) => value === null || value === undefined ? 'Mask' : typeof value === 'object' ? 'Atoms' : String(value)
        return <td key={track}><label><input type="checkbox" aria-label={`采用 ${residue.residue_id} ${track}`} disabled={!source.tracks[track].present} checked={adoptions.some(item => item.track === track && item.source_residue_ids.includes(residue.residue_id))} onChange={event => toggleTrack(track, residue.residue_id, event.target.checked)} />{!source.tracks[track].present ? 'Absent' : shown(value)}</label><small>{mapping ? `目标 ${mapping.target_residue_id}: ${shown(previous)}` : '未对应'}</small></td>
      })}</tr>)}</tbody></table></div>
      {adoptions.map(adoption => <label key={adoption.track}>{adoption.track} · 来源 Mask<select aria-label={`${adoption.track} Mask 处理`} value={adoption.mask_policy} onChange={event => setAdoptions(current => current.map(item => item.track === adoption.track ? { ...item, mask_policy: event.target.value as DraftAdoption['mask_policy'] } : item))}><option value="">明确选择 Mask 处理</option><option value="preserve">保留目标值</option><option value="adopt">明确清除目标值</option></select></label>)}
      <strong>采用完整来源 annotations</strong>{annotationIntents(source).map(item => <label key={tupleKey(item)}><input type="checkbox" checked={adoptAnnotations.some(value => tupleKey(value) === tupleKey(item))} onChange={event => setAdoptAnnotations(toggleTuple(adoptAnnotations, item, event.target.checked))} />{item.label} · {item.start_residue_id}–{item.end_residue_id}</label>)}
      <strong>明确移除目标基线 annotations</strong>{targetAnnotations.map(item => <label key={tupleKey(item)}><input type="checkbox" checked={removeAnnotations.some(value => tupleKey(value) === tupleKey(item))} onChange={event => setRemoveAnnotations(toggleTuple(removeAnnotations, item, event.target.checked))} />{item.label} · {item.start_residue_id}–{item.end_residue_id}</label>)}
      <p className="ps-help">新增残基先为 Mask；仅采用所勾选轨道。区间不连续或不完整的 annotation 会在预览中报错。</p>
      <button disabled={busy || !previewEnabled} onClick={preview}>预览区域合并</button>
      {evidenceOpen && targetStage && <PromptMergeEvidence source={source} target={targetStage} result={projection} rows={rows} selectedSource={selectedSource} selectedTarget={selectedTarget} selectedRow={selectedRow} adoptions={adoptions} adoptAnnotations={adoptAnnotations} removeAnnotations={removeAnnotations} onSelection={selectEvidence} onInsert={(added, position) => { setRows(current => [...current.slice(0, position), ...added, ...current.slice(position)]); setSelectedRow(position) }} onRegion={adoptRegion} onMaskPolicy={(track, policy) => setAdoptions(current => current.map(item => item.track === track ? { ...item, mask_policy: policy } : item))} onPreview={preview} previewEnabled={previewEnabled} busy={busy} diagnostics={diagnostics} onClose={() => setEvidenceOpen(false)} />}
    </>}
  </section>
}
