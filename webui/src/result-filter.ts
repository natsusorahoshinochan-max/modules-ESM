import type { CandidateReference } from './protocol/client'
import { referenceKey, uniqueScalarObservation, type ResultIndex } from './result-explorer'
import type { Predicate } from './selection-authoring'

export type ResultFilterChoice = { key: string; label: string; ambiguous: boolean }
export type ResultScoreLookup = ResultIndex['observations']

export function resultFilterOutcome(predicate: Predicate, reference: CandidateReference, scores: ResultScoreLookup): boolean | null {
  if (predicate.kind === 'group') {
    const results = predicate.children.filter((child) => resultFilterKeys(child).length > 0).map((child) => resultFilterOutcome(child, reference, scores))
    if (results.length === 0) return true
    if (results.includes(null)) return null
    return predicate.operator === 'and' ? results.every(Boolean) : results.some(Boolean)
  }
  const matches = scores.get(predicate.selectorId)?.subjects.get(referenceKey(reference)) ?? []
  const value = uniqueScalarObservation(matches)
  if (predicate.threshold === undefined || value === undefined) return null
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
