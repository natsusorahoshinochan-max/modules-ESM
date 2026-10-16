import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { StructureComponents } from './StructureComponents'
import { StructureViewer } from '../../../webui/src/StructureViewer'
import { AlignmentComparison } from './AlignmentComparison'
import { ResultFilter, ResultObservationEditor } from './ResultFilter'
import { filterComplete, resultCondition, resultObservation, resultSelection, type Predicate } from './result-filter'
import { type PublishedStructure, type CatalogSnapshot, type ResultLocation, type RunProjection } from '../../../webui/src/protocol/client'
import { candidateViewKey, exportCandidates, locationKey, observationKey, referenceKey, scalarObservationChoices, type CandidateView, type ResultIndex, type ScoreView } from './result-explorer'
import type { CandidateResults } from './candidate-results'
import type { ObservationDraft } from '../../selection/ui/selection-authoring'
import '../../../webui/src/results.css'

const errorMessage = (reason: unknown) => reason instanceof Error ? reason.message : JSON.stringify(reason)
const emptyFilter = (): Predicate => ({ kind: 'group', operator: 'and', children: [] })
type ResultsViewState = {
  stageKey: string; focusedKey?: string; checked: string[]; search: string; sort: string; descending: boolean
  predicate: Predicate; filterDraft: Predicate; sortSelection?: ObservationDraft; sortDraft: string; sortDescendingDraft: boolean; sortSelectionDraft?: ObservationDraft; candidateIndices?: number[]; page: number; compare: boolean; comparisonKeys: string[]; basketOpen: boolean
  mainScroll: number; listScroll: number; detailScroll: number
  loadedCollections: { source: ResultLocation; count: number }[]
}
export type ResultsViewStateStore = Map<string, ResultsViewState>

function CandidateDetail({ candidate, results, scores, catalog }: { candidate: CandidateView; results: CandidateResults; scores: ScoreView[]; catalog: CatalogSnapshot }) {
  const [structure, setStructure] = useState<PublishedStructure | null>()
  const key = candidateViewKey(candidate)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void results.structure(key).then((value) => { if (active) setStructure(value) }, (reason) => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [key, results])
  return <article className="result-detail">
    <h3>{candidate.reference.candidate_id}</h3>
    {error ? <p role="alert">{error}</p> : structure === undefined ? <p>加载候选…</p> : <>
      {structure !== null ? <><StructureComponents results={results} candidateKey={key} /><details><summary>原结构三维视图</summary><div className="result-structure"><StructureViewer structure={structure} /></div></details></> : <p>此候选没有结构</p>}
      <h4>序列</h4><code className="sequence-block">{candidate.sequence ?? '尚无已发布序列证据'}</code>
    </>}
    <details><summary>精确数据与来源</summary><pre>{JSON.stringify({ reference: candidate.reference, source: candidate.source, output: candidate.output, metadata: candidate.metadata }, null, 2)}</pre></details>
    {scores.map((score, position) => {
      const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'metric' && contract.reference.contract_id === score.metric.contract_id)!.descriptor
      return <section className="result-observation" key={`${observationKey(score)}:${position}`}><strong>{String(descriptor.title ?? score.metric.contract_id)} · {String(descriptor.unit)}</strong><span>{typeof score.value === 'number' ? score.value.toPrecision(6) : JSON.stringify(score.value)}</span><small>{score.method.contract_id} · {String(descriptor.direction)}</small><details><summary>参考、范围、聚合与来源</summary><pre>{JSON.stringify({ context: score.context, definition: descriptor, residue_axis: score.residue_axis, source: score.source }, null, 2)}</pre></details></section>
    })}
  </article>
}

export function CandidateWorkbench({ results, run, index, loading = false, loadError = '', catalog, scienceStatus, viewStateStore, workspaceProjectId, active = true, requestedSource, onLocateNode, nodeLabels }: { results: CandidateResults; run: RunProjection; index: ResultIndex; loading?: boolean; loadError?: string; catalog: CatalogSnapshot; scienceStatus: 'current' | 'stale' | 'unknown'; viewStateStore?: ResultsViewStateStore; workspaceProjectId?: string; active?: boolean; requestedSource?: ResultLocation & { requestId: number }; onLocateNode: (nodeId: string) => void; nodeLabels: Record<string, string> }) {
  const collections = index.collections
  const stageRevision = useRef(0)
  const handledSourceRequest = useRef<number | undefined>(undefined)
  const [exactSource, setExactSource] = useState<ResultLocation>()
  const viewKey = JSON.stringify([workspaceProjectId ?? run.project_id, run.project_id, run.run_id])
  const [restored] = useState(() => viewStateStore?.get(viewKey))
  const [stageKey, setStageKey] = useState(restored?.stageKey ?? '')
  const [focusedKey, setFocusedKey] = useState<string | undefined>(restored?.focusedKey)
  const [checked, setChecked] = useState<string[]>(restored?.checked ?? [])
  const [search, setSearch] = useState(restored?.search ?? '')
  const [sort, setSort] = useState(restored?.sort ?? '')
  const [descending, setDescending] = useState(restored?.descending ?? true)
  const [sortSelection, setSortSelection] = useState<ObservationDraft | undefined>(restored?.sortSelection)
  const [sortDraft, setSortDraft] = useState(restored?.sortDraft ?? restored?.sort ?? '')
  const [sortDescendingDraft, setSortDescendingDraft] = useState(restored?.sortDescendingDraft ?? restored?.descending ?? true)
  const [sortSelectionDraft, setSortSelectionDraft] = useState<ObservationDraft | undefined>(restored?.sortSelectionDraft ?? restored?.sortSelection)
  const [candidateIndices, setCandidateIndices] = useState<number[] | undefined>(restored?.candidateIndices)
  const [predicate, setPredicate] = useState<Predicate>(restored?.predicate ?? emptyFilter())
  const [filterDraft, setFilterDraft] = useState<Predicate>(restored?.filterDraft ?? emptyFilter())
  const [page, setPage] = useState(restored?.page ?? 0)
  const [compare, setCompare] = useState(restored?.compare ?? false)
  const [comparisonKeys, setComparisonKeys] = useState<string[]>(restored?.comparisonKeys ?? [])
  const [basketOpen, setBasketOpen] = useState(restored?.basketOpen ?? false)
  const mainRef = useRef<HTMLElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const detailRef = useRef<HTMLElement>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const sourceTarget = requestedSource && handledSourceRequest.current !== requestedSource.requestId ? requestedSource : exactSource
  const collection = sourceTarget ? collections.find(entry => locationKey(entry.source) === locationKey(sourceTarget)) : collections.find((entry) => locationKey(entry.source) === stageKey) ?? collections[0]
  const displayedSource = collection?.source ?? sourceTarget
  const sourceInCurrentGraph = displayedSource !== undefined && Object.hasOwn(nodeLabels, displayedSource.node_id)
  const sourceTitle = (source: ResultLocation) => `${nodeLabels[source.node_id] ?? '历史节点'} · ${source.output_port} · 输出 ${source.value_index + 1}`
  const byKey = index.candidates
  const selected = useMemo(() => checked.flatMap((key) => byKey.has(key) ? [byKey.get(key)!] : []), [byKey, checked])
  const compared = useMemo(() => comparisonKeys.flatMap((key) => byKey.has(key) ? [byKey.get(key)!] : []), [byKey, comparisonKeys])
  const scoreChoices = useMemo(() => scalarObservationChoices(index).map((choice) => ({ ...choice, label: `${choice.score.metric.contract_id} · ${choice.score.method.contract_id} · ${choice.score.source.node_id}/${choice.score.source.output_port} [${choice.score.source.value_index + 1}] · ${choice.score.source_partition} · ${JSON.stringify(choice.score.context_profile)}${choice.ambiguous ? '（请选择确切上下文，或由服务明确检查歧义）' : ''}` })), [index])
  const candidates = useMemo(() => {
    const items = collection?.items ?? []
    const chosen = candidateIndices === undefined ? items : candidateIndices.flatMap(index => items[index] ? [items[index]] : [])
    return chosen.filter(candidate => `${candidate.reference.candidate_id} ${candidate.sequence ?? ''} ${JSON.stringify(candidate.metadata)}`.toLowerCase().includes(search.toLowerCase()))
  }, [collection, candidateIndices, search])
  const visible = new Set(candidates.map(candidateViewKey))
  const hidden = selected.filter((candidate) => !visible.has(candidateViewKey(candidate))).length
  const focusedCandidate = sourceTarget && !collection ? undefined : (focusedKey ? byKey.get(focusedKey) : undefined) ?? candidates[0]
  const pageCandidates = candidates.slice(page * 50, (page + 1) * 50)
  const onPage = new Set(pageCandidates.map(candidateViewKey))
  const offPageChecked = selected.filter((candidate) => !onPage.has(candidateViewKey(candidate))).length
  const parents = focusedCandidate ? [...new Map(focusedCandidate.parent_ids.flatMap(id => index.parentCandidates.get(id) ?? []).map(candidate => [referenceKey(candidate.reference), candidate])).values()] : []
  const action = async (work: () => Promise<void>) => { setBusy(true); setError(''); try { await work() } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) } }

  const complete = collection !== undefined && collection.items.length === collection.total
  const filterPending = JSON.stringify([filterDraft, sortDraft, sortDescendingDraft, sortSelectionDraft]) !== JSON.stringify([predicate, sort, descending, sortSelection])
  function clearFilter() {
    const empty = emptyFilter()
    setPredicate(empty); setFilterDraft(empty); setSort(''); setSortDraft(''); setSortSelection(undefined); setSortSelectionDraft(undefined)
    setDescending(true); setSortDescendingDraft(true); setCandidateIndices(undefined); setPage(0)
  }
  async function applyTemporaryView() {
    if (!collection) return
    const revision = stageRevision.current
    try {
      const condition = resultCondition(filterDraft, scoreChoices)
      const choice = scoreChoices.find(choice => choice.key === sortDraft)
      if (sortDraft && !choice) throw new Error('所选排序评价来源当前不可用。')
      const selection = sortDraft ? sortSelectionDraft ?? resultObservation(choice!) : undefined
      const indices = await results.temporaryView(collection.source, {
        ...(condition ? { condition } : {}),
        ...(selection ? { sort: { selection: resultSelection(selection), direction: sortDescendingDraft ? 'descending' : 'ascending' } } : {}),
      })
      if (!indices || revision !== stageRevision.current) return
      setCandidateIndices(indices); setPredicate(filterDraft); setSort(sortDraft); setDescending(sortDescendingDraft); setSortSelection(selection); setSortSelectionDraft(selection); setPage(0)
    } catch (reason) {
      if (revision === stageRevision.current) throw new Error(`本次临时筛选和排序未应用。列表保留此前的查看结果。${errorMessage(reason)}`)
    }
  }
  function selectStage(source: ResultLocation) {
    stageRevision.current += 1
    if (requestedSource) handledSourceRequest.current = requestedSource.requestId
    setExactSource(source)
    setStageKey(locationKey(source)); setFocusedKey(undefined); setPage(0); setSearch(''); setSort(''); clearFilter()
    if (listRef.current) listRef.current.scrollTop = 0
  }
  useEffect(() => {
    if (!requestedSource || handledSourceRequest.current === requestedSource.requestId) return
    const source = collections.find(entry => locationKey(entry.source) === locationKey(requestedSource))?.source
    if (!source) return
    // A navigation request is consumed once, after its exact output arrives.
    // Subsequent index refreshes must not reset the user's local view edits.
    handledSourceRequest.current = requestedSource.requestId
    stageRevision.current += 1
    setExactSource(source); setStageKey(locationKey(source)); setFocusedKey(undefined)
    setPage(0); setSearch(''); clearFilter()
    if (listRef.current) listRef.current.scrollTop = 0
  }, [requestedSource, collections])
  function rememberView() {
    const previous = viewStateStore?.get(viewKey) ?? restored
    const recordScroll = active && scrollRestored.current
    const loadedCollections = new Map(previous?.loadedCollections.map(request => [locationKey(request.source), request]) ?? [])
    for (const entry of collections) loadedCollections.set(locationKey(entry.source), { source: entry.source, count: Math.max(entry.items.length, loadedCollections.get(locationKey(entry.source))?.count ?? 0) })
    viewStateStore?.set(viewKey, { stageKey: stageKey || (collection ? locationKey(collection.source) : ''), focusedKey, checked, search, sort, descending, sortSelection, sortDraft, sortDescendingDraft, sortSelectionDraft, candidateIndices, predicate, filterDraft, page, compare, comparisonKeys, basketOpen, mainScroll: recordScroll ? mainRef.current?.scrollTop ?? 0 : previous?.mainScroll ?? 0, listScroll: recordScroll ? listRef.current?.scrollTop ?? 0 : previous?.listScroll ?? 0, detailScroll: recordScroll ? detailRef.current?.scrollTop ?? 0 : previous?.detailScroll ?? 0, loadedCollections: [...loadedCollections.values()] })
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
    if (requestedSource) handledSourceRequest.current = requestedSource.requestId
    setExactSource(candidate.source)
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
  const [exportFormat, setExportFormat] = useState<'pdb' | 'mmcif'>('pdb')
  async function exportSelected() {
    const material = await results.prepareExport(checked, exportFormat)
    if (material) exportCandidates(material, scienceStatus)
  }
  async function nextPage() {
    if (!collection) return
    const revision = stageRevision.current
    const snapshot = await results.ensureCandidates({ source: collection.source, count: (page + 2) * 50 })
    if (snapshot && revision === stageRevision.current) setPage(page + 1)
  }

  return <div className="results-explorer">
    <aside className="result-stages"><h2>已发布结果</h2><p>{run.status}</p><p>{scienceStatus === 'current' ? '结果与当前科学流程一致' : scienceStatus === 'stale' ? '结果来自已修改的流程' : '结果一致性待确认'}</p><small>Run {run.run_id}<br />Commit {run.workflow_commit_id}</small><nav aria-label="结果阶段">{collections.map((entry) => <button className={collection === entry ? 'active' : ''} aria-current={collection === entry ? 'true' : undefined} key={locationKey(entry.source)} data-testid={`result-source-${locationKey(entry.source)}`} onClick={() => selectStage(entry.source)}>{sourceTitle(entry.source)}<strong>{entry.total}</strong></button>)}</nav></aside>
    <main ref={mainRef} tabIndex={-1} aria-label="已发布结果工作区" onScroll={rememberView} aria-busy={loading && !loadError}>
      <header><h1>{displayedSource ? sourceTitle(displayedSource) : collection?.title ?? (loadError ? '结果读取失败' : loading ? '已发布结果' : '尚无已发布候选')}</h1><div><button disabled={!byKey.size || busy} onClick={openComparison}>{compare ? '关闭比较' : `并排比较 (${comparisonKeys.filter(Boolean).length})`}</button><button aria-expanded={basketOpen} onClick={() => setBasketOpen(!basketOpen)}>查看已选 ({checked.length})</button><label>结构导出格式<select aria-label="结构导出格式" value={exportFormat} disabled={busy} onChange={event => setExportFormat(event.target.value as 'pdb' | 'mmcif')}><option value="pdb">PDB</option><option value="mmcif">mmCIF</option></select></label><button disabled={!selected.length || busy} onClick={() => void action(exportSelected)}>导出所选 · ZIP</button></div></header>
      {displayedSource && <section className="result-source" aria-label="当前结果来源"><div><span>来源：{sourceTitle(displayedSource)}</span>{<button disabled={!sourceInCurrentGraph} onClick={() => onLocateNode(displayedSource.node_id)}>在画布中定位</button>}{!sourceInCurrentGraph && <span>来源节点已不在当前图中</span>}</div><details><summary>精确输出位置</summary><code>{JSON.stringify(displayedSource)}</code></details></section>}
      {sourceTarget && !collection && <p role="status" className="result-unpublished">{loading ? '正在读取此节点输出…' : loadError ? '此节点输出读取失败，请查看下方错误。' : '此 Run 尚未发布这个节点输出的候选集合。可以从左侧选择其他已发布输出。'}</p>}
      {<p className="result-selection-summary" aria-label="结果交互状态">焦点：{focusedCandidate?.reference.candidate_id ?? '无'}（查看详情） · 比较：{comparisonKeys.filter(Boolean).length} 项（并排查看） · 勾选：{checked.length} 项（导出）。三者独立，切换输出保留比较和勾选。</p>}
      {error && <p role="alert">{error}</p>}
      {loadError && <p role="alert">{loadError}<button disabled={busy} onClick={() => void action(async () => { await results.refresh(); await results.ensureCandidates(collection ? { source: collection.source, count: 'all' } : { all: true }) })}>重新读取结果</button></p>}
      {loading && !collection && !loadError && <p role="status">正在加载已发布结果…</p>}
      {busy && <p role="status">正在读取或准备所选操作…</p>}
      {basketOpen && <section className="result-basket" aria-label="已选候选清单"><header><h2>已选候选 · {checked.length}</h2><button disabled={!checked.length || busy} onClick={() => setChecked([])}>清空全部勾选</button></header><p>勾选用于导出；比较位置单独管理。{offPageChecked} 项不在当前页。</p>{checked.length === 0 ? <p>尚未勾选候选。</p> : <ul>{checked.map(key => {
        const candidate = byKey.get(key)
        return <li key={key}>{candidate ? <><button onClick={() => revealCandidate(candidate)}>{candidate.reference.candidate_id}</button><small>{candidate.source.node_id} / {candidate.source.output_port} · 第 {candidate.item_index + 1} 项</small></> : <span>正在恢复已选候选…</span>}<button aria-label={`移除勾选 ${candidate?.reference.candidate_id ?? key}`} disabled={busy} onClick={() => setChecked(current => current.filter(item => item !== key))}>移除</button></li>
      })}</ul>}</section>}
      {collection && !complete && <p>已加载 {collection.items.length} / {collection.total} 个候选。<button disabled={busy} onClick={() => void action(async () => { await results.ensureCandidates({ source: collection.source, count: 'all' }) })}>加载全部候选以搜索、筛选和排序</button></p>}
      <fieldset disabled={!complete || busy}><div className="result-controls"><label>搜索候选或序列<input value={search} onChange={(event) => { setSearch(event.target.value); setPage(0) }} /></label><label>临时排序<select aria-label="临时排序" value={sortDraft} onChange={(event) => { const choice = scoreChoices.find(choice => choice.key === event.target.value); setSortDraft(event.target.value); setSortSelectionDraft(choice ? resultObservation(choice) : undefined) }}><option value="">原始顺序</option>{scoreChoices.map(({ key, label }) => <option key={key} value={key}>{label}</option>)}</select></label><button onClick={() => setSortDescendingDraft(!sortDescendingDraft)}>{sortDescendingDraft ? '降序' : '升序'}</button><span>{selected.length} 已勾选 · {hidden} 项不在当前视图 · {offPageChecked} 项不在当前页</span></div>
      {sortDraft && sortSelectionDraft && <ResultObservationEditor value={sortSelectionDraft} observations={index.scores} candidates={collection?.items.map(candidate => candidate.reference) ?? []} catalog={catalog} onChange={setSortSelectionDraft} />}
      <details><summary>临时条件筛选 · 支持 AND/OR 分组</summary><ResultFilter value={filterDraft} choices={scoreChoices} observations={index.scores} candidates={collection?.items.map(candidate => candidate.reference) ?? []} catalog={catalog} onChange={setFilterDraft} /></details>
      <button disabled={!filterComplete(filterDraft) || !filterPending} onClick={() => void action(applyTemporaryView)}>应用临时筛选和排序</button><button disabled={!filterPending} onClick={() => { setFilterDraft(predicate); setSortDraft(sort); setSortDescendingDraft(descending); setSortSelectionDraft(sortSelection) }}>放弃修改</button><button onClick={clearFilter}>清除临时筛选和排序</button>
      <p>{filterPending && (filterComplete(filterDraft) ? '设置已修改，点击“应用临时筛选和排序”更新列表。' : '条件尚未填写完整；列表继续显示此前的查看结果。')}搜索文字仅改变显示。清除全部条件表示不筛选；嵌套空组须补全或移除。所选评价缺失、为 null 或仍有歧义时停止本次操作。</p>
      {candidateIndices !== undefined && <p aria-label="已应用的临时查看">列表显示此前成功应用的临时筛选和排序；未应用的设置不改变列表。</p>}
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
  </div>
}
