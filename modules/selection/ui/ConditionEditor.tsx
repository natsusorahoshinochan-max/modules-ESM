import type { CandidateReference, CatalogSnapshot, Workflow } from '../../../webui/src/protocol/client'
import { ObservationContextEditor, type AlignmentReading, type ScoreObservationReading } from './ObservationContextEditor'
import { ObservationEditor, ScalarField } from './SelectionObservationEditor'
import { newObservation, type ComparisonOperator, type SelectionSource } from './selection-authoring'
import type { ConditionDraft } from './selection-conditions'
import { observationOptionKey } from './selection-observations'

type Props = {
  value?: ConditionDraft; catalog: CatalogSnapshot; workflow: Workflow; nodeId: string
  scoreSources: Array<SelectionSource & { label: string }>; published: ScoreObservationReading[]
  alignments?: AlignmentReading[]; candidates: CandidateReference[]; onChange: (value?: ConditionDraft) => void
}
const operators: ComparisonOperator[] = ['>', '>=', '<', '<=', '==', '!=']
const comparison = (): ConditionDraft => ({ kind: 'comparison', selection: newObservation(), operator: '>=' })
const group = (): ConditionDraft => ({ kind: 'group', operator: 'and', children: [] })

/** Every comparison edits the complete evaluation it uses. */
export function ConditionEditor({ value, onChange, ...props }: Props) {
  if (!value) return <div className="selection-actions"><button type="button" onClick={() => onChange(comparison())}>添加比较</button><button type="button" onClick={() => onChange(group())}>添加分组</button><p>条件尚未完成，可以手动保存后继续编辑；完整配置后才能运行。</p></div>
  if (value.kind === 'comparison') return <fieldset className="selection-condition-comparison"><legend>指标阈值条件</legend>
    <ObservationEditor value={value.selection} index={0} {...props} ranking={false} weighted={false} onChange={(selection) => onChange({ ...value, selection })} />
    <ObservationContextEditor key={`${value.selection.id}:${observationOptionKey(value.selection)}`} value={value.selection} workflow={props.workflow} catalog={props.catalog} nodeId={props.nodeId} observations={props.published} alignments={props.alignments} candidates={props.candidates} onChange={(selection) => onChange({ ...value, selection })} />
    <label>比较<select aria-label="比较符" value={value.operator} onChange={(event) => onChange({ ...value, operator: event.target.value as ComparisonOperator })}>{operators.map((operator) => <option key={operator}>{operator}</option>)}</select></label>
    <ScalarField label="阈值（Metric 原单位）" value={value.threshold} onChange={(threshold) => onChange({ ...value, threshold })} />
    <div className="selection-actions"><button type="button" onClick={() => onChange({ kind: 'group', operator: 'and', children: [value, comparison()] })}>添加并列比较</button><button type="button" onClick={() => onChange(undefined)}>移除比较</button></div>
  </fieldset>
  return <fieldset className="selection-predicate"><legend><select aria-label="分组逻辑" value={value.operator} onChange={(event) => onChange({ ...value, operator: event.target.value as 'and' | 'or' })}><option value="and">全部满足（AND）</option><option value="or">任一满足（OR）</option></select></legend>
    {value.children.map((child, index) => <ConditionEditor key={child.kind === 'comparison' ? child.selection.id : index} {...props} value={child} onChange={(next) => onChange({ ...value, children: value.children.flatMap((entry, cursor) => cursor === index ? next ? [next] : [] : [entry]) })} />)}
    {value.children.length === 0 && <p>分组尚无条件，可以保存并继续编辑；完整配置后才能运行。</p>}
    <div className="selection-actions"><button type="button" onClick={() => onChange({ ...value, children: [...value.children, comparison()] })}>添加比较</button><button type="button" onClick={() => onChange({ ...value, children: [...value.children, group()] })}>添加分组</button><button type="button" onClick={() => onChange(undefined)}>移除分组</button></div>
  </fieldset>
}
