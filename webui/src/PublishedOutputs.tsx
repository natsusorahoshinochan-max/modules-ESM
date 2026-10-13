import { lazy, Suspense, useEffect, useState } from 'react'
import { PublicV2Client, type PublishedOutput, type PublishedPrompt, type PublishedResultValue, type ResultLocation, type RunProjection } from './protocol/client'
import type { PublishedResults } from './published-results'
import './published-outputs.css'

const client = new PublicV2Client()
const StructureViewer = lazy(() => import('./StructureViewer').then(module => ({ default: module.StructureViewer })))
const readingTypes = new Set(['score.collection', 'structure_transform.candidate_resolved_residue_axis_associations', 'structure_comparison.alignment_evidence', 'protein.sequence', 'protein.structure', 'protein.prompt', 'structure_transform.resolved_residue_axis'])
const outputKey = (output: PublishedOutput) => JSON.stringify([output.node_id, output.output_port, output.content_digest])
const errorMessage = (reason: unknown) => reason instanceof Error ? reason.message : JSON.stringify(reason)

function RawValue({ value, label = '查看原始已发布值' }: { value: unknown; label?: string }) {
  const [expanded, setExpanded] = useState(false)
  return <details className="published-raw" onToggle={event => setExpanded(event.currentTarget.open)}><summary>{label}</summary>{expanded && <pre>{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>}</details>
}

function PublishedRawValue({ results, source }: { results: PublishedResults; source: ResultLocation }) {
  const [expanded, setExpanded] = useState(false)
  const [value, setValue] = useState<unknown>()
  const [error, setError] = useState('')
  useEffect(() => {
    if (!expanded) return
    let active = true
    void results.rawValue(source).then(value => { if (active) setValue(value) }, reason => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [expanded, results, source])
  return <details className="published-raw" onToggle={event => setExpanded(event.currentTarget.open)}><summary>查看原始已发布值</summary>{expanded && (error ? <p role="alert">{error}</p> : value === undefined ? <p>加载原值…</p> : <pre>{JSON.stringify(value, null, 2)}</pre>)}</details>
}

function PromptValue({ value }: { value: PublishedPrompt }) {
  const [page, setPage] = useState(0)
  const residueIds = value.residue_ids
  const offset = page * 100
  return <section aria-label="已发布 Prompt"><p>{residueIds.length} 个残基；Mask 表示该残基没有条件，未提供整条轨道与 Mask 分别显示。</p>
    <div className="published-prompt-scroll"><table><thead><tr><th>残基身份</th><th>序列</th><th>原子坐标（Å）</th><th>二级结构（SS8）</th><th>SASA（Å²）</th></tr></thead><tbody>{residueIds.slice(offset, offset + 100).map((id, row) => {
      const index = offset + row
      const coordinates = value.coordinates[index]
      return <tr key={id}><th scope="row">{id}</th><td>{value.sequence[index] ?? 'Mask'}</td><td>{coordinates === null ? 'Mask' : <details><summary>{coordinates.atoms.length} 个原子</summary>{coordinates.atoms.map(([name, position]) => <p key={name}>{name}: ({position.join(', ')})</p>)}</details>}</td><td>{value.secondary_structure === null ? '未提供整条轨道' : value.secondary_structure[index] ?? 'Mask'}</td><td>{value.sasa === null ? '未提供整条轨道' : value.sasa[index] ?? 'Mask'}</td></tr>
    })}</tbody></table></div>
    {residueIds.length > 100 && <div className="published-pagination"><button disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>{offset + 1}–{Math.min(offset + 100, residueIds.length)} / {residueIds.length}</span><button disabled={offset + 100 >= residueIds.length} onClick={() => setPage(page + 1)}>下一页</button></div>}
    <h4>功能注释</h4>{value.function_annotations.length === 0 ? <p>没有功能注释。</p> : <ul>{value.function_annotations.map((annotation, index) => <li key={index}>{annotation.label} · {annotation.start_residue_id} → {annotation.end_residue_id}</li>)}</ul>}
  </section>
}

function ValuePresentation({ payload }: { payload: PublishedResultValue }) {
  if (payload.kind === 'sequence') {
    const value = payload.value
    return <section aria-label="已发布序列"><p>{value.sequence.length} 个序列位置</p><pre className="published-sequence">{value.sequence}</pre>{value.residue_ids === null ? <p>该序列未提供残基身份列表。</p> : <RawValue value={value.residue_ids} label="查看已发布残基身份" />}</section>
  }
  if (payload.kind === 'structure') return <section aria-label="已发布结构"><Suspense fallback={<p role="status">加载结构查看器…</p>}><StructureViewer pdb={payload.value.pdb} /></Suspense><RawValue value={payload.value.pdb} label="查看原始 PDB 文本" /></section>
  if (payload.kind === 'prompt') return <PromptValue value={payload.value} />
  return <RawValue value={payload.value} label="查看已发布科学事实" />
}

/** Local state controls presentation; immutable reads and retirement belong to PublishedResults. */
function LoadValue({ results, output, valueIndex }: { results: PublishedResults; output: PublishedOutput; valueIndex: number }) {
  const [payload, setPayload] = useState<PublishedResultValue>()
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const source: ResultLocation = { node_id: output.node_id, output_port: output.output_port, value_index: valueIndex }
  async function load() {
    setBusy(true)
    setError('')
    try {
      if (readingTypes.has(output.port_type.contract_id)) {
        const value = await results.value(source)
        if (value) { setPayload(value); setLoaded(true) }
      } else if (await results.rawValue(source)) setLoaded(true)
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <div className="published-value">{!loaded && <><p>点击后读取此值；打开输出列表不会下载值内容。</p><button disabled={busy} onClick={() => void load()}>{busy ? '加载中…' : '加载此值'}</button></>}{error && <p role="alert">{error}</p>}{loaded && <>{payload ? <ValuePresentation payload={payload} /> : <p>已加载 {output.port_type.contract_id} 的完整类型值。</p>}<PublishedRawValue results={results} source={source} /></>}</div>
}

function OutputDetail({ results, output }: { results: PublishedResults; output: PublishedOutput }) {
  const [valueIndex, setValueIndex] = useState(0)
  return <section className="published-output-detail" aria-label="输出详情"><h4>{output.node_id} / {output.output_port}</h4><p>类型：{output.port_type.contract_id}</p>
    <RawValue value={{ content_digest: output.content_digest, result_identity: output.result_identity, producer_provenance: output.producer_provenance }} label="查看输出身份与来源" />
    {output.value_count === 0 ? <p>该输出没有已发布值。</p> : <><label className="published-index">值索引（从 0 开始）<select aria-label="输出值索引" value={valueIndex} onChange={event => setValueIndex(Number(event.target.value))}>{Array.from({ length: output.value_count }, (_, index) => <option key={index} value={index}>{index}</option>)}</select></label><LoadValue key={valueIndex} results={results} output={output} valueIndex={valueIndex} /></>}
  </section>
}

function RunOutputs({ run, results }: { run: RunProjection; results: PublishedResults }) {
  const [selectedKey, setSelectedKey] = useState('')
  const selected = run.outputs.find(output => outputKey(output) === selectedKey)
  return <section className="published-outputs" aria-label="全部已发布输出"><header><h3>已发布输出与附件</h3><p>{run.outputs.length} 个输出 · {run.artifact_index.length} 件附件</p></header>
    <div className="published-output-browser"><nav aria-label="选择已发布输出">{run.outputs.map(output => <button key={outputKey(output)} aria-pressed={selectedKey === outputKey(output)} onClick={() => setSelectedKey(outputKey(output))}><strong>{output.node_id} / {output.output_port}</strong><span>{output.port_type.contract_id} · {output.value_count} 个值</span></button>)}{run.outputs.length === 0 && <p>本次 Run 还没有发布输出。</p>}</nav>{selected ? <OutputDetail key={outputKey(selected)} results={results} output={selected} /> : <p className="published-output-placeholder">选择输出后按需查看任意值。</p>}</div>
    <section className="published-artifacts" aria-label="已发布附件"><h4>附件下载</h4>{run.artifact_index.length === 0 ? <p>本次 Run 还没有发布附件。</p> : <ul>{run.artifact_index.map(artifact => <li key={artifact.artifact_reference}><a href={client.artifactUrl(run.project_id, run.run_id, artifact.artifact_reference)} download={artifact.filename}>{artifact.filename}</a><span>{artifact.node_id} / {artifact.output_port} · {artifact.artifact_kind} · {artifact.media_type} · {artifact.size} bytes{artifact.candidate_id ? ` · Candidate ${artifact.candidate_id}` : ''}</span><RawValue value={{ artifact_reference: artifact.artifact_reference, content_digest: artifact.content_digest }} label="查看附件身份" /></li>)}</ul>}</section>
  </section>
}

/** Works for every Run, including workflows without Candidate Collections. */
export function PublishedOutputs({ run, results }: { run: RunProjection; results: PublishedResults }) {
  return <RunOutputs key={JSON.stringify([run.project_id, run.run_id])} run={run} results={results} />
}
