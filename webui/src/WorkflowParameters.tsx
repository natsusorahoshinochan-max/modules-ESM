import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { ParameterPresentation, ParameterValueContract } from './workflow-authoring'
import './workflow-authoring.css'

export type ParameterChoice = { value: string; label: string }
export type ParameterChoices = Record<string, ParameterChoice[]>

type ValueEditorProps = {
  label: string
  fieldName: string
  contract: ParameterValueContract
  value: unknown
  choices: ParameterChoices
  onChange: (value: unknown) => void
}

const residueFields = new Set(['residue_id', 'residue_ids', 'designable_residue_ids', 'fixed_residue_ids', 'tied_residue_groups'])
const chainFields = new Set(['chain_ids', 'designed_chains', 'fixed_chains'])
const fieldLabels: Record<string, string> = {
  residue_id: '残基', amino_acid: '氨基酸', bias: 'Logit 偏置',
  designable_residue_ids: '可设计残基', fixed_residue_ids: '固定残基',
  designed_chains: '设计链', fixed_chains: '固定链', chain_ids: '链',
  omit_amino_acids: '排除的氨基酸', tied_residue_groups: '同一采样氨基酸的残基组',
  bias_by_residue: '逐残基氨基酸偏置',
}

function scalarValue(raw: string, contract: ParameterValueContract): unknown {
  if (raw === '') return undefined
  return contract.type === 'number' || contract.type === 'integer' ? Number(raw) : raw
}

function ScalarEditor({ label, contract, value, onChange }: Pick<ValueEditorProps, 'label' | 'contract' | 'value' | 'onChange'>) {
  const [text, setText] = useState(value === undefined ? '' : String(value))
  useEffect(() => { setText(value === undefined ? '' : String(value)) }, [value])
  const numeric = contract.type === 'integer' || contract.type === 'number'
  return <input aria-label={label} type={numeric ? 'number' : 'text'} value={text}
    min={contract.minimum} max={contract.maximum} step={contract.type === 'integer' ? 1 : contract.multipleOf ?? 'any'}
    minLength={contract.minLength} maxLength={contract.maxLength} pattern={contract.pattern}
    onChange={(event) => setText(event.target.value)}
    onBlur={() => { if (text !== (value === undefined ? '' : String(value))) onChange(scalarValue(text, contract)) }}
    onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} />
}

function selectionChoices(fieldName: string, choices: ParameterChoices): ParameterChoice[] | undefined {
  if (residueFields.has(fieldName)) return choices.residues ?? []
  if (chainFields.has(fieldName)) return choices.chains ?? []
  return choices[fieldName]
}

function ValueEditor({ label, fieldName, contract, value, choices, onChange }: ValueEditorProps) {
  if (Object.hasOwn(contract, 'const')) return <output className="parameter-fixed-value">{String(contract.const)}</output>
  const options = selectionChoices(fieldName, choices)
  if (contract.type === 'array') {
    const values = (value ?? []) as unknown[]
    const item = contract.items!
    const available = item.enum?.map((entry) => ({ value: String(entry), label: String(entry) })) ?? (item.type === 'string' ? options : undefined)
    if (available) return <div className="parameter-choice-set" role="group" aria-label={label}>
      {available.map((option) => <label key={option.value}><input type="checkbox" checked={values.includes(option.value)} onChange={(event) => onChange(event.target.checked ? [...values, option.value] : values.filter((entry) => entry !== option.value))} /><span>{option.label}</span></label>)}
      {available.length === 0 && <p className="parameter-empty-hint">连接来源并取得残基布局后选择{chainFields.has(fieldName) ? '链' : '残基'}。</p>}
      {values.filter((entry) => !available.some((option) => option.value === entry)).map((entry, index) => <span className="parameter-unresolved" key={index}>{String(entry)} · 当前来源中未找到 <button type="button" aria-label={`移除 ${String(entry)}`} onClick={() => onChange(values.filter((candidate) => candidate !== entry))}>移除</button></span>)}
    </div>
    return <div className="parameter-array" role="group" aria-label={label}>{values.map((entry, index) => <div className="parameter-array-entry" key={index}>
      <span className="parameter-entry-number">{index + 1}</span>
      <ValueEditor label={`${label} ${index + 1}`} fieldName={fieldName} contract={item} value={entry} choices={choices} onChange={(next) => onChange(values.map((current, cursor) => cursor === index ? next : current))} />
      <button type="button" aria-label={`移除 ${label} ${index + 1}`} onClick={() => onChange(values.filter((_, cursor) => cursor !== index))}>移除</button>
    </div>)}<button type="button" className="parameter-add" onClick={() => onChange([...values, Object.hasOwn(item, 'default') ? item.default : item.type === 'object' ? {} : item.type === 'array' ? [] : ''])}>添加{fieldLabels[fieldName] ?? '条目'}</button></div>
  }
  if (contract.type === 'object') {
    const values = (value ?? {}) as Record<string, unknown>
    return <div className="parameter-object">{Object.entries(contract.properties ?? {}).map(([key, child]) => <div className="parameter-object-field" key={key}>
      <span title={child.scientific_meaning}>{fieldLabels[key] ?? child.title ?? key}{contract.required?.includes(key) ? ' *' : ''}</span>
      <ValueEditor label={`${label} · ${fieldLabels[key] ?? child.title ?? key}`} fieldName={key} contract={child} value={values[key]} choices={choices} onChange={(next) => {
        const updated = { ...values }
        if (next === undefined) delete updated[key]
        else updated[key] = next
        onChange(updated)
      }} />
    </div>)}</div>
  }
  if (contract.enum || options) {
    const available = contract.enum?.map((entry) => ({ value: String(entry), label: String(entry) })) ?? options!
    return <select aria-label={label} value={value === undefined ? '' : String(value)} onChange={(event) => onChange(scalarValue(event.target.value, contract))}>
      <option value="">选择…</option>
      {value !== undefined && !available.some((option) => option.value === String(value)) && <option value={String(value)}>{String(value)} · 当前来源中未找到</option>}
      {available.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  }
  if (contract.type === 'boolean') return <label className="parameter-boolean"><input type="checkbox" aria-label={label} checked={value === true} onChange={(event) => onChange(event.target.checked)} /><span>{value === undefined ? '未设置' : value ? '启用' : '关闭'}</span></label>
  return <ScalarEditor label={label} contract={contract} value={value} onChange={onChange} />
}

function parameterValue(parameter: ParameterPresentation): unknown {
  if (parameter.value === '') return undefined
  if (parameter.valueType === 'string') return parameter.value
  return JSON.parse(parameter.value)
}

function encodedValue(value: unknown): string {
  if (value === undefined) return ''
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/** Edits the Catalog contract; scientific admission remains the backend owner's job. */
export function WorkflowParameters({ parameters, onParameter, choices = {}, renderParameter }: {
  parameters: ParameterPresentation[]
  onParameter: (parameter: ParameterPresentation, raw: string, commit: boolean) => void
  choices?: ParameterChoices
  renderParameter?: (parameter: ParameterPresentation) => ReactNode | undefined
}) {
  const groups = new Map<string, { title: string; parameters: ParameterPresentation[] }>()
  for (const parameter of parameters) {
    const group = groups.get(parameter.groupId) ?? { title: parameter.groupTitle, parameters: [] }
    group.parameters.push(parameter)
    groups.set(parameter.groupId, group)
  }
  return <details className="parameter-group nodrag nowheel"><summary aria-label="编辑参数">参数 <span>{parameters.length}</span></summary>
    <div className="parameter-fields schema-parameter-fields">{[...groups].map(([id, group]) => <fieldset key={id}><legend>{group.title}</legend>{group.parameters.map((parameter) => {
      const custom = renderParameter?.(parameter)
      if (custom !== undefined) return <div key={parameter.key}>{custom}</div>
      const numeric = parameter.valueType === 'number' || parameter.valueType === 'integer'
      return <div className="schema-parameter-field" key={parameter.key}>
        <span className="parameter-label" title={parameter.description}>{fieldLabels[parameter.key] ?? parameter.label}{parameter.required ? ' *' : ''}{parameter.unit && <em>{parameter.unit}</em>}</span>
        <ValueEditor label={parameter.label} fieldName={parameter.key} contract={parameter.contract} value={parameterValue(parameter)} choices={parameter.resourceKind === 'project_input' ? { ...choices, [parameter.key]: choices[parameter.key] ?? [] } : choices} onChange={(value) => {
          const raw = encodedValue(value)
          onParameter(parameter, raw, false)
          onParameter(parameter, raw, true)
        }} />
        {numeric && (parameter.contract.minimum !== undefined || parameter.contract.maximum !== undefined || parameter.contract.exclusiveMinimum !== undefined || parameter.contract.exclusiveMaximum !== undefined) && <small className="parameter-range">范围：{parameter.contract.exclusiveMinimum !== undefined ? `> ${parameter.contract.exclusiveMinimum}` : parameter.contract.minimum ?? '−∞'} — {parameter.contract.exclusiveMaximum !== undefined ? `< ${parameter.contract.exclusiveMaximum}` : parameter.contract.maximum ?? '+∞'}</small>}
        {parameter.resourceKind === 'project_input' && !(parameter.key in choices) && <small className="parameter-empty-hint">从项目输入列表选择文件。</small>}
        {parameter.description && <small className="parameter-description">{parameter.description}</small>}
      </div>
    })}</fieldset>)}</div>
  </details>
}
