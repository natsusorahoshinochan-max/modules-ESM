import { useEffect, useState, type ComponentType } from 'react'
import { PublicV2Client, type PublishedArtifact, type PublishedOutput, type PublishedResultValue, type ResultLocation, type RunProjection } from './protocol/client'
import type { PublishedResults } from './published-results'
import { loadResultViewer, resultViewers, type ModuleUiManifest, type ModuleViewerProps, type RegisteredResultViewer } from './module-ui'
import './published-outputs.css'

type OutputRequest = ResultLocation & { requestId: number }
type Props = { run: RunProjection; results: PublishedResults; requestedSource?: OutputRequest }

const client = new PublicV2Client()
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

function ModuleViewer({ payload, viewers }: { payload: PublishedResultValue; viewers: RegisteredResultViewer[] }) {
  const [selected, setSelected] = useState(() => viewers.find(viewer => viewer.definition.is_default)!.definition.viewer_id)
  const [Component, setComponent] = useState<ComponentType<ModuleViewerProps>>()
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setComponent(undefined)
    setError('')
    const viewer = viewers.find(item => item.definition.viewer_id === selected)!
    void loadResultViewer(viewer).then(component => { if (active) setComponent(() => component) }, reason => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [selected, viewers])
  return <><label>结果查看器<select aria-label="结果查看器" value={selected} onChange={event => setSelected(event.target.value)}>{viewers.map(viewer => <option key={viewer.definition.viewer_id} value={viewer.definition.viewer_id}>{viewer.definition.title}</option>)}</select></label>{error ? <p role="alert">{error}</p> : Component ? <Component reading={payload} /> : <p role="status">加载结果查看器…</p>}</>
}

/** Local state controls presentation; immutable reads and retirement belong to PublishedResults. */
function LoadValue({ results, output, valueIndex }: { results: PublishedResults; output: PublishedOutput; valueIndex: number }) {
  const [manifest, setManifest] = useState<ModuleUiManifest>()
  const [viewers, setViewers] = useState<RegisteredResultViewer[]>([])
  const [payload, setPayload] = useState<PublishedResultValue>()
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const source: ResultLocation = { node_id: output.node_id, output_port: output.output_port, value_index: valueIndex }
  async function load() {
    setBusy(true)
    setError('')
    try {
      const available = manifest ?? await client.moduleUi()
      setManifest(available)
      setViewers(resultViewers(available, output.port_type.contract_id))
      if (available.readers.some(reader => reader.port_type_id === output.port_type.contract_id)) {
        const value = await results.value(source)
        if (value) { setPayload(value); setLoaded(true) }
      } else if (await results.rawValue(source)) setLoaded(true)
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <div className="published-value">{!loaded && <><p>点击后读取此值；打开输出列表不会下载值内容。</p><button disabled={busy} onClick={() => void load()}>{busy ? '加载中…' : '加载此值'}</button></>}{error && <p role="alert">{error}</p>}{loaded && <>{payload ? (viewers.length ? <ModuleViewer payload={payload} viewers={viewers} /> : <RawValue value={payload.value} label="查看已发布科学事实" />) : <p>已加载 {output.port_type.contract_id} 的完整类型值。</p>}<PublishedRawValue results={results} source={source} /></>}</div>
}

function OutputDetail({ results, output, requestedSource }: { results: PublishedResults; output: PublishedOutput; requestedSource?: OutputRequest }) {
  const [valueIndex, setValueIndex] = useState(requestedSource?.value_index ?? 0)
  useEffect(() => { if (requestedSource) setValueIndex(requestedSource.value_index) }, [requestedSource])
  return <section className="published-output-detail" aria-label="输出详情"><h4>{output.node_id} / {output.output_port}</h4><p>类型：{output.port_type.contract_id}</p>
    <RawValue value={{ content_digest: output.content_digest, result_identity: output.result_identity, producer_provenance: output.producer_provenance }} label="查看输出身份与来源" />
    {output.value_count === 0 ? <p>该输出没有已发布值。</p> : <><label className="published-index">值索引（从 0 开始）<select aria-label="输出值索引" value={valueIndex} onChange={event => setValueIndex(Number(event.target.value))}>{Array.from({ length: output.value_count }, (_, index) => <option key={index} value={index}>{index}</option>)}</select></label><LoadValue key={valueIndex} results={results} output={output} valueIndex={valueIndex} /></>}
  </section>
}

function ArtifactDownload({ artifact, results }: { artifact: PublishedArtifact; results: PublishedResults }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function download() {
    setBusy(true); setError('')
    try {
      const bundle = await results.exportArtifact(artifact)
      if (!bundle) return
      const url = URL.createObjectURL(new Blob([bundle as Uint8Array<ArrayBuffer>], { type: 'application/zip' }))
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${artifact.filename}.zip`; anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <><button disabled={busy} onClick={() => void download()}>{artifact.filename} · ZIP</button>{error && <p role="alert">{error}</p>}</>
}

function RunOutputs({ run, results, requestedSource }: Props) {
  const [selectedKey, setSelectedKey] = useState('')
  const requestedOutput = run.outputs.find(output => output.node_id === requestedSource?.node_id && output.output_port === requestedSource.output_port)
  const requestedKey = requestedOutput ? outputKey(requestedOutput) : undefined
  useEffect(() => { if (requestedKey) setSelectedKey(requestedKey) }, [requestedSource?.requestId, requestedKey])
  const selected = run.outputs.find(output => outputKey(output) === selectedKey)
  return <section className="published-outputs" aria-label="全部已发布输出"><header><h3>已发布输出与附件</h3><p>{run.outputs.length} 个输出 · {run.artifact_index.length} 件附件</p></header>
    <div className="published-output-browser"><nav aria-label="选择已发布输出">{run.outputs.map(output => <button key={outputKey(output)} aria-pressed={selectedKey === outputKey(output)} onClick={() => setSelectedKey(outputKey(output))}><strong>{output.node_id} / {output.output_port}</strong><span>{output.port_type.contract_id} · {output.value_count} 个值</span></button>)}{run.outputs.length === 0 && <p>本次 Run 还没有发布输出。</p>}</nav>{selected ? <OutputDetail key={outputKey(selected)} results={results} output={selected} requestedSource={requestedSource?.node_id === selected.node_id && requestedSource.output_port === selected.output_port ? requestedSource : undefined} /> : <p className="published-output-placeholder">选择输出后按需查看任意值。</p>}</div>
    <section className="published-artifacts" aria-label="已发布附件"><h4>附件下载</h4>{run.artifact_index.length === 0 ? <p>本次 Run 还没有发布附件。</p> : <ul>{run.artifact_index.map(artifact => <li key={artifact.artifact_reference}><ArtifactDownload artifact={artifact} results={results} /><span>{artifact.node_id} / {artifact.output_port} · {artifact.artifact_kind} · {artifact.media_type} · {artifact.size} bytes{artifact.candidate_id ? ` · Candidate ${artifact.candidate_id}` : ''}</span><RawValue value={{ artifact_reference: artifact.artifact_reference, content_digest: artifact.content_digest }} label="查看附件身份" /></li>)}</ul>}</section>
  </section>
}

/** Works for every Run, including workflows without Candidate Collections. */
export function PublishedOutputs({ run, results, requestedSource }: Props) {
  return <RunOutputs key={JSON.stringify([run.project_id, run.run_id])} run={run} results={results} requestedSource={requestedSource} />
}
