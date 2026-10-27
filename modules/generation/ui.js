const messages = {

  "label_85": {
    "zh-CN": "链 {0} 的序列",
    "en": "Chain {0} sequence"
  }
,
  "samples": {
    "zh-CN": "生成数量",
    "en": "Samples"
  },
  "completed": {
    "zh-CN": "已完成 {0} / {1}",
    "en": "Completed {0} / {1}"
  },
  "candidate": {
    "zh-CN": "候选",
    "en": "Candidate"
  },
  "candidate_2": {
    "zh-CN": "候选 {0}",
    "en": "Candidate {0}"
  },
  "generate_sequence": {
    "zh-CN": "生成序列",
    "en": "Generate sequence"
  },
  "no_3d_coordinates_at_this_stage": {
    "zh-CN": "此阶段没有三维坐标",
    "en": "No 3D coordinates at this stage"
  },
  "actual_native_atom37_coordinates_xy_view": {
    "zh-CN": "原生 atom37 坐标，XY 视图",
    "en": "Actual native atom37 coordinates, XY view"
  },
  "atoms_xy_projection": {
    "zh-CN": "{0} 个原子 · XY 投影",
    "en": "{0} atoms · XY projection"
  },
  "sequence_completed": {
    "zh-CN": "序列已完成 {0}",
    "en": "Sequence completed {0}"
  },
  "sequence_completed_waiting_for_coordinates": {
    "zh-CN": "序列已完成，等待三维坐标",
    "en": "Sequence completed; waiting for coordinates"
  },
  "stage": {
    "zh-CN": "阶段",
    "en": "Stage"
  },
  "3d_coordinates": {
    "zh-CN": "三维坐标",
    "en": "3D coordinates"
  },
  "sequence": {
    "zh-CN": "序列",
    "en": "Sequence"
  },
  "joint_generation": {
    "zh-CN": "联合生成",
    "en": "Joint generation"
  },
  "select_design_chain": {
    "zh-CN": "选择设计链",
    "en": "Select design chain"
  },
  "chain": {
    "zh-CN": "链",
    "en": "Chain"
  },
  "actual_sequence_chain": {
    "zh-CN": "序列所属链",
    "en": "Actual sequence chain"
  },
  "sequence_extraction_node_added": {
    "zh-CN": "已添加提取序列节点",
    "en": "Sequence extraction node added"
  },
  "design_results": {
    "zh-CN": "设计结果",
    "en": "Design results"
  },
  "chain_2": {
    "zh-CN": "链 {0}",
    "en": "Chain {0}"
  },
  "design_nll_global_nll": {
    "zh-CN": "设计 NLL {0} · 全局 NLL {1}",
    "en": "Design NLL {0} · Global NLL {1}"
  },
  "parameters": {
    "zh-CN": "计算参数",
    "en": "Parameters"
  },
  "select_chains": {
    "zh-CN": "选择链",
    "en": "Select chains"
  },
  "adding": {
    "zh-CN": "添加中…",
    "en": "Adding…"
  },
  "extract_sequences": {
    "zh-CN": "提取序列",
    "en": "Extract sequences"
  },
  "designed_sequence": {
    "zh-CN": "设计序列",
    "en": "Designed sequence"
  }
};
export const runtime = { react: 19 };
function ResultValues({React,values}) {
  const h=React.createElement;
  const scalar=value=>value===null?'—':typeof value==='number'?Number(value.toPrecision(5)):String(value);
  const rows=Object.entries(values??{}).flatMap(([key,value])=>value!==null&&typeof value==='object'&&!Array.isArray(value)?Object.entries(value).filter(([,v])=>v===null||typeof v!=='object').map(([name,v])=>[`${key} · ${name}`,v]):!Array.isArray(value)?[[key,value]]:[]);
  return h('dl',null,rows.map(([key,value])=>h(React.Fragment,{key},h('dt',null,key.replaceAll('_',' ')),h('dd',null,scalar(value)))))
}
function registerSequence({ React, i18n }) {
 const t = i18n.translator(messages);
  const h = React.createElement;
  function Editor({ parameters, onChange, readOnly }) {
    return h('section', null,
      h('label', null, t("samples"), h('input', { type: 'number', min: 1, value: parameters.samples ?? 1, disabled: readOnly, onChange: event => onChange({ ...parameters, samples: Number(event.target.value) }) })));
  }
  function Viewer({ package: pkg, host }) {
    const [document, setDocument] = React.useState(null), [error, setError] = React.useState('');
    const [values, setValues] = React.useState(null), [selected, setSelected] = React.useState(0);
    React.useEffect(() => { let active = true; setDocument(null); setValues(null); setError(''); setSelected(0); host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => { if (active) setDocument(JSON.parse(text)); }).catch(failure => { if (active) setError(i18n.error(failure)); }); return () => { active = false; }; }, [pkg.id, pkg.entry, host.readFile]);
    React.useEffect(() => { let active = true; setValues(null); const object = document?.objects[selected]; if (object) host.readFile(pkg.id, object.native.file).then(blob => blob.text()).then(text => { if (active) setValues(JSON.parse(text)); }).catch(failure => { if (active) setError(i18n.error(failure)); }); return () => { active = false; }; }, [document, selected, pkg.id, host.readFile]);
    return h('section', null, error && h('p', { role: 'alert' }, error), document && h(React.Fragment, null,
      h('p', null, t("completed", {"0": document.batch.completed, "1": document.batch.total})),
      h('label', null, t("candidate"), h('select', { value: selected, onChange: event => setSelected(Number(event.target.value)) }, document.objects.map((object, index) => h('option', { key: object.id, value: index }, t("candidate_2", {"0": index + 1}))))),
      h('pre', null, document.objects[selected]?.sequence),

      values && h(ResultValues,{React,values:values.metrics})));
  }
  return { editors: [{ node: 'workbench.complete_sequence', inline: true, component: Editor }], viewers: [{ id: 'workbench.esm3.generated', name: messages.generate_sequence, formats: ['workbench.esm3_generation'], component: Viewer }] };
}

function registerJoint({ React, i18n }) {
 const t = i18n.translator(messages);
  const h = React.createElement;
  function Coordinates({ coordinates }) {
    const points = Array.isArray(coordinates) ? coordinates.flatMap(row => Array.isArray(row) ? row.filter(point => Array.isArray(point) && point.length === 3 && point.every(value => typeof value === 'number' && Number.isFinite(value))) : []) : [];
    if (!points.length) return h('p', null, t("no_3d_coordinates_at_this_stage"));
    let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
    for (const point of points) { xmin = Math.min(xmin, point[0]); xmax = Math.max(xmax, point[0]); ymin = Math.min(ymin, point[1]); ymax = Math.max(ymax, point[1]); }
    const scale = 260 / Math.max(xmax - xmin, ymax - ymin, 1);
    return h('figure', null,
      h('svg', { viewBox: '0 0 300 300', width: 300, height: 300, role: 'img', 'aria-label': t("actual_native_atom37_coordinates_xy_view") }, points.map((point, index) => h('circle', { key: index, cx: 20 + (point[0] - xmin) * scale, cy: 280 - (point[1] - ymin) * scale, r: 2, fill: '#1976b6' }, h('title', null, point.join(', '))))),
      h('figcaption', null, t("atoms_xy_projection", {"0": points.length})));
  }
  function Viewer({ package: pkg, host }) {
    const [loaded, setLoaded] = React.useState(null), [loadedValues, setLoadedValues] = React.useState(null), [error, setError] = React.useState('');
    const [selected, setSelected] = React.useState(0), [phase, setPhase] = React.useState('structure');
    const document = loaded?.id === pkg.id && loaded.entry === pkg.entry ? loaded.document : null;
    React.useEffect(() => { let active = true; setLoaded(null); setLoadedValues(null); setError(''); setSelected(0); setPhase('structure'); host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => { if (active) setLoaded({ id: pkg.id, entry: pkg.entry, document: JSON.parse(text) }); }).catch(failure => { if (active) setError(i18n.error(failure)); }); return () => { active = false; }; }, [pkg.id, pkg.entry, host.readFile]);
    const objects = document ? [...document.objects, ...(document.pending_sequence ? [document.pending_sequence] : [])] : [];
    const sample = objects[selected];
    const pending = sample && document?.pending_sequence?.id === sample.id;
    const object = sample?.sequence_stage && phase === 'sequence' ? sample.sequence_stage : sample;
    const nativeFile = object?.native.file;
    const values = loadedValues?.id === pkg.id && loadedValues.file === nativeFile ? loadedValues.document : null;
    React.useEffect(() => { let active = true; setLoadedValues(null); if (nativeFile) host.readFile(pkg.id, nativeFile).then(blob => blob.text()).then(text => { if (active) setLoadedValues({ id: pkg.id, file: nativeFile, document: JSON.parse(text) }); }).catch(failure => { if (active) setError(i18n.error(failure)); }); return () => { active = false; }; }, [nativeFile, pkg.id, host.readFile]);
    return h('section', null, error && h('p', { role: 'alert' }, error), document && h(React.Fragment, null,
      h('p', null, t("completed", {"0": document.batch.completed, "1": document.batch.total})),
      h('p', null, t("sequence_completed", {"0": document.batch.sequence_completed})),
      h('label', null, t("candidate"), h('select', { value: selected, onChange: event => setSelected(Number(event.target.value)) }, objects.map((obj, index) => h('option', { key: obj.id, value: index }, t("candidate_2", {"0": index + 1}))))),
      pending ? h('p', null, t("sequence_completed_waiting_for_coordinates")) : sample && h('label', null, t("stage"), h('select', { value: phase, onChange: event => setPhase(event.target.value) }, h('option', { value: 'structure' }, t("3d_coordinates")), h('option', { value: 'sequence' }, t("sequence")))),
      object && h(React.Fragment, null,
        h('pre', null, object.sequence),

        values && h(React.Fragment, null, h(Coordinates, { coordinates: values.tracks.coordinates }), h(ResultValues,{React,values:values.metrics})))));
  }
  return { editors: [], viewers: [{ id: 'workbench.joint_generation.native', name: messages.joint_generation, formats: ['workbench.joint_generation'], component: Viewer }] };
}

function registerBackbone({ React, i18n }) {
 const t = i18n.translator(messages);
  const h = React.createElement;
  function ChainEditor({ parameters, onChange, readOnly }) {
    return h('section', null, h('h4', null, t("select_design_chain")),
      h('label', null, t("chain"), h('input', { 'aria-label': t("actual_sequence_chain"), value: parameters.chain || '', disabled: readOnly,
        onChange: event => onChange(event.target.value ? { chain: event.target.value } : {}) })));
  }
  function Viewer({ package: pkg, host }) {
    const [doc, setDoc] = React.useState(null), [error, setError] = React.useState('');
    const [chain, setChain] = React.useState(''), [adding, setAdding] = React.useState(false), [status, setStatus] = React.useState('');
    React.useEffect(() => { let active = true; setDoc(null); setError(''); setChain(''); setStatus('');
      host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(JSON.parse).then(value => { if (active) setDoc(value); }).catch(err => { if (active) setError(i18n.error(err)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    async function addChain() {
      if (!chain || host.readOnly || adding) return;
      setAdding(true); setError(''); setStatus('');
      try {
        await host.addNode({ type: 'workbench.proteinmpnn_chain_sequence', parameters: { chain }, inputs: { design: [pkg.id] } });
        setStatus(t("sequence_extraction_node_added"));
      } catch (failure) { setError(i18n.error(failure)); }
      finally { setAdding(false); }
    }
    const chains = doc ? [...new Set(doc.objects.flatMap(obj => Object.keys(obj.chains)))] : [];
    return h('section', null, h('h3', null, t("design_results")), error && h('p', { role: 'alert' }, error),
      doc && h(React.Fragment, null, doc.batch && h('p', null, t("completed", {"0": doc.batch.completed, "1": doc.batch.total})),
        ...doc.objects.map((obj, i) => h('article', { key: obj.id }, h('h4', null, obj.label || t("candidate_2", {"0": i + 1})),
          ...Object.entries(obj.chains).map(([name, sequence]) => h('div', { key: name }, h('h5', null, t("chain_2", {"0": name})), h('pre', { 'aria-label': t("label_85", {"0": name}) }, sequence))),
          obj.design && h(React.Fragment, null, h('p', null, t("design_nll_global_nll", {"0": obj.design.score, "1": obj.design.global_score})),
            h('details', null, h('summary', null, t("parameters")), h(ResultValues,{React,values:obj.tool.parameters}))))),
        h('label', null, t("chain"), h('select', { 'aria-label': t("chain"), value: chain, disabled: host.readOnly || adding, onChange: event => { setChain(event.target.value); setStatus(''); } },
          h('option', { value: '' }, t("select_chains")), ...chains.map(name => h('option', { key: name, value: name }, name)))),
        h('button', { disabled: host.readOnly || adding || !chain, onClick: addChain }, adding ? t("adding") : t("extract_sequences")),
        status && h('p', { role: 'status' }, status)));
  }
  return { editors: [{ node: 'workbench.proteinmpnn_chain_sequence', component: ChainEditor }], viewers: [{ id: 'workbench.proteinmpnn.design', name: messages.designed_sequence, formats: ['workbench.proteinmpnn_design'], component: Viewer }] };
}

export function register(api) {
  const rows = [registerSequence(api), registerJoint(api), registerBackbone(api)];
  return { editors: rows.flatMap(row => row.editors), viewers: rows.flatMap(row => row.viewers) };
}
