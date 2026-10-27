const messages = {
"source_suffix": {"zh-CN": " · 来源 {n}", "en": " · Source {n}"},
"analysis_suffix": {"zh-CN": " · 分析来源 {n}", "en": " · Analysis source {n}"},
"evaluation": {"zh-CN": "评价", "en": "Evaluation"},

  "label_78": {
    "zh-CN": "参考：{0}",
    "en": "Reference: {0}"
  },
  "label_79": {
    "zh-CN": "方法：{0}",
    "en": "Method: {0}"
  },
  "label_80": {
    "zh-CN": "条件 {0} 比较方式",
    "en": "Condition {0} comparison"
  },
  "label_81": {
    "zh-CN": "条件 {0} 数值",
    "en": "Condition {0} value"
  }
,
  "evaluation_input": {
    "zh-CN": "评价输入 {0}{1} · {2} · {3}{4}",
    "en": "Evaluation input {0}{1} · {2} · {3}{4}"
  },
  "reference": {
    "zh-CN": "参考对象",
    "en": "Reference"
  },
  "no_reference": {
    "zh-CN": "无参考",
    "en": "No reference"
  },
  "candidate": {
    "zh-CN": " · 候选 ",
    "en": " · Candidate "
  },
  "score": {
    "zh-CN": "分数",
    "en": "Score"
  },
  "score_2": {
    "zh-CN": "{0} 分数",
    "en": "{0} score"
  },
  "configured": {
    "zh-CN": "{0} · 已配置",
    "en": "{0} · Configured"
  },
  "read_scores_first": {
    "zh-CN": "先读取分数",
    "en": "Read scores first"
  },
  "reference_2": {
    "zh-CN": "{0} 参考对象",
    "en": "{0} reference"
  },
  "selected_score_s_reference": {
    "zh-CN": "所选分数的参考",
    "en": "Selected score's reference"
  },
  "use_connected_evaluations": {
    "zh-CN": "使用已连接的评价",
    "en": "Use connected evaluations"
  },
  "score_details": {
    "zh-CN": "分数详情",
    "en": "Score details"
  },
  "selected_region": {
    "zh-CN": "所选区域：{0}",
    "en": "Selected region: {0}"
  },
  "source_method": {
    "zh-CN": "来源方法：{0}",
    "en": "Source method: {0}"
  },
  "source_region": {
    "zh-CN": "来源区域：{0}",
    "en": "Source region: {0}"
  },
  "view_reference_file": {
    "zh-CN": "查看参考文件",
    "en": "View reference file"
  },
  "reference_file_unavailable": {
    "zh-CN": "参考文件不可用",
    "en": "Reference file unavailable"
  },
  "reference_file_contents": {
    "zh-CN": "参考文件内容",
    "en": "Reference file contents"
  },
  "match_by": {
    "zh-CN": "匹配方式",
    "en": "Match by"
  },
  "evaluation_selection": {
    "zh-CN": "{0} 分数选择",
    "en": "{0} evaluation selection"
  },
  "choose_per_candidate": {
    "zh-CN": "逐候选选择",
    "en": "Choose per candidate"
  },
  "match_score": {
    "zh-CN": "按分数匹配",
    "en": "Match score"
  },
  "evaluation_for_input_item": {
    "zh-CN": "{0}：输入 {1} 候选 {2} 的评分",
    "en": "{0} evaluation for input {1} item {2}"
  },
  "select_score": {
    "zh-CN": "选择分数",
    "en": "Select score"
  },
  "filter_parameters": {
    "zh-CN": "筛选参数",
    "en": "Filter parameters"
  },
  "read_scores": {
    "zh-CN": "读取分数",
    "en": "Read scores"
  },
  "conditions": {
    "zh-CN": "筛选条件",
    "en": "Conditions"
  },
  "condition": {
    "zh-CN": "条件 {0}",
    "en": "Condition {0}"
  },
  "remove_condition": {
    "zh-CN": "删除条件",
    "en": "Remove condition"
  },
  "add_condition": {
    "zh-CN": "添加条件",
    "en": "Add condition"
  },
  "sort": {
    "zh-CN": "排序",
    "en": "Sort"
  },
  "sort_direction": {
    "zh-CN": "排序方向",
    "en": "Sort direction"
  },
  "low_to_high": {
    "zh-CN": "从低到高",
    "en": "Low to high"
  },
  "high_to_low": {
    "zh-CN": "从高到低",
    "en": "High to low"
  },
  "keep_count": {
    "zh-CN": "保留数量",
    "en": "Keep count"
  }
};
export const runtime={react:19}
export function register({ React, i18n }) {
  const t = i18n.translator(messages);
 const h=React.createElement
 const metrics=['workbench.metric_analysis','workbench.proteinmpnn_design','workbench.esm3_generation','workbench.structure_confidence','workbench.comparison','workbench.solubility','workbench.prediction','workbench.sequence_backbone_evaluation','workbench.collection']
 const candidates=['workbench.sequence','workbench.structure_set','workbench.proteinmpnn_design','workbench.collection',...metrics.filter(format=>format!=='workbench.metric_analysis')]
 const methodText=value=>typeof value==='string'?value:Object.entries(value??{}).filter(([key])=>['name','method','id','tmtools','algorithm','scope','parameters','actual_seed','statistic'].includes(key)).map(([key,value])=>`${key}: ${typeof value==='object'?JSON.stringify(value):value}`).join('; ')
 const contextText=c=>t("evaluation_input", {"0": (c.context?.input??c.evaluation.input)+1, "1": c.context?.source===undefined?'':t('source_suffix',{n:c.context.source+1}), "2": c.context?.format??t('evaluation'), "3": c.context?.entry??'', "4": c.context?.analysis_source===undefined?'':t('analysis_suffix',{n:c.context.analysis_source+1})})
 const referenceText=c=>c.reference_display?[c.reference_display.label??c.reference_display.name??t("reference"),c.reference_display.file,c.reference_display.format].filter(Boolean).join(' · '):(c.reference?t("reference"):t("no_reference"))
 const choiceLabel=c=>`${c.metric} · ${referenceText(c)} · ${typeof c.method==='string'?c.method:c.method?.name??c.method?.method??''}${c.sample==null?'':t("candidate")+(c.sample+1)}`
 function EvaluationRule({evaluation,onSelect,label,disabled,rows}) {
  const ruleFor=choice=>({metric:choice.metric,method:choice.method,region:choice.region,...(evaluation.reference_mode==='provided_evaluations'?{reference_mode:'provided_evaluations'}:{reference:choice.reference})})
  const choices=[...new Map(rows.flatMap(row=>row.choices).filter(choice=>!choice.unavailable).map(choice=>[JSON.stringify(ruleFor(choice)),choice])).values()]
  const current=choices.findIndex(choice=>{const rule=ruleFor(choice);return rule.metric===evaluation.metric&&JSON.stringify(rule.method)===JSON.stringify(evaluation.method)&&JSON.stringify(rule.region)===JSON.stringify(evaluation.region)&&(evaluation.reference_mode==='provided_evaluations'||JSON.stringify(rule.reference)===JSON.stringify(evaluation.reference))})
  return h('div',null,
   h('label',null,t("score"),h('select',{'aria-label':t("score_2", {"0": label}),disabled,value:current<0?'saved':String(current),onChange:event=>{const choice=choices[Number(event.target.value)];if(choice)onSelect({...evaluation,...ruleFor(choice)})}},
    current<0&&h('option',{value:'saved'},evaluation.metric?t("configured", {"0": evaluation.metric}):t("read_scores_first")),...choices.map((choice,index)=>h('option',{key:index,value:String(index)},choiceLabel(choice))))),
   h('label',null,t("reference"),h('select',{'aria-label':t("reference_2", {"0": label}),disabled,value:evaluation.reference_mode==='provided_evaluations'?'provided_evaluations':'exact',onChange:event=>{
    const next={...evaluation};if(event.target.value==='provided_evaluations'){delete next.reference;next.reference_mode='provided_evaluations'}else{delete next.reference_mode;next.reference=current>=0?choices[current].reference:null}onSelect(next)
   }},h('option',{value:'exact'},t("selected_score_s_reference")),h('option',{value:'provided_evaluations'},t("use_connected_evaluations")))))
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
  return h('section',{'aria-label':t("score_details")},
   h('p',null,contextText(choice)),h('p',null,t("label_78", {"0": referenceText(choice)})),
   h('p',null,t("label_79", {"0": methodText(choice.method)})),h('p',null,t("selected_region", {"0": JSON.stringify(choice.region)})),
   choice.method?.source_method&&h('p',null,t("source_method", {"0": methodText(choice.method.source_method)})),
   choice.method?.source_region!==undefined&&h('p',null,t("source_region", {"0": JSON.stringify(choice.method.source_region)})),
   access?.key&&packageId?h('button',{type:'button',disabled:busy,onClick:view},t("view_reference_file")):h('p',null,access?.unavailable??t("reference_file_unavailable")),
   error&&h('p',{role:'alert'},error),text&&h('pre',{'aria-label':t("reference_file_contents")},text))
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
   const mode=h('label',{key:'mode'},t("match_by"),h('select',{'aria-label':t("evaluation_selection", {"0": key}),disabled,value:semantic?'meaning':'records',onChange:event=>onSelect(event.target.value==='meaning'?{metric:'',method:null,reference:null,region:null}:{bindings:[]})},h('option',{value:'records'},t("choose_per_candidate")),h('option',{value:'meaning'},t("match_score"))))
   if(semantic)return [mode,h(EvaluationRule,{key:'rule',evaluation,onSelect,label:key,disabled,rows})]
   return [mode,...rows.map((row,index)=>{
    const bound=evaluation?.bindings?.find(binding=>binding.candidate.input===row.input&&binding.candidate.item===row.item)
    const selected=row.choices.findIndex(choice=>JSON.stringify(choice.evaluation)===JSON.stringify(bound?.evaluation))
    return h('div',{key:index},h('label',null,`${row.label}`,h('select',{'aria-label':t("evaluation_for_input_item", {"0": key, "1": row.input+1, "2": row.item+1}),disabled,value:selected<0?'':String(selected),onChange:event=>onSelect(bindings(evaluation,row,event.target.value))},h('option',{value:''},t("select_score")),...row.choices.map((choice,i)=>h('option',{key:i,value:String(i),disabled:!!choice.unavailable},choiceLabel(choice))))),selected>=0&&h('details',null,h('summary',null,t("score_details")),h(ReferenceDetails,{choice:row.choices[selected],host,inputs})))
   })]
  }
  return h('section',{'aria-label':t("filter_parameters")},
   h('button',{disabled:busy,onClick:()=>invoke('workbench.filter.inspect')},t("read_scores")),
   error&&h('p',{role:'alert'},error),

   h('fieldset',null,h('legend',null,t("conditions")),
    ...(parameters.conditions??[]).map((condition,index)=>h('fieldset',{key:index},h('legend',null,t("condition", {"0": index+1})),
     ...evaluationFields(condition.evaluation,evaluation=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,evaluation}:c)}),t("condition", {"0": index+1})),
     h('select',{'aria-label':t("label_80", {"0": index+1}),disabled,value:condition.operator,onChange:event=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,operator:event.target.value}:c)})},...['lt','le','eq','ge','gt'].map((op,i)=>h('option',{key:op,value:op},['<','≤','=','≥','>'][i]))),
     h('input',{'aria-label':t("label_81", {"0": index+1}),disabled,type:'number',step:'any',value:condition.value??'',onChange:event=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,value:event.target.value===''?null:Number(event.target.value)}:c)})}),
     h('button',{disabled,onClick:()=>change({...parameters,conditions:parameters.conditions.filter((_,i)=>i!==index)})},t("remove_condition")))),
    h('button',{disabled,onClick:()=>change({...parameters,conditions:[...(parameters.conditions??[]),{evaluation:{bindings:[]},operator:'ge',value:0}]})},t("add_condition")),
    h('label',null,h('input',{type:'checkbox',disabled,checked:!!parameters.sort,onChange:event=>{const next={...parameters};if(event.target.checked)next.sort={evaluation:{bindings:[]},direction:'ascending'};else delete next.sort;change(next)}}),t("sort")),
    parameters.sort&&h('div',null,...evaluationFields(parameters.sort.evaluation,evaluation=>change({...parameters,sort:{...parameters.sort,evaluation}}),t('sort')),h('select',{'aria-label':t("sort_direction"),disabled,value:parameters.sort.direction,onChange:event=>change({...parameters,sort:{...parameters.sort,direction:event.target.value}})},h('option',{value:'ascending'},t("low_to_high")),h('option',{value:'descending'},t("high_to_low")))),
    h('label',null,t("keep_count"),h('input',{'aria-label':t("keep_count"),disabled,type:'number',min:0,step:1,value:parameters.limit??'',onChange:event=>{const next={...parameters};if(event.target.value==='')delete next.limit;else next.limit=Number(event.target.value);change(next)}}))),
   )
 }

 function Editor({context,parameters,onChange,readOnly}) {
  return h('section',null,...Object.entries(context.inputs).map(([port,input])=>input.unavailable&&h('p',{key:port},input.unavailable)),h(Controls,{host:context.host,inputs:Object.fromEntries(Object.entries(context.inputs).map(([port,input])=>[port,input.packages.map(pkg=>pkg.id)])),parameters,onChange,disabled:readOnly}))
 }
 return {editors:[{node:'workbench.filter',component:Editor}]}
}
