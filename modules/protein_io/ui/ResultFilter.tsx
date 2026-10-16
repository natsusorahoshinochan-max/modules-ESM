import type { ComparisonOperator, Predicate } from '../../selection/ui/selection-authoring'
import type { ResultFilterChoice } from './result-filter'

export function ResultFilter({ value, choices, onChange, onRemove }: { value: Predicate; choices: ResultFilterChoice[]; onChange: (value: Predicate) => void; onRemove?: () => void }) {
  if (value.kind === 'comparison') return <div className="result-filter-comparison">
    <label>分数条件<select aria-label="临时筛选分数" value={value.selectorId} onChange={(event) => onChange({ ...value, selectorId: event.target.value })}><option value="">选择分数…</option>{choices.map((choice) => <option key={choice.key} value={choice.key} disabled={choice.ambiguous}>{choice.label}</option>)}</select></label>
    <select aria-label="临时筛选比较符" value={value.operator} onChange={(event) => onChange({ ...value, operator: event.target.value as ComparisonOperator })}>{['>', '>=', '<', '<=', '==', '!='].map((operator) => <option key={operator}>{operator}</option>)}</select>
    <label>阈值（分数原单位）<input type="number" step="any" value={value.threshold ?? ''} onChange={(event) => onChange({ ...value, threshold: event.target.value === '' ? undefined : Number(event.target.value) })} /></label>
    {onRemove && <button onClick={onRemove}>移除条件</button>}
  </div>
  return <fieldset className="result-filter-group"><legend><select aria-label="临时筛选分组" value={value.operator} onChange={(event) => onChange({ ...value, operator: event.target.value as 'and' | 'or' })}><option value="and">全部满足（AND）</option><option value="or">任一满足（OR）</option></select></legend>
    {value.children.map((child, index) => <ResultFilter key={index} value={child} choices={choices} onChange={(next) => onChange({ ...value, children: value.children.map((item, position) => position === index ? next : item) })} onRemove={() => onChange({ ...value, children: value.children.filter((_, position) => position !== index) })} />)}
    <button disabled={!choices.some((choice) => !choice.ambiguous)} onClick={() => onChange({ ...value, children: [...value.children, { kind: 'comparison', selectorId: choices.find((choice) => !choice.ambiguous)!.key, operator: '>=' }] })}>添加条件</button>
    <button onClick={() => onChange({ ...value, children: [...value.children, { kind: 'group', operator: 'and', children: [] }] })}>添加 AND/OR 分组</button>
    {onRemove && <button onClick={onRemove}>移除此组</button>}
  </fieldset>
}
