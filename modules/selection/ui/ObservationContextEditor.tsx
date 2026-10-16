import type { CandidateReference, JsonObject, PublishedAlignment, PublishedObservation, ResultLocation, Workflow } from '../../../webui/src/protocol/client'
import { candidateReferenceKey, selectionSources, sourceKey, type ObservationDraft, type SelectionSource } from './selection-authoring'
import type { CatalogSnapshot } from '../../../webui/src/protocol/client'
import { sameContext } from './selection-observations'

export type ScoreObservationReading = PublishedObservation & { source: ResultLocation }
export type AlignmentReading = PublishedAlignment & { value_content_digest: string }

function factKey(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) => item && typeof item === 'object' && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right))) : item)
}

function actualContextLabel(context: JsonObject, residueAxis: unknown, subject: CandidateReference, alignments: AlignmentReading[]): string {
  const axis = residueAxis ? ` · 残基轴 ${((residueAxis as { layout: { residue_ids: string[] } }).layout.residue_ids).join('、')}` : ''
  if (context.kind !== 'pairwise') return `候选自身${axis}`
  const reference = (context.reference as { candidate: CandidateReference }).candidate
  const recordedSubject = (context.subject as { candidate: CandidateReference }).candidate
  // Evidence supplies display text only. The selected Context remains the original fact.
  const evidence = typeof context.evidence_content_digest === 'string' && typeof context.subject_axis_content_digest === 'string' && typeof context.reference_axis_content_digest === 'string'
    && candidateReferenceKey(subject) === candidateReferenceKey(recordedSubject)
    ? alignments.find((entry) => entry.value_content_digest === context.evidence_content_digest
      && candidateReferenceKey(entry.subject) === candidateReferenceKey(subject)
      && candidateReferenceKey(entry.reference) === candidateReferenceKey(reference)
      && entry.subject_axis_content_digest === context.subject_axis_content_digest
      && entry.reference_axis_content_digest === context.reference_axis_content_digest)
    : undefined
  const region = (value: unknown) => value === undefined || value === null ? '未记录' : (value as string[]).length ? (value as string[]).join('、') : '完整结构'
  return `参考 ${reference.candidate_id} · 候选区域 ${region(context.subject_region ?? evidence?.subject_region)} · 参考区域 ${region(context.reference_region ?? evidence?.reference_region)} · 归一化 ${String(context.normalization)}${context.aligned_atom_count ? ` · 对齐原子 ${String(context.aligned_atom_count)}` : ''}${context.sequence_correspondence ? ` · 位置对应 ${JSON.stringify(context.sequence_correspondence)}` : ''}${axis}`
}

/** Select actual existing facts, or a relation that will arrive through an ordinary input. */
export function ObservationContextEditor({ value, workflow, catalog, nodeId, observations, candidates, alignments = [], onChange, allowRelations = true }: {
  value: ObservationDraft; workflow: Workflow; catalog: CatalogSnapshot; nodeId: string
  observations: ScoreObservationReading[]; candidates: CandidateReference[]; alignments?: AlignmentReading[]; allowRelations?: boolean; onChange: (value: ObservationDraft) => void
}) {
  const mode = value.exactContexts !== undefined ? 'exact' : value.relationInput ? 'relation' : value.reference ? 'reference' : 'unique'
  const matching = observations.filter((entry) => value.scoreSource && sourceKey(entry.source) === sourceKey(value.scoreSource) && entry.metric.contract_id === value.metricId && entry.method.contract_id === value.methodId && entry.source_partition === value.partition && sameContext(entry.context_profile, value.context))
  const subjects = [...new Map([...candidates, ...matching.map((entry) => entry.subject), ...(value.exactContexts ?? []).map((entry) => entry.subject)].map((subject) => [candidateReferenceKey(subject), subject])).values()]
  const relations = selectionSources(workflow, catalog, nodeId, 'candidate.relation')
  const references = [...new Map([...matching.filter((entry) => entry.context.kind === 'pairwise').map((entry) => (entry.context.reference as { candidate: CandidateReference }).candidate), ...(value.reference ? [value.reference] : [])].map((reference) => [candidateReferenceKey(reference), reference])).values()]
  const changeMode = (next: string) => {
    onChange({ ...value, reference: next === 'reference' ? value.reference : undefined, exactContexts: next === 'exact' ? [] : undefined, relationInput: next === 'relation' ? `input-${crypto.randomUUID()}` : undefined, relationSource: undefined })
  }
  const changeRelation = (source?: SelectionSource) => {
    const edge = source && workflow.edges.find((entry) => entry.target_node_id === nodeId && entry.target_port === 'relations' && entry.source_node_id === source.node_id && entry.source_port === source.output_port)
    onChange({ ...value, relationSource: source, relationInput: edge?.target_slot ?? `input-${crypto.randomUUID()}` })
  }
  return <fieldset className="selection-context"><legend>评价对象与区域</legend>
    <label>评价上下文选择方式<select aria-label="评价上下文选择方式" value={mode} onChange={(event) => changeMode(event.target.value)}>
      <option value="unique">每个候选在所选来源中唯一的评价</option>
      {allowRelations && value.context.kind === 'pairwise' && <option value="relation">使用明确的候选关系输入</option>}
      {value.reference && <option value="reference">已保存的共同参考对象</option>}
      <option value="exact">逐候选选择已有结果的确切上下文</option>
    </select></label>
    {mode === 'unique' && <p>各候选可以使用不同参考对象。参考对象或区域使同一候选仍有多项评价时，运行会报告歧义。</p>}
    {mode === 'relation' && <label>候选关系来源<select aria-label="候选关系来源" value={value.relationSource ? sourceKey(value.relationSource) : ''} onChange={(event) => changeRelation(relations.find((source) => sourceKey(source) === event.target.value))}><option value="">选择来源…</option>{value.relationSource && !relations.some((source) => sourceKey(source) === sourceKey(value.relationSource!)) && <option value={sourceKey(value.relationSource)}>已保存来源当前不可用</option>}{relations.map((source) => <option key={sourceKey(source)} value={sourceKey(source)}>{source.label}</option>)}</select></label>}
    {mode === 'reference' && <label>共同参考对象<select aria-label="共同参考对象" value={value.reference ? candidateReferenceKey(value.reference) : ''} onChange={(event) => onChange({ ...value, reference: references.find((reference) => candidateReferenceKey(reference) === event.target.value) })}>{references.map((reference) => <option key={candidateReferenceKey(reference)} value={candidateReferenceKey(reference)}>{reference.candidate_id}</option>)}</select></label>}
    {mode === 'exact' && <><p>选择已有评价时保留实际参考对象、区域、残基轴与位置对应。未选择或仍有歧义时停止。</p>{subjects.map((subject) => {
      const key = candidateReferenceKey(subject)
      const selected = value.exactContexts?.find((entry) => candidateReferenceKey(entry.subject) === key)
      const choices = [...new Map(matching.filter((entry) => candidateReferenceKey(entry.subject) === key).map((entry) => [factKey({ context: entry.context, residue_axis: entry.residue_axis }), entry])).values()]
      const selectedKey = selected ? factKey({ context: selected.context, residue_axis: selected.residue_axis }) : ''
      return <div key={key}><label>候选 {subject.candidate_id} 的评价上下文<select aria-label={`候选 ${subject.candidate_id} 的评价上下文`} value={selectedKey} onChange={(event) => {
        const choice = choices.find((entry) => factKey({ context: entry.context, residue_axis: entry.residue_axis }) === event.target.value)
        onChange({ ...value, exactContexts: [...(value.exactContexts ?? []).filter((entry) => candidateReferenceKey(entry.subject) !== key), ...(choice ? [{ subject, context: choice.context, residue_axis: choice.residue_axis }] : [])] })
      }}><option value="">选择确切评价…</option>{selected && !choices.some((entry) => factKey({ context: entry.context, residue_axis: entry.residue_axis }) === selectedKey) && <option value={selectedKey}>已保存上下文 · {actualContextLabel(selected.context, selected.residue_axis, subject, alignments)}</option>}{choices.map((entry, index) => <option key={factKey({ context: entry.context, residue_axis: entry.residue_axis })} value={factKey({ context: entry.context, residue_axis: entry.residue_axis })}>评价 {index + 1} · {actualContextLabel(entry.context, entry.residue_axis, subject, alignments)}</option>)}</select></label>{selected && <details><summary>查看已选评价的对象、区域与位置对应</summary><p>{actualContextLabel(selected.context, selected.residue_axis, subject, alignments)}</p><pre>{JSON.stringify({ context: selected.context, residue_axis: selected.residue_axis }, null, 2)}</pre></details>}</div>
    })}{subjects.length === 0 && <p>当前没有可读取的已有评价。请先读取结果或选择明确关系输入。</p>}</>}
  </fieldset>
}
