import { useEffect, useState, type FormEvent } from 'react'
import type { CatalogSnapshot, Workflow } from './protocol/client'
import { existingPromptSources, inputContentBase64, prepareCandidateInput, preparePromptSource, type CandidateInputPlan, type InputSourceClient, type ProjectInputInspection, type ProjectInputPublication, type PromptSourceChoice, type PromptSourcePlan } from './input-sources'
import './input-sources.css'

export type InputSourceDialogProps = {
  projectId: string
  workflow: Workflow
  catalog: CatalogSnapshot
  client: InputSourceClient
  mergeTargetNodeId?: string
  onPreparePrompt: (plan: PromptSourcePlan) => Promise<void>
  onImportCandidates: (plan: CandidateInputPlan) => Promise<void>
  onClose: () => void
}
type SourceMode = 'blank' | 'fasta' | 'pdb' | 'prompt' | 'batch'
type InputMode = 'file' | 'paste' | 'existing'
type ChainRow = { chain_id: string; length: string }

const sourceModes: Array<{ value: SourceMode; title: string; description: string }> = [
  { value: 'blank', title: '空白 Prompt', description: '声明一条或多条链' },
  { value: 'fasta', title: 'FASTA → Prompt', description: '完整序列与明确链布局' },
  { value: 'pdb', title: 'PDB → Prompt', description: '选择有序结构链' },
  { value: 'prompt', title: '已有 ProteinPrompt', description: '连接现有节点输出' },
  { value: 'batch', title: '批量 FASTA Candidates', description: '每条 record 独立导入' },
]

function errorText(error: unknown) {
  return error instanceof Error ? error.message : (error as { error: { message: string } }).error.message
}

export function InputSourceDialog({ projectId, workflow, catalog, client, mergeTargetNodeId, onPreparePrompt, onImportCandidates, onClose }: InputSourceDialogProps) {
  const [mode, setMode] = useState<SourceMode>('blank')
  const [inputMode, setInputMode] = useState<InputMode>('file')
  const [inputs, setInputs] = useState<ProjectInputPublication[]>([])
  const [inputsLoading, setInputsLoading] = useState(true)
  const [inputRef, setInputRef] = useState('')
  const [file, setFile] = useState<File>()
  const [pasted, setPasted] = useState('')
  const [filename, setFilename] = useState('input.fasta')
  const [inspection, setInspection] = useState<ProjectInputInspection>()
  const [chains, setChains] = useState<ChainRow[]>([{ chain_id: 'A', length: '100' }])
  const [pdbChains, setPdbChains] = useState<string[]>([])
  const [promptKey, setPromptKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const promptSources = existingPromptSources(workflow, catalog, mergeTargetNodeId)
  const selectedPrompt = promptSources.find(item => `${item.nodeId}/${item.outputPort}` === promptKey)
  const format = mode === 'pdb' ? 'pdb' : 'fasta'
  const usesInput = mode === 'fasta' || mode === 'pdb' || mode === 'batch'
  const selectedInput = inputs.find(item => item.project_input_ref === inputRef)
  const chainLength = chains.reduce((total, chain) => total + Number(chain.length), 0)
  const chainLengthMatches = mode !== 'fasta' || inspection?.format === 'fasta' && chainLength === inspection.total_length

  useEffect(() => {
    let active = true
    client.listProjectInputs(projectId).then(result => { if (active) { setInputs(result.inputs); setInputsLoading(false) } }).catch(cause => { if (active) { setError(errorText(cause)); setInputsLoading(false) } })
    return () => { active = false }
  }, [client, projectId])

  const changeMode = (next: SourceMode) => {
    setMode(next); setInspection(undefined); setError(''); setPdbChains([])
    setFilename(next === 'pdb' ? 'input.pdb' : 'input.fasta')
  }
  const changeInputMode = (next: InputMode) => { setInputMode(next); setInspection(undefined); setError('') }
  const inspect = async (reference: string) => {
    const result = await client.inspectProjectInput(projectId, reference, format)
    setInspection(result)
    if (result.format === 'fasta') setChains([{ chain_id: 'A', length: String(result.total_length) }])
    else setPdbChains([])
  }
  const readInput = async () => {
    setBusy(true); setError(''); setInspection(undefined)
    try {
      if (inputMode === 'existing') await inspect(inputRef)
      else {
        const content = inputMode === 'file' ? new Uint8Array(await file!.arrayBuffer()) : new TextEncoder().encode(pasted)
        const publication = await client.publishProjectInput(projectId, { filename: inputMode === 'file' ? file!.name : filename, content_base64: inputContentBase64(content) })
        setInputs(current => [...current, publication]); setInputRef(publication.project_input_ref)
        await inspect(publication.project_input_ref)
      }
    } catch (cause) { setError(errorText(cause)) }
    finally { setBusy(false) }
  }
  const prepare = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    try {
      if (mode === 'batch') await onImportCandidates(prepareCandidateInput(workflow, catalog, inputRef))
      else {
        let source: PromptSourceChoice
        if (mode === 'blank') source = { kind: 'blank', chains: chains.map(chain => ({ chain_id: chain.chain_id, length: Number(chain.length) })) }
        else if (mode === 'fasta') source = { kind: 'fasta', projectInputRef: inputRef, chains: chains.map(chain => ({ chain_id: chain.chain_id, length: Number(chain.length) })) }
        else if (mode === 'pdb') source = { kind: 'pdb', projectInputRef: inputRef, chainIds: pdbChains }
        else source = { kind: 'prompt', nodeId: selectedPrompt!.nodeId, outputPort: selectedPrompt!.outputPort }
        await onPreparePrompt(preparePromptSource(workflow, catalog, source, mergeTargetNodeId))
      }
    } catch (cause) { setError(errorText(cause)) }
    finally { setBusy(false) }
  }
  const movePdbChain = (index: number, direction: -1 | 1) => setPdbChains(current => {
    const next = [...current]
    ;[next[index], next[index + direction]] = [next[index + direction], next[index]]
    return next
  })

  return <div className="input-source-backdrop">
    <section className="input-source-dialog" role="dialog" aria-modal="true" aria-labelledby="input-source-title" onKeyDown={event => { event.stopPropagation(); if (event.key === 'Escape' && !busy) onClose() }}>
      <header><div><span className="input-source-kicker">SOURCES</span><h2 id="input-source-title">{mergeTargetNodeId ? '添加手动合并来源' : '添加来源'}</h2></div><button type="button" aria-label="关闭来源输入" disabled={busy} onClick={onClose}>×</button></header>
      <nav className="input-source-modes" aria-label="来源类型">{sourceModes.filter(item => !mergeTargetNodeId || item.value !== 'batch').map(item => <button key={item.value} type="button" disabled={busy} aria-pressed={mode === item.value} onClick={() => changeMode(item.value)}><strong>{item.title}</strong><small>{item.description}</small></button>)}</nav>
      <form onSubmit={event => { void prepare(event) }}>
        <fieldset disabled={busy}>
          {usesInput && <section className="input-source-section" aria-label="输入文件">
            <div className="input-source-tabs">{([{ value: 'file', title: '上传文件' }, { value: 'paste', title: '粘贴文本' }, { value: 'existing', title: '已有 Input' }] as const).map(item => <button key={item.value} type="button" aria-pressed={inputMode === item.value} onClick={() => changeInputMode(item.value)}>{item.title}</button>)}</div>
            {inputMode === 'file' && <label>选择 {format === 'pdb' ? 'PDB' : 'FASTA'} 文件<input aria-label="来源文件" type="file" accept={format === 'pdb' ? '.pdb,.ent' : '.fasta,.fa,.faa,.fas,.txt'} onChange={event => { setFile(event.target.files?.[0]); setInspection(undefined); setError('') }} /></label>}
            {inputMode === 'paste' && <><label>保存的文件名<input aria-label="输入文件名" value={filename} onChange={event => { setFilename(event.target.value); setInspection(undefined) }} /></label><label>{format === 'pdb' ? 'PDB 文本' : 'FASTA 文本'}<textarea aria-label="来源文本" rows={7} spellCheck={false} value={pasted} onChange={event => { setPasted(event.target.value); setInspection(undefined) }} placeholder={format === 'fasta' ? '>record name\nACDEFGHIKLMNPQRSTVWY' : '粘贴完整 PDB 文本'} /></label></>}
            {inputMode === 'existing' && <label>项目内的原始输入<select aria-label="已有 Input" value={inputRef} onChange={event => { setInputRef(event.target.value); setInspection(undefined); setError('') }}><option value="">{inputsLoading ? '正在读取输入列表…' : inputs.length ? '选择 Input' : '项目中尚无 Input'}</option>{inputs.map(input => <option key={input.project_input_ref} value={input.project_input_ref}>{input.filename} · {input.size.toLocaleString()} bytes · {input.project_input_ref}</option>)}</select></label>}
            <button type="button" className="input-source-secondary" disabled={inputMode === 'file' ? !file : inputMode === 'paste' ? !filename.trim() || !pasted.trim() : !inputRef} onClick={() => { void readInput() }}>{inputMode === 'existing' ? '检查所选 Input' : '上传并检查输入'}</button>
            {selectedInput && inspection && <p className="input-source-provenance">{selectedInput.filename} · {selectedInput.size.toLocaleString()} bytes<br /><code>{selectedInput.project_input_ref}</code><br /><small>内容身份：{inspection.content_digest}</small></p>}
          </section>}

          {inspection?.format === 'fasta' && <section className="input-source-section" aria-label="FASTA 记录预览">
            <h3>{inspection.records.length} 条记录 · {inspection.total_length} 个残基</h3>
            <div className="input-source-table"><table><thead><tr><th>记录</th><th>名称 / Header</th><th>来源行</th><th>长度</th></tr></thead><tbody>{inspection.records.map(record => <tr key={record.record_index}><td>{record.record_index}</td><td>{record.display_name}<small>{record.header || '无名称；以记录序号显示'}</small></td><td>{record.line_number}</td><td>{record.length}</td></tr>)}</tbody></table></div>
            <p>{mode === 'batch' ? '每条 record 形成独立 Candidate；名称或序列重复仍保留。输入顺序与原始来源保存在结果中。' : '这些 record 按输入顺序组成一个完整序列。下方明确声明 Prompt 链长度；Header 不会自动成为链标识。'}</p>
          </section>}

          {(mode === 'blank' || mode === 'fasta' && inspection?.format === 'fasta') && <section className="input-source-section" aria-label="Prompt 链布局">
            <h3>Prompt 链布局</h3>
            {chains.map((chain, index) => <div className="input-source-chain" key={index}><label>Chain ID<input aria-label={`来源 Chain ${index + 1} ID`} required pattern="[A-Za-z0-9]" maxLength={1} value={chain.chain_id} onChange={event => setChains(current => current.map((item, i) => i === index ? { ...item, chain_id: event.target.value } : item))} /></label><label>残基数<input aria-label={`来源 Chain ${index + 1} length`} type="number" required min={1} max={2000000} step={1} value={chain.length} onChange={event => setChains(current => current.map((item, i) => i === index ? { ...item, length: event.target.value } : item))} /></label><button type="button" aria-label={`移除来源 Chain ${index + 1}`} disabled={chains.length === 1} onClick={() => setChains(current => current.filter((_, i) => i !== index))}>移除</button></div>)}
            <button type="button" onClick={() => setChains(current => [...current, { chain_id: '', length: '1' }])}>添加来源 Chain</button>
            {mode === 'fasta' && <p className={chainLengthMatches ? '' : 'input-source-warning'}>链总长度 {chainLength} / 序列长度 {inspection?.format === 'fasta' ? inspection.total_length : 0}。按所列链顺序分配序列。</p>}
          </section>}

          {mode === 'pdb' && inspection?.format === 'pdb' && <section className="input-source-section" aria-label="PDB 链选择">
            <h3>选择结构链</h3><p>链身份来自后端 PDB 读取。选择顺序决定输出顺序。</p>
            <div className="input-source-chain-options">{inspection.chain_ids.map(chain => <label key={chain}><input type="checkbox" aria-label={`选择 PDB Chain ${chain}`} checked={pdbChains.includes(chain)} onChange={event => setPdbChains(current => event.target.checked ? [...current, chain] : current.filter(item => item !== chain))} />Chain {chain}</label>)}</div>
            <ol className="input-source-order">{pdbChains.map((chain, index) => <li key={chain}><span>Chain {chain}</span><button type="button" aria-label={`上移 PDB Chain ${chain}`} disabled={index === 0} onClick={() => movePdbChain(index, -1)}>↑</button><button type="button" aria-label={`下移 PDB Chain ${chain}`} disabled={index === pdbChains.length - 1} onClick={() => movePdbChain(index, 1)}>↓</button></li>)}</ol>
            <p>结构导入 → 按链选择 → 解析残基轴 → ProteinPrompt。未解析的结构问题将在 Prompt 预览中显示。</p>
          </section>}

          {mode === 'prompt' && <section className="input-source-section"><label>ProteinPrompt 输出<select aria-label="已有 ProteinPrompt 输出" value={promptKey} onChange={event => setPromptKey(event.target.value)}><option value="">{promptSources.length ? '选择节点输出' : '当前流程没有可连接的 ProteinPrompt 输出'}</option>{promptSources.map(source => <option key={`${source.nodeId}/${source.outputPort}`} value={`${source.nodeId}/${source.outputPort}`}>{source.title} · {source.nodeId} / {source.outputPort}</option>)}</select></label><p>连线保留精确节点与输出端口。来源中的轨道、Mask 和注释由 Prompt 预览解释。</p></section>}
        </fieldset>
        {error && <p className="input-source-error" role="alert">{error}</p>}
        <footer><p>{mergeTargetNodeId ? '来源先进入手动对应编辑；确认保存时一并写入来源、连线与 Prompt。' : mode === 'batch' ? '确认后添加独立记录导入节点；可从其候选输出连接评分、筛选与折叠。' : '下一步进入 Prompt Studio；确认保存时一并写入来源、连线与 Prompt。'}<small>取消不改动 Workflow；已上传的 Input 保留在项目输入列表。</small></p><div><button type="button" disabled={busy} onClick={onClose}>取消</button><button className="input-source-primary" type="submit" disabled={busy || usesInput && !inspection || !chainLengthMatches || mode === 'pdb' && !pdbChains.length || mode === 'prompt' && !selectedPrompt}>{busy ? '处理中…' : mode === 'batch' ? '确认导入独立 Candidates' : '进入 Prompt 预览'}</button></div></footer>
      </form>
    </section>
  </div>
}
