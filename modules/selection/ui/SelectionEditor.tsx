import { useState } from 'react'
import type { CandidateReference, CatalogSnapshot, ResultCandidate, Workflow } from '../../../webui/src/protocol/client'
import { candidateReferenceKey, newObservation, readSelectionDraft, saveSelectionDraft, selectionSources, sourceKey, type SelectionDraft, type SelectionOperation, type SelectionSource } from './selection-authoring'
import { effectiveWeightPercentages, observationOptionKey } from './selection-observations'
import './selection-editor.css'
import { ObservationEditor, ScalarField, SourcePicker } from './SelectionObservationEditor'
import { ConditionEditor } from './ConditionEditor'
import { ObservationContextEditor, type ScoreObservationReading } from './ObservationContextEditor'

const operationLabels: Record<SelectionOperation, string> = { filter: '条件筛选', sort: '按原值排序', top_k: '按原值排序并取前 N 个', weighted_rank: '加权排序', pareto: 'Pareto 前沿', diversity: '多样性选择', manual: '勾选候选' }
export type SelectionEditorProps = { catalog: CatalogSnapshot; workflow: Workflow; nodeId: string; candidateCollections?: Array<{ source: SelectionSource; items: ResultCandidate[] }>; scoreObservations?: ScoreObservationReading[]; onChange: (workflow: Workflow) => void; onDraftChange?: (workflow: Workflow) => void; onCancel?: () => void }

/** Parent mounts this editor with key=nodeId; only Apply changes the Workflow. */
export function SelectionEditor({ catalog, workflow, nodeId, candidateCollections = [], scoreObservations = [], onChange, onDraftChange, onCancel }: SelectionEditorProps) {
  const [draft, setDraft] = useState(() => readSelectionDraft(workflow, nodeId))
  const [search, setSearch] = useState('')
  const candidates = candidateCollections.find((collection) => draft.candidateSource && sourceKey(collection.source) === sourceKey(draft.candidateSource))?.items ?? []
  const candidateSources = selectionSources(workflow, catalog, nodeId, 'candidate.collection')
  const scoreSources = selectionSources(workflow, catalog, nodeId, 'score.collection')
  const selectedKeys = new Set(draft.selectedCandidates.map(candidateReferenceKey))
  const currentKeys = new Set(candidates.map((value) => candidateReferenceKey(value.reference)))
  const missing = draft.selectedCandidates.filter((value) => !currentKeys.has(candidateReferenceKey(value)))
  const multiple = ['weighted_rank', 'pareto', 'diversity'].includes(draft.operation)
  const raw = draft.operation === 'sort' || draft.operation === 'top_k'
  const weightPercentages = effectiveWeightPercentages(draft.observations)
  const publishDraft = (value: SelectionDraft) => saveSelectionDraft(workflow, nodeId, value)
  const scopePreview = publishDraft(draft)
  const update = (change: Partial<SelectionDraft>) => {
    const next = { ...draft, ...change }
    setDraft(next)
    const prepared = publishDraft(next)
    onDraftChange?.(prepared)
  }
  function removeObservation(id: string) { update({ observations: draft.observations.filter((value) => value.id !== id) }) }
  function apply() {
    onChange(scopePreview)
  }
  function toggleCandidate(reference: CandidateReference, checked: boolean) { update({ selectedCandidates: checked ? [...draft.selectedCandidates, reference] : draft.selectedCandidates.filter((value) => candidateReferenceKey(value) !== candidateReferenceKey(reference)) }) }
  return <section className="selection-editor nodrag nowheel" aria-label="流程筛选编辑器"><h3>流程筛选</h3>
    <label>操作<select aria-label="筛选操作" value={draft.operation} onChange={(event) => update({ operation: event.target.value as SelectionOperation })}>{Object.entries(operationLabels).map(([operation, label]) => <option key={operation} value={operation}>{label}</option>)}</select></label>
    <SourcePicker label="Candidate Collection 来源" source={draft.candidateSource} sources={candidateSources} onChange={(candidateSource) => update({ candidateSource })} />
    {draft.operation === 'manual' ? <><p>已保存 {draft.selectedCandidates.length} 个精确候选引用。执行时只在当前输入集合匹配，缺失时明确报错。</p><label>搜索候选<input aria-label="搜索候选" value={search} onChange={(event) => setSearch(event.target.value)} /></label><div className="selection-candidates">{candidates.filter((candidate) => `${candidate.reference.candidate_id} ${String(candidate.metadata.display_name ?? '')}`.toLowerCase().includes(search.toLowerCase())).map((candidate) => <label key={candidateReferenceKey(candidate.reference)}><input type="checkbox" checked={selectedKeys.has(candidateReferenceKey(candidate.reference))} onChange={(event) => toggleCandidate(candidate.reference, event.target.checked)} /><span>{String(candidate.metadata.display_name ?? candidate.reference.candidate_id)}<small>{candidate.reference.candidate_id} · {candidate.reference.data_type_id}</small></span></label>)}</div>{candidates.length === 0 && <p>选择已有运行结果的候选集合后勾选；空选择会产生空集合。</p>}{missing.length > 0 && <div role="status"><p>{missing.length} 个已保存引用不在当前显示的候选集合中；不会自动替换或跳过。</p>{missing.map((reference) => <p key={candidateReferenceKey(reference)}>{reference.candidate_id}<button type="button" onClick={() => toggleCandidate(reference, false)}>移除该引用</button></p>)}</div>}</> : draft.operation === 'filter' ? <><ConditionEditor value={draft.condition} catalog={catalog} workflow={workflow} nodeId={nodeId} scoreSources={scoreSources} published={scoreObservations} candidates={candidates.map((candidate) => candidate.reference)} onChange={(condition) => update({ condition })} /><p className="selection-science">先检查全部所选评价，再判断组合条件；任一必需评价缺失或有歧义时停止。未选择的其他评价不影响筛选。阈值采用指标原单位，保留候选身份、来源与输入顺序。</p></> : <>
      {draft.observations.slice(0, multiple ? undefined : 1).map((value, index) => <ObservationEditor key={value.id} value={value} index={index} catalog={catalog} workflow={workflow} nodeId={nodeId} scoreSources={scoreSources} published={scoreObservations} ranking={!raw} weighted={['weighted_rank', 'diversity', 'pareto'].includes(draft.operation)} weightPercent={weightPercentages[index]} onChange={(next) => update({ observations: draft.observations.map((item) => item.id === next.id ? next : item) })} onRemove={() => removeObservation(value.id)} />)}
      {raw && draft.observations[0] && <ObservationContextEditor key={observationOptionKey(draft.observations[0])} value={draft.observations[0]} workflow={workflow} catalog={catalog} nodeId={nodeId} observations={scoreObservations} candidates={candidates.map((candidate) => candidate.reference)} onChange={(next) => update({ observations: [next] })} />}
      {(multiple || draft.observations.length === 0) && <button type="button" onClick={() => update({ observations: [...draft.observations, newObservation()] })}>添加观察条件</button>}
      {['top_k', 'diversity'].includes(draft.operation) && <ScalarField label="候选数量 N" min={1} value={draft.k} onChange={(k) => update({ k })} />}
      {raw && <><label>原值排序方向<select aria-label="原值排序方向" value={draft.direction ?? ''} onChange={(event) => update({ direction: event.target.value ? event.target.value as SelectionDraft['direction'] : undefined })}><option value="">选择方向…</option><option value="ascending">升序（较小值在前）</option><option value="descending">降序（较大值在前）</option></select></label><p className="selection-science">按指标原值排序，同分保持输入顺序。缺少必需评价或评价有歧义时停止。{draft.operation === 'top_k' && '最多取 N 个；候选不足时返回全部，空输入返回空集合，不扩大临界并列。'}</p></>}
    </>}
    <div className="selection-actions">{!onDraftChange && <button type="button" onClick={apply}>应用到流程</button>}{onCancel && <button type="button" onClick={onCancel}>取消</button>}</div>
  </section>
}
