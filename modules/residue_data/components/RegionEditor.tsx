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

export function RegionEditor({ workflow, nodeId, onApply, onCancel }: ModuleEditorProps) {
  const node = workflow.nodes.find(value => value.node_id === nodeId)!
  const fields = [['region', '处理区域']]
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
  const valid = fields.every(([name]) => ((parameters[name] ?? []) as Location[]).every(value => value.chain_id.length > 0 && value.residue_number.length > 0))
  return <section>
    <p>此操作明确提取所选残基，产生新结构候选；原结构保持不变。</p>
    <fieldset disabled={pending}>
    {fields.map(([name, title]) => <RegionFields key={name} title={title} value={(parameters[name] ?? []) as Location[]} onChange={value => setParameters({ ...parameters, [name]: value })} />)}
    </fieldset>
    {error && <p role="alert">{error}</p>}
    {!valid && <p role="alert">请填写每个位置的链和作者残基编号。</p>}
    <footer><button type="button" disabled={pending} onClick={onCancel}>取消区域编辑</button><button type="button" disabled={!valid || pending} onClick={() => void apply()}>{pending ? '正在采用…' : '采用区域选择'}</button></footer>
  </section>
}
