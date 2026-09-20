import { useEffect, useMemo, useRef, useState } from 'react'
import { StructureViewer } from './StructureViewer'
import { AlignmentComparison } from './AlignmentComparison'
import { PublishedOutputs } from './PublishedOutputs'
import { SelectionEditor } from './SelectionEditor'
import { ResultFilter } from './ResultFilter'
import { remapResultFilter, resultFilterKeys, resultFilterOutcome, resultScoreLookup } from './result-filter'
import { PublicV2Client, type CatalogSnapshot, type ResultCandidateDetail, type RunProjection, type Workflow } from './protocol/client'
import { candidateDetail, candidateViewKey, exportCandidates, locationKey, observationContextSelector, observationKey, referenceKey, scalarObservationChoices, type CandidateView, type ResultIndex, type ScoreView } from './result-explorer'
import type { PublishedResults } from './published-results'
import { saveSelectionDraft, createSelectionDraft, newObservation, sourceKey, type Predicate, type SelectionOperation, type SelectionSource } from './selection-authoring'
import './results.css'

const client = new PublicV2Client()
const errorMessage = (reason: unknown) => reason instanceof Error ? reason.message : JSON.stringify(reason)
const emptyFilter = (): Predicate => ({ kind: 'group', operator: 'and', children: [] })
type SelectionPreview = { originalWorkflow: Workflow; workflow: Workflow; nodeIds: string[]; label: string }

function CandidateDetail({ candidate, run, scores, catalog }: { candidate: CandidateView; run: RunProjection; scores: ScoreView[]; catalog: CatalogSnapshot }) {
  const [detail, setDetail] = useState<ResultCandidateDetail>()
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void candidateDetail(client, run, candidate).then((value) => { if (active) setDetail(value) }, (reason) => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [candidate, run])
  return <article className="result-detail">
    <h3>{candidate.reference.candidate_id}</h3>
    {error ? <p role="alert">{error}</p> : !detail ? <p>加载候选…</p> : <>
      <div className="result-structure">{detail.pdb ? <StructureViewer pdb={detail.pdb} /> : <p>此候选没有结构</p>}</div>
      <h4>序列</h4><code className="sequence-block">{candidate.sequence ?? '尚无已发布序列证据'}</code>
    </>}
    <details><summary>精确数据与来源</summary><pre>{JSON.stringify({ reference: candidate.reference, source: candidate.source, output: candidate.output, metadata: candidate.metadata }, null, 2)}</pre></details>
    {scores.filter((score) => referenceKey(score.subject) === referenceKey(candidate.reference)).map((score, position) => {
      const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'metric' && contract.reference.contract_id === score.metric.contract_id)!.descriptor
      return <section className="result-observation" key={`${observationKey(score)}:${position}`}><strong>{String(descriptor.title ?? score.metric.contract_id)} · {String(descriptor.unit)}</strong><span>{typeof score.value === 'number' ? score.value.toPrecision(6) : JSON.stringify(score.value)}</span><small>{score.method.contract_id} · {String(descriptor.direction)}</small><details><summary>参考、范围、聚合与来源</summary><pre>{JSON.stringify({ context: score.context, definition: descriptor, residue_axis: score.residue_axis, source: score.source }, null, 2)}</pre></details></section>
    })}
  </article>
}

export function ResultsWorkbench({ results, run, index, loading = false, loadError = '', catalog, authoringCatalog, workflow, scienceStatus, onBack, onSaveWorkflow }: { results: PublishedResults; run: RunProjection; index: ResultIndex; loading?: boolean; loadError?: string; catalog: CatalogSnapshot; authoringCatalog: CatalogSnapshot; workflow: Workflow; scienceStatus: 'current' | 'stale' | 'unknown'; onBack: () => void; onSaveWorkflow: (workflow: Workflow) => Promise<void> }) {
  const collections = index.collections
  const stageRevision = useRef(0)
  const [stageKey, setStageKey] = useState('')
  const [focusedKey, setFocusedKey] = useState<string>()
  const [checked, setChecked] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('')
  const [descending, setDescending] = useState(true)
  const [predicate, setPredicate] = useState<Predicate>(emptyFilter)
  const [page, setPage] = useState(0)
  const [compare, setCompare] = useState(false)
  const [preview, setPreview] = useState<SelectionPreview>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const collection = collections.find((entry) => locationKey(entry.source) === stageKey) ?? collections[0]
  const allCandidates = useMemo(() => collections.flatMap((entry) => entry.items), [collections])
  const byKey = useMemo(() => new Map(allCandidates.map((candidate) => [candidateViewKey(candidate), candidate])), [allCandidates])
  const selected = useMemo(() => checked.flatMap((key) => byKey.has(key) ? [byKey.get(key)!] : []), [byKey, checked])
  const scoreLookup = useMemo(() => resultScoreLookup(index.scores), [index.scores])
  const scoreChoices = useMemo(() => scalarObservationChoices(index.scores).map((choice) => ({ ...choice, label: `${choice.score.metric.contract_id} · ${choice.score.method.contract_id} · ${choice.score.source.node_id}/${choice.score.source.output_port} · ${choice.score.source_partition} · ${JSON.stringify(observationContextSelector(choice.score.context))}${choice.ambiguous ? '（每个候选存在多项观察）' : ''}` })), [index.scores])
  const filteredOutcomes = useMemo(() => new Map((collection?.items ?? []).map((candidate) => [candidateViewKey(candidate), resultFilterOutcome(predicate, candidate.reference, scoreLookup)])), [collection, predicate, scoreLookup])
  const missingObservations = [...filteredOutcomes.values()].filter((value) => value === null).length
  const candidates = useMemo(() => {
    const filtered = (collection?.items ?? []).filter((candidate) => filteredOutcomes.get(candidateViewKey(candidate)) === true && `${candidate.reference.candidate_id} ${candidate.sequence ?? ''} ${JSON.stringify(candidate.metadata)}`.toLowerCase().includes(search.toLowerCase()))
    if (!sort) return filtered
    const values = scoreLookup.get(sort)
    return filtered.sort((left, right) => {
      const leftScores = values?.get(referenceKey(left.reference)); const rightScores = values?.get(referenceKey(right.reference))
      const a = leftScores?.length === 1 ? leftScores[0].value as number : undefined
      const b = rightScores?.length === 1 ? rightScores[0].value as number : undefined
      if (a === undefined) return b === undefined ? 0 : 1
      if (b === undefined) return -1
      return (descending ? b - a : a - b) || left.reference.candidate_id.localeCompare(right.reference.candidate_id)
    })
  }, [collection, descending, filteredOutcomes, scoreLookup, search, sort])
  const visible = new Set(candidates.map(candidateViewKey))
  const hidden = selected.filter((candidate) => !visible.has(candidateViewKey(candidate))).length
  const focusedCandidate = (focusedKey ? byKey.get(focusedKey) : undefined) ?? candidates[0]
  const parents = focusedCandidate ? [...new Map(allCandidates.filter((candidate) => focusedCandidate.parent_ids.includes(candidate.reference.candidate_id)).map((candidate) => [referenceKey(candidate.reference), candidate])).values()] : []
  const action = async (work: () => Promise<void>) => { setBusy(true); setError(''); try { await work() } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) } }

  const complete = collection !== undefined && collection.items.length === collection.total
  async function exportSelected() {
    const selectedKeys = new Set(checked)
    const snapshot = await results.ensureCandidates({ all: true })
    if (!snapshot?.run) return
    const candidates = snapshot.index.collections.flatMap((entry) => entry.items).filter((candidate) => selectedKeys.has(candidateViewKey(candidate)))
    await exportCandidates(client, candidates, snapshot.index, snapshot.run, { ...catalog, contracts: snapshot.index.definitions }, scienceStatus)
  }
  async function nextPage() {
    if (!collection) return
    const revision = stageRevision.current
    const snapshot = await results.ensureCandidates({ source: collection.source, count: (page + 2) * 50 })
    if (snapshot && revision === stageRevision.current) setPage(page + 1)
  }

  async function prepareSelection(operation: SelectionOperation) {
    const selectedKeys = new Set(checked)
    const source = collection?.source
    const snapshot = await results.ensureCandidates({ all: true })
    if (!snapshot) return
    const selected = snapshot.index.collections.flatMap((entry) => entry.items).filter((candidate) => selectedKeys.has(candidateViewKey(candidate)))
    const completeCollection = snapshot.index.collections.find((entry) => source && locationKey(entry.source) === locationKey(source))
    const choices = scalarObservationChoices(snapshot.index.scores)
    let next = workflow
    const groups = new Map<string, { source: SelectionSource; values: CandidateView[] }>()
    if (operation === 'manual') for (const candidate of selected) {
      const source = { node_id: candidate.source.node_id, output_port: candidate.source.output_port }
      const key = sourceKey(source)
      groups.set(key, { source, values: [...(groups.get(key)?.values ?? []), candidate] })
    }
    else if (completeCollection) groups.set(sourceKey(completeCollection.source), { source: { node_id: completeCollection.source.node_id, output_port: completeCollection.source.output_port }, values: completeCollection.items })
    const nodeIds: string[] = []
    for (const { source, values } of groups.values()) {
      if (!workflow.nodes.some((node) => node.node_id === source.node_id)) throw new Error('候选来源已不在当前流程中，请先恢复来源节点。')
      const nodeId = `selection-${crypto.randomUUID()}`
      const draft = createSelectionDraft(operation, { node_id: source.node_id, output_port: source.output_port })
      if (operation === 'manual') draft.selectedCandidates = [...new Map(values.map((value) => [referenceKey(value.reference), value.reference])).values()]
      else {
        draft.outOfScope = 'ignore'
        const keys = operation === 'filter' ? [...new Set(resultFilterKeys(predicate))] : sort ? [sort] : []
        const ids = new Map<string, string>()
        draft.observations = keys.map((key) => {
          const score = choices.find((choice) => choice.key === key)!.score
          const observation = { ...newObservation(), scoreSource: { node_id: score.source.node_id, output_port: score.source.output_port }, metricId: score.metric.contract_id, methodId: score.method.contract_id, partition: score.source_partition, context: observationContextSelector(score.context) }
          ids.set(key, observation.id)
          return observation
        })
        if (operation === 'filter') draft.predicate = remapResultFilter(predicate, ids)
      }
      next = saveSelectionDraft(next, nodeId, draft)
      nodeIds.push(nodeId)
    }
    setPreview({ originalWorkflow: workflow, workflow: next, nodeIds, label: operation === 'manual' ? '勾选候选' : operation === 'filter' ? '条件筛选' : '排序并取前 N 个' })
  }

  function updatePreview(next: Workflow) { setPreview((current) => current ? { ...current, workflow: next } : current) }
  const preparedWorkflow = preview?.workflow
  const addedNodes = preparedWorkflow?.nodes.filter((node) => !preview!.originalWorkflow.nodes.some((entry) => entry.node_id === node.node_id)) ?? []

  return <div className="results-explorer">
    <aside><button onClick={onBack}>返回 Workflow</button><h2>已发布结果</h2><p>{run.status}</p><p>{scienceStatus === 'current' ? '结果与当前科学流程一致' : scienceStatus === 'stale' ? '结果来自已修改的流程' : '结果一致性待确认'}</p><small>Run {run.run_id}<br />Commit {run.workflow_commit_id}</small><nav>{collections.map((entry) => <button className={collection === entry ? 'active' : ''} key={locationKey(entry.source)} onClick={() => { stageRevision.current += 1; setStageKey(locationKey(entry.source)); setFocusedKey(undefined); setPage(0); setSearch(''); setSort(''); setPredicate(emptyFilter()) }}>{entry.title}<strong>{entry.total}</strong></button>)}</nav></aside>
    <main aria-busy={loading && !loadError}><header><h1>{collection?.title ?? (loadError ? '结果读取失败' : loading ? '已发布结果' : '尚无已发布候选')}</h1><div><button disabled={!selected.length || busy} onClick={() => setCompare(!compare)}>{compare ? '关闭比较' : `并排比较 (${selected.length})`}</button><button disabled={!selected.length || busy} onClick={() => void action(() => prepareSelection('manual'))}>勾选保存为流程</button><button disabled={!selected.length || busy} onClick={() => void action(exportSelected)}>导出所选 · ZIP</button></div></header>
      {error && <p role="alert">{error}</p>}
      {loadError && <p role="alert">{loadError}</p>}
      {loading && !collection && !loadError && <p role="status">正在加载已发布结果…</p>}
      <details><summary>全部已发布类型值与附件</summary><PublishedOutputs run={run} /></details>
      {collection && !complete && <p>已加载 {collection.items.length} / {collection.total} 个候选。<button disabled={busy} onClick={() => void action(async () => { await results.ensureCandidates({ source: collection.source, count: 'all' }) })}>加载全部候选以搜索、筛选和排序</button></p>}
      <fieldset disabled={!complete || busy}><div className="result-controls"><label>搜索候选或序列<input value={search} onChange={(event) => { setSearch(event.target.value); setPage(0) }} /></label><label>临时排序<select value={sort} onChange={(event) => { setSort(event.target.value); setPage(0) }}><option value="">原始顺序</option>{scoreChoices.map(({ key, label, ambiguous }) => <option key={key} value={key} disabled={ambiguous}>{label}</option>)}</select></label><button onClick={() => setDescending(!descending)}>{descending ? '降序' : '升序'}</button><button disabled={!collection || busy} onClick={() => void action(async () => prepareSelection('top_k'))}>配置排序并取前 N 个</button><span>{selected.length} 已勾选 · {hidden} 项不在当前视图</span></div>
      <details><summary>临时条件筛选 · 支持 AND/OR 分组</summary><ResultFilter value={predicate} choices={scoreChoices} onChange={(next) => { setPredicate(next); setPage(0) }} /><button onClick={() => { setPredicate(emptyFilter()); setPage(0) }}>清除条件</button><button disabled={!collection || !resultFilterKeys(predicate).length || busy} onClick={() => void action(async () => prepareSelection('filter'))}>条件保存为流程</button><p>搜索文字仅改变显示；保存条件保留完整分组，空组不产生条件。{missingObservations > 0 && `${missingObservations} 个候选缺少唯一匹配观察值或条件未填写，当前未显示；保存为流程后遵守缺失即报错的合同。`}</p></details>
      </fieldset><section className="result-table"><div className="result-table-heading"><span>勾选</span><span>Candidate</span><span>类型 / 长度</span><span>全部 parents</span></div>{candidates.slice(page * 50, (page + 1) * 50).map((candidate) => {
        const key = candidateViewKey(candidate)
        return <div key={key} className={focusedCandidate && candidateViewKey(focusedCandidate) === key ? 'active' : ''}><input type="checkbox" aria-label={`勾选 ${candidate.reference.candidate_id}`} checked={checked.includes(key)} onChange={(event) => setChecked((current) => event.target.checked ? [...current, key] : current.filter((value) => value !== key))} /><button onClick={() => { setFocusedKey(key); setCompare(false) }}>{candidate.reference.candidate_id}</button><span>{candidate.has_structure ? '结构' : '序列'} · {candidate.sequence?.length ?? '尚无序列证据'}</span><span>{candidate.parent_ids.map((id) => <code key={id}>{id}</code>)}</span></div>
      })}</section>
      {collection && <footer><button disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>{page + 1} / {Math.max(1, Math.ceil((complete ? candidates.length : collection.total) / 50))} · {complete ? candidates.length : collection.total} 候选</span><button disabled={busy || (page + 1) * 50 >= (complete ? candidates.length : collection.total)} onClick={() => void action(nextPage)}>下一页</button></footer>}
      {focusedCandidate && <section className="result-lineage"><strong>直接父候选</strong>{parents.map((parent) => <button key={referenceKey(parent.reference)} onClick={() => { setFocusedKey(candidateViewKey(parent)); setCompare(false) }}>{parent.reference.candidate_id} · {parent.reference.data_type_id}</button>)}{focusedCandidate.parent_ids.filter((id) => !parents.some((parent) => parent.reference.candidate_id === id)).map((id) => <span key={id}>{id}（尚未加载其数据）</span>)}</section>}
      <div className="result-comparison">{(compare ? selected.slice(0, 4) : focusedCandidate ? [focusedCandidate] : []).map((candidate) => <CandidateDetail key={candidateViewKey(candidate)} candidate={candidate} run={run} scores={index.scores} catalog={catalog} />)}</div>{compare && selected.length > 4 && <p>当前显示前 4 个勾选项；减少勾选可比较其他候选。</p>}
      {compare && <AlignmentComparison alignments={index.alignments} candidates={selected} run={run} />}
    </main>
    {preview && <div className="result-selection-backdrop"><section className="result-selection-dialog" role="dialog" aria-modal="true" aria-label="保存流程操作预览"><h2>{preview.label} · 将新增 {addedNodes.length} 个可编辑节点</h2><p>当前 Run {run.run_id} 的结果保持可查看。在此编辑新增节点，确认后整体保存到 Draft。</p>{preview.label === '排序并取前 N 个' && <p>流程排名使用明确选择的 Utility Transform 和 N；请确认它表达所需排名方向。临时原值排序不会代替此科学配置。</p>}
      <section aria-label="将新增的流程节点"><h3>新增节点及来源</h3><ul>{addedNodes.map((node) => <li key={node.node_id}><strong>{String(authoringCatalog.contracts.find((entry) => entry.reference.contract_kind === 'node_type' && entry.reference.contract_id === node.node_type_id)?.descriptor.title ?? node.node_type_id)}</strong> · {node.node_id}<ul>{preparedWorkflow!.edges.filter((edge) => edge.target_node_id === node.node_id).map((edge) => <li key={JSON.stringify(edge)}>{edge.source_node_id} / {edge.source_port} → {edge.target_port}</li>)}</ul></li>)}</ul></section>
      {preview.nodeIds.map((nodeId) => <SelectionEditor key={nodeId} catalog={authoringCatalog} workflow={preview.workflow} nodeId={nodeId} candidateCollections={collections.map((entry) => ({ source: entry.source, items: entry.items }))} onChange={updatePreview} onDraftChange={updatePreview} />)}
      <footer><button disabled={busy} onClick={() => void action(async () => { await onSaveWorkflow(preparedWorkflow!); setPreview(undefined) })}>确认保存到流程</button><button disabled={busy} onClick={() => setPreview(undefined)}>取消</button></footer>
    </section></div>}
  </div>
}
