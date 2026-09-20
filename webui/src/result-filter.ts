import type { CandidateReference } from './protocol/client'
import { observationKey, referenceKey, type ScoreView } from './result-explorer'
import type { Predicate } from './selection-authoring'

export type ResultFilterChoice = { key: string; label: string; ambiguous: boolean }
export type ResultScoreLookup = Map<string, Map<string, ScoreView[]>>

export function resultScoreLookup(scores: ScoreView[]): ResultScoreLookup {
  const lookup: ResultScoreLookup = new Map()
  for (const score of scores) {
    const key = observationKey(score)
    const subjects = lookup.get(key) ?? new Map<string, ScoreView[]>()
    const subject = referenceKey(score.subject)
    subjects.set(subject, [...(subjects.get(subject) ?? []), score])
    lookup.set(key, subjects)
  }
  return lookup
}

export function resultFilterOutcome(predicate: Predicate, reference: CandidateReference, scores: ResultScoreLookup): boolean | null {
  if (predicate.kind === 'group') {
    const results = predicate.children.filter((child) => resultFilterKeys(child).length > 0).map((child) => resultFilterOutcome(child, reference, scores))
    if (results.length === 0) return true
    if (results.includes(null)) return null
    return predicate.operator === 'and' ? results.every(Boolean) : results.some(Boolean)
  }
  const matches = scores.get(predicate.selectorId)?.get(referenceKey(reference)) ?? []
  if (predicate.threshold === undefined || matches.length !== 1 || typeof matches[0].value !== 'number') return null
  const value = matches[0].value
  switch (predicate.operator) {
    case '>': return value > predicate.threshold
    case '>=': return value >= predicate.threshold
    case '<': return value < predicate.threshold
    case '<=': return value <= predicate.threshold
    case '==': return value === predicate.threshold
    case '!=': return value !== predicate.threshold
  }
}

export function resultFilterKeys(predicate: Predicate): string[] {
  return predicate.kind === 'comparison' ? [predicate.selectorId] : predicate.children.flatMap(resultFilterKeys)
}

export function remapResultFilter(predicate: Predicate, ids: Map<string, string>): Predicate {
  return predicate.kind === 'comparison' ? { ...predicate, selectorId: ids.get(predicate.selectorId)! } : { ...predicate, children: predicate.children.map((child) => remapResultFilter(child, ids)) }
}

