import type { CandidateReference, CatalogSnapshot, Workflow } from '../../../webui/src/protocol/client'
import { ObservationContextEditor } from '../../selection/ui/ObservationContextEditor'
import type { ComparisonOperator, ObservationDraft } from '../../selection/ui/selection-authoring'
import { locationKey, referenceKey, type ScoreView } from './result-explorer'
import { resultObservation, type Predicate, type ResultFilterChoice } from './result-filter'

const viewingWorkflow: Workflow = { schema_version: '2.1.0', workflow_id: 'result-view', nodes: [], edges: [], observation_selectors: [], selection_objectives: [] }
type ContextProps = { observations: ScoreView[]; candidates: CandidateReference[]; catalog: CatalogSnapshot }

export function ResultObservationEditor({ value, observations, candidates, catalog, onChange }: ContextProps & { value: ObservationDraft; onChange: (value: ObservationDraft) => void }) {
  const subjects = new Set(candidates.map(referenceKey))
  const existing = observations.filter(entry => value.scoreSource && locationKey(entry.source) === value.scoreInput && subjects.has(referenceKey(entry.subject)))
  return <ObservationContextEditor allowRelations={false} key={value.id} value={value} observations={existing} candidates={candidates} catalog={catalog} workflow={viewingWorkflow} nodeId="result-view" onChange={onChange} />
}

export function ResultFilter({ value, choices, onChange, onRemove, ...context }: ContextProps & { value: Predicate; choices: ResultFilterChoice[]; onChange: (value: Predicate) => void; onRemove?: () => void }) {
  if (value.kind === 'comparison') {
    const choice = choices.find(choice => choice.key === value.selectorId)
    const selection = value.selection ?? (choice ? resultObservation(choice) : undefined)
    return <div className="result-filter-comparison">
      <label>分数条件<select aria-label="临时筛选分数" value={value.selectorId} onChange={(event) => { const choice = choices.find(choice => choice.key === event.target.value); onChange({ ...value, selectorId: event.target.value, selection: choice ? resultObservation(choice) : undefined }) }}><option value="">选择分数…</option>{choices.map((choice) => <option key={choice.key} value={choice.key}>{choice.label}</option>)}</select></label>
      {selection && <ResultObservationEditor {...context} value={selection} onChange={selection => onChange({ ...value, selection })} />}
      <select aria-label="临时筛选比较符" value={value.operator} onChange={(event) => onChange({ ...value, operator: event.target.value as ComparisonOperator })}>{['>', '>=', '<', '<=', '==', '!='].map((operator) => <option key={operator}>{operator}</option>)}</select>
      <label>阈值（分数原单位）<input type="number" step="any" value={value.threshold ?? ''} onChange={(event) => onChange({ ...value, threshold: event.target.value === '' ? undefined : Number(event.target.value) })} /></label>
      {onRemove && <button onClick={onRemove}>移除条件</button>}
    </div>
  }
  return <fieldset className="result-filter-group"><legend><select aria-label="临时筛选分组" value={value.operator} onChange={(event) => onChange({ ...value, operator: event.target.value as 'and' | 'or' })}><option value="and">全部满足（AND）</option><option value="or">任一满足（OR）</option></select></legend>
    {value.children.map((child, index) => <ResultFilter key={index} {...context} value={child} choices={choices} onChange={(next) => onChange({ ...value, children: value.children.map((item, position) => position === index ? next : item) })} onRemove={() => onChange({ ...value, children: value.children.filter((_, position) => position !== index) })} />)}
    <button disabled={!choices.length} onClick={() => onChange({ ...value, children: [...value.children, { kind: 'comparison', selectorId: choices[0].key, selection: resultObservation(choices[0]), operator: '>=' }] })}>添加条件</button>
    <button onClick={() => onChange({ ...value, children: [...value.children, { kind: 'group', operator: 'and', children: [] }] })}>添加 AND/OR 分组</button>
    {onRemove && <button onClick={onRemove}>移除此组</button>}
  </fieldset>
}
