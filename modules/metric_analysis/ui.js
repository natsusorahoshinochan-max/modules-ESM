const messages = {

  "label_86": {
    "zh-CN": "输入 {0} · {1} · {2} · {3}",
    "en": "Input {0} · {1} · {2} · {3}"
  },
  "label_87": {
    "zh-CN": "不可用：",
    "en": "Unavailable: "
  },
  "label_88": {
    "zh-CN": "指标 {0} 的链",
    "en": "Metric {0} chain"
  },
  "label_89": {
    "zh-CN": "指标 {0} 的位置 {1}",
    "en": "Metric {0} position {1}"
  },
  "label_90": {
    "zh-CN": "整体",
    "en": "Whole"
  },
  "label_91": {
    "zh-CN": "所选区域",
    "en": "Selected region"
  },
  "label_92": {
    "zh-CN": "数量 {0}；平均 {1}；最小 {2}；最大 {3}",
    "en": "Count {0}; mean {1}; minimum {2}; maximum {3}"
  }
,
  "existing_metric_selections": {
    "zh-CN": "已选指标",
    "en": "Existing metric selections"
  },
  "read_metrics": {
    "zh-CN": "读取指标",
    "en": "Read metrics"
  },
  "saved_metric_selection_input": {
    "zh-CN": "已选指标 {0} · 输入 {1} · {2}",
    "en": "Saved metric selection {0} · Input {1} · {2}"
  },
  "score_not_present_in_current_inputs": {
    "zh-CN": "当前输入中没有此分数",
    "en": "Score not present in current inputs"
  },
  "remove_saved_selection": {
    "zh-CN": "删除已存选择 {0}",
    "en": "Remove saved selection {0}"
  },
  "remove_selection": {
    "zh-CN": "删除已存选择",
    "en": "Remove selection"
  },
  "generation_confidence": {
    "zh-CN": "生成置信度",
    "en": "Generation confidence"
  },
  "use_metric": {
    "zh-CN": "使用指标 {0}",
    "en": "Use metric {0}"
  },
  "use_metric_2": {
    "zh-CN": "选择此指标",
    "en": "Use metric"
  },
  "select_residues": {
    "zh-CN": "选择残基 {0}",
    "en": "Select residues {0}"
  },
  "select_residues_2": {
    "zh-CN": "选择残基",
    "en": "Select residues"
  },
  "chain": {
    "zh-CN": "链",
    "en": "Chain"
  },
  "all_chains": {
    "zh-CN": "全部链",
    "en": "All chains"
  },
  "blank_chain": {
    "zh-CN": "（空白链）",
    "en": "(blank chain)"
  },
  "scalar": {
    "zh-CN": "标量",
    "en": "Scalar"
  },
  "apply_selection": {
    "zh-CN": "采用选择",
    "en": "Apply selection"
  },
  "reference": {
    "zh-CN": "参考：",
    "en": "Reference: "
  },
  "selected_reference": {
    "zh-CN": "所选参考",
    "en": "Selected reference"
  },
  "no_reference": {
    "zh-CN": "无参考",
    "en": "No reference"
  },
  "method": {
    "zh-CN": "方法：",
    "en": "Method: "
  },
  "region": {
    "zh-CN": "区域：{0}",
    "en": "Region: {0}"
  },
  "original_scores": {
    "zh-CN": "原始分数",
    "en": "Original scores"
  },
  "add_metric_analysis_node": {
    "zh-CN": "添加指标分析节点",
    "en": "Add metric analysis node"
  },
  "metric_analysis": {
    "zh-CN": "指标分析",
    "en": "Metric analysis"
  }
};
export const runtime = {react:19}
export function register({ React, i18n }) {
  const t = i18n.translator(messages);
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
    return h('section',{'aria-label':t("existing_metric_selections")},
      ...Object.values(context.inputs).map((input,i)=>input.unavailable&&h('p',{key:i},input.unavailable)),
      h('button',{onClick:inspect,disabled:busy},t("read_metrics")),error&&h('p',{role:'alert'},error),
      inspected&&selected.map((selection,index)=>!choices.some(choice=>same(selection,choice.selector))&&h('fieldset',{key:`saved-${index}`,disabled:readOnly||busy},
        h('legend',null,t("saved_metric_selection_input", {"0": index+1, "1": selection.input+1, "2": selection.metric})),
        h('p',null,t("score_not_present_in_current_inputs")),
        h('button',{'aria-label':t("remove_saved_selection", {"0": index+1}),onClick:()=>setSelected(items=>items.filter((_,offset)=>offset!==index))},t("remove_selection")))),
      ...choices.map((choice,index)=>{
        const selection=selected.find(item=>same(item,choice.selector)),number=index+1
        const region=selection?.region
        const visible=(choice.positions??[]).filter(p=>!chains[index]||p.chain===chains[index])
        return h('fieldset',{key:JSON.stringify(choice.selector),disabled:readOnly||busy},
          h('legend',null,t("label_86", {"0": choice.selector.input+1, "1": choice.object_label, "2": choice.reference_label, "3": choice.selector.metric})),
          h('p',null,`${choice.selector.origin==='generation'?t("generation_confidence"):`Evaluation ${choice.selector.evaluation===undefined?'':choice.selector.evaluation+1}`}${choice.selector.sample===undefined?'':` · Sample ${choice.selector.sample+1}`} · ${methodName(choice.source_method)} · ${choice.unit} · ${choice.meaning}`),

          choice.unavailable&&h('p',null,t("label_87"),choice.unavailable),
          h('label',null,h('input',{type:'checkbox','aria-label':t("use_metric", {"0": number}),disabled:!!choice.unavailable&&!selection,checked:!!selection,onChange:event=>change(choice,undefined,event.target.checked)}),t("use_metric_2")),
          !choice.unavailable&&choice.positions&&selection&&h(React.Fragment,null,
            h('label',null,h('input',{type:'checkbox','aria-label':t("select_residues", {"0": number}),checked:Array.isArray(region),onChange:event=>change(choice,event.target.checked?[]:undefined)}),t("select_residues_2")),
            Array.isArray(region)&&h(React.Fragment,null,
              h('label',null,t("chain"),h('select',{'aria-label':t("label_88", {"0": number}),value:chains[index]??'',onChange:event=>set链s({...chains,[index]:event.target.value})},
                h('option',{value:''},t("all_chains")),...[...new Set(choice.positions.map(p=>p.chain))].map(chain=>h('option',{key:chain,value:chain},chain||t("blank_chain"))))),
              ...visible.map(p=>h('label',{key:positionName(p)},h('input',{type:'checkbox','aria-label':t("label_89", {"0": number, "1": positionName(p)}),checked:region.some(item=>same(item,p)),onChange:event=>change(choice,event.target.checked?[...region,p]:region.filter(item=>!same(item,p)))}),positionName(p))))),
          !choice.unavailable&&!choice.positions&&h('p',null,t("scalar")))
      }),h('button',{onClick:apply,disabled:readOnly||busy||!choices.length||!selected.length||selected.some(item=>!choices.some(choice=>same(item,choice.selector)&&!choice.unavailable)||(Array.isArray(item.region)&&!item.region.length))},t("apply_selection")))
  }
  function Viewer({package:pkg,host}) {
    const [document,setDocument]=React.useState(null),[error,setError]=React.useState('')
    React.useEffect(()=>{let active=true;setDocument(null);setError('');host.readFile(pkg.id,pkg.entry).then(blob=>blob.text()).then(text=>{if(active)setDocument(JSON.parse(text))}).catch(error=>{if(active)setError(error.message)});return()=>{active=false}},[pkg.id,pkg.entry])
    return h('section',null,error&&h('p',{role:'alert'},error),
      pkg.format==='workbench.metric_analysis'?(document?.analyses??[]).map((analysis,index)=>h('article',{key:index},
        h('h3',null,`${analysis.object.label??`Object ${index+1}`} · ${analysis.metric}`),
        h('p',null,t("reference"),analysis.reference?.label??(analysis.reference?t("selected_reference"):t("no_reference"))),
        h('p',null,t("method"),methodName(analysis.source_method)),h('p',null,analysis.method,' · ',analysis.unit,' · ',analysis.meaning),
        h('p',null,t("region", {"0": analysis.region===null?t("label_90"):Array.isArray(analysis.region)?analysis.region.map(positionName).join(', '):t("label_91")})),
        h('p',null,t("label_92", {"0": analysis.statistics.count, "1": analysis.statistics.mean, "2": analysis.statistics.minimum, "3": analysis.statistics.maximum})),
        h('details',null,h('summary',null,t("original_scores")),h('table',null,h('tbody',null,analysis.input_values.map((value,i)=>h('tr',{key:i},h('td',null,analysis.positions?.[i]?positionName(analysis.positions[i]):i+1),h('td',null,String(value)))))))))
      :h('button',{disabled:host.readOnly,onClick:async()=>{try{await host.addNode({type:'workbench.analyze_metrics',inputs:{metrics:[pkg.id]},parameters:{}})}catch(error){setError(error.message)}}},t("add_metric_analysis_node")))
  }
  return {
    editors:[{node:'workbench.analyze_metrics',component:Editor}],
    viewers:[{id:'workbench.metric_analysis',name:messages.metric_analysis,formats:[...supported,'workbench.metric_analysis'],component:Viewer}]}
}
