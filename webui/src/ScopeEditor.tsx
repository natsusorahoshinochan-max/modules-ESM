import { useState } from 'react'
import type { FlowNode, Scope } from '@protein-workbench/module-ui'
import type { Catalog } from './host-client'
import { declarationFor } from './flow-model'

export function ScopeEditor({ node, catalog, disabled, onChange }: { node: FlowNode; catalog: Catalog; disabled: boolean; onChange(scope: Scope): void }) {
  const scope = node.scope!
  const [inputName, setInputName] = useState(''), [inputFormats, setInputFormats] = useState('')
  const [outputName, setOutputName] = useState(''), [outputFormat, setOutputFormat] = useState('')
  const [inputMany, setInputMany] = useState(false), [input必填, setInput必填] = useState(true), [outputMany, setOutputMany] = useState(node.type==='host.map')
  const [inputLink, setInputLink] = useState({input:'',node:'',port:''}), [outputLink, setOutputLink] = useState({output:'',node:'',port:''})
  const [error, setError] = useState('')
  const formats = [...new Set(catalog.nodes.flatMap(item => [...Object.values(item.outputs).map(port => port.format), ...Object.values(item.inputs).flatMap(port => port.accepts)]))].sort()
  const inputTarget = declarationFor(scope.body.nodes.find(item => item.id === inputLink.node), catalog)
  const outputSource = declarationFor(scope.body.nodes.find(item => item.id === outputLink.node), catalog)
  function apply(next: Scope) { try { onChange(next); setError('') } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)) } }
  function addInput() {
    const name = inputName.trim(), accepts = [...new Set(inputFormats.split(',').map(value => value.trim()).filter(Boolean))]
    if (!name || !accepts.length || scope.inputs[name]) { setError('Enter a new input name and at least one accepted format'); return }
    apply({...scope, inputs:{...scope.inputs,[name]:{accepts,cardinality:inputMany?'many':'one',required:input必填}}}); setInputName(''); setInputFormats('')
  }
  function addOutput() {
    const name = outputName.trim(), format = outputFormat.trim()
    if (!name || !format || scope.outputs[name]) { setError('Enter a new output name and its format'); return }
    apply({...scope, outputs:{...scope.outputs,[name]:{format,cardinality:outputMany?'many':'one'}}}); setOutputName(''); setOutputFormat('')
  }
  function addInputBinding() {
    const outer = scope.inputs[inputLink.input], inner = inputTarget?.inputs[inputLink.port]
    if (!outer || !inner || !outer.accepts.every(format => inner.accepts.includes(format))) { setError('The child input must accept every declared input format'); return }
    const isItem = node.type === 'host.map' && scope.item_input === inputLink.input
    if (!isItem && outer.cardinality === 'many' && inner.cardinality === 'one') { setError('A many input requires a many child input; select the per-item input for single-package processing'); return }
    if (scope.input_bindings.some(binding => binding.input === inputLink.input && binding.node === inputLink.node && binding.port === inputLink.port)) { setError('This input binding already exists'); return }
    apply({...scope,input_bindings:[...scope.input_bindings,inputLink]})
  }
  function addOutputBinding() {
    const outer = scope.outputs[outputLink.output], inner = outputSource?.outputs[outputLink.port]
    if (!outer || !inner || outer.format !== inner.format || (outer.cardinality === 'one' && (inner.cardinality === 'many' || node.type === 'host.map'))) { setError('Output format and cardinality must match; Map collects a many output'); return }
    if (scope.output_bindings.some(binding => binding.output === outputLink.output && binding.node === outputLink.node && binding.port === outputLink.port)) { setError('This output binding already exists'); return }
    apply({...scope,output_bindings:[...scope.output_bindings,outputLink]})
  }
  return <details className="scope-editor" aria-label="子流程设置"><summary>子流程设置</summary>
    {error && <p role="alert">{error}</p>}
    <fieldset disabled={disabled}><legend>执行</legend>{node.type === 'host.map' ? <label>逐项输入<select aria-label="逐项输入" value={scope.item_input ?? ''} onChange={event => apply({...scope,item_input:event.target.value})}><option value="">选择输入</option>{Object.keys(scope.inputs).map(port => <option key={port}>{port}</option>)}</select></label> : <label>循环轮数<input aria-label="循环轮数" type="number" min="1" step="1" value={scope.rounds ?? 1} onChange={event => { const rounds=Number(event.target.value); if(Number.isInteger(rounds) && rounds>0) apply({...scope,rounds}) }} /></label>}</fieldset>
    <datalist id={`formats-${node.id}`}>{formats.map(format => <option key={format} value={format} />)}</datalist>
    <details open><summary>输入与输出</summary><div className="scope-columns"><fieldset disabled={disabled}><legend>输入</legend>
      {Object.entries(scope.inputs).map(([name, port]) => <div className="scope-port" key={name}><strong>{name}</strong> · {port.accepts.join(', ')} · {port.cardinality}{port.required ? ' · required' : ''}
        <button aria-label={`删除 scope input ${name}`} onClick={() => { const { [name]: removed, ...inputs }=scope.inputs; void removed; const {[name]: old, ...feedback}=scope.feedback??{}; void old; apply({...scope,inputs,input_bindings:scope.input_bindings.filter(binding=>binding.input!==name),...(node.type==='host.map'?{item_input:scope.item_input===name?'':scope.item_input}:{feedback})}) }}>删除</button></div>)}
      <label>输入名称<input value={inputName} onChange={event=>setInputName(event.target.value)} /></label><label>数据格式（逗号分隔）<input list={`formats-${node.id}`} value={inputFormats} onChange={event=>setInputFormats(event.target.value)} /></label>
      <label className="inline-check"><input type="checkbox" checked={inputMany} onChange={event=>setInputMany(event.target.checked)} /> 多个数据包</label><label className="inline-check"><input type="checkbox" checked={input必填} onChange={event=>setInput必填(event.target.checked)} /> 必填</label><button onClick={addInput}>添加输入</button>
    </fieldset><fieldset disabled={disabled}><legend>输出</legend>
      {Object.entries(scope.outputs).map(([name, port]) => <div className="scope-port" key={name}><strong>{name}</strong> · {port.format} · {port.cardinality}<button aria-label={`删除 scope output ${name}`} onClick={() => {const {[name]:removed,...outputs}=scope.outputs;void removed;apply({...scope,outputs,output_bindings:scope.output_bindings.filter(binding=>binding.output!==name),...(node.type==='host.repeat'?{feedback:Object.fromEntries(Object.entries(scope.feedback??{}).filter(([,output])=>output!==name))}:{})})}}>删除</button></div>)}
      <label>输出名称<input value={outputName} onChange={event=>setOutputName(event.target.value)}/></label><label>数据格式<input list={`formats-${node.id}`} value={outputFormat} onChange={event=>setOutputFormat(event.target.value)}/></label><label className="inline-check"><input type="checkbox" checked={outputMany} onChange={event=>setOutputMany(event.target.checked)}/>多个结果</label><button onClick={addOutput}>添加输出</button>
    </fieldset></div></details>
    <details open><summary>连接子流程</summary><div className="scope-columns"><fieldset disabled={disabled}><legend>输入 → 节点</legend>
      <select aria-label="Boundary input" value={inputLink.input} onChange={event=>setInputLink({...inputLink,input:event.target.value})}><option value="">子流程输入</option>{Object.keys(scope.inputs).map(port=><option key={port}>{port}</option>)}</select>
      <select aria-label="Input binding child" value={inputLink.node} onChange={event=>setInputLink({...inputLink,node:event.target.value,port:''})}><option value="">内部节点</option>{scope.body.nodes.map((child,index)=><option key={child.id} value={child.id}>{index+1}: {declarationFor(child,catalog)?.name??child.type}</option>)}</select>
      <select aria-label="节点输入" value={inputLink.port} onChange={event=>setInputLink({...inputLink,port:event.target.value})}><option value="">节点输入</option>{Object.keys(inputTarget?.inputs??{}).map(port=><option key={port}>{port}</option>)}</select><button onClick={addInputBinding}>连接输入</button>
      <ul>{scope.input_bindings.map((binding,index)=><li key={index}>{binding.input} → {scope.body.nodes.findIndex(child=>child.id===binding.node)+1}:{binding.port} <button aria-label={`删除 input binding ${index+1}`} onClick={()=>apply({...scope,input_bindings:scope.input_bindings.filter((_,i)=>i!==index)})}>断开</button></li>)}</ul>
    </fieldset><fieldset disabled={disabled}><legend>节点 → 输出</legend>
      <select aria-label="Output binding child" value={outputLink.node} onChange={event=>setOutputLink({...outputLink,node:event.target.value,port:''})}><option value="">内部节点</option>{scope.body.nodes.map((child,index)=><option key={child.id} value={child.id}>{index+1}: {declarationFor(child,catalog)?.name??child.type}</option>)}</select>
      <select aria-label="节点输出" value={outputLink.port} onChange={event=>setOutputLink({...outputLink,port:event.target.value})}><option value="">节点输出</option>{Object.keys(outputSource?.outputs??{}).map(port=><option key={port}>{port}</option>)}</select>
      <select aria-label="Boundary output" value={outputLink.output} onChange={event=>setOutputLink({...outputLink,output:event.target.value})}><option value="">子流程输出</option>{Object.keys(scope.outputs).map(port=><option key={port}>{port}</option>)}</select><button onClick={addOutputBinding}>连接输出</button>
      <ul>{scope.output_bindings.map((binding,index)=><li key={index}>{scope.body.nodes.findIndex(child=>child.id===binding.node)+1}:{binding.port} → {binding.output} <button aria-label={`删除 output binding ${index+1}`} onClick={()=>apply({...scope,output_bindings:scope.output_bindings.filter((_,i)=>i!==index)})}>断开</button></li>)}</ul>
    </fieldset></div></details>
    {node.type==='host.repeat' && <fieldset disabled={disabled}><legend>下一轮输入</legend>{Object.entries(scope.inputs).map(([input,port])=><label key={input}>{input}<select aria-label={`Feedback for ${input}`} value={scope.feedback?.[input]??''} onChange={event=>{const feedback={...scope.feedback};if(event.target.value)feedback[input]=event.target.value;else delete feedback[input];apply({...scope,feedback})}}><option value="">保留原输入</option>{Object.entries(scope.outputs).filter(([,output])=>port.accepts.includes(output.format) && (port.cardinality==='many'||output.cardinality==='one')).map(([output])=><option key={output} value={output}>上一轮： {output}</option>)}</select></label>)}</fieldset>}
  </details>
}
