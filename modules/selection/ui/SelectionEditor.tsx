import { useState } from 'react'
import type { CandidateReference, CatalogSnapshot, ContractReference, JsonObject, ResultCandidate, Workflow } from '../../../webui/src/protocol/client'
import { candidateReferenceKey, newObservation, observationLabel, readSelectionDraft, saveSelectionDraft, selectionSources, sourceKey, type ComparisonOperator, type ObservationDraft, type Predicate, type SelectionDraft, type SelectionOperation, type SelectionSource } from './selection-authoring'
import { chooseObservation, contextLabel, contractTitle, effectiveWeightPercentages, observationOptionKey, sameContext, useObservationOptions } from './selection-observations'
import './selection-editor.css'
import { ObservationContextEditor, type ScoreObservationReading } from './ObservationContextEditor'

const operationLabels: Record<SelectionOperation, string> = { filter: '条件筛选', sort: '按原值排序', top_k: '按原值排序并取前 N 个', weighted_rank: '加权排序', pareto: 'Pareto 前沿', diversity: '多样性选择', manual: '勾选候选' }
const comparisonLabels: ComparisonOperator[] = ['>', '>=', '<', '<=', '==', '!=']
type SourceOption = SelectionSource & { label: string }
type Contract = CatalogSnapshot['contracts'][number]

function SourcePicker({ label, source, sources, onChange }: { label: string; source?: SelectionSource; sources: SourceOption[]; onChange: (source?: SelectionSource) => void }) {
  return <label>{label}<select aria-label={label} value={source ? sourceKey(source) : ''} onChange={(event) => { const selected = sources.find((item) => sourceKey(item) === event.target.value); onChange(selected ? { node_id: selected.node_id, output_port: selected.output_port } : undefined) }}>
    <option value="">选择来源…</option>{source && !sources.some((item) => sourceKey(item) === sourceKey(source)) && <option value={sourceKey(source)}>已保存来源当前不可用 · {source.node_id} / {source.output_port}</option>}{sources.map((item) => <option value={sourceKey(item)} key={sourceKey(item)}>{item.label}</option>)}
  </select></label>
}

function ContractPicker({ label, value, contracts, onChange }: { label: string; value: string; contracts: Contract[]; onChange: (value: string) => void }) {
  return <label>{label}<select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}><option value="">选择…</option>{value && !contracts.some((item) => item.reference.contract_id === value) && <option value={value}>{value} · 与当前条件不匹配</option>}{contracts.map((item) => <option key={item.reference.contract_id} value={item.reference.contract_id}>{String(item.descriptor.title ?? (item.descriptor.algorithm_identity as JsonObject | undefined)?.name ?? item.reference.contract_id)} · {item.reference.contract_id}</option>)}</select></label>
}

function ScalarField({ label, value, min, onChange }: { label: string; value?: number; min?: number; onChange: (value?: number) => void }) {
  return <label>{label}<input aria-label={label} type="number" step="any" min={min} value={value ?? ''} onChange={(event) => onChange(event.target.value === '' ? undefined : Number(event.target.value))} /></label>
}

function ObservationEditor({ value, index, catalog, workflow, nodeId, scoreSources, published, ranking, weighted, weightPercent, onChange, onRemove }: { value: ObservationDraft; index: number; catalog: CatalogSnapshot; workflow: Workflow; nodeId: string; scoreSources: SourceOption[]; published: ScoreObservationReading[]; ranking: boolean; weighted: boolean; weightPercent?: number; onChange: (value: ObservationDraft) => void; onRemove: () => void }) {
  const { observations, error } = useObservationOptions(workflow, catalog, ranking, value.scoreSource, published)
  const selectedKey = value.metricId ? observationOptionKey(value) : ''
  const selected = observations.find((option) => option.key === selectedKey)
  const metric = catalog.contracts.find((item) => item.reference.contract_kind === 'metric' && item.reference.contract_id === value.metricId)
  const transforms = catalog.contracts.filter((item) => {
    if (item.reference.contract_kind !== 'utility_transform') return false
    const contract = item.descriptor.compatible_input_contract as { metric: ContractReference; method: ContractReference; context_profile: JsonObject }
    return contract.metric.contract_id === value.metricId && contract.method.contract_id === value.methodId && sameContext(contract.context_profile, value.context)
  })
  const transform = transforms.find((item) => item.reference.contract_id === value.transformId)
  const transformParameters = (transform?.descriptor.parameters ?? {}) as Record<string, { scientific_meaning: string; required?: boolean; default?: unknown; value_contract: { type: string; minimum?: number; maximum?: number; enum?: unknown[] } }>
  const changeTransformParameter = (name: string, text: string, numeric: boolean) => {
    const parameters = { ...value.transformParameters }
    if (text === '') delete parameters[name]
    else parameters[name] = numeric ? Number(text) : text
    onChange({ ...value, transformParameters: parameters })
  }
  return <fieldset className="selection-observation"><legend>观察条件 {index + 1}</legend>
    <SourcePicker label="Score Collection 来源" source={value.scoreSource} sources={scoreSources} onChange={(scoreSource) => {
      const edge = scoreSource && workflow.edges.find((entry) => entry.target_node_id === nodeId && entry.target_port === 'scores' && entry.source_node_id === scoreSource.node_id && entry.source_port === scoreSource.output_port)
      onChange({ ...value, scoreInput: edge?.target_slot ?? `input-${crypto.randomUUID()}`, scoreSource, metricId: '', methodId: '', partition: '', context: { kind: 'intrinsic' }, transformId: '', transformParameters: {}, reference: undefined, exactContexts: undefined, relationSource: undefined, relationInput: undefined })
    }} />
    {value.scoreInput && !value.scoreSource && <p role="status">所选分数输入未连接；请选择评价来源。保存的规则不会改用其他已连接来源。</p>}
    <label>科学观察<select aria-label="科学观察" value={selectedKey} onChange={(event) => { const option = observations.find((entry) => entry.key === event.target.value); if (option) onChange(chooseObservation(value, option)) }}><option value="">选择来源声明的观察…</option>{selectedKey && !selected && <option value={selectedKey}>已保存观察与当前来源不匹配 · {observationLabel(value, catalog)}</option>}{observations.map((option) => <option value={option.key} key={option.key} >{option.label}</option>)}</select></label>
    {error && <p role="alert">{error}</p>}
    {value.scoreSource && observations.length === 0 && <p>当前来源没有已声明的标量观察；请先选择来源 Binding 并连接其输入。</p>}
    {selectedKey && !selected && <p role="status">已保存的 Metric、Method、分区或 Context 与当前来源不匹配，请重新选择观察。 已保存事实保持不变。</p>}
    {metric && <p className="selection-science">{String(metric.descriptor.description)}<br />单位：{String(metric.descriptor.unit)} · 方向：{String(metric.descriptor.direction)} · 范围：{JSON.stringify(metric.descriptor.canonical_range)} · 聚合：{JSON.stringify(metric.descriptor.aggregation_semantics)}</p>}
    {value.metricId && <dl className="selection-facts"><dt>Method</dt><dd>{contractTitle(catalog, 'method', value.methodId)}</dd><dt>分数分区</dt><dd>{value.partition}</dd><dt>Observation Context</dt><dd>{contextLabel(value.context)}</dd></dl>}
    {ranking && <><ContractPicker label="Utility Transform（输出 0–1）" value={value.transformId} contracts={transforms} onChange={(transformId) => {
      const chosen = transforms.find((item) => item.reference.contract_id === transformId)
      const declarations = (chosen?.descriptor.parameters ?? {}) as Record<string, { default?: unknown }>
      onChange({ ...value, transformId, transformParameters: Object.fromEntries(Object.entries(declarations).filter(([, entry]) => entry.default !== undefined).map(([key, entry]) => [key, entry.default])) })
    }} />{transforms.length === 0 && <p>当前 Metric、Method 和 Context 没有匹配的已注册 Utility Transform。</p>}
      {Object.entries(transformParameters).map(([name, parameter]) => <label key={name}>{name}{parameter.required ? ' *' : ''}<small>{parameter.scientific_meaning}</small>{parameter.value_contract.enum ? <select aria-label={`Utility ${name}`} value={String(value.transformParameters[name] ?? '')} onChange={(event) => changeTransformParameter(name, event.target.value, ['number', 'integer'].includes(parameter.value_contract.type))}><option value="">选择…</option>{parameter.value_contract.enum.map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}</select> : <input aria-label={`Utility ${name}`} type={['number', 'integer'].includes(parameter.value_contract.type) ? 'number' : 'text'} min={parameter.value_contract.minimum} max={parameter.value_contract.maximum} step={parameter.value_contract.type === 'integer' ? 1 : 'any'} value={String(value.transformParameters[name] ?? '')} onChange={(event) => changeTransformParameter(name, event.target.value, ['number', 'integer'].includes(parameter.value_contract.type))} />}</label>)}
      {weighted && <><ScalarField label="声明权重（大于 0）" min={0} value={value.weight} onChange={(weight) => onChange({ ...value, weight })} /><p className="selection-weight" aria-label={`观察条件 ${index + 1} 的有效权重`}>有效权重：{weightPercent === undefined ? '待完整填写，每项声明权重须大于 0' : `${Number(weightPercent.toFixed(2))}%`}</p></>}
    </>}
    <label>缺失观察值<select aria-label="缺失观察值" value="error" disabled><option value="error">报错（当前科学合同）</option></select></label><p className="selection-science">每个候选必须匹配恰好一项完整数据引用的观察值。</p>
    <button type="button" onClick={onRemove}>移除此观察条件</button>
  </fieldset>
}

function PredicateEditor({ value, observations, catalog, onChange, onRemove }: { value: Predicate; observations: ObservationDraft[]; catalog: CatalogSnapshot; onChange: (value: Predicate) => void; onRemove?: () => void }) {
  if (value.kind === 'comparison') return <div className="selection-comparison"><label>观察条件<select aria-label="比较使用的观察条件" value={value.selectorId} onChange={(event) => onChange({ ...value, selectorId: event.target.value })}><option value="">选择…</option>{observations.map((observation, index) => <option value={observation.id} key={observation.id}>{index + 1}. {observationLabel(observation, catalog)}</option>)}</select></label><label>比较<select aria-label="比较符" value={value.operator} onChange={(event) => onChange({ ...value, operator: event.target.value as ComparisonOperator })}>{comparisonLabels.map((operator) => <option key={operator}>{operator}</option>)}</select></label><ScalarField label="阈值（Metric 原单位）" value={value.threshold} onChange={(threshold) => onChange({ ...value, threshold })} />{onRemove && <button type="button" onClick={onRemove}>移除比较</button>}</div>
  return <fieldset className="selection-predicate"><legend><select aria-label="分组逻辑" value={value.operator} onChange={(event) => onChange({ ...value, operator: event.target.value as 'and' | 'or' })}><option value="and">全部满足（AND）</option><option value="or">任一满足（OR）</option></select></legend>{value.children.map((child, index) => <PredicateEditor key={index} value={child} observations={observations} catalog={catalog} onChange={(next) => onChange({ ...value, children: value.children.map((entry, cursor) => cursor === index ? next : entry) })} onRemove={() => onChange({ ...value, children: value.children.filter((_, cursor) => cursor !== index) })} />)}<div className="selection-actions"><button type="button" disabled={observations.length === 0} onClick={() => onChange({ ...value, children: [...value.children, { kind: 'comparison', selectorId: observations[0].id, operator: '>=' }] })}>添加比较</button><button type="button" onClick={() => onChange({ ...value, children: [...value.children, { kind: 'group', operator: 'and', children: [] }] })}>添加分组</button>{onRemove && <button type="button" onClick={onRemove}>移除分组</button>}</div></fieldset>
}

function predicateReferences(predicate: Predicate): string[] { return predicate.kind === 'comparison' ? [predicate.selectorId] : predicate.children.flatMap(predicateReferences) }
function removePredicateReference(predicate: Predicate, id: string): Predicate { return predicate.kind === 'comparison' ? predicate.selectorId === id ? { kind: 'group', operator: 'and', children: [] } : predicate : { ...predicate, children: predicate.children.filter((child) => child.kind !== 'comparison' || child.selectorId !== id).map((child) => removePredicateReference(child, id)) } }

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
  const multiple = ['filter', 'weighted_rank', 'pareto', 'diversity'].includes(draft.operation)
  const raw = draft.operation === 'sort' || draft.operation === 'top_k'
  const weightPercentages = effectiveWeightPercentages(draft.observations)
  const publishDraft = (value: SelectionDraft) => {
    const used = new Set(predicateReferences(value.predicate))
    return saveSelectionDraft(workflow, nodeId, value.operation === 'filter' ? { ...value, observations: value.observations.filter((observation) => used.has(observation.id)) } : value)
  }
  const scopePreview = publishDraft(draft)
  const update = (change: Partial<SelectionDraft>) => {
    const next = { ...draft, ...change }
    setDraft(next)
    const prepared = publishDraft(next)
    onDraftChange?.(prepared)
  }
  function removeObservation(id: string) { update({ observations: draft.observations.filter((value) => value.id !== id), predicate: removePredicateReference(draft.predicate, id) }) }
  function apply() {
    onChange(scopePreview)
  }
  function toggleCandidate(reference: CandidateReference, checked: boolean) { update({ selectedCandidates: checked ? [...draft.selectedCandidates, reference] : draft.selectedCandidates.filter((value) => candidateReferenceKey(value) !== candidateReferenceKey(reference)) }) }
  return <section className="selection-editor nodrag nowheel" aria-label="流程筛选编辑器"><h3>流程筛选</h3>
    <label>操作<select aria-label="筛选操作" value={draft.operation} onChange={(event) => update({ operation: event.target.value as SelectionOperation })}>{Object.entries(operationLabels).map(([operation, label]) => <option key={operation} value={operation}>{label}</option>)}</select></label>
    <SourcePicker label="Candidate Collection 来源" source={draft.candidateSource} sources={candidateSources} onChange={(candidateSource) => update({ candidateSource })} />
    {draft.operation === 'manual' ? <><p>已保存 {draft.selectedCandidates.length} 个精确候选引用。执行时只在当前输入集合匹配，缺失时明确报错。</p><label>搜索候选<input aria-label="搜索候选" value={search} onChange={(event) => setSearch(event.target.value)} /></label><div className="selection-candidates">{candidates.filter((candidate) => `${candidate.reference.candidate_id} ${String(candidate.metadata.display_name ?? '')}`.toLowerCase().includes(search.toLowerCase())).map((candidate) => <label key={candidateReferenceKey(candidate.reference)}><input type="checkbox" checked={selectedKeys.has(candidateReferenceKey(candidate.reference))} onChange={(event) => toggleCandidate(candidate.reference, event.target.checked)} /><span>{String(candidate.metadata.display_name ?? candidate.reference.candidate_id)}<small>{candidate.reference.candidate_id} · {candidate.reference.data_type_id}</small></span></label>)}</div>{candidates.length === 0 && <p>选择已有运行结果的候选集合后勾选；空选择会产生空集合。</p>}{missing.length > 0 && <div role="status"><p>{missing.length} 个已保存引用不在当前显示的候选集合中；不会自动替换或跳过。</p>{missing.map((reference) => <p key={candidateReferenceKey(reference)}>{reference.candidate_id}<button type="button" onClick={() => toggleCandidate(reference, false)}>移除该引用</button></p>)}</div>}</> : <>
      {draft.observations.slice(0, multiple ? undefined : 1).map((value, index) => <ObservationEditor key={value.id} value={value} index={index} catalog={catalog} workflow={workflow} nodeId={nodeId} scoreSources={scoreSources} published={scoreObservations} ranking={!raw && draft.operation !== 'filter'} weighted={['weighted_rank', 'diversity', 'pareto'].includes(draft.operation)} weightPercent={weightPercentages[index]} onChange={(next) => update({ observations: draft.observations.map((item) => item.id === next.id ? next : item) })} onRemove={() => removeObservation(value.id)} />)}
      {raw && draft.observations[0] && <ObservationContextEditor key={observationOptionKey(draft.observations[0])} value={draft.observations[0]} workflow={workflow} catalog={catalog} nodeId={nodeId} observations={scoreObservations} candidates={candidates.map((candidate) => candidate.reference)} onChange={(next) => update({ observations: [next] })} />}
      {(multiple || draft.observations.length === 0) && <button type="button" onClick={() => { const value = newObservation(); const comparison: Predicate = { kind: 'comparison', selectorId: value.id, operator: '>=' }; update({ observations: [...draft.observations, value], predicate: draft.predicate.kind === 'group' ? { ...draft.predicate, children: [...draft.predicate.children, comparison] } : { kind: 'group', operator: 'and', children: [draft.predicate, comparison] } }) }}>添加观察条件</button>}
      {draft.operation === 'filter' && <PredicateEditor value={draft.predicate} observations={draft.observations} catalog={catalog} onChange={(predicate) => update({ predicate })} />}
      {['top_k', 'diversity'].includes(draft.operation) && <ScalarField label="候选数量 N" min={1} value={draft.k} onChange={(k) => update({ k })} />}
      {draft.operation === 'filter' && <label>所选条件范围外的观察值<select aria-label="范围外观察值" value={draft.outOfScope} onChange={(event) => update({ outOfScope: event.target.value as 'error' | 'ignore' })}><option value="error">报错</option><option value="ignore">忽略</option></select></label>}
      {raw && <><label>原值排序方向<select aria-label="原值排序方向" value={draft.direction ?? ''} onChange={(event) => update({ direction: event.target.value ? event.target.value as SelectionDraft['direction'] : undefined })}><option value="">选择方向…</option><option value="ascending">升序（较小值在前）</option><option value="descending">降序（较大值在前）</option></select></label><p className="selection-science">按指标原值排序，同分保持输入顺序。缺少必需评价或评价有歧义时停止。{draft.operation === 'top_k' && '最多取 N 个；候选不足时返回全部，空输入返回空集合，不扩大临界并列。'}</p></>}
    </>}
    <div className="selection-actions">{!onDraftChange && <button type="button" onClick={apply}>应用到流程</button>}{onCancel && <button type="button" onClick={onCancel}>取消</button>}</div>
  </section>
}
