export const runtime={react:19}
export function register({React}) {
 const h=React.createElement
 const metrics=['workbench.metric_analysis','workbench.proteinmpnn_design','workbench.esm3_generation','workbench.structure_confidence','workbench.comparison','workbench.solubility','workbench.prediction','workbench.sequence_backbone_evaluation','workbench.collection']
 const candidates=['workbench.sequence','workbench.structure_set','workbench.proteinmpnn_design','workbench.collection',...metrics.filter(format=>format!=='workbench.metric_analysis')]
 const methodText=value=>typeof value==='string'?value:Object.entries(value??{}).filter(([key])=>['name','method','id','tmtools','algorithm','scope','parameters','actual_seed','statistic'].includes(key)).map(([key,value])=>`${key}: ${typeof value==='object'?JSON.stringify(value):value}`).join('; ')
 const contextText=c=>`Evaluation input ${(c.context?.input??c.evaluation.input)+1}${c.context?.source===undefined?'':` · source ${c.context.source+1}`} · ${c.context?.format??'Evaluation'} · ${c.context?.entry??''}${c.context?.analysis_source===undefined?'':` · analysis source ${c.context.analysis_source+1}`}`
 const referenceText=c=>c.reference_display?[c.reference_display.label??c.reference_display.name??'Unnamed reference',c.reference_display.file,c.reference_display.format].filter(Boolean).join(' · '):(c.reference?'Unnamed reference':'No reference')
 const choiceLabel=c=>`${contextText(c)} · ${c.metric} · ${referenceText(c)} · ${methodText(c.method)} · Region ${JSON.stringify(c.region)} · ${c.sample===null||c.sample===undefined?'':`Sample ${c.sample+1} · `}${c.unit??''} · ${c.meaning??''}${c.unavailable?' · Unavailable: '+c.unavailable:''}`
 function EvaluationRule({evaluation,onSelect,label,disabled}) {
  const value=JSON.stringify(evaluation,null,2)
  const [draft,setDraft]=React.useState(value),[error,setError]=React.useState('')
  React.useEffect(()=>{setDraft(value);setError('')},[value])
  let referenceMode=evaluation.reference_mode==='provided_evaluations'?'provided_evaluations':'exact'
  try{referenceMode=JSON.parse(draft).reference_mode==='provided_evaluations'?'provided_evaluations':'exact'}catch{}
  function chooseReference(mode){
   try{
    const rule=JSON.parse(draft)
    if(!rule||Array.isArray(rule)||typeof rule!=='object')throw new Error('Enter an evaluation rule object before changing its reference selection.')
    if(mode==='provided_evaluations'){delete rule.reference;rule.reference_mode=mode}
    else{delete rule.reference_mode;rule.reference=null}
    setDraft(JSON.stringify(rule,null,2));setError('')
   }catch(failure){setError(failure.message)}
  }
  function apply(){
   try{
    const rule=JSON.parse(draft),allowed=['metric','method','reference','reference_mode','region','origin','sample']
    const validReference=rule&&((Object.hasOwn(rule,'reference')&&!Object.hasOwn(rule,'reference_mode'))||(!Object.hasOwn(rule,'reference')&&rule.reference_mode==='provided_evaluations'))
    if(!rule||Array.isArray(rule)||typeof rule!=='object'||Object.keys(rule).some(key=>!allowed.includes(key))||!['metric','method','region'].every(key=>Object.hasOwn(rule,key))||typeof rule.metric!=='string'||!rule.metric.trim()||!validReference)throw new Error('Specify metric, method and region, and either reference or reference_mode: "provided_evaluations"; optional fields are origin and sample.')
    onSelect(rule);setError('')
   }catch(failure){setError(failure.message)}
  }
  return h('div',null,h('p',null,'Match the specified metric, actual method and original region for each current object. Missing or multiple matching evaluations stop the operation.'),
   h('label',null,'Reference selection',h('select',{'aria-label':`${label} reference selection`,disabled,value:referenceMode,onChange:event=>chooseReference(event.target.value)},h('option',{value:'exact'},'Exact reference in rule'),h('option',{value:'provided_evaluations'},'Reference from connected evaluations'))),
   h('p',null,referenceMode==='provided_evaluations'?'Use only the explicitly connected evaluation packages. Each current object must have one matching evaluation, even when its reference changes between rounds. Multiple reference matches are ambiguous.':'The rule reference must match exactly. Use null for an evaluation with no reference.'),
   h('label',null,'Evaluation rule JSON',h('textarea',{'aria-label':`${label} evaluation rule JSON`,disabled,value:draft,onChange:event=>{setDraft(event.target.value);setError('')}})),
   h('button',{type:'button',disabled,onClick:apply},`Apply ${label} rule`),error&&h('p',{role:'alert'},error))
 }
 function ReferenceDetails({choice,host,inputs}) {
  const [text,setText]=React.useState(''),[error,setError]=React.useState(''),[busy,setBusy]=React.useState(false)
  const epoch=React.useRef(0),mounted=React.useRef(false),current=React.useRef(null)
  const access=choice.reference_access,packageId=inputs.evaluations?.[access?.input]
  const key=JSON.stringify([choice.evaluation,packageId,access?.key])
  current.current=key
  React.useEffect(()=>{mounted.current=true;setText('');setError('');setBusy(false);return()=>{mounted.current=false;epoch.current++}},[key])
  async function view() {
   const request=++epoch.current,origin=key
   const live=()=>mounted.current&&epoch.current===request&&current.current===origin
   setBusy(true);setError('');setText('')
   try{const file=await host.readFile(packageId,access.key);const content=await file.text();if(live())setText(content)}
   catch(error){if(live())setError(error.message)}finally{if(live())setBusy(false)}
  }
  return h('section',{'aria-label':'Selected evaluation details'},
   h('p',null,contextText(choice)),h('p',null,`Reference: ${referenceText(choice)}`),
   h('p',null,`Method: ${methodText(choice.method)}`),h('p',null,`Selected region: ${JSON.stringify(choice.region)}`),
   choice.method?.source_method&&h('p',null,`Source method: ${methodText(choice.method.source_method)}`),
   choice.method?.source_region!==undefined&&h('p',null,`Source region: ${JSON.stringify(choice.method.source_region)}`),
   access?.key&&packageId?h('button',{type:'button',disabled:busy,onClick:view},'View reference file'):h('p',null,access?.unavailable??'Reference file access unavailable'),
   error&&h('p',{role:'alert'},error),text&&h('pre',{'aria-label':'Reference file content'},text))
 }
 function Controls({host,inputs,parameters,onChange,disabled=false,temporary=false}) {
  const [rows,setRows]=React.useState([]),[error,setError]=React.useState(''),[busy,setBusy]=React.useState(false),[selected,setSelected]=React.useState(null)
  const epoch=React.useRef(0),abort=React.useRef(null)
  const signature=JSON.stringify(inputs)
  React.useEffect(()=>{epoch.current++;abort.current?.abort();setRows([]);setSelected(null);setError('');setBusy(false);return()=>{epoch.current++;abort.current?.abort()}},[signature])
  function change(next){epoch.current++;abort.current?.abort();setBusy(false);setSelected(null);onChange(next)}
  async function invoke(name) {
   const current=++epoch.current;abort.current?.abort();abort.current=new AbortController();setBusy(true);setError('')
   try {
    const response=await host.preview(name,inputs,name.endsWith('inspect')?{}:parameters,{signal:abort.current.signal})
    try{if(current===epoch.current){if(name.endsWith('inspect'))setRows(response.data.candidates);else setSelected(response.data.selected)}}
    finally{await host.cancelPreview(response.id)}
   }catch(error){if(current===epoch.current)setError(error.message)}finally{if(current===epoch.current)setBusy(false)}
  }
  const bindings=(evaluation,row,value)=>({bindings:[...(evaluation?.bindings??[]).filter(binding=>JSON.stringify(binding.candidate)!==JSON.stringify({input:row.input,item:row.item})),...(value===''?[]:[{candidate:{input:row.input,item:row.item},evaluation:row.choices[Number(value)].evaluation}])]})
  function evaluationFields(evaluation,onSelect,key) {
   const semantic=evaluation!==undefined&&!Object.hasOwn(evaluation,'bindings')
   const mode=h('label',{key:'mode'},'Evaluation selection',h('select',{'aria-label':`${key} evaluation selection`,disabled,value:semantic?'meaning':'records',onChange:event=>onSelect(event.target.value==='meaning'?{metric:'',method:null,reference:null,region:null}:{bindings:[]})},h('option',{value:'records'},'Choose actual evaluation records'),h('option',{value:'meaning'},'Match evaluation meaning for current objects')))
   if(semantic)return [mode,h(EvaluationRule,{key:'rule',evaluation,onSelect,label:key,disabled})]
   return [mode,...rows.map((row,index)=>{
    const bound=evaluation?.bindings?.find(binding=>binding.candidate.input===row.input&&binding.candidate.item===row.item)
    const selected=row.choices.findIndex(choice=>JSON.stringify(choice.evaluation)===JSON.stringify(bound?.evaluation))
    return h('div',{key:index},h('label',null,`Input ${row.input+1} · ${row.label}`,h('select',{'aria-label':`${key} evaluation for input ${row.input+1} item ${row.item+1}`,disabled,value:selected<0?'':String(selected),onChange:event=>onSelect(bindings(evaluation,row,event.target.value))},h('option',{value:''},'Choose actual evaluation'),...row.choices.map((choice,i)=>h('option',{key:i,value:String(i),disabled:!!choice.unavailable},choiceLabel(choice))))),selected>=0&&h(ReferenceDetails,{choice:row.choices[selected],host,inputs}))
   })]
  }
  return h('section',{'aria-label':temporary?'Temporary filtering':'Node filtering parameters'},
   h('button',{disabled:busy,onClick:()=>invoke('workbench.filter.inspect')},'Inspect selected inputs'),
   error&&h('p',{role:'alert'},error),
   ...rows.map((row,index)=>h('p',{key:index},`Input ${row.input+1} · ${row.label} · ${row.choices.length} existing evaluation choices`)),
   h('fieldset',null,h('legend',null,'Conditions'),
    ...(parameters.conditions??[]).map((condition,index)=>h('fieldset',{key:index},h('legend',null,`Condition ${index+1}`),
     ...evaluationFields(condition.evaluation,evaluation=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,evaluation}:c)}),`Condition ${index+1}`),
     h('select',{'aria-label':`Condition ${index+1} comparison`,disabled,value:condition.operator,onChange:event=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,operator:event.target.value}:c)})},...['lt','le','eq','ge','gt'].map((op,i)=>h('option',{key:op,value:op},['<','≤','=','≥','>'][i]))),
     h('input',{'aria-label':`Condition ${index+1} value`,disabled,type:'number',step:'any',value:condition.value??'',onChange:event=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,value:event.target.value===''?null:Number(event.target.value)}:c)})}),
     h('button',{disabled,onClick:()=>change({...parameters,conditions:parameters.conditions.filter((_,i)=>i!==index)})},'Remove condition'))),
    h('button',{disabled,onClick:()=>change({...parameters,conditions:[...(parameters.conditions??[]),{evaluation:{bindings:[]},operator:'ge',value:0}]})},'Add condition'),
    h('label',null,h('input',{type:'checkbox',disabled,checked:!!parameters.sort,onChange:event=>{const next={...parameters};if(event.target.checked)next.sort={evaluation:{bindings:[]},direction:'ascending'};else delete next.sort;change(next)}}),'Sort by an existing evaluation'),
    parameters.sort&&h('div',null,...evaluationFields(parameters.sort.evaluation,evaluation=>change({...parameters,sort:{...parameters.sort,evaluation}}),'Sort'),h('select',{'aria-label':'Sort direction',disabled,value:parameters.sort.direction,onChange:event=>change({...parameters,sort:{...parameters.sort,direction:event.target.value}})},h('option',{value:'ascending'},'Ascending'),h('option',{value:'descending'},'Descending'))),
    h('label',null,'Quantity limit',h('input',{'aria-label':'Quantity limit',disabled,type:'number',min:0,step:1,value:parameters.limit??'',onChange:event=>{const next={...parameters};if(event.target.value==='')delete next.limit;else next.limit=Number(event.target.value);change(next)}}))),
   temporary&&h('button',{disabled:busy,onClick:()=>invoke('workbench.filter')},'Apply temporary filter'),
   selected&&h('ol',{'aria-label':'Temporarily selected items'},...selected.map((item,index)=>h('li',{key:index},`Input ${item.input+1} · Item ${item.item+1}`))))
 }
 function ResultAction({host,packages}) {
  const [inputIds,setInputs]=React.useState([]),[evaluationIds,setEvaluations]=React.useState([]),[parameters,setParameters]=React.useState({})
  const signature=packages.map(pkg=>pkg.id).join(',')
  React.useEffect(()=>{setInputs(ids=>ids.filter(id=>packages.some(pkg=>pkg.id===id)));setEvaluations(ids=>ids.filter(id=>packages.some(pkg=>pkg.id===id)))},[signature])
  function pick(formatList,ids,setIds,title){return h('fieldset',null,h('legend',null,title),...packages.map((pkg,index)=>formatList.includes(pkg.format)&&h('label',{key:pkg.id},h('input',{type:'checkbox',checked:ids.includes(pkg.id),onChange:event=>setIds(event.target.checked?[...ids,pkg.id]:ids.filter(id=>id!==pkg.id))}),`Input ${index+1} · ${pkg.format}`)))}
  return h('section',{'aria-label':'Result filtering'},h('h3',null,'Temporary filter and sort'),pick(candidates,inputIds,setInputs,'Candidate packages'),pick(metrics,evaluationIds,setEvaluations,'Existing evaluation packages'),h(Controls,{host,inputs:{candidates:inputIds,evaluations:evaluationIds},parameters,onChange:setParameters,temporary:true}))
 }
 function Editor({context,parameters,onChange,readOnly}) {
  return h('section',null,...Object.entries(context.inputs).map(([port,input])=>input.unavailable&&h('p',{key:port},input.unavailable)),h(Controls,{host:context.host,inputs:Object.fromEntries(Object.entries(context.inputs).map(([port,input])=>[port,input.packages.map(pkg=>pkg.id)])),parameters,onChange,disabled:readOnly}))
 }
 return {resultActions:[{id:'workbench.filtering',name:'Temporary filter and sort',component:ResultAction}],editors:[{node:'workbench.filter',component:Editor}]}
}
