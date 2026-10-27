export const runtime={react:19}
export function register({React}) {
 const h=React.createElement
 const metrics=['workbench.metric_analysis','workbench.proteinmpnn_design','workbench.esm3_generation','workbench.structure_confidence','workbench.comparison','workbench.solubility','workbench.prediction','workbench.sequence_backbone_evaluation','workbench.collection']
 const candidates=['workbench.sequence','workbench.structure_set','workbench.proteinmpnn_design','workbench.collection',...metrics.filter(format=>format!=='workbench.metric_analysis')]
 const methodText=value=>typeof value==='string'?value:Object.entries(value??{}).filter(([key])=>['name','method','id','tmtools','algorithm','scope','parameters','actual_seed','statistic'].includes(key)).map(([key,value])=>`${key}: ${typeof value==='object'?JSON.stringify(value):value}`).join('; ')
 const contextText=c=>`Evaluation input ${(c.context?.input??c.evaluation.input)+1}${c.context?.source===undefined?'':` · source ${c.context.source+1}`} · ${c.context?.format??'Evaluation'} · ${c.context?.entry??''}${c.context?.analysis_source===undefined?'':` · analysis source ${c.context.analysis_source+1}`}`
 const referenceText=c=>c.reference_display?[c.reference_display.label??c.reference_display.name??'参考对象',c.reference_display.file,c.reference_display.format].filter(Boolean).join(' · '):(c.reference?'参考对象':'无参考')
 const choiceLabel=c=>`${c.metric} · ${referenceText(c)} · ${typeof c.method==='string'?c.method:c.method?.name??c.method?.method??''}${c.sample==null?'':' · 候选 '+(c.sample+1)}`
 function EvaluationRule({evaluation,onSelect,label,disabled,rows}) {
  const ruleFor=choice=>({metric:choice.metric,method:choice.method,region:choice.region,...(evaluation.reference_mode==='provided_evaluations'?{reference_mode:'provided_evaluations'}:{reference:choice.reference})})
  const choices=[...new Map(rows.flatMap(row=>row.choices).filter(choice=>!choice.unavailable).map(choice=>[JSON.stringify(ruleFor(choice)),choice])).values()]
  const current=choices.findIndex(choice=>{const rule=ruleFor(choice);return rule.metric===evaluation.metric&&JSON.stringify(rule.method)===JSON.stringify(evaluation.method)&&JSON.stringify(rule.region)===JSON.stringify(evaluation.region)&&(evaluation.reference_mode==='provided_evaluations'||JSON.stringify(rule.reference)===JSON.stringify(evaluation.reference))})
  return h('div',null,
   h('label',null,'分数',h('select',{'aria-label':`${label} 分数`,disabled,value:current<0?'saved':String(current),onChange:event=>{const choice=choices[Number(event.target.value)];if(choice)onSelect({...evaluation,...ruleFor(choice)})}},
    current<0&&h('option',{value:'saved'},evaluation.metric?`${evaluation.metric} · 已配置`:'先读取分数'),...choices.map((choice,index)=>h('option',{key:index,value:String(index)},choiceLabel(choice))))),
   h('label',null,'参考对象',h('select',{'aria-label':`${label} 参考对象`,disabled,value:evaluation.reference_mode==='provided_evaluations'?'provided_evaluations':'exact',onChange:event=>{
    const next={...evaluation};if(event.target.value==='provided_evaluations'){delete next.reference;next.reference_mode='provided_evaluations'}else{delete next.reference_mode;next.reference=current>=0?choices[current].reference:null}onSelect(next)
   }},h('option',{value:'exact'},'所选分数的参考'),h('option',{value:'provided_evaluations'},'使用已连接的评价'))))
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
  return h('section',{'aria-label':'分数详情'},
   h('p',null,contextText(choice)),h('p',null,`Reference: ${referenceText(choice)}`),
   h('p',null,`Method: ${methodText(choice.method)}`),h('p',null,`Selected region: ${JSON.stringify(choice.region)}`),
   choice.method?.source_method&&h('p',null,`Source method: ${methodText(choice.method.source_method)}`),
   choice.method?.source_region!==undefined&&h('p',null,`Source region: ${JSON.stringify(choice.method.source_region)}`),
   access?.key&&packageId?h('button',{type:'button',disabled:busy,onClick:view},'查看参考文件'):h('p',null,access?.unavailable??'参考文件不可用'),
   error&&h('p',{role:'alert'},error),text&&h('pre',{'aria-label':'参考文件内容'},text))
 }
 function Controls({host,inputs,parameters,onChange,disabled=false}) {
  const [rows,setRows]=React.useState([]),[error,setError]=React.useState(''),[busy,setBusy]=React.useState(false)
  const epoch=React.useRef(0),abort=React.useRef(null)
  const signature=JSON.stringify(inputs)
  React.useEffect(()=>{epoch.current++;abort.current?.abort();setRows([]);setError('');setBusy(false);return()=>{epoch.current++;abort.current?.abort()}},[signature])
  function change(next){epoch.current++;abort.current?.abort();setBusy(false);onChange(next)}
  async function invoke(name) {
   const current=++epoch.current;abort.current?.abort();abort.current=new AbortController();setBusy(true);setError('')
   try {
    const response=await host.preview(name,inputs,name.endsWith('inspect')?{}:parameters,{signal:abort.current.signal})
    try{if(current===epoch.current){setRows(response.data.candidates)}}
    finally{await host.cancelPreview(response.id)}
   }catch(error){if(current===epoch.current)setError(error.message)}finally{if(current===epoch.current)setBusy(false)}
  }
  const bindings=(evaluation,row,value)=>({bindings:[...(evaluation?.bindings??[]).filter(binding=>JSON.stringify(binding.candidate)!==JSON.stringify({input:row.input,item:row.item})),...(value===''?[]:[{candidate:{input:row.input,item:row.item},evaluation:row.choices[Number(value)].evaluation}])]})
  function evaluationFields(evaluation,onSelect,key) {
   const semantic=evaluation!==undefined&&!Object.hasOwn(evaluation,'bindings')
   const mode=h('label',{key:'mode'},'匹配方式',h('select',{'aria-label':`${key} evaluation selection`,disabled,value:semantic?'meaning':'records',onChange:event=>onSelect(event.target.value==='meaning'?{metric:'',method:null,reference:null,region:null}:{bindings:[]})},h('option',{value:'records'},'逐候选选择'),h('option',{value:'meaning'},'按分数匹配')))
   if(semantic)return [mode,h(EvaluationRule,{key:'rule',evaluation,onSelect,label:key,disabled,rows})]
   return [mode,...rows.map((row,index)=>{
    const bound=evaluation?.bindings?.find(binding=>binding.candidate.input===row.input&&binding.candidate.item===row.item)
    const selected=row.choices.findIndex(choice=>JSON.stringify(choice.evaluation)===JSON.stringify(bound?.evaluation))
    return h('div',{key:index},h('label',null,`${row.label}`,h('select',{'aria-label':`${key} evaluation for input ${row.input+1} item ${row.item+1}`,disabled,value:selected<0?'':String(selected),onChange:event=>onSelect(bindings(evaluation,row,event.target.value))},h('option',{value:''},'选择分数'),...row.choices.map((choice,i)=>h('option',{key:i,value:String(i),disabled:!!choice.unavailable},choiceLabel(choice))))),selected>=0&&h('details',null,h('summary',null,'分数详情'),h(ReferenceDetails,{choice:row.choices[selected],host,inputs})))
   })]
  }
  return h('section',{'aria-label':'筛选参数'},
   h('button',{disabled:busy,onClick:()=>invoke('workbench.filter.inspect')},'读取分数'),
   error&&h('p',{role:'alert'},error),

   h('fieldset',null,h('legend',null,'筛选条件'),
    ...(parameters.conditions??[]).map((condition,index)=>h('fieldset',{key:index},h('legend',null,`条件 ${index+1}`),
     ...evaluationFields(condition.evaluation,evaluation=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,evaluation}:c)}),`条件 ${index+1}`),
     h('select',{'aria-label':`Condition ${index+1} comparison`,disabled,value:condition.operator,onChange:event=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,operator:event.target.value}:c)})},...['lt','le','eq','ge','gt'].map((op,i)=>h('option',{key:op,value:op},['<','≤','=','≥','>'][i]))),
     h('input',{'aria-label':`Condition ${index+1} value`,disabled,type:'number',step:'any',value:condition.value??'',onChange:event=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,value:event.target.value===''?null:Number(event.target.value)}:c)})}),
     h('button',{disabled,onClick:()=>change({...parameters,conditions:parameters.conditions.filter((_,i)=>i!==index)})},'删除条件'))),
    h('button',{disabled,onClick:()=>change({...parameters,conditions:[...(parameters.conditions??[]),{evaluation:{bindings:[]},operator:'ge',value:0}]})},'添加条件'),
    h('label',null,h('input',{type:'checkbox',disabled,checked:!!parameters.sort,onChange:event=>{const next={...parameters};if(event.target.checked)next.sort={evaluation:{bindings:[]},direction:'ascending'};else delete next.sort;change(next)}}),'排序'),
    parameters.sort&&h('div',null,...evaluationFields(parameters.sort.evaluation,evaluation=>change({...parameters,sort:{...parameters.sort,evaluation}}),'Sort'),h('select',{'aria-label':'Sort direction',disabled,value:parameters.sort.direction,onChange:event=>change({...parameters,sort:{...parameters.sort,direction:event.target.value}})},h('option',{value:'ascending'},'从低到高'),h('option',{value:'descending'},'从高到低'))),
    h('label',null,'保留数量',h('input',{'aria-label':'保留数量',disabled,type:'number',min:0,step:1,value:parameters.limit??'',onChange:event=>{const next={...parameters};if(event.target.value==='')delete next.limit;else next.limit=Number(event.target.value);change(next)}}))),
   )
 }

 function Editor({context,parameters,onChange,readOnly}) {
  return h('section',null,...Object.entries(context.inputs).map(([port,input])=>input.unavailable&&h('p',{key:port},input.unavailable)),h(Controls,{host:context.host,inputs:Object.fromEntries(Object.entries(context.inputs).map(([port,input])=>[port,input.packages.map(pkg=>pkg.id)])),parameters,onChange,disabled:readOnly}))
 }
 return {editors:[{node:'workbench.filter',component:Editor}]}
}
