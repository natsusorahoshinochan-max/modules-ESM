import { useEffect, useState } from 'react'
import { PublicV2Client } from '../../../webui/src/protocol/client'
import type { CatalogSnapshot, JsonObject, PublishedObservation, ResultLocation, Workflow } from '../../../webui/src/protocol/client'
import { sourceKey, type ObservationDraft, type SelectionSource } from './selection-authoring'

export type ObservationOption = {
  key: string; label: string; partition: string; metricId: string;
  methodId: string; context: JsonObject;
}
const client = new PublicV2Client()

/** Context profiles are closed Catalog records containing scalar facts. */
export function sameContext(left: JsonObject, right: JsonObject): boolean {
  return Object.keys(left).length === Object.keys(right).length && Object.entries(left).every(([key, value]) => right[key] === value)
}

function contextKey(context: JsonObject) { return Object.entries(context).sort(([left], [right]) => left.localeCompare(right)) }
export function observationOptionKey(value: Pick<ObservationDraft, 'partition' | 'metricId' | 'methodId' | 'context'>): string {
  return JSON.stringify([value.partition, value.metricId, value.methodId, contextKey(value.context)])
}

export function contractTitle(catalog: CatalogSnapshot, kind: string, id: string): string {
  const descriptor = catalog.contracts.find((entry) => entry.reference.contract_kind === kind && entry.reference.contract_id === id)?.descriptor
  return String(descriptor?.title ?? (descriptor?.algorithm_identity as JsonObject | undefined)?.name ?? id)
}

export function contextLabel(context: JsonObject): string {
  if (context.kind === 'intrinsic') return '候选自身'
  if (context.kind === 'calibration') return `校准：${String(context.calibration_metric)} = ${String(context.calibration_value)} ${String(context.calibration_unit)} · 群体 ${String(context.population_id)}`
  return `${String(context.subject_role)} → ${String(context.reference_role)} · ${context.pairing_mode === 'explicit_relation' ? '显式候选关系' : '固定参考候选'} · 归一化 ${String(context.normalization)}`
}

export function useObservationOptions(workflow: Workflow, catalog: CatalogSnapshot, ranking: boolean, scoreSource?: SelectionSource, published: Array<PublishedObservation & { source: ResultLocation }> = []): { observations: ObservationOption[]; error: string } {
  const [state, setState] = useState<{ observations: ObservationOption[]; error: string }>({ observations: [], error: '' })
  useEffect(() => {
    let active = true
    setState({ observations: [], error: '' })
    if (!scoreSource) return
    void client.observationOptions(workflow, ranking).then(({ options }) => {
      if (!active) return
      const values = options.filter((entry) => sourceKey(entry.source) === sourceKey(scoreSource)).map((entry) => {
        const value = { partition: entry.partition, metricId: entry.metric_id, methodId: entry.method_id, context: entry.context }
        return { ...value, key: observationOptionKey(value), label: `${contractTitle(catalog, 'metric', value.metricId)} · ${contractTitle(catalog, 'method', value.methodId)} · ${contextLabel(value.context)} · ${value.partition}` }
      })
      setState({ observations: [...new Map(values.map((entry) => [entry.key, entry])).values()], error: '' })
    }, (reason: unknown) => { if (active) setState({ observations: [], error: reason instanceof Error ? reason.message : String(reason) }) })
    return () => { active = false }
  }, [workflow, catalog, ranking, scoreSource])
  const existing = published.filter((entry) => scoreSource && sourceKey(entry.source) === sourceKey(scoreSource)).map((entry) => {
    const value = { partition: entry.source_partition, metricId: entry.metric.contract_id, methodId: entry.method.contract_id, context: entry.context_profile }
    return { ...value, key: observationOptionKey(value), label: `${contractTitle(catalog, 'metric', value.metricId)} · ${contractTitle(catalog, 'method', value.methodId)} · ${contextLabel(value.context)} · ${value.partition}` }
  })
  return { error: state.error, observations: [...new Map([...state.observations, ...existing].map((entry) => [entry.key, entry])).values()] }
}

export function chooseObservation(value: ObservationDraft, option: ObservationOption): ObservationDraft {
  return { ...value, metricId: option.metricId, methodId: option.methodId, partition: option.partition, context: { ...option.context }, transformId: '', transformParameters: {}, reference: undefined, exactContexts: undefined, relationInput: undefined, relationSource: undefined }
}

export function effectiveWeightPercentages(observations: ObservationDraft[]): Array<number | undefined> {
  if (observations.some((entry) => entry.weight === undefined || !Number.isFinite(entry.weight) || entry.weight < 0)) return observations.map(() => undefined)
  const total = observations.reduce((sum, entry) => sum + entry.weight!, 0)
  return observations.map((entry) => Number.isFinite(total) && total > 0 ? entry.weight! / total * 100 : undefined)
}
