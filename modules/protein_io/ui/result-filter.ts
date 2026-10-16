import type { JsonObject } from '../../../webui/src/protocol/client'
import type { ComparisonOperator, ObservationDraft } from '../../selection/ui/selection-authoring'
import { locationKey, type ScoreView } from './result-explorer'

export type Predicate =
  | { kind: 'comparison'; selectorId: string; selection?: ObservationDraft; operator: ComparisonOperator; threshold?: number }
  | { kind: 'group'; operator: 'and' | 'or'; children: Predicate[] }
export type ResultFilterChoice = { key: string; label: string; ambiguous: boolean; score: ScoreView }

export function resultObservation(choice: ResultFilterChoice): ObservationDraft {
  const score = choice.score
  return { id: choice.key, scoreInput: locationKey(score.source), scoreSource: score.source,
    metricId: score.metric.contract_id, methodId: score.method.contract_id, partition: score.source_partition,
    context: score.context_profile, transformId: '', transformParameters: {} }
}

export function resultSelection(value: ObservationDraft): JsonObject {
  return { score_input: value.scoreInput, metric_id: value.metricId, method_id: value.methodId,
    source_partition: value.partition, context: value.context,
    ...(value.reference ? { reference: value.reference } : {}),
    ...(value.exactContexts !== undefined ? { exact_contexts: value.exactContexts } : {}) }
}

export function resultCondition(value: Predicate, choices: ResultFilterChoice[]): JsonObject | undefined {
  if (value.kind === 'group') return value.children.length ? { kind: 'group', operator: value.operator, children: value.children.map(child => resultCondition(child, choices)) } : undefined
  const choice = choices.find(choice => choice.key === value.selectorId)
  if (!choice) throw new Error('所选评价来源当前不可用；本次临时筛选和排序未应用。')
  return { kind: 'comparison', selection: resultSelection(value.selection ?? resultObservation(choice)), operator: value.operator, threshold: value.threshold }
}

export function filterComplete(value: Predicate, root = true): boolean {
  return value.kind === 'comparison' ? value.selectorId !== '' && value.threshold !== undefined
    : (root || value.children.length > 0) && value.children.every(child => filterComplete(child, false))
}
