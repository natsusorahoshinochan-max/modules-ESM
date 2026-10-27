import { i18n, text } from './i18n'
const messages = {
  "not_set": {
    "zh-CN": "未设置",
    "en": "Not set"
  },
  "remove": {
    "zh-CN": "删除 {0}",
    "en": "Remove {0}"
  },
  "name": {
    "zh-CN": "{0} 名称",
    "en": "{0} name"
  },
  "name_2": {
    "zh-CN": "名称",
    "en": "Name"
  },
  "value_type": {
    "zh-CN": "{0} 值类型",
    "en": "{0} value type"
  },
  "number": {
    "zh-CN": "数值",
    "en": "Number"
  },
  "text": {
    "zh-CN": "文字",
    "en": "Text"
  },
  "toggle": {
    "zh-CN": "开关",
    "en": "Toggle"
  },
  "list": {
    "zh-CN": "列表",
    "en": "List"
  },
  "group": {
    "zh-CN": "分组",
    "en": "Group"
  },
  "add": {
    "zh-CN": "添加",
    "en": "Add"
  },
  "reset": {
    "zh-CN": "重置",
    "en": "Reset"
  },
  "remove_2": {
    "zh-CN": "删除 {0} {1}",
    "en": "Remove {0} {1}"
  },
  "automatic": {
    "zh-CN": "自动",
    "en": "Automatic"
  },
  "more_parameters": {
    "zh-CN": "更多参数",
    "en": "More parameters"
  }
};
const t = i18n.translator(messages)
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
    <option value="">{t("not_set")}</option>{schema.enum.map(item => <option key={JSON.stringify(item)} value={JSON.stringify(item)}>{text((record(schema.enumLabels)[String(item)] ?? String(item)) as import('@protein-workbench/module-ui').DisplayText)}</option>)}
  </select></label>
  if (type === 'boolean') return <label className="parameter-toggle">{label}<input type="checkbox" disabled={disabled} checked={current === true} onChange={event => onChange(event.target.checked)}/></label>
  if (type === 'object') {
    const values = record(current), fields = record(schema.properties), extra = record(schema.additionalProperties)
    return <details className="parameter-group"><summary>{label}</summary>
      {[...new Set([...Object.keys(fields), ...Object.keys(values)])].map(key => <div className="parameter-item" key={key}>
        <ValueField label={text((record(fields[key]).title ?? key) as import('@protein-workbench/module-ui').DisplayText)} value={values[key]} schema={fields[key] ? record(fields[key]) : extra} disabled={disabled} onChange={nextValue => { const next = {...values}; if (nextValue === undefined) delete next[key]; else next[key] = nextValue; onChange(next) }}/>
        {!Object.hasOwn(fields, key) && <button disabled={disabled} aria-label={t("remove", {"0": key})} onClick={() => {const next = {...values}; delete next[key]; onChange(next)}}>×</button>}
      </div>)}
      {!schema.properties && <div className="parameter-add"><input aria-label={t("name", {"0": label})} placeholder={t("name_2")} disabled={disabled} value={newKey} onChange={event => setNewKey(event.target.value)}/>{!schema.additionalProperties && <select aria-label={t("value_type", {"0": label})} disabled={disabled} value={newType} onChange={event=>setNewType(event.target.value)}>{Object.entries({number:t("number"),string:t("text"),boolean:t("toggle"),array:t("list"),object:t("group")}).map(([key,name])=><option key={key} value={key}>{name}</option>)}</select>}<button disabled={disabled || !newKey.trim() || Object.hasOwn(values, newKey.trim())} onClick={() => {onChange({...values, [newKey.trim()]: initialValue(schema.additionalProperties ? extra : {type:newType})}); setNewKey('')}}>{t("add")}</button></div>}
      {value !== undefined && <button disabled={disabled} onClick={reset}>{t("reset")}</button>}
    </details>
  }
  if (type === 'array') {
    const values = Array.isArray(current) ? current : []
    const itemSchema = schema.items ? record(schema.items) : {type: valueType(values[0])}
    return <details className="parameter-group"><summary>{label}{values.length ? ` · ${values.length}` : ''}</summary>
      {values.map((item, index) => <div className="parameter-item" key={index}><ValueField label={`${index + 1}`} value={item} schema={Array.isArray(schema.prefixItems) ? record(schema.prefixItems[index]) : itemSchema} disabled={disabled} onChange={next => onChange(values.map((old, offset) => index === offset ? next : old))}/><button aria-label={t("remove_2", {"0": label, "1": index + 1})} disabled={disabled} onClick={() => onChange(values.filter((_, offset) => index !== offset))}>×</button></div>)}
      <button disabled={disabled || (Array.isArray(schema.prefixItems) && values.length >= schema.prefixItems.length)} onClick={() => onChange([...values, initialValue(Array.isArray(schema.prefixItems) ? record(schema.prefixItems[values.length]) : itemSchema)])}>{t("add")}</button>{value !== undefined && <button disabled={disabled} onClick={reset}>{t("reset")}</button>}
    </details>
  }
  const numeric = type === 'number' || type === 'integer'
  return <label>{label}<input disabled={disabled} type={numeric ? 'number' : 'text'} step={type === 'integer' ? 1 : 'any'} min={typeof schema.minimum === 'number' ? schema.minimum : undefined} max={typeof schema.maximum === 'number' ? schema.maximum : undefined} value={current == null ? '' : String(current)} placeholder={current === null ? t("automatic") : undefined} onChange={event => {
    if (event.target.value === '') {onChange(schema.nullable ? null : undefined); return}
    if (numeric) {const number = Number(event.target.value); if (Number.isFinite(number)) onChange(number)} else onChange(event.target.value)
  }}/></label>
}
export function ParameterFields({schema, value, disabled, onChange}: {schema: RecordValue; value: RecordValue; disabled: boolean; onChange(value: RecordValue): void}) {
  const fields = parameterFields(schema), keys = [...new Set([...Object.keys(fields), ...Object.keys(value)])]
  function field(key: string) {
    const config = record(fields[key])
    return <ValueField key={key} label={text((config.title ?? key.replaceAll('_', ' ')) as import('@protein-workbench/module-ui').DisplayText)} schema={config} value={value[key]} disabled={disabled} onChange={nextValue => { const next = {...value}; if (nextValue === undefined) delete next[key]; else next[key] = nextValue; onChange(next) }}/>
  }
  const advanced = keys.filter(key => record(fields[key]).advanced)
  return <div className="parameter-fields">{keys.filter(key => !record(fields[key]).advanced).map(field)}{advanced.length > 0 && <details><summary>{t("more_parameters")}</summary>{advanced.map(field)}</details>}</div>
}
