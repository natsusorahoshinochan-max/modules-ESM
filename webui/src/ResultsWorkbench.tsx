import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { StructureViewer } from './StructureViewer'
import { AlignmentComparison } from './AlignmentComparison'
import { PublishedOutputs } from './PublishedOutputs'
import { SelectionEditor } from './SelectionEditor'
import { ResultFilter } from './ResultFilter'
import { InteractionDialog } from './InteractionDialog'
import { remapResultFilter, resultFilterKeys, resultFilterOutcome } from './result-filter'
import { type CatalogSnapshot, type ResultLocation, type RunProjection, type Workflow } from './protocol/client'
import { candidateViewKey, exportCandidates, locationKey, observationKey, referenceKey, scalarObservationChoices, uniqueScalarObservation, type CandidateView, type ResultIndex, type ScoreView } from './result-explorer'
import type { PublishedResults } from './published-results'
import type { WorkspaceEditSession } from './workspace-editor'
import { saveSelectionDraft, createSelectionDraft, newObservation, sourceKey, type Predicate, type SelectionOperation, type SelectionSource } from './selection-authoring'
import './results.css'

const errorMessage = (reason: unknown) => reason instanceof Error ? reason.message : JSON.stringify(reason)
const emptyFilter = (): Predicate => ({ kind: 'group', operator: 'and', children: [] })
const filterComplete = (filter: Predicate): boolean => filter.kind === 'group' ? filter.children.every(filterComplete) : filter.selectorId !== '' && filter.threshold !== undefined
type SelectionPreview = { session: WorkspaceEditSession; originalWorkflow: Workflow; workflow: Workflow; nodeIds: string[]; label: string }
type ResultsViewState = {
  stageKey: string; focusedKey?: string; checked: string[]; search: string; sort: string; descending: boolean
  predicate: Predicate; filterDraft: Predicate; page: number; compare: boolean; comparisonKeys: string[]; basketOpen: boolean
  mainScroll: number; listScroll: number; detailScroll: number
  loadedCollections: { source: ResultLocation; count: number }[]
}
export type ResultsViewStateStore = Map<string, ResultsViewState>

function CandidateDetail({ candidate, results, scores, catalog }: { candidate: CandidateView; results: PublishedResults; scores: ScoreView[]; catalog: CatalogSnapshot }) {
  const [pdb, setPdb] = useState<string | null>()
  const key = candidateViewKey(candidate)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void results.structure(key).then((value) => { if (active) setPdb(value) }, (reason) => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [key, results])
  return <article className="result-detail">
    <h3>{candidate.reference.candidate_id}</h3>
    {error ? <p role="alert">{error}</p> : pdb === undefined ? <p>加载候选…</p> : <>
      {pdb !== null ? <div className="result-structure"><StructureViewer pdb={pdb} /></div> : <p>此候选没有结构</p>}
      <h4>序列</h4><code className="sequence-block">{candidate.sequence ?? '尚无已发布序列证据'}</code>
    </>}
    <details><summary>精确数据与来源</summary><pre>{JSON.stringify({ reference: candidate.reference, source: candidate.source, output: candidate.output, metadata: candidate.metadata }, null, 2)}</pre></details>
    {scores.map((score, position) => {
      const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'metric' && contract.reference.contract_id === score.metric.contract_id)!.descriptor
      return <section className="result-observation" key={`${observationKey(score)}:${position}`}><strong>{String(descriptor.title ?? score.metric.contract_id)} · {String(descriptor.unit)}</strong><span>{typeof score.value === 'number' ? score.value.toPrecision(6) : JSON.stringify(score.value)}</span><small>{score.method.contract_id} · {String(descriptor.direction)}</small><details><summary>参考、范围、聚合与来源</summary><pre>{JSON.stringify({ context: score.context, definition: descriptor, residue_axis: score.residue_axis, source: score.source }, null, 2)}</pre></details></section>
    })}
  </article>
}

export function ResultsWorkbench({ results, run, index, loading = false, loadError = '', catalog, authoringCatalog, scienceStatus, onBack, onBeginEdit, onSaveWorkflow, saveError, onRetrySave, viewStateStore, workspaceProjectId, runControls, active = true }: { results: PublishedResults; run: RunProjection; index: ResultIndex; loading?: boolean; loadError?: string; catalog: CatalogSnapshot; authoringCatalog: CatalogSnapshot; scienceStatus: 'current' | 'stale' | 'unknown'; onBack: () => void; onBeginEdit: () => Promise<WorkspaceEditSession | undefined>; onSaveWorkflow: (session: WorkspaceEditSession, workflow: Workflow) => Promise<unknown>; saveError: string; onRetrySave: () => Promise<unknown>; viewStateStore?: ResultsViewStateStore; workspaceProjectId?: string; runControls?: ReactNode; active?: boolean }) {
  const collections = index.collections
  const stageRevision = useRef(0)
  const viewKey = JSON.stringify([workspaceProjectId ?? run.project_id, run.project_id, run.run_id])
  const [restored] = useState(() => viewStateStore?.get(viewKey))
  const [stageKey, setStageKey] = useState(restored?.stageKey ?? '')
  const [focusedKey, setFocusedKey] = useState<string | undefined>(restored?.focusedKey)
  const [checked, setChecked] = useState<string[]>(restored?.checked ?? [])
  const [search, setSearch] = useState(restored?.search ?? '')
  const [sort, setSort] = useState(restored?.sort ?? '')
  const [descending, setDescending] = useState(restored?.descending ?? true)
  const [predicate, setPredicate] = useState<Predicate>(restored?.predicate ?? emptyFilter())
  const [filterDraft, setFilterDraft] = useState<Predicate>(restored?.filterDraft ?? emptyFilter())
  const [page, setPage] = useState(restored?.page ?? 0)
  const [compare, setCompare] = useState(restored?.compare ?? false)
  const [comparisonKeys, setComparisonKeys] = useState<string[]>(restored?.comparisonKeys ?? [])
  const [basketOpen, setBasketOpen] = useState(restored?.basketOpen ?? false)
  const mainRef = useRef<HTMLElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const detailRef = useRef<HTMLElement>(null)
  const previewTrigger = useRef<HTMLButtonElement>(null)
  const [preview, setPreview] = useState<SelectionPreview>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const collection = collections.find((entry) => locationKey(entry.source) === stageKey) ?? collections[0]
  const byKey = index.candidates
  const selected = useMemo(() => checked.flatMap((key) => byKey.has(key) ? [byKey.get(key)!] : []), [byKey, checked])
  const compared = useMemo(() => comparisonKeys.flatMap((key) => byKey.has(key) ? [byKey.get(key)!] : []), [byKey, comparisonKeys])
  const scoreLookup = index.observations
  const scoreChoices = useMemo(() => scalarObservationChoices(index).map((choice) => ({ ...choice, label: `${choice.score.metric.contract_id} · ${choice.score.method.contract_id} · ${choice.score.source.node_id}/${choice.score.source.output_port} · ${choice.score.source_partition} · ${JSON.stringify(choice.score.context_profile)}${choice.ambiguous ? '（每个候选存在多项观察）' : ''}` })), [index])
  const filteredOutcomes = useMemo(() => new Map((collection?.items ?? []).map((candidate) => [candidateViewKey(candidate), resultFilterOutcome(predicate, candidate.reference, scoreLookup)])), [collection, predicate, scoreLookup])
  const missingObservations = [...filteredOutcomes.values()].filter((value) => value === null).length
  const candidates = useMemo(() => {
    const filtered = (collection?.items ?? []).filter((candidate) => filteredOutcomes.get(candidateViewKey(candidate)) === true && `${candidate.reference.candidate_id} ${candidate.sequence ?? ''} ${JSON.stringify(candidate.metadata)}`.toLowerCase().includes(search.toLowerCase()))
    if (!sort) return filtered
    const values = scoreLookup.get(sort)?.subjects
    return filtered.sort((left, right) => {
      const leftScores = values?.get(referenceKey(left.reference)); const rightScores = values?.get(referenceKey(right.reference))
      const a = uniqueScalarObservation(leftScores)
      const b = uniqueScalarObservation(rightScores)
      if (a === undefined) return b === undefined ? 0 : 1
      if (b === undefined) return -1
      return (descending ? b - a : a - b) || left.reference.candidate_id.localeCompare(right.reference.candidate_id)
    })
  }, [collection, descending, filteredOutcomes, scoreLookup, search, sort])
  const visible = new Set(candidates.map(candidateViewKey))
  const hidden = selected.filter((candidate) => !visible.has(candidateViewKey(candidate))).length
  const focusedCandidate = (focusedKey ? byKey.get(focusedKey) : undefined) ?? candidates[0]
  const pageCandidates = candidates.slice(page * 50, (page + 1) * 50)
  const onPage = new Set(pageCandidates.map(candidateViewKey))
  const offPageChecked = selected.filter((candidate) => !onPage.has(candidateViewKey(candidate))).length
  const parents = focusedCandidate ? [...new Map(focusedCandidate.parent_ids.flatMap(id => index.parentCandidates.get(id) ?? []).map(candidate => [referenceKey(candidate.reference), candidate])).values()] : []
  const action = async (work: () => Promise<void>) => { setBusy(true); setError(''); try { await work() } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) } }

  const complete = collection !== undefined && collection.items.length === collection.total
  const filterPending = JSON.stringify(filterDraft) !== JSON.stringify(predicate)
  function clearFilter() { const empty = emptyFilter(); setPredicate(empty); setFilterDraft(empty); setPage(0) }
  function rememberView() {
    const previous = viewStateStore?.get(viewKey) ?? restored
    const recordScroll = active && scrollRestored.current
    const loadedCollections = new Map(previous?.loadedCollections.map(request => [locationKey(request.source), request]) ?? [])
    for (const entry of collections) loadedCollections.set(locationKey(entry.source), { source: entry.source, count: Math.max(entry.items.length, loadedCollections.get(locationKey(entry.source))?.count ?? 0) })
    viewStateStore?.set(viewKey, { stageKey: stageKey || (collection ? locationKey(collection.source) : ''), focusedKey, checked, search, sort, descending, predicate, filterDraft, page, compare, comparisonKeys, basketOpen, mainScroll: recordScroll ? mainRef.current?.scrollTop ?? 0 : previous?.mainScroll ?? 0, listScroll: recordScroll ? listRef.current?.scrollTop ?? 0 : previous?.listScroll ?? 0, detailScroll: recordScroll ? detailRef.current?.scrollTop ?? 0 : previous?.detailScroll ?? 0, loadedCollections: [...loadedCollections.values()] })
  }
  useEffect(rememberView)
  const scrollRestored = useRef(false)
  useLayoutEffect(() => {
    if (!active) { scrollRestored.current = false; return }
    if (scrollRestored.current || !collection || stageKey && locationKey(collection.source) !== stageKey || collection.items.length < Math.min(collection.total, (page + 1) * 50)) return
    const previous = viewStateStore?.get(viewKey) ?? restored
    scrollRestored.current = true
    if (mainRef.current) mainRef.current.scrollTop = previous?.mainScroll ?? 0
    if (listRef.current) listRef.current.scrollTop = previous?.listScroll ?? 0
    if (detailRef.current) detailRef.current.scrollTop = previous?.detailScroll ?? 0
  }, [active, restored, collection, page, stageKey, viewKey, viewStateStore])

  // A returning Run initially contains only its first pages. Restore this view's
  // requested range through the same reading owner used by ordinary navigation.
  const restoredRequested = useRef(false)
  useEffect(() => {
    if (!restored || !collections.length || restoredRequested.current) return
    restoredRequested.current = true
    void Promise.all(restored.loadedCollections.map(request => results.ensureCandidates(request))).catch(reason => setError(errorMessage(reason)))
  }, [restored, collections, results])

  function focusCandidate(candidate: CandidateView) {
    setFocusedKey(candidateViewKey(candidate))
    if (detailRef.current) detailRef.current.scrollTop = 0
  }
  function revealCandidate(candidate: CandidateView) {
    stageRevision.current += 1
    setStageKey(locationKey(candidate.source))
    setSearch(''); setSort(''); clearFilter(); setCompare(false)
    setPage(Math.floor(candidate.item_index / 50))
    focusCandidate(candidate)
    if (listRef.current) listRef.current.scrollTop = 0
  }
  function openComparison() {
    if (!compare && !comparisonKeys.some(Boolean) && focusedCandidate) setComparisonKeys([candidateViewKey(focusedCandidate)])
    setCompare(!compare)
  }
  async function exportSelected() {
    const material = await results.prepareExport(checked)
    if (material) exportCandidates(material, scienceStatus)
  }
  async function nextPage() {
    if (!collection) return
    const revision = stageRevision.current
    const snapshot = await results.ensureCandidates({ source: collection.source, count: (page + 2) * 50 })
    if (snapshot && revision === stageRevision.current) setPage(page + 1)
  }

  async function prepareSelection(operation: SelectionOperation) {
    const session = await onBeginEdit()
    if (!session) return
    const workflow = session.base.workflow
    const selectedKeys = new Set(checked)
    const source = collection?.source
    const snapshot = await results.ensureCandidates({ all: true })
    if (!snapshot) return
    const selected = snapshot.index.collections.flatMap((entry) => entry.items).filter((candidate) => selectedKeys.has(candidateViewKey(candidate)))
    const completeCollection = snapshot.index.collections.find((entry) => source && locationKey(entry.source) === locationKey(source))
    const choices = scalarObservationChoices(snapshot.index)
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
          const observation = { ...newObservation(), scoreSource: { node_id: score.source.node_id, output_port: score.source.output_port }, metricId: score.metric.contract_id, methodId: score.method.contract_id, partition: score.source_partition, context: score.context_profile }
          ids.set(key, observation.id)
          return observation
        })
        if (operation === 'filter') draft.predicate = remapResultFilter(predicate, ids)
      }
      next = saveSelectionDraft(next, nodeId, draft)
      nodeIds.push(nodeId)
    }
    setPreview({ session, originalWorkflow: workflow, workflow: next, nodeIds, label: operation === 'manual' ? '勾选候选' : operation === 'filter' ? '条件筛选' : '排序并取前 N 个' })
  }

  function updatePreview(next: Workflow) { setPreview((current) => current ? { ...current, workflow: next } : current) }
  function restorePreviewFocus() {
    const trigger = previewTrigger.current
    if (trigger?.isConnected && trigger.getClientRects().length > 0 && !trigger.matches(':disabled') && !trigger.closest('[inert]')) trigger.focus()
    else if (mainRef.current?.getClientRects().length) mainRef.current.focus()
  }
  const preparedWorkflow = preview?.workflow
  const addedNodes = preparedWorkflow?.nodes.filter((node) => !preview!.originalWorkflow.nodes.some((entry) => entry.node_id === node.node_id)) ?? []

  return <div className="results-explorer">
    <aside className="result-stages"><button onClick={onBack}>返回 Workflow</button><h2>已发布结果</h2><p>{run.status}</p><p>{scienceStatus === 'current' ? '结果与当前科学流程一致' : scienceStatus === 'stale' ? '结果来自已修改的流程' : '结果一致性待确认'}</p><small>Run {run.run_id}<br />Commit {run.workflow_commit_id}</small><nav aria-label="结果阶段">{collections.map((entry) => <button className={collection === entry ? 'active' : ''} aria-current={collection === entry ? 'true' : undefined} key={locationKey(entry.source)} onClick={() => { stageRevision.current += 1; setStageKey(locationKey(entry.source)); setFocusedKey(undefined); setPage(0); setSearch(''); setSort(''); clearFilter(); if (listRef.current) listRef.current.scrollTop = 0 }}>{entry.title}<strong>{entry.total}</strong></button>)}</nav></aside>
    <main ref={mainRef} tabIndex={-1} aria-label="已发布结果工作区" onScroll={rememberView} aria-busy={loading && !loadError}>
      {runControls && <div className="result-run-controls">{runControls}</div>}
      <header><h1>{collection?.title ?? (loadError ? '结果读取失败' : loading ? '已发布结果' : '尚无已发布候选')}</h1><div><button disabled={!byKey.size || busy} onClick={openComparison}>{compare ? '关闭比较' : `并排比较 (${comparisonKeys.filter(Boolean).length})`}</button><button aria-expanded={basketOpen} onClick={() => setBasketOpen(!basketOpen)}>查看已选 ({checked.length})</button><button disabled={!selected.length || busy} onClick={event => { previewTrigger.current = event.currentTarget; void action(() => prepareSelection('manual')) }}>勾选保存为流程</button><button disabled={!selected.length || busy} onClick={() => void action(exportSelected)}>导出所选 · ZIP</button></div></header>
      {error && <p role="alert">{error}</p>}
      {saveError && <p role="alert">{saveError}<button onClick={() => void action(async () => { await onRetrySave(); setPreview(undefined) })}>重试保存</button></p>}
      {loadError && <p role="alert">{loadError}</p>}
      {loading && !collection && !loadError && <p role="status">正在加载已发布结果…</p>}
      {busy && <p role="status">正在读取或准备所选操作…</p>}
      {basketOpen && <section className="result-basket" aria-label="已选候选清单"><header><h2>已选候选 · {checked.length}</h2><button disabled={!checked.length || busy} onClick={() => setChecked([])}>清空全部勾选</button></header><p>勾选用于导出和保存到流程；比较位置单独管理。{offPageChecked} 项不在当前页。</p>{checked.length === 0 ? <p>尚未勾选候选。</p> : <ul>{checked.map(key => {
        const candidate = byKey.get(key)
        return <li key={key}>{candidate ? <><button onClick={() => revealCandidate(candidate)}>{candidate.reference.candidate_id}</button><small>{candidate.source.node_id} / {candidate.source.output_port} · 第 {candidate.item_index + 1} 项</small></> : <span>正在恢复已选候选…</span>}<button aria-label={`移除勾选 ${candidate?.reference.candidate_id ?? key}`} disabled={busy} onClick={() => setChecked(current => current.filter(item => item !== key))}>移除</button></li>
      })}</ul>}</section>}
      <details><summary>全部已发布类型值与附件</summary><PublishedOutputs run={run} results={results} /></details>
      {collection && !complete && <p>已加载 {collection.items.length} / {collection.total} 个候选。<button disabled={busy} onClick={() => void action(async () => { await results.ensureCandidates({ source: collection.source, count: 'all' }) })}>加载全部候选以搜索、筛选和排序</button></p>}
      <fieldset disabled={!complete || busy}><div className="result-controls"><label>搜索候选或序列<input value={search} onChange={(event) => { setSearch(event.target.value); setPage(0) }} /></label><label>临时排序<select value={sort} onChange={(event) => { setSort(event.target.value); setPage(0) }}><option value="">原始顺序</option>{scoreChoices.map(({ key, label, ambiguous }) => <option key={key} value={key} disabled={ambiguous}>{label}</option>)}</select></label><button onClick={() => setDescending(!descending)}>{descending ? '降序' : '升序'}</button><button disabled={!collection || busy} onClick={event => { previewTrigger.current = event.currentTarget; void action(() => prepareSelection('top_k')) }}>配置排序并取前 N 个</button><span>{selected.length} 已勾选 · {hidden} 项不在当前视图 · {offPageChecked} 项不在当前页</span></div>
      <details><summary>临时条件筛选 · 支持 AND/OR 分组</summary><ResultFilter value={filterDraft} choices={scoreChoices} onChange={setFilterDraft} /><button disabled={!filterComplete(filterDraft) || !filterPending} onClick={() => { setPredicate(filterDraft); setPage(0) }}>应用筛选</button><button disabled={!filterPending} onClick={() => setFilterDraft(predicate)}>放弃条件修改</button><button onClick={clearFilter}>清除条件</button><button disabled={!collection || !resultFilterKeys(predicate).length || busy || filterPending} onClick={event => { previewTrigger.current = event.currentTarget; void action(() => prepareSelection('filter')) }}>条件保存为流程</button><p>{filterPending && (filterComplete(filterDraft) ? '条件已修改，点击“应用筛选”更新列表。' : '条件尚未填写完整；列表继续显示已应用的条件。')}搜索文字仅改变显示；保存条件保留完整分组，空组不产生条件。{missingObservations > 0 && `${missingObservations} 个候选缺少唯一匹配观察值或条件未填写，当前未显示；保存为流程后遵守缺失即报错的合同。`}</p></details>
      </fieldset>
      <div className={`result-workspace ${compare ? 'is-comparing' : ''}`}>
      <section className="result-list-pane" aria-label="候选列表">
      <div className="result-list-scroll" ref={listRef} onScroll={rememberView}><section className="result-table"><div className="result-table-heading"><span>勾选</span><span>Candidate</span><span>类型 / 长度</span><span>全部 parents</span></div>{pageCandidates.map((candidate) => {
        const key = candidateViewKey(candidate)
        return <div key={key} className={focusedCandidate && candidateViewKey(focusedCandidate) === key ? 'active' : ''}><input type="checkbox" aria-label={`勾选 ${candidate.reference.candidate_id}`} checked={checked.includes(key)} onChange={(event) => setChecked((current) => event.target.checked ? [...current, key] : current.filter((value) => value !== key))} /><button aria-pressed={focusedCandidate && candidateViewKey(focusedCandidate) === key} onClick={() => focusCandidate(candidate)}>{candidate.reference.candidate_id}</button><span>{candidate.has_structure ? '结构' : '序列'} · {candidate.sequence?.length ?? '尚无序列证据'}</span><span>{candidate.parent_ids.map((id) => <code key={id}>{id}</code>)}</span></div>
      })}</section>{collection && complete && candidates.length === 0 && <p className="result-empty">{collection.total === 0 ? '此阶段没有已发布候选。' : '没有匹配当前搜索或条件的候选。'}{checked.length > 0 && ` 已保留 ${checked.length} 个勾选项，可在“查看已选”中管理。`}{collection.total > 0 && <button onClick={() => { setSearch(''); clearFilter() }}>清除搜索和条件</button>}</p>}</div>
      {collection && <footer><button disabled={busy || page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>{page + 1} / {Math.max(1, Math.ceil((complete ? candidates.length : collection.total) / 50))} · {complete ? candidates.length : collection.total} 候选</span><button disabled={busy || (page + 1) * 50 >= (complete ? candidates.length : collection.total)} onClick={() => void action(nextPage)}>下一页</button></footer>}
      </section>
      <section className="result-detail-pane" aria-label={compare ? '候选比较' : '候选详情'} ref={detailRef} onScroll={rememberView}>
      {compare && <section className="result-compare-tray" aria-label="比较位置"><h2>比较位置 · 最多 4 个</h2><p>替换或清空位置不改变导出勾选。可选择当前 Run 中已加载的候选。</p><div>{Array.from({ length: 4 }, (_, position) => <label key={position}>位置 {position + 1}<select aria-label={`比较位置 ${position + 1}`} value={comparisonKeys[position] ?? ''} onChange={event => setComparisonKeys(current => { const next = [...current]; next[position] = event.target.value; return next })}><option value="">空位置</option>{[...byKey].map(([key, candidate]) => <option key={key} value={key} disabled={comparisonKeys.includes(key) && comparisonKeys[position] !== key}>{candidate.reference.candidate_id} · {candidate.source.node_id}/{candidate.source.output_port} · #{candidate.item_index + 1}</option>)}</select></label>)}</div>{compared.length === 0 && <p>请选择要比较的候选。</p>}</section>}
      {!compare && focusedCandidate && <><div className="result-detail-source"><strong>正在查看</strong><span>{focusedCandidate.source.node_id} / {focusedCandidate.source.output_port} · 第 {focusedCandidate.item_index + 1} 项</span>{!onPage.has(candidateViewKey(focusedCandidate)) && <><span>此候选不在当前页或筛选结果中。</span><button onClick={() => revealCandidate(focusedCandidate)}>在列表中显示</button></>}</div><section className="result-lineage"><strong>直接父候选</strong>{parents.map((parent) => <button key={referenceKey(parent.reference)} onClick={() => revealCandidate(parent)}>{parent.reference.candidate_id} · {parent.reference.data_type_id}</button>)}{focusedCandidate.parent_ids.filter((id) => !parents.some((parent) => parent.reference.candidate_id === id)).map((id) => <span key={id}>{id}（{index.complete ? '当前 Run 未发布其数据' : '索引尚未完整'}）</span>)}</section></>}
      <div className="result-comparison">{(compare ? compared : focusedCandidate ? [focusedCandidate] : []).map((candidate) => <CandidateDetail key={candidateViewKey(candidate)} candidate={candidate} results={results} scores={index.subjectScores.get(referenceKey(candidate.reference)) ?? []} catalog={catalog} />)}</div>
      {!compare && !focusedCandidate && <p className="result-empty">在候选列表中点击名称查看详情；使用复选框加入导出清单。</p>}
      {compare && <AlignmentComparison alignments={index.alignments} candidates={compared} results={results} />}
      </section></div>
    </main>
    {active && preview && <InteractionDialog title="保存流程操作预览" className="result-selection-dialog" busy={busy} onRestoreFocus={restorePreviewFocus} onClose={() => setPreview(undefined)}><h2>{preview.label} · 将新增 {addedNodes.length} 个可编辑节点</h2><p>当前 Run {run.run_id} 的结果保持可查看。在此编辑新增节点，确认后整体保存到 Draft。</p>{preview.label === '排序并取前 N 个' && <p>流程排名使用明确选择的 Utility Transform 和 N；请确认它表达所需排名方向。临时原值排序不会代替此科学配置。</p>}
      <section aria-label="将新增的流程节点"><h3>新增节点及来源</h3><ul>{addedNodes.map((node) => <li key={node.node_id}><strong>{String(authoringCatalog.contracts.find((entry) => entry.reference.contract_kind === 'node_type' && entry.reference.contract_id === node.node_type_id)?.descriptor.title ?? node.node_type_id)}</strong> · {node.node_id}<ul>{preparedWorkflow!.edges.filter((edge) => edge.target_node_id === node.node_id).map((edge) => <li key={JSON.stringify(edge)}>{edge.source_node_id} / {edge.source_port} → {edge.target_port}</li>)}</ul></li>)}</ul></section>
      {saveError && <p role="alert">{saveError}<button onClick={() => void action(async () => { await onRetrySave(); setPreview(undefined) })}>重试保存</button></p>}
      <div inert={preview.session.submitted} style={{ display: 'contents' }}>{preview.nodeIds.map((nodeId) => <SelectionEditor key={nodeId} catalog={authoringCatalog} workflow={preview.workflow} nodeId={nodeId} candidateCollections={collections.map((entry) => ({ source: entry.source, items: entry.items }))} onChange={updatePreview} onDraftChange={updatePreview} />)}</div>
      <footer><button disabled={busy || preview.session.submitted || !!saveError} onClick={() => void action(async () => { await onSaveWorkflow(preview.session, preparedWorkflow!); setPreview(undefined) })}>确认保存到流程</button><button disabled={busy} onClick={() => setPreview(undefined)}>取消</button></footer>
    </InteractionDialog>}
  </div>
}
