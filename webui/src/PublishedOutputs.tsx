import { lazy, Suspense, useState } from 'react'
import { PublicV2Client, type PublishedOutput, type RunProjection } from './protocol/client'
import './published-outputs.css'

const client = new PublicV2Client()
const StructureViewer = lazy(() => import('./StructureViewer').then((module) => ({ default: module.StructureViewer })))
type TypedValue = Awaited<ReturnType<PublicV2Client['typedValue']>>
type Dataclass<T> = { $dataclass: string; fields: T }
type SequenceFields = { sequence: string; residue_ids: string[] | null }
type StructureFields = { pdb_string: string }
type PromptFields = {
  layout: Dataclass<{ residue_ids: string[] }>
  sequence: Array<string | null>
  coordinates: Array<Dataclass<{ atoms: { $tuple: Array<{ $tuple: [string, { $tuple: [number, number, number] }] }> } }> | null>
  secondary_structure: Array<string | null> | null
  sasa: Array<number | null> | null
  function_annotations: Array<Dataclass<{ label: string; start_residue_id: string; end_residue_id: string }>>
}
const outputKey = (output: PublishedOutput) => JSON.stringify([output.node_id, output.output_port, output.content_digest])
const errorMessage = (reason: unknown) => reason instanceof Error ? reason.message : (reason as { error: { message: string } }).error.message

function RawValue({ value, label = '查看原始已发布值' }: { value: unknown; label?: string }) {
  const [expanded, setExpanded] = useState(false)
  return <details className="published-raw" onToggle={(event) => setExpanded(event.currentTarget.open)}><summary>{label}</summary>{expanded && <pre>{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>}</details>
}

function PromptValue({ value }: { value: PromptFields }) {
  const [page, setPage] = useState(0)
  const residueIds = value.layout.fields.residue_ids
  const offset = page * 100
  return <section aria-label="已发布 Prompt"><p>{residueIds.length} 个残基；Mask 表示该残基没有条件，未提供整条轨道与 Mask 分别显示。</p>
    <div className="published-prompt-scroll"><table><thead><tr><th>残基身份</th><th>序列</th><th>原子坐标（Å）</th><th>二级结构（SS8）</th><th>SASA（Å²）</th></tr></thead><tbody>{residueIds.slice(offset, offset + 100).map((id, row) => {
      const index = offset + row
      const coordinates = value.coordinates[index]
      return <tr key={id}><th scope="row">{id}</th><td>{value.sequence[index] ?? 'Mask'}</td><td>{coordinates === null ? 'Mask' : <details><summary>{coordinates.fields.atoms.$tuple.length} 个原子</summary>{coordinates.fields.atoms.$tuple.map((atom) => <p key={atom.$tuple[0]}>{atom.$tuple[0]}: ({atom.$tuple[1].$tuple.join(', ')})</p>)}</details>}</td><td>{value.secondary_structure === null ? '未提供整条轨道' : value.secondary_structure[index] ?? 'Mask'}</td><td>{value.sasa === null ? '未提供整条轨道' : value.sasa[index] ?? 'Mask'}</td></tr>
    })}</tbody></table></div>
    {residueIds.length > 100 && <div className="published-pagination"><button disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>{offset + 1}–{Math.min(offset + 100, residueIds.length)} / {residueIds.length}</span><button disabled={offset + 100 >= residueIds.length} onClick={() => setPage(page + 1)}>下一页</button></div>}
    <h4>功能注释</h4>{value.function_annotations.length === 0 ? <p>没有功能注释。</p> : <ul>{value.function_annotations.map(({ fields }, index) => <li key={index}>{fields.label} · {fields.start_residue_id} → {fields.end_residue_id}</li>)}</ul>}
  </section>
}

function ValuePresentation({ payload }: { payload: TypedValue }) {
  if (payload.port_type_id === 'protein.sequence') {
    const value = (payload.value as Dataclass<SequenceFields>).fields
    return <section aria-label="已发布序列"><p>{value.sequence.length} 个序列位置</p><pre className="published-sequence">{value.sequence}</pre>{value.residue_ids === null ? <p>该序列未提供残基身份列表。</p> : <RawValue value={value.residue_ids} label="查看已发布残基身份" />}<RawValue value={payload} /></section>
  }
  if (payload.port_type_id === 'protein.structure') {
    const value = (payload.value as Dataclass<StructureFields>).fields
    return <section aria-label="已发布结构"><Suspense fallback={<p role="status">加载结构查看器…</p>}><StructureViewer pdb={value.pdb_string} /></Suspense><RawValue value={value.pdb_string} label="查看原始 PDB 文本" /><RawValue value={payload} /></section>
  }
  if (payload.port_type_id === 'protein.prompt') return <><PromptValue value={(payload.value as Dataclass<PromptFields>).fields} /><RawValue value={payload} /></>
  return <><p>已加载 {payload.port_type_id} 的完整类型值。</p><RawValue value={payload} /></>
}

/** Each exact value owns its request state, so switching outputs cannot show stale data. */
function LoadValue({ run, output, valueIndex }: { run: RunProjection; output: PublishedOutput; valueIndex: number }) {
  const [payload, setPayload] = useState<TypedValue>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function load() {
    setBusy(true)
    setError('')
    try { setPayload(await client.typedValue(run.project_id, run.run_id, output.node_id, output.output_port, valueIndex)) }
    catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <div className="published-value">{!payload && <><p>点击后读取此值；打开输出列表不会下载值内容。</p><button disabled={busy} onClick={() => void load()}>{busy ? '加载中…' : '加载此值'}</button></>}{error && <p role="alert">{error}</p>}{payload && <ValuePresentation payload={payload} />}</div>
}

function OutputDetail({ run, output }: { run: RunProjection; output: PublishedOutput }) {
  const [valueIndex, setValueIndex] = useState(0)
  return <section className="published-output-detail" aria-label="输出详情"><h4>{output.node_id} / {output.output_port}</h4><p>类型：{output.port_type.contract_id}</p>
    <RawValue value={{ content_digest: output.content_digest, result_identity: output.result_identity, producer_provenance: output.producer_provenance }} label="查看输出身份与来源" />
    {output.value_count === 0 ? <p>该输出没有已发布值。</p> : <><label className="published-index">值索引（从 0 开始）<select aria-label="输出值索引" value={valueIndex} onChange={(event) => setValueIndex(Number(event.target.value))}>{Array.from({ length: output.value_count }, (_, index) => <option key={index} value={index}>{index}</option>)}</select></label><LoadValue key={valueIndex} run={run} output={output} valueIndex={valueIndex} /></>}
  </section>
}

function RunOutputs({ run }: { run: RunProjection }) {
  const [selectedKey, setSelectedKey] = useState('')
  const selected = run.outputs.find((output) => outputKey(output) === selectedKey)
  return <section className="published-outputs" aria-label="全部已发布输出"><header><h3>已发布输出与附件</h3><p>{run.outputs.length} 个输出 · {run.artifact_index.length} 件附件</p></header>
    <div className="published-output-browser"><nav aria-label="选择已发布输出">{run.outputs.map((output) => <button key={outputKey(output)} aria-pressed={selectedKey === outputKey(output)} onClick={() => setSelectedKey(outputKey(output))}><strong>{output.node_id} / {output.output_port}</strong><span>{output.port_type.contract_id} · {output.value_count} 个值</span></button>)}{run.outputs.length === 0 && <p>本次 Run 还没有发布输出。</p>}</nav>{selected ? <OutputDetail key={outputKey(selected)} run={run} output={selected} /> : <p className="published-output-placeholder">选择输出后按需查看任意值。</p>}</div>
    <section className="published-artifacts" aria-label="已发布附件"><h4>附件下载</h4>{run.artifact_index.length === 0 ? <p>本次 Run 还没有发布附件。</p> : <ul>{run.artifact_index.map((artifact) => <li key={artifact.artifact_reference}><a href={client.artifactUrl(run.project_id, run.run_id, artifact.artifact_reference)} download={artifact.filename}>{artifact.filename}</a><span>{artifact.node_id} / {artifact.output_port} · {artifact.artifact_kind} · {artifact.media_type} · {artifact.size} bytes{artifact.candidate_id ? ` · Candidate ${artifact.candidate_id}` : ''}</span><RawValue value={{ artifact_reference: artifact.artifact_reference, content_digest: artifact.content_digest }} label="查看附件身份" /></li>)}</ul>}</section>
  </section>
}

/** Works for every Run, including workflows without Candidate Collections. */
export function PublishedOutputs({ run }: { run: RunProjection }) {
  return <RunOutputs key={JSON.stringify([run.project_id, run.run_id])} run={run} />
}
