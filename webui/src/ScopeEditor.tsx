import { i18n } from './i18n'
const messages = {
"one": {"zh-CN": "单个", "en": "Single"},
"many": {"zh-CN": "多个", "en": "Multiple"},
  "enter_a_new_input_name_and_at": {
    "zh-CN": "请输入新的输入名称及接受的数据格式",
    "en": "Enter a new input name and at least one accepted format"
  },
  "enter_a_new_output_name_and_its": {
    "zh-CN": "请输入新的输出名称及数据格式",
    "en": "Enter a new output name and its format"
  },
  "the_child_input_must_accept_every_declared": {
    "zh-CN": "内部节点需接受此输入声明的所有格式",
    "en": "The child input must accept every declared input format"
  },
  "a_many_input_requires_a_many_child": {
    "zh-CN": "请连接可接收多个数据包的输入，或选为逐项输入",
    "en": "A many input requires a many child input; select the per-item input for single-package processing"
  },
  "this_input_binding_already_exists": {
    "zh-CN": "此输入连接已存在",
    "en": "This input binding already exists"
  },
  "output_format_and_cardinality_must_match_map": {
    "zh-CN": "输出格式和数量不匹配；逐项处理会收集多个输出",
    "en": "Output format and cardinality must match; Map collects a many output"
  },
  "this_output_binding_already_exists": {
    "zh-CN": "此输出连接已存在",
    "en": "This output binding already exists"
  },
  "subflow_settings": {
    "zh-CN": "子流程设置",
    "en": "Subflow settings"
  },
  "execution": {
    "zh-CN": "执行",
    "en": "Execution"
  },
  "per_item_input": {
    "zh-CN": "逐项输入",
    "en": "Per-item input"
  },
  "select_input": {
    "zh-CN": "选择输入",
    "en": "Select input"
  },
  "rounds": {
    "zh-CN": "循环轮数",
    "en": "Rounds"
  },
  "inputs_and_outputs": {
    "zh-CN": "输入与输出",
    "en": "Inputs and outputs"
  },
  "input": {
    "zh-CN": "输入",
    "en": "Input"
  },
  "remove_input": {
    "zh-CN": "删除 scope input {0}",
    "en": "Remove input {0}"
  },
  "delete": {
    "zh-CN": "删除",
    "en": "Delete"
  },
  "input_name": {
    "zh-CN": "输入名称",
    "en": "Input name"
  },
  "formats_comma_separated": {
    "zh-CN": "数据格式（逗号分隔）",
    "en": "Formats, comma-separated"
  },
  "multiple_packages": {
    "zh-CN": "多个数据包",
    "en": "Multiple packages"
  },
  "required": {
    "zh-CN": "必填",
    "en": "Required"
  },
  "add_input": {
    "zh-CN": "添加输入",
    "en": "Add input"
  },
  "output": {
    "zh-CN": "输出",
    "en": "Output"
  },
  "remove_output": {
    "zh-CN": "删除 scope output {0}",
    "en": "Remove output {0}"
  },
  "output_name": {
    "zh-CN": "输出名称",
    "en": "Output name"
  },
  "format": {
    "zh-CN": "数据格式",
    "en": "Format"
  },
  "multiple_results": {
    "zh-CN": "多个结果",
    "en": "Multiple results"
  },
  "add_output": {
    "zh-CN": "添加输出",
    "en": "Add output"
  },
  "subflow_connections": {
    "zh-CN": "连接子流程",
    "en": "Subflow connections"
  },
  "input_node": {
    "zh-CN": "输入 → 节点",
    "en": "Input → Node"
  },
  "boundary_input": {
    "zh-CN": "子流程输入",
    "en": "Boundary input"
  },
  "subflow_input": {
    "zh-CN": "子流程输入",
    "en": "Subflow input"
  },
  "input_binding_child": {
    "zh-CN": "接收输入的内部节点",
    "en": "Input binding child"
  },
  "child_node": {
    "zh-CN": "内部节点",
    "en": "Child node"
  },
  "node_input": {
    "zh-CN": "节点输入",
    "en": "Node input"
  },
  "connect_input": {
    "zh-CN": "连接输入",
    "en": "Connect input"
  },
  "remove_input_connection": {
    "zh-CN": "删除 input binding {0}",
    "en": "Remove input connection {0}"
  },
  "disconnect": {
    "zh-CN": "断开",
    "en": "Disconnect"
  },
  "node_output": {
    "zh-CN": "节点 → 输出",
    "en": "Node → Output"
  },
  "output_binding_child": {
    "zh-CN": "提供输出的内部节点",
    "en": "Output binding child"
  },
  "node_output_2": {
    "zh-CN": "节点输出",
    "en": "Node output"
  },
  "boundary_output": {
    "zh-CN": "子流程输出",
    "en": "Boundary output"
  },
  "subflow_output": {
    "zh-CN": "子流程输出",
    "en": "Subflow output"
  },
  "connect_output": {
    "zh-CN": "连接输出",
    "en": "Connect output"
  },
  "remove_output_connection": {
    "zh-CN": "删除 output binding {0}",
    "en": "Remove output connection {0}"
  },
  "next_round_inputs": {
    "zh-CN": "下一轮输入",
    "en": "Next round inputs"
  },
  "feedback_for": {
    "zh-CN": "{0} 的反馈",
    "en": "Feedback for {0}"
  },
  "keep_original_input": {
    "zh-CN": "保留原输入",
    "en": "Keep original input"
  },
  "previous_round": {
    "zh-CN": "上一轮：",
    "en": "Previous round: "
  }
};
const t = i18n.translator(messages)
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
    if (!name || !accepts.length || scope.inputs[name]) { setError(t("enter_a_new_input_name_and_at")); return }
    apply({...scope, inputs:{...scope.inputs,[name]:{accepts,cardinality:inputMany?'many':'one',required:input必填}}}); setInputName(''); setInputFormats('')
  }
  function addOutput() {
    const name = outputName.trim(), format = outputFormat.trim()
    if (!name || !format || scope.outputs[name]) { setError(t("enter_a_new_output_name_and_its")); return }
    apply({...scope, outputs:{...scope.outputs,[name]:{format,cardinality:outputMany?'many':'one'}}}); setOutputName(''); setOutputFormat('')
  }
  function addInputBinding() {
    const outer = scope.inputs[inputLink.input], inner = inputTarget?.inputs[inputLink.port]
    if (!outer || !inner || !outer.accepts.every(format => inner.accepts.includes(format))) { setError(t("the_child_input_must_accept_every_declared")); return }
    const isItem = node.type === 'host.map' && scope.item_input === inputLink.input
    if (!isItem && outer.cardinality === 'many' && inner.cardinality === 'one') { setError(t("a_many_input_requires_a_many_child")); return }
    if (scope.input_bindings.some(binding => binding.input === inputLink.input && binding.node === inputLink.node && binding.port === inputLink.port)) { setError(t("this_input_binding_already_exists")); return }
    apply({...scope,input_bindings:[...scope.input_bindings,inputLink]})
  }
  function addOutputBinding() {
    const outer = scope.outputs[outputLink.output], inner = outputSource?.outputs[outputLink.port]
    if (!outer || !inner || outer.format !== inner.format || (outer.cardinality === 'one' && (inner.cardinality === 'many' || node.type === 'host.map'))) { setError(t("output_format_and_cardinality_must_match_map")); return }
    if (scope.output_bindings.some(binding => binding.output === outputLink.output && binding.node === outputLink.node && binding.port === outputLink.port)) { setError(t("this_output_binding_already_exists")); return }
    apply({...scope,output_bindings:[...scope.output_bindings,outputLink]})
  }
  return <details className="scope-editor" aria-label={t("subflow_settings")}><summary>{t("subflow_settings")}</summary>
    {error && <p role="alert">{error}</p>}
    <fieldset disabled={disabled}><legend>{t("execution")}</legend>{node.type === 'host.map' ? <label>{t("per_item_input")}<select aria-label={t("per_item_input")} value={scope.item_input ?? ''} onChange={event => apply({...scope,item_input:event.target.value})}><option value="">{t("select_input")}</option>{Object.keys(scope.inputs).map(port => <option key={port}>{port}</option>)}</select></label> : <label>{t("rounds")}<input aria-label={t("rounds")} type="number" min="1" step="1" value={scope.rounds ?? 1} onChange={event => { const rounds=Number(event.target.value); if(Number.isInteger(rounds) && rounds>0) apply({...scope,rounds}) }} /></label>}</fieldset>
    <datalist id={`formats-${node.id}`}>{formats.map(format => <option key={format} value={format} />)}</datalist>
    <details open><summary>{t("inputs_and_outputs")}</summary><div className="scope-columns"><fieldset disabled={disabled}><legend>{t("input")}</legend>
      {Object.entries(scope.inputs).map(([name, port]) => <div className="scope-port" key={name}><strong>{name}</strong> · {port.accepts.join(', ')} · {t(port.cardinality)}{port.required ? ' · '+t('required') : ''}
        <button aria-label={t("remove_input", {"0": name})} onClick={() => { const { [name]: removed, ...inputs }=scope.inputs; void removed; const {[name]: old, ...feedback}=scope.feedback??{}; void old; apply({...scope,inputs,input_bindings:scope.input_bindings.filter(binding=>binding.input!==name),...(node.type==='host.map'?{item_input:scope.item_input===name?'':scope.item_input}:{feedback})}) }}>{t("delete")}</button></div>)}
      <label>{t("input_name")}<input value={inputName} onChange={event=>setInputName(event.target.value)} /></label><label>{t("formats_comma_separated")}<input list={`formats-${node.id}`} value={inputFormats} onChange={event=>setInputFormats(event.target.value)} /></label>
      <label className="inline-check"><input type="checkbox" checked={inputMany} onChange={event=>setInputMany(event.target.checked)} />  {t("multiple_packages")}</label><label className="inline-check"><input type="checkbox" checked={input必填} onChange={event=>setInput必填(event.target.checked)} />  {t("required")}</label><button onClick={addInput}>{t("add_input")}</button>
    </fieldset><fieldset disabled={disabled}><legend>{t("output")}</legend>
      {Object.entries(scope.outputs).map(([name, port]) => <div className="scope-port" key={name}><strong>{name}</strong> · {port.format} · {t(port.cardinality)}<button aria-label={t("remove_output", {"0": name})} onClick={() => {const {[name]:removed,...outputs}=scope.outputs;void removed;apply({...scope,outputs,output_bindings:scope.output_bindings.filter(binding=>binding.output!==name),...(node.type==='host.repeat'?{feedback:Object.fromEntries(Object.entries(scope.feedback??{}).filter(([,output])=>output!==name))}:{})})}}>{t("delete")}</button></div>)}
      <label>{t("output_name")}<input value={outputName} onChange={event=>setOutputName(event.target.value)}/></label><label>{t("format")}<input list={`formats-${node.id}`} value={outputFormat} onChange={event=>setOutputFormat(event.target.value)}/></label><label className="inline-check"><input type="checkbox" checked={outputMany} onChange={event=>setOutputMany(event.target.checked)}/>{t("multiple_results")}</label><button onClick={addOutput}>{t("add_output")}</button>
    </fieldset></div></details>
    <details open><summary>{t("subflow_connections")}</summary><div className="scope-columns"><fieldset disabled={disabled}><legend>{t("input_node")}</legend>
      <select aria-label={t("boundary_input")} value={inputLink.input} onChange={event=>setInputLink({...inputLink,input:event.target.value})}><option value="">{t("subflow_input")}</option>{Object.keys(scope.inputs).map(port=><option key={port}>{port}</option>)}</select>
      <select aria-label={t("input_binding_child")} value={inputLink.node} onChange={event=>setInputLink({...inputLink,node:event.target.value,port:''})}><option value="">{t("child_node")}</option>{scope.body.nodes.map((child,index)=><option key={child.id} value={child.id}>{index+1}: {declarationFor(child,catalog)?.name??child.type}</option>)}</select>
      <select aria-label={t("node_input")} value={inputLink.port} onChange={event=>setInputLink({...inputLink,port:event.target.value})}><option value="">{t("node_input")}</option>{Object.keys(inputTarget?.inputs??{}).map(port=><option key={port}>{port}</option>)}</select><button onClick={addInputBinding}>{t("connect_input")}</button>
      <ul>{scope.input_bindings.map((binding,index)=><li key={index}>{binding.input} → {scope.body.nodes.findIndex(child=>child.id===binding.node)+1}:{binding.port} <button aria-label={t("remove_input_connection", {"0": index+1})} onClick={()=>apply({...scope,input_bindings:scope.input_bindings.filter((_,i)=>i!==index)})}>{t("disconnect")}</button></li>)}</ul>
    </fieldset><fieldset disabled={disabled}><legend>{t("node_output")}</legend>
      <select aria-label={t("output_binding_child")} value={outputLink.node} onChange={event=>setOutputLink({...outputLink,node:event.target.value,port:''})}><option value="">{t("child_node")}</option>{scope.body.nodes.map((child,index)=><option key={child.id} value={child.id}>{index+1}: {declarationFor(child,catalog)?.name??child.type}</option>)}</select>
      <select aria-label={t("node_output_2")} value={outputLink.port} onChange={event=>setOutputLink({...outputLink,port:event.target.value})}><option value="">{t("node_output_2")}</option>{Object.keys(outputSource?.outputs??{}).map(port=><option key={port}>{port}</option>)}</select>
      <select aria-label={t("boundary_output")} value={outputLink.output} onChange={event=>setOutputLink({...outputLink,output:event.target.value})}><option value="">{t("subflow_output")}</option>{Object.keys(scope.outputs).map(port=><option key={port}>{port}</option>)}</select><button onClick={addOutputBinding}>{t("connect_output")}</button>
      <ul>{scope.output_bindings.map((binding,index)=><li key={index}>{scope.body.nodes.findIndex(child=>child.id===binding.node)+1}:{binding.port} → {binding.output} <button aria-label={t("remove_output_connection", {"0": index+1})} onClick={()=>apply({...scope,output_bindings:scope.output_bindings.filter((_,i)=>i!==index)})}>{t("disconnect")}</button></li>)}</ul>
    </fieldset></div></details>
    {node.type==='host.repeat' && <fieldset disabled={disabled}><legend>{t("next_round_inputs")}</legend>{Object.entries(scope.inputs).map(([input,port])=><label key={input}>{input}<select aria-label={t("feedback_for", {"0": input})} value={scope.feedback?.[input]??''} onChange={event=>{const feedback={...scope.feedback};if(event.target.value)feedback[input]=event.target.value;else delete feedback[input];apply({...scope,feedback})}}><option value="">{t("keep_original_input")}</option>{Object.entries(scope.outputs).filter(([,output])=>port.accepts.includes(output.format) && (port.cardinality==='many'||output.cardinality==='one')).map(([output])=><option key={output} value={output}>{t("previous_round")} {output}</option>)}</select></label>)}</fieldset>}
  </details>
}
