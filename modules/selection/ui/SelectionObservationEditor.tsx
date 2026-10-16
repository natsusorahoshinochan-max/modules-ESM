import type { CatalogSnapshot, Workflow } from '../../../webui/src/protocol/client'
import { observationLabel, sourceKey, type ObservationDraft, type SelectionSource } from './selection-authoring'
import { chooseObservation, contextLabel, contractTitle, observationOptionKey, useObservationOptions } from './selection-observations'
import type { ScoreObservationReading } from './ObservationContextEditor'

import { ScoringChoiceEditor } from './ScoringChoiceEditor'

type SourceOption = SelectionSource & { label: string }

export function SourcePicker({ label, source, sources, onChange }: { label: string; source?: SelectionSource; sources: SourceOption[]; onChange: (source?: SelectionSource) => void }) {
  return <label>{label}<select aria-label={label} value={source ? sourceKey(source) : ''} onChange={(event) => { const selected = sources.find((item) => sourceKey(item) === event.target.value); onChange(selected ? { node_id: selected.node_id, output_port: selected.output_port } : undefined) }}>
    <option value="">选择来源…</option>{source && !sources.some((item) => sourceKey(item) === sourceKey(source)) && <option value={sourceKey(source)}>已保存来源当前不可用 · {source.node_id} / {source.output_port}</option>}{sources.map((item) => <option value={sourceKey(item)} key={sourceKey(item)}>{item.label}</option>)}
  </select></label>
}

export function ScalarField({ label, value, min, onChange }: { label: string; value?: number; min?: number; onChange: (value?: number) => void }) {
  return <label>{label}<input aria-label={label} type="number" step="any" min={min} value={value ?? ''} onChange={(event) => onChange(event.target.value === '' ? undefined : Number(event.target.value))} /></label>
}

export function ObservationEditor({ value, index, catalog, workflow, nodeId, scoreSources, published, ranking, weighted, weightPercent, onChange, onRemove }: { value: ObservationDraft; index: number; catalog: CatalogSnapshot; workflow: Workflow; nodeId: string; scoreSources: SourceOption[]; published: ScoreObservationReading[]; ranking: boolean; weighted: boolean; weightPercent?: number; onChange: (value: ObservationDraft) => void; onRemove?: () => void }) {
  const { observations, error } = useObservationOptions(workflow, catalog, ranking, value.scoreSource, published)
  const selectedKey = value.metricId ? observationOptionKey(value) : ''
  const selected = observations.find((option) => option.key === selectedKey)
  const metric = catalog.contracts.find((item) => item.reference.contract_kind === 'metric' && item.reference.contract_id === value.metricId)
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
    {ranking && <><ScoringChoiceEditor value={value} catalog={catalog} onChange={onChange} />
      {weighted && <><ScalarField label="相对权重（非负）" min={0} value={value.weight} onChange={(weight) => onChange({ ...value, weight })} /><p className="selection-weight" aria-label={`观察条件 ${index + 1} 的有效权重`}>有效权重：{weightPercent === undefined ? '待完整填写；权重非负且总和须大于 0' : `${Number(weightPercent.toFixed(2))}%`}</p></>}
    </>}
    <label>缺失观察值<select aria-label="缺失观察值" value="error" disabled><option value="error">报错（当前科学合同）</option></select></label><p className="selection-science">每个候选必须匹配恰好一项完整数据引用的观察值。</p>
    {onRemove && <button type="button" onClick={onRemove}>移除此观察条件</button>}
  </fieldset>
}
