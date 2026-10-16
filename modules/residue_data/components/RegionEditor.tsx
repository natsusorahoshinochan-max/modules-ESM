import { useState } from 'react'
import type { ModuleEditorProps } from '../../../webui/src/module-ui'
import type { JsonObject } from '../../../webui/src/protocol/client'

type Location = { chain_id: string; residue_number: string; insertion_code: string }

export function RegionFields({ title, value, onChange }: { title: string; value: Location[]; onChange: (value: Location[]) => void }) {
  return <fieldset><legend>{title}</legend><p>按原结构填写链、作者残基编号和插入码；可添加不连续位置。留空使用完整残基轴。</p>
    {value.map((location, index) => <div key={index} style={{ display: 'flex', gap: 8 }}>
      {([['chain_id', '链'], ['residue_number', '作者编号'], ['insertion_code', '插入码']] as const).map(([field, label]) => <label key={field}>{label}<input aria-label={`${label} ${index + 1}`} value={location[field]} onChange={event => onChange(value.map((entry, cursor) => cursor === index ? { ...entry, [field]: event.target.value } : entry))} /></label>)}
      <button type="button" onClick={() => onChange(value.filter((_, cursor) => cursor !== index))}>移除残基 {index + 1}</button>
    </div>)}
    <button type="button" onClick={() => onChange([...value, { chain_id: '', residue_number: '', insertion_code: '' }])}>添加残基</button>
  </fieldset>
}

export function RegionEditor({ catalog, workflow, nodeId, onApply, onCancel }: ModuleEditorProps) {
  const node = workflow.nodes.find(value => value.node_id === nodeId)!
  const comparison = node.node_type_id === 'structure_comparison.align_pairs'
  const statistics = node.node_type_id === 'structure_comparison.region_statistics'
  const metrics = catalog.contracts.filter(value => value.reference.contract_kind === 'metric' && value.descriptor.value_shape === 'per_residue')
  const fields = comparison ? [['subject_region', '主体区域'], ['reference_region', '参考区域']] : [['region', statistics ? '统计区域' : '处理区域']]
  const [parameters, setParameters] = useState<JsonObject>(() => ({ ...node.node_parameters }))
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  async function apply() {
    setPending(true)
    setError('')
    try {
      await onApply({ ...workflow, nodes: workflow.nodes.map(value => value.node_id === nodeId ? { ...value, node_parameters: parameters } : value) })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setPending(false)
    }
  }
  const valid = (!statistics || !!parameters.metric_id) && fields.every(([name]) => ((parameters[name] ?? []) as Location[]).every(value => value.chain_id.length > 0 && value.residue_number.length > 0))
  return <section>
    <p>{comparison ? '所选位置用于自动对应、对齐和比较；完整输入结构保持不变。' : statistics ? '仅统计已有逐残基数值，不重新调用预测工具。均值采用原指标单位，有效数量仅包含非空值；全空区域无法统计。' : '此操作明确提取所选残基，产生新结构候选；原结构保持不变。'}</p>
    <fieldset disabled={pending}>
    {statistics && <>
      <label>原始逐残基指标<select aria-label="原始逐残基指标" value={String(parameters.metric_id ?? '')} onChange={event => setParameters({ ...parameters, metric_id: event.target.value })}><option value="">选择原指标…</option>{typeof parameters.metric_id === 'string' && !metrics.some(metric => metric.reference.contract_id === parameters.metric_id) && <option value={String(parameters.metric_id)}>{String(parameters.metric_id)} · 当前不可用</option>}{metrics.map(metric => <option key={metric.reference.contract_id} value={metric.reference.contract_id}>{String(metric.descriptor.title)} · {metric.reference.contract_id}</option>)}</select></label>
      <label>区域缺值处理<select aria-label="区域缺值处理" value={String(parameters.missing_values ?? 'exclude_null')} onChange={event => setParameters({ ...parameters, missing_values: event.target.value })}><option value="exclude_null">排除缺值，报告有效数量</option><option value="require_all">所选位置必须全部有值</option></select></label>
    </>}
    {fields.map(([name, title]) => <RegionFields key={name} title={title} value={(parameters[name] ?? []) as Location[]} onChange={value => setParameters({ ...parameters, [name]: value })} />)}
    {comparison && <label><input type="checkbox" checked={parameters.pin_matching_chain_ids === true} onChange={event => setParameters({ ...parameters, pin_matching_chain_ids: event.target.checked })} />优先对应相同链名</label>}
    </fieldset>
    {error && <p role="alert">{error}</p>}
    {!valid && <p role="alert">{statistics ? '请选择统计指标，并填写每个位置的链和作者残基编号。' : '请填写每个位置的链和作者残基编号。'}</p>}
    <footer><button type="button" disabled={pending} onClick={onCancel}>取消区域编辑</button><button type="button" disabled={!valid || pending} onClick={() => void apply()}>{pending ? '正在采用…' : '采用区域选择'}</button></footer>
  </section>
}
