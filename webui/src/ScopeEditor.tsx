import { useState } from 'react'
import type { FlowNode, Scope } from '@protein-workbench/module-ui'
import type { Catalog } from './host-client'
import { declarationFor } from './flow-model'

export function ScopeEditor({ node, catalog, disabled, onChange }: { node: FlowNode; catalog: Catalog; disabled: boolean; onChange(scope: Scope): void }) {
  const scope = node.scope!
  const [inputName, setInputName] = useState(''), [inputFormats, setInputFormats] = useState('')
  const [outputName, setOutputName] = useState(''), [outputFormat, setOutputFormat] = useState('')
  const [inputMany, setInputMany] = useState(false), [inputRequired, setInputRequired] = useState(true), [outputMany, setOutputMany] = useState(node.type==='host.map')
  const [inputLink, setInputLink] = useState({input:'',node:'',port:''}), [outputLink, setOutputLink] = useState({output:'',node:'',port:''})
  const [error, setError] = useState('')
  const formats = [...new Set(catalog.nodes.flatMap(item => [...Object.values(item.outputs).map(port => port.format), ...Object.values(item.inputs).flatMap(port => port.accepts)]))].sort()
  const inputTarget = declarationFor(scope.body.nodes.find(item => item.id === inputLink.node), catalog)
  const outputSource = declarationFor(scope.body.nodes.find(item => item.id === outputLink.node), catalog)
  function apply(next: Scope) { try { onChange(next); setError('') } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)) } }
  function addInput() {
    const name = inputName.trim(), accepts = [...new Set(inputFormats.split(',').map(value => value.trim()).filter(Boolean))]
    if (!name || !accepts.length || scope.inputs[name]) { setError('Enter a new input name and at least one accepted format'); return }
    apply({...scope, inputs:{...scope.inputs,[name]:{accepts,cardinality:inputMany?'many':'one',required:inputRequired}}}); setInputName(''); setInputFormats('')
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
  return <section className="scope-editor" aria-label="Subflow boundary"><h3>{node.type === 'host.map' ? 'For each package' : 'Repeat subflow'} · boundary and feedback</h3>
    <p>{node.type === 'host.map' ? 'Each package on the selected input runs this body once. Other inputs are passed unchanged to every item. Outputs collect successful item deliveries.' : 'Each round runs this body. Feedback replaces only the connected inputs for the next round. Other inputs stay fixed. The scope output contains the last round; every round remains available in Runs.'}</p>
    {error && <p role="alert">{error}</p>}
    <fieldset disabled={disabled}><legend>Execution</legend>{node.type === 'host.map' ? <label>Per-item input<select aria-label="Per-item input" value={scope.item_input ?? ''} onChange={event => apply({...scope,item_input:event.target.value})}><option value="">Choose input</option>{Object.keys(scope.inputs).map(port => <option key={port}>{port}</option>)}</select></label> : <label>Number of rounds<input aria-label="Number of rounds" type="number" min="1" step="1" value={scope.rounds ?? 1} onChange={event => { const rounds=Number(event.target.value); if(Number.isInteger(rounds) && rounds>0) apply({...scope,rounds}) }} /></label>}</fieldset>
    <datalist id={`formats-${node.id}`}>{formats.map(format => <option key={format} value={format} />)}</datalist>
    <details open><summary>Declare boundary ports</summary><div className="scope-columns"><fieldset disabled={disabled}><legend>Inputs</legend>
      {Object.entries(scope.inputs).map(([name, port]) => <div className="scope-port" key={name}><strong>{name}</strong> · {port.accepts.join(', ')} · {port.cardinality}{port.required ? ' · required' : ''}
        <button aria-label={`Remove scope input ${name}`} onClick={() => { const { [name]: removed, ...inputs }=scope.inputs; void removed; const {[name]: old, ...feedback}=scope.feedback??{}; void old; apply({...scope,inputs,input_bindings:scope.input_bindings.filter(binding=>binding.input!==name),...(node.type==='host.map'?{item_input:scope.item_input===name?'':scope.item_input}:{feedback})}) }}>Remove</button></div>)}
      <label>Input name<input value={inputName} onChange={event=>setInputName(event.target.value)} /></label><label>Accepted formats (comma separated)<input list={`formats-${node.id}`} value={inputFormats} onChange={event=>setInputFormats(event.target.value)} /></label>
      <label className="inline-check"><input type="checkbox" checked={inputMany} onChange={event=>setInputMany(event.target.checked)} /> Multiple packages</label><label className="inline-check"><input type="checkbox" checked={inputRequired} onChange={event=>setInputRequired(event.target.checked)} /> Required</label><button onClick={addInput}>Add scope input</button>
    </fieldset><fieldset disabled={disabled}><legend>Outputs</legend>
      {Object.entries(scope.outputs).map(([name, port]) => <div className="scope-port" key={name}><strong>{name}</strong> · {port.format} · {port.cardinality}<button aria-label={`Remove scope output ${name}`} onClick={() => {const {[name]:removed,...outputs}=scope.outputs;void removed;apply({...scope,outputs,output_bindings:scope.output_bindings.filter(binding=>binding.output!==name),...(node.type==='host.repeat'?{feedback:Object.fromEntries(Object.entries(scope.feedback??{}).filter(([,output])=>output!==name))}:{})})}}>Remove</button></div>)}
      <label>Output name<input value={outputName} onChange={event=>setOutputName(event.target.value)} /></label><label>Output format<input list={`formats-${node.id}`} value={outputFormat} onChange={event=>setOutputFormat(event.target.value)} /></label><label className="inline-check"><input type="checkbox" checked={outputMany} onChange={event=>setOutputMany(event.target.checked)} /> Multiple packages</label><button onClick={addOutput}>Add scope output</button>
    </fieldset></div></details>
    <details open><summary>Connect boundary ports to child nodes</summary><div className="scope-columns"><fieldset disabled={disabled}><legend>Input → child input</legend>
      <select aria-label="Boundary input" value={inputLink.input} onChange={event=>setInputLink({...inputLink,input:event.target.value})}><option value="">Scope input</option>{Object.keys(scope.inputs).map(port=><option key={port}>{port}</option>)}</select>
      <select aria-label="Input binding child" value={inputLink.node} onChange={event=>setInputLink({...inputLink,node:event.target.value,port:''})}><option value="">Child node</option>{scope.body.nodes.map((child,index)=><option key={child.id} value={child.id}>{index+1}: {declarationFor(child,catalog)?.name??child.type}</option>)}</select>
      <select aria-label="Child input" value={inputLink.port} onChange={event=>setInputLink({...inputLink,port:event.target.value})}><option value="">Child input</option>{Object.keys(inputTarget?.inputs??{}).map(port=><option key={port}>{port}</option>)}</select><button onClick={addInputBinding}>Bind scope input</button>
      <ul>{scope.input_bindings.map((binding,index)=><li key={index}>{binding.input} → {scope.body.nodes.findIndex(child=>child.id===binding.node)+1}:{binding.port} <button aria-label={`Remove input binding ${index+1}`} onClick={()=>apply({...scope,input_bindings:scope.input_bindings.filter((_,i)=>i!==index)})}>Disconnect</button></li>)}</ul>
    </fieldset><fieldset disabled={disabled}><legend>Child output → output</legend>
      <select aria-label="Output binding child" value={outputLink.node} onChange={event=>setOutputLink({...outputLink,node:event.target.value,port:''})}><option value="">Child node</option>{scope.body.nodes.map((child,index)=><option key={child.id} value={child.id}>{index+1}: {declarationFor(child,catalog)?.name??child.type}</option>)}</select>
      <select aria-label="Child output" value={outputLink.port} onChange={event=>setOutputLink({...outputLink,port:event.target.value})}><option value="">Child output</option>{Object.keys(outputSource?.outputs??{}).map(port=><option key={port}>{port}</option>)}</select>
      <select aria-label="Boundary output" value={outputLink.output} onChange={event=>setOutputLink({...outputLink,output:event.target.value})}><option value="">Scope output</option>{Object.keys(scope.outputs).map(port=><option key={port}>{port}</option>)}</select><button onClick={addOutputBinding}>Bind scope output</button>
      <ul>{scope.output_bindings.map((binding,index)=><li key={index}>{scope.body.nodes.findIndex(child=>child.id===binding.node)+1}:{binding.port} → {binding.output} <button aria-label={`Remove output binding ${index+1}`} onClick={()=>apply({...scope,output_bindings:scope.output_bindings.filter((_,i)=>i!==index)})}>Disconnect</button></li>)}</ul>
    </fieldset></div></details>
    {node.type==='host.repeat' && <fieldset disabled={disabled}><legend>Next-round feedback</legend>{Object.entries(scope.inputs).map(([input,port])=><label key={input}>{input}<select aria-label={`Feedback for ${input}`} value={scope.feedback?.[input]??''} onChange={event=>{const feedback={...scope.feedback};if(event.target.value)feedback[input]=event.target.value;else delete feedback[input];apply({...scope,feedback})}}><option value="">Keep original input each round</option>{Object.entries(scope.outputs).filter(([,output])=>port.accepts.includes(output.format) && (port.cardinality==='many'||output.cardinality==='one')).map(([output])=><option key={output} value={output}>Previous round: {output}</option>)}</select></label>)}</fieldset>}
  </section>
}
