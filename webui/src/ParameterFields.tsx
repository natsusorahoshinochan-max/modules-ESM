import { useState } from 'react'

type RecordValue = Record<string, unknown>
const record = (value: unknown): RecordValue => value && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : {}
const valueType = (value: unknown) => Array.isArray(value) ? 'array' : value !== null && typeof value === 'object' ? 'object' : typeof value === 'number' ? 'number' : typeof value === 'boolean' ? 'boolean' : 'string'
function initialValue(schema: RecordValue): unknown {
  if (schema.default !== undefined) return structuredClone(schema.default)
  return schema.type === 'object' ? {} : schema.type === 'array' ? [] : schema.type === 'number' || schema.type === 'integer' ? 0 : schema.type === 'boolean' ? false : ''
}
export function parameterFields(schema: RecordValue): RecordValue {
  if (schema.properties) return record(schema.properties)
  if (!schema.defaults) return schema
  const defaults = record(schema.defaults)
  return Object.fromEntries([...new Set([...Object.keys(defaults), ...Object.keys(schema).filter(key => key !== 'defaults')])].map(key => [key, {
    ...(Object.hasOwn(defaults, key) ? { default: defaults[key] } : {}),
    ...(Array.isArray(schema[key]) ? { enum: schema[key] } : record(schema[key])),
  }]))
}
function ValueField({ label, value, schema, disabled, onChange }: {label: string; value: unknown; schema: RecordValue; disabled: boolean; onChange(value: unknown): void}) {
  const [newKey, setNewKey] = useState('')
  const [newType, setNewType] = useState('number')
  const current = value === undefined ? schema.default : value
  const type = String(schema.type ?? valueType(current))
  const reset = () => onChange(undefined)
  if (Array.isArray(schema.enum)) return <label>{label}<select disabled={disabled} value={current === undefined ? '' : JSON.stringify(current)} onChange={event => onChange(event.target.value === '' ? undefined : JSON.parse(event.target.value))}>
    <option value="">未设置</option>{schema.enum.map(item => <option key={JSON.stringify(item)} value={JSON.stringify(item)}>{String(record(schema.enumLabels)[String(item)] ?? item)}</option>)}
  </select></label>
  if (type === 'boolean') return <label className="parameter-toggle">{label}<input type="checkbox" disabled={disabled} checked={current === true} onChange={event => onChange(event.target.checked)}/></label>
  if (type === 'object') {
    const values = record(current), fields = record(schema.properties), extra = record(schema.additionalProperties)
    return <details className="parameter-group"><summary>{label}</summary>
      {[...new Set([...Object.keys(fields), ...Object.keys(values)])].map(key => <div className="parameter-item" key={key}>
        <ValueField label={String(record(fields[key]).title ?? key)} value={values[key]} schema={fields[key] ? record(fields[key]) : extra} disabled={disabled} onChange={nextValue => { const next = {...values}; if (nextValue === undefined) delete next[key]; else next[key] = nextValue; onChange(next) }}/>
        {!Object.hasOwn(fields, key) && <button disabled={disabled} aria-label={`删除 ${key}`} onClick={() => {const next = {...values}; delete next[key]; onChange(next)}}>×</button>}
      </div>)}
      {!schema.properties && <div className="parameter-add"><input aria-label={`${label} 名称`} placeholder="名称" disabled={disabled} value={newKey} onChange={event => setNewKey(event.target.value)}/>{!schema.additionalProperties && <select aria-label={`${label} 值类型`} disabled={disabled} value={newType} onChange={event=>setNewType(event.target.value)}>{Object.entries({number:'数值',string:'文字',boolean:'开关',array:'列表',object:'分组'}).map(([key,name])=><option key={key} value={key}>{name}</option>)}</select>}<button disabled={disabled || !newKey.trim() || Object.hasOwn(values, newKey.trim())} onClick={() => {onChange({...values, [newKey.trim()]: initialValue(schema.additionalProperties ? extra : {type:newType})}); setNewKey('')}}>添加</button></div>}
      {value !== undefined && <button disabled={disabled} onClick={reset}>重置</button>}
    </details>
  }
  if (type === 'array') {
    const values = Array.isArray(current) ? current : []
    const itemSchema = schema.items ? record(schema.items) : {type: valueType(values[0])}
    return <details className="parameter-group"><summary>{label}{values.length ? ` · ${values.length}` : ''}</summary>
      {values.map((item, index) => <div className="parameter-item" key={index}><ValueField label={`${index + 1}`} value={item} schema={Array.isArray(schema.prefixItems) ? record(schema.prefixItems[index]) : itemSchema} disabled={disabled} onChange={next => onChange(values.map((old, offset) => index === offset ? next : old))}/><button aria-label={`删除 ${label} ${index + 1}`} disabled={disabled} onClick={() => onChange(values.filter((_, offset) => index !== offset))}>×</button></div>)}
      <button disabled={disabled || (Array.isArray(schema.prefixItems) && values.length >= schema.prefixItems.length)} onClick={() => onChange([...values, initialValue(Array.isArray(schema.prefixItems) ? record(schema.prefixItems[values.length]) : itemSchema)])}>添加</button>{value !== undefined && <button disabled={disabled} onClick={reset}>重置</button>}
    </details>
  }
  const numeric = type === 'number' || type === 'integer'
  return <label>{label}<input disabled={disabled} type={numeric ? 'number' : 'text'} step={type === 'integer' ? 1 : 'any'} min={typeof schema.minimum === 'number' ? schema.minimum : undefined} max={typeof schema.maximum === 'number' ? schema.maximum : undefined} value={current == null ? '' : String(current)} placeholder={current === null ? '自动' : undefined} onChange={event => {
    if (event.target.value === '') {onChange(schema.nullable ? null : undefined); return}
    if (numeric) {const number = Number(event.target.value); if (Number.isFinite(number)) onChange(number)} else onChange(event.target.value)
  }}/></label>
}
export function ParameterFields({schema, value, disabled, onChange}: {schema: RecordValue; value: RecordValue; disabled: boolean; onChange(value: RecordValue): void}) {
  const fields = parameterFields(schema), keys = [...new Set([...Object.keys(fields), ...Object.keys(value)])]
  function field(key: string) {
    const config = record(fields[key])
    return <ValueField key={key} label={String(config.title ?? key.replaceAll('_', ' '))} schema={config} value={value[key]} disabled={disabled} onChange={nextValue => { const next = {...value}; if (nextValue === undefined) delete next[key]; else next[key] = nextValue; onChange(next) }}/>
  }
  const advanced = keys.filter(key => record(fields[key]).advanced)
  return <div className="parameter-fields">{keys.filter(key => !record(fields[key]).advanced).map(field)}{advanced.length > 0 && <details><summary>更多参数</summary>{advanced.map(field)}</details>}</div>
}
