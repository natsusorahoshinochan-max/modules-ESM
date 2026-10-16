import { useSyncExternalStore } from 'react'
import { candidateResults } from './candidate-results'
import { CandidateWorkbench, type ResultsViewStateStore } from './ResultsWorkbench'
import type { ModuleRunViewerProps } from '../../../webui/src/module-ui'
import { StructureViewer } from '../../../webui/src/StructureViewer'
import type { PublishedStructure, PublishedScientificValue } from '../../../webui/src/protocol/client'
import type { ModuleViewerProps } from '../../../webui/src/module-ui'

function Structure3D({ reading }: ModuleViewerProps) {
  return <section aria-label="已发布结构"><StructureViewer structure={reading.value as PublishedStructure} /></section>
}
function StructureText({ reading }: ModuleViewerProps) {
  return <section aria-label="已发布结构原文"><pre>{(reading.value as PublishedStructure).text}</pre></section>
}
function Sequence({ reading }: ModuleViewerProps) {
  const value = (reading as Extract<PublishedScientificValue, { kind: 'sequence' }>).value
  return <section aria-label="已发布序列"><p>{value.sequence.length} 个序列位置</p><pre className="published-sequence">{value.sequence}</pre>{value.residue_ids === null ? <p>该序列未提供残基身份列表。</p> : <details><summary>查看已发布残基身份</summary><pre>{JSON.stringify(value.residue_ids, null, 2)}</pre></details>}</section>
}
function Candidates({ results, client, ...props }: ModuleRunViewerProps) {
  const reading = candidateResults(results, client)
  const snapshot = useSyncExternalStore(reading.subscribe, reading.getSnapshot)
  return <CandidateWorkbench {...props} viewStateStore={props.viewStateStore as ResultsViewStateStore} results={reading} index={snapshot.index} catalog={{ contracts: snapshot.index.definitions, availability: [] }} loading={snapshot.phase === 'loading'} loadError={snapshot.phase === 'error' ? String(snapshot.error) : ''} />
}
export function register() { return { Structure3D, StructureText, Sequence, Candidates } }
