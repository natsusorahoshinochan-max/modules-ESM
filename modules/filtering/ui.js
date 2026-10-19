export const runtime={react:19}
export function register({React}) {
 const h=React.createElement
 const metrics=['workbench.metric_analysis','workbench.proteinmpnn_design','workbench.esm3_generation','workbench.structure_confidence','workbench.comparison','workbench.solubility','workbench.prediction','workbench.sequence_backbone_evaluation','workbench.filtered_collection']
 const candidates=['workbench.sequence','workbench.structure_set','workbench.proteinmpnn_design','workbench.filtered_collection',...metrics.filter(format=>format!=='workbench.metric_analysis')]
 const label=value=>typeof value==='string'?value:(value?.name??value?.method??value?.id??'Recorded method')
 const choiceLabel=(c,i)=>`${i+1}. ${c.metric} · ${label(c.method)} · ${c.reference?.label??(c.reference?'Selected reference':'No reference')} · ${JSON.stringify(c.region)} · ${c.sample===null||c.sample===undefined?'':`Sample ${c.sample+1} · `}${c.unit??''} · ${c.meaning??''}${c.unavailable?' · Unavailable: '+c.unavailable:''}`
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
   return rows.map((row,index)=>{
    const bound=evaluation?.bindings?.find(binding=>binding.candidate.input===row.input&&binding.candidate.item===row.item)
    const selected=row.choices.findIndex(choice=>JSON.stringify(choice.evaluation)===JSON.stringify(bound?.evaluation))
    return h('label',{key:index},`Input ${row.input+1} · ${row.label}`,h('select',{'aria-label':`${key} evaluation for input ${row.input+1} item ${row.item+1}`,disabled,value:selected<0?'':String(selected),onChange:event=>onSelect(bindings(evaluation,row,event.target.value))},h('option',{value:''},'Choose actual evaluation'),...row.choices.map((choice,i)=>h('option',{key:i,value:String(i),disabled:!!choice.unavailable},choiceLabel(choice,i)))))
   })
  }
  return h('section',{'aria-label':temporary?'Temporary filtering':'Node filtering parameters'},
   h('button',{disabled:busy,onClick:()=>invoke('workbench.filter.inspect')},'Inspect selected inputs'),
   error&&h('p',{role:'alert'},error),
   ...rows.map((row,index)=>h('p',{key:index},`Input ${row.input+1} · ${row.label} · ${row.choices.length} existing evaluation choices`)),
   h('fieldset',{disabled},h('legend',null,'Conditions'),
    ...(parameters.conditions??[]).map((condition,index)=>h('fieldset',{key:index},h('legend',null,`Condition ${index+1}`),
     ...evaluationFields(condition.evaluation,evaluation=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,evaluation}:c)}),`Condition ${index+1}`),
     h('select',{'aria-label':`Condition ${index+1} comparison`,value:condition.operator,onChange:event=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,operator:event.target.value}:c)})},...['lt','le','eq','ge','gt'].map((op,i)=>h('option',{key:op,value:op},['<','≤','=','≥','>'][i]))),
     h('input',{'aria-label':`Condition ${index+1} value`,type:'number',step:'any',value:condition.value??'',onChange:event=>change({...parameters,conditions:parameters.conditions.map((c,i)=>i===index?{...c,value:event.target.value===''?null:Number(event.target.value)}:c)})}),
     h('button',{onClick:()=>change({...parameters,conditions:parameters.conditions.filter((_,i)=>i!==index)})},'Remove condition'))),
    h('button',{onClick:()=>change({...parameters,conditions:[...(parameters.conditions??[]),{evaluation:{bindings:[]},operator:'ge',value:0}]})},'Add condition'),
    h('label',null,h('input',{type:'checkbox',checked:!!parameters.sort,onChange:event=>{const next={...parameters};if(event.target.checked)next.sort={evaluation:{bindings:[]},direction:'ascending'};else delete next.sort;change(next)}}),'Sort by an existing evaluation'),
    parameters.sort&&h('div',null,...evaluationFields(parameters.sort.evaluation,evaluation=>change({...parameters,sort:{...parameters.sort,evaluation}}),'Sort'),h('select',{'aria-label':'Sort direction',value:parameters.sort.direction,onChange:event=>change({...parameters,sort:{...parameters.sort,direction:event.target.value}})},h('option',{value:'ascending'},'Ascending'),h('option',{value:'descending'},'Descending'))),
    h('label',null,'Quantity limit',h('input',{'aria-label':'Quantity limit',type:'number',min:0,step:1,value:parameters.limit??'',onChange:event=>{const next={...parameters};if(event.target.value==='')delete next.limit;else next.limit=Number(event.target.value);change(next)}}))),
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
 function Viewer({package:pkg,host}) {
  const [document,setDocument]=React.useState(null),[error,setError]=React.useState('')
  React.useEffect(()=>{let live=true;host.readFile(pkg.id,pkg.entry).then(blob=>blob.text()).then(text=>{if(live)setDocument(JSON.parse(text))}).catch(error=>{if(live)setError(error.message)});return()=>{live=false}},[pkg.id])
  return h('section',null,error&&h('p',{role:'alert'},error),...(document?.items??[]).map((item,index)=>h('p',{key:index},item.object.label??`Selected object ${index+1}`)),h('button',{disabled:host.readOnly,onClick:()=>host.addNode({type:'workbench.filter.extract_structures',parameters:{},inputs:{collection:[pkg.id]}}).catch(error=>setError(error.message))},'Extract selected structures'))
 }
 return {resultActions:[{id:'workbench.filtering',name:'Temporary filter and sort',component:ResultAction}],editors:[{node:'workbench.filter',component:Editor}],viewers:[{id:'workbench.filtered_collection',name:'Filtered collection',formats:['workbench.filtered_collection'],component:Viewer}]}
}
