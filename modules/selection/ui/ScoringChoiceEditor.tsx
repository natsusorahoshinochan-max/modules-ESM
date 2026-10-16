import type { CatalogSnapshot, ContractReference, JsonObject } from '../../../webui/src/protocol/client'
import type { ObservationDraft } from './selection-authoring'
import { sameContext } from './selection-observations'

/** The metric owner declares the scoring scale; Selection presents its meaning. */
export function ScoringChoiceEditor({ value, catalog, onChange }: { value: ObservationDraft; catalog: CatalogSnapshot; onChange: (value: ObservationDraft) => void }) {
  const choices = catalog.contracts.filter((item) => {
    if (item.reference.contract_kind !== 'utility_transform') return false
    const input = item.descriptor.compatible_input_contract as { metric: ContractReference; method: ContractReference; context_profile: JsonObject }
    const parameters = (item.descriptor.parameters ?? {}) as Record<string, { required?: boolean; default?: unknown }>
    const ready = Object.values(parameters).every((parameter) => !parameter.required || Object.hasOwn(parameter, 'default'))
    return ready && input.metric.contract_id === value.metricId && input.method.contract_id === value.methodId && sameContext(input.context_profile, value.context)
  })
  const selected = choices.find((item) => item.reference.contract_id === value.transformId)
  return <div className="selection-scoring">
    <label>加权评分方式<select aria-label="加权评分方式" value={value.transformId} onChange={(event) => {
      onChange({ ...value, transformId: event.target.value, transformParameters: {} })
    }}><option value="">选择指标模块提供的评分方式…</option>
      {value.transformId && !selected && <option value={value.transformId}>已保存评分方式当前不适用</option>}
      {choices.map((item) => <option key={item.reference.contract_id} value={item.reference.contract_id}>{String(item.descriptor.title)}</option>)}
    </select></label>
    {selected && <><p>{String(selected.descriptor.meaning)}</p><p>适用条件：{String(selected.descriptor.applicability)}</p><ul aria-label="评分方式限制">{(selected.descriptor.limitations as string[]).map((limitation, index) => <li key={index}>{limitation}</li>)}</ul></>}
    {value.weight === 0 ? <p role="status">此项权重为 0，不参与计算，无需评分方式。</p> : !selected && <p role="status">{choices.length === 0 ? '当前评价没有适用评分方式，加权不可用。原值筛选、排序和 Pareto 仍可使用。' : '请选择适用评分方式；已保存的不适用选择不会自动替换。'}</p>}
  </div>
}
