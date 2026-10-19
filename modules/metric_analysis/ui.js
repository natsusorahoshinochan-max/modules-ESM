export const runtime = {react:19}
export function register({React}) {
  const h=React.createElement
  const supported=['workbench.structure_confidence','workbench.comparison','workbench.solubility','workbench.prediction','workbench.sequence_backbone_evaluation']
  const same=(a,b)=>Object.keys(b).every(key=>JSON.stringify(a[key])===JSON.stringify(b[key]))
  const positionName=p=>`${p.chain}:${p.author_number}${p.insertion_code}`
  const methodName=value=>typeof value==='string'?value:JSON.stringify(value)
  function Editor({context,parameters,readOnly}) {
    const [choices,setChoices]=React.useState([]),[selected,setSelected]=React.useState(parameters.selections??[])
    const [busy,setBusy]=React.useState(false),[error,setError]=React.useState(''),[chains,setChains]=React.useState({})
    const epoch=React.useRef(0),abort=React.useRef(null),origin=React.useRef(null)
    React.useEffect(()=>{
      epoch.current++;abort.current?.abort();setChoices([]);setSelected(parameters.selections??[]);setBusy(false);setError('')
      return()=>{epoch.current++;abort.current?.abort()}
    },[context.projectId,context.nodeId,context.revision])
    async function inspect() {
      const current=++epoch.current, source=context
      abort.current?.abort();abort.current=new AbortController();setBusy(true);setError('')
      try {
        const inputs=Object.fromEntries(Object.entries(source.inputs).map(([port,input])=>[port,input.packages.map(pkg=>pkg.id)]))
        const response=await source.host.preview('workbench.inspect_metrics',inputs,{}, {signal:abort.current.signal})
        try {if(current===epoch.current){setChoices(response.data.choices);origin.current=source}}
        finally {await source.host.cancelPreview(response.id)}
      }catch(error){if(current===epoch.current)setError(error.message)}
      finally{if(current===epoch.current)setBusy(false)}
    }
    function change(choice,region,enabled=true) {
      const rest=selected.filter(item=>!same(item,choice.selector))
      setSelected(enabled?[...rest,{...choice.selector,...(region===undefined?{}:{region})}]:rest)
    }
    async function apply() {
      setBusy(true);setError('')
      try{await origin.current.update({parameters:{...parameters,selections:selected}})}
      catch(error){setError(error.message)}
      finally{setBusy(false)}
    }
    return h('section',{'aria-label':'Existing metric selections'},
      ...Object.values(context.inputs).map((input,i)=>input.unavailable&&h('p',{key:i},input.unavailable)),
      h('button',{onClick:inspect,disabled:busy},'Inspect existing metrics'),error&&h('p',{role:'alert'},error),
      ...choices.map((choice,index)=>{
        const selection=selected.find(item=>same(item,choice.selector)),number=index+1
        const region=selection?.region
        const visible=(choice.positions??[]).filter(p=>!chains[index]||p.chain===chains[index])
        return h('fieldset',{key:JSON.stringify(choice.selector),disabled:readOnly||busy},
          h('legend',null,`Input ${choice.selector.input+1} · ${choice.object_label} · ${choice.reference_label} · ${choice.selector.metric}`),
          h('p',null,`${choice.selector.origin==='generation'?'Generation confidence':`Evaluation ${choice.selector.evaluation===undefined?'':choice.selector.evaluation+1}`}${choice.selector.sample===undefined?'':` · Sample ${choice.selector.sample+1}`} · ${methodName(choice.source_method)} · ${choice.unit} · ${choice.meaning}`),
          h('p',null,'Original scope: ',JSON.stringify(choice.source_region)),
          h('label',null,h('input',{type:'checkbox','aria-label':`Use metric ${number}`,checked:!!selection,onChange:event=>change(choice,undefined,event.target.checked)}),'Use existing metric'),
          choice.positions&&selection&&h(React.Fragment,null,
            h('label',null,h('input',{type:'checkbox','aria-label':`Select individual positions ${number}`,checked:Array.isArray(region),onChange:event=>change(choice,event.target.checked?[]:undefined)}),'Select individual positions'),
            Array.isArray(region)&&h(React.Fragment,null,
              h('label',null,'Chain',h('select',{'aria-label':`Metric ${number} chain`,value:chains[index]??'',onChange:event=>setChains({...chains,[index]:event.target.value})},
                h('option',{value:''},'All available chains'),...[...new Set(choice.positions.map(p=>p.chain))].map(chain=>h('option',{key:chain,value:chain},chain||'(blank chain)')))),
              ...visible.map(p=>h('label',{key:positionName(p)},h('input',{type:'checkbox','aria-label':`Metric ${number} position ${positionName(p)}`,checked:region.some(item=>same(item,p)),onChange:event=>change(choice,event.target.checked?[...region,p]:region.filter(item=>!same(item,p)))}),positionName(p))))),
          !choice.positions&&h('p',null,'Scalar value: analysis retains the original evaluation scope.'))
      }),h('button',{onClick:apply,disabled:readOnly||busy||!choices.length||!selected.length||selected.some(item=>Array.isArray(item.region)&&!item.region.length)},'Apply metric selections'))
  }
  function Action({host}) {
    const [error,setError]=React.useState('')
    return h('section',null,h('button',{disabled:host.readOnly,onClick:async()=>{try{await host.addNode({type:'workbench.analyze_metrics',inputs:{},parameters:{}})}catch(error){setError(error.message)}}},'Add existing metric analysis'),error&&h('p',{role:'alert'},error))
  }
  function Viewer({package:pkg,host}) {
    const [document,setDocument]=React.useState(null),[error,setError]=React.useState('')
    React.useEffect(()=>{let active=true;setDocument(null);setError('');host.readFile(pkg.id,pkg.entry).then(blob=>blob.text()).then(text=>{if(active)setDocument(JSON.parse(text))}).catch(error=>{if(active)setError(error.message)});return()=>{active=false}},[pkg.id,pkg.entry])
    return h('section',null,error&&h('p',{role:'alert'},error),
      pkg.format==='workbench.metric_analysis'?(document?.analyses??[]).map((analysis,index)=>h('article',{key:index},
        h('h3',null,`${analysis.object.label??`Object ${index+1}`} · ${analysis.metric}`),
        h('p',null,'Reference: ',analysis.reference?.label??(analysis.reference?'Selected reference':'No reference')),
        h('p',null,'Source method: ',methodName(analysis.source_method)),h('p',null,analysis.method,' · ',analysis.unit,' · ',analysis.meaning),
        h('p',null,'Analyzed region: ',JSON.stringify(analysis.region)),
        h('p',null,`Count ${analysis.statistics.count}; mean ${analysis.statistics.mean}; minimum ${analysis.statistics.minimum}; maximum ${analysis.statistics.maximum}`),
        h('details',null,h('summary',null,'Existing input values'),h('pre',null,JSON.stringify(analysis.positions?analysis.positions.map((p,i)=>({position:p,value:analysis.input_values[i]})):analysis.input_values)))))
      :h('button',{disabled:host.readOnly,onClick:async()=>{try{await host.addNode({type:'workbench.analyze_metrics',inputs:{metrics:[pkg.id]},parameters:{}})}catch(error){setError(error.message)}}},'Analyze these existing metrics'))
  }
  return {actions:[{id:'workbench.metric_analysis',name:'Existing metric analysis',component:Action}],
    editors:[{node:'workbench.analyze_metrics',component:Editor}],
    viewers:[{id:'workbench.metric_analysis',name:'Existing metric analysis',formats:[...supported,'workbench.metric_analysis'],component:Viewer}]}
}
