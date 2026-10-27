export const runtime = {react:19}
export function register({React}) {
  const h=React.createElement
  const supported=['workbench.metric_analysis','workbench.proteinmpnn_design','workbench.esm3_generation','workbench.structure_confidence','workbench.comparison','workbench.solubility','workbench.prediction','workbench.sequence_backbone_evaluation']
  const same=(a,b)=>Object.keys(b).every(key=>JSON.stringify(a[key])===JSON.stringify(b[key]))
  const positionName=p=>`${p.chain}:${p.author_number}${p.insertion_code}`
  const methodName=value=>typeof value==='string'?value:JSON.stringify(value)
  function Editor({context,parameters,readOnly}) {
    const [choices,setChoices]=React.useState([]),[selected,setSelected]=React.useState(parameters.selections??[]),[inspected,setInspected]=React.useState(false)
    const [busy,setBusy]=React.useState(false),[error,setError]=React.useState(''),[chains,set链s]=React.useState({})
    const epoch=React.useRef(0),abort=React.useRef(null),origin=React.useRef(null)
    React.useEffect(()=>{
      epoch.current++;abort.current?.abort();setChoices([]);setSelected(parameters.selections??[]);setInspected(false);setBusy(false);setError('')
      return()=>{epoch.current++;abort.current?.abort()}
    },[context.projectId,context.nodeId,context.revision])
    async function inspect() {
      const current=++epoch.current, source=context
      abort.current?.abort();abort.current=new AbortController();setBusy(true);setError('')
      try {
        const inputs=Object.fromEntries(Object.entries(source.inputs).map(([port,input])=>[port,input.packages.map(pkg=>pkg.id)]))
        const response=await source.host.preview('workbench.inspect_metrics',inputs,{}, {signal:abort.current.signal})
        try {if(current===epoch.current){setChoices(response.data.choices);setInspected(true);origin.current=source}}
        finally {await source.host.cancelPreview(response.id)}
      }catch(error){if(current===epoch.current)setError(error.message)}
      finally{if(current===epoch.current)setBusy(false)}
    }
    function change(choice,region,enabled=true) {
      if(enabled&&choice.unavailable)return
      const rest=selected.filter(item=>!same(item,choice.selector))
      setSelected(enabled?[...rest,{...choice.selector,...(region===undefined?{}:{region})}]:rest)
    }
    async function apply() {
      if(selected.some(item=>!choices.some(choice=>same(item,choice.selector)&&!choice.unavailable)))return
      setBusy(true);setError('')
      try{await origin.current.update({parameters:{...parameters,selections:selected}})}
      catch(error){setError(error.message)}
      finally{setBusy(false)}
    }
    return h('section',{'aria-label':'Existing metric selections'},
      ...Object.values(context.inputs).map((input,i)=>input.unavailable&&h('p',{key:i},input.unavailable)),
      h('button',{onClick:inspect,disabled:busy},'读取指标'),error&&h('p',{role:'alert'},error),
      inspected&&selected.map((selection,index)=>!choices.some(choice=>same(selection,choice.selector))&&h('fieldset',{key:`saved-${index}`,disabled:readOnly||busy},
        h('legend',null,`Saved metric selection ${index+1} · Input ${selection.input+1} · ${selection.metric}`),
        h('p',null,'当前输入中没有此分数'),
        h('button',{'aria-label':`删除已存选择 ${index+1}`,onClick:()=>setSelected(items=>items.filter((_,offset)=>offset!==index))},'删除已存选择'))),
      ...choices.map((choice,index)=>{
        const selection=selected.find(item=>same(item,choice.selector)),number=index+1
        const region=selection?.region
        const visible=(choice.positions??[]).filter(p=>!chains[index]||p.chain===chains[index])
        return h('fieldset',{key:JSON.stringify(choice.selector),disabled:readOnly||busy},
          h('legend',null,`Input ${choice.selector.input+1} · ${choice.object_label} · ${choice.reference_label} · ${choice.selector.metric}`),
          h('p',null,`${choice.selector.origin==='generation'?'Generation confidence':`Evaluation ${choice.selector.evaluation===undefined?'':choice.selector.evaluation+1}`}${choice.selector.sample===undefined?'':` · Sample ${choice.selector.sample+1}`} · ${methodName(choice.source_method)} · ${choice.unit} · ${choice.meaning}`),

          choice.unavailable&&h('p',null,'Unavailable: ',choice.unavailable),
          h('label',null,h('input',{type:'checkbox','aria-label':`Use metric ${number}`,disabled:!!choice.unavailable&&!selection,checked:!!selection,onChange:event=>change(choice,undefined,event.target.checked)}),'选择此指标'),
          !choice.unavailable&&choice.positions&&selection&&h(React.Fragment,null,
            h('label',null,h('input',{type:'checkbox','aria-label':`选择残基 ${number}`,checked:Array.isArray(region),onChange:event=>change(choice,event.target.checked?[]:undefined)}),'选择残基'),
            Array.isArray(region)&&h(React.Fragment,null,
              h('label',null,'链',h('select',{'aria-label':`Metric ${number} chain`,value:chains[index]??'',onChange:event=>set链s({...chains,[index]:event.target.value})},
                h('option',{value:''},'全部链'),...[...new Set(choice.positions.map(p=>p.chain))].map(chain=>h('option',{key:chain,value:chain},chain||'(blank chain)')))),
              ...visible.map(p=>h('label',{key:positionName(p)},h('input',{type:'checkbox','aria-label':`Metric ${number} position ${positionName(p)}`,checked:region.some(item=>same(item,p)),onChange:event=>change(choice,event.target.checked?[...region,p]:region.filter(item=>!same(item,p)))}),positionName(p))))),
          !choice.unavailable&&!choice.positions&&h('p',null,'标量'))
      }),h('button',{onClick:apply,disabled:readOnly||busy||!choices.length||!selected.length||selected.some(item=>!choices.some(choice=>same(item,choice.selector)&&!choice.unavailable)||(Array.isArray(item.region)&&!item.region.length))},'采用选择'))
  }
  function Viewer({package:pkg,host}) {
    const [document,setDocument]=React.useState(null),[error,setError]=React.useState('')
    React.useEffect(()=>{let active=true;setDocument(null);setError('');host.readFile(pkg.id,pkg.entry).then(blob=>blob.text()).then(text=>{if(active)setDocument(JSON.parse(text))}).catch(error=>{if(active)setError(error.message)});return()=>{active=false}},[pkg.id,pkg.entry])
    return h('section',null,error&&h('p',{role:'alert'},error),
      pkg.format==='workbench.metric_analysis'?(document?.analyses??[]).map((analysis,index)=>h('article',{key:index},
        h('h3',null,`${analysis.object.label??`Object ${index+1}`} · ${analysis.metric}`),
        h('p',null,'参考：',analysis.reference?.label??(analysis.reference?'所选参考':'无参考')),
        h('p',null,'方法：',methodName(analysis.source_method)),h('p',null,analysis.method,' · ',analysis.unit,' · ',analysis.meaning),
        h('p',null,`区域：${analysis.region===null?'整体':Array.isArray(analysis.region)?analysis.region.map(positionName).join(', '):'所选区域'}`),
        h('p',null,`Count ${analysis.statistics.count}; mean ${analysis.statistics.mean}; minimum ${analysis.statistics.minimum}; maximum ${analysis.statistics.maximum}`),
        h('details',null,h('summary',null,'原始分数'),h('table',null,h('tbody',null,analysis.input_values.map((value,i)=>h('tr',{key:i},h('td',null,analysis.positions?.[i]?positionName(analysis.positions[i]):i+1),h('td',null,String(value)))))))))
      :h('button',{disabled:host.readOnly,onClick:async()=>{try{await host.addNode({type:'workbench.analyze_metrics',inputs:{metrics:[pkg.id]},parameters:{}})}catch(error){setError(error.message)}}},'添加指标分析节点'))
  }
  return {
    editors:[{node:'workbench.analyze_metrics',component:Editor}],
    viewers:[{id:'workbench.metric_analysis',name:'指标分析',formats:[...supported,'workbench.metric_analysis'],component:Viewer}]}
}
