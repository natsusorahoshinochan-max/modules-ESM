const messages = {
  "a_nonempty_sequence_object_batch_is_required": {
    "zh-CN": "序列对象列表不能为空。",
    "en": "A nonempty sequence object batch is required."
  },
  "unsupported_sequence_object_components_or_conditions": {
    "zh-CN": "序列对象包含不支持的字段。",
    "en": "Unsupported sequence object components or conditions."
  },
  "sequence_object_ids_must_be_nonempty_and": {
    "zh-CN": "序列对象标识需非空且唯一。",
    "en": "Sequence object IDs must be nonempty and unique."
  },
  "sequence_requires_the_20_standard_amino_acid": {
    "zh-CN": "序列需使用 20 种标准氨基酸字母。",
    "en": "Sequence requires the 20 standard amino acid letters."
  },
  "sequence_label_must_be_text": {
    "zh-CN": "序列名称需为文字。",
    "en": "Sequence label must be text."
  },
  "source_requires_explicit_name_record_or_text": {
    "zh-CN": "来源需包含有效的名称、记录或文本字段。",
    "en": "Source requires explicit name, record or text fields."
  },
  "positions_must_cover_every_sequence_residue": {
    "zh-CN": "位置记录需覆盖每个残基。",
    "en": "Positions must cover every sequence residue."
  },
  "positions_require_ordered_one_based_sequence_index": {
    "zh-CN": "位置需按从 1 开始的序号排列。",
    "en": "Positions require ordered one-based sequence_index values."
  },
  "residue_correspondence_requires_explicit_chain_author_number": {
    "zh-CN": "残基对应需包含链、原始编号和插入码。",
    "en": "Residue correspondence requires explicit chain, author_number and insertion_code."
  },
  "repeated_residue_correspondence": {
    "zh-CN": "残基对应重复。",
    "en": "Repeated residue correspondence."
  },
  "label_correspondence_requires_chain_and_a_positive": {
    "zh-CN": "标签对应需包含链及从 1 开始的位置。",
    "en": "Label correspondence requires chain and a positive one-based position."
  },
  "repeated_label_correspondence": {
    "zh-CN": "标签对应重复。",
    "en": "Repeated label correspondence."
  },
  "prediction_result_requires_the_actual_tool_id": {
    "zh-CN": "预测结果需包含实际工具标识及参数。",
    "en": "Prediction result requires the actual tool id and existing parameters."
  },
  "prediction_result_requires_sequence_objects": {
    "zh-CN": "预测结果缺少序列对象。",
    "en": "Prediction result requires sequence objects."
  },
  "each_prediction_requires_a_sequence_object": {
    "zh-CN": "每个预测需对应一个序列对象。",
    "en": "Each prediction requires a sequence object."
  },
  "result_references_require_explicit_file_keys_distinct": {
    "zh-CN": "结果文件需指定独立于 manifest.json 的文件键。",
    "en": "Result references require explicit file keys distinct from manifest.json."
  },
  "unsupported_prediction_result_fields": {
    "zh-CN": "预测结果包含不支持的字段。",
    "en": "Unsupported prediction result fields."
  },
  "supplied_input_sequence_and_prediction_sequence_disagree": {
    "zh-CN": "输入序列与预测序列不一致。",
    "en": "Supplied input sequence and prediction sequence disagree."
  },
  "each_prediction_requires_a_pdb_or_mmcif": {
    "zh-CN": "每个预测需提供 PDB 或 mmCIF 文件。",
    "en": "Each prediction requires a PDB or mmCIF structure."
  },
  "unsupported_prediction_confidence": {
    "zh-CN": "预测置信度格式不支持。",
    "en": "Unsupported prediction confidence."
  },
  "prediction_plddt_requires_its_declared_0_1": {
    "zh-CN": "预测 pLDDT 需使用声明的 0–1 范围。",
    "en": "Prediction pLDDT requires its declared 0-1 scale."
  },
  "prediction_ptm_must_be_a_finite_0": {
    "zh-CN": "预测 pTM 需为 0–1 范围内的有限数值。",
    "en": "Prediction pTM must be a finite 0-1 value."
  },
  "select_the_required_file_for": {
    "zh-CN": "请选择 {0} 对应的文件。",
    "en": "Select the required file for {0}."
  },
  "prediction_plddt_must_contain_one_finite_0": {
    "zh-CN": "每个残基需有一个 0–1 范围内的 pLDDT 数值。",
    "en": "Prediction pLDDT must contain one finite 0-1 value per sequence residue."
  },
  "imported_view_in_results": {
    "zh-CN": "已导入，可在结果面板查看。",
    "en": "Imported. View in Results."
  },
  "import_prediction": {
    "zh-CN": "导入预测结果",
    "en": "Import prediction"
  },
  "result_manifest": {
    "zh-CN": "结果清单",
    "en": "Result manifest"
  },
  "file_for": {
    "zh-CN": "{0} 对应的文件",
    "en": "File for {0}"
  },
  "importing": {
    "zh-CN": "导入中…",
    "en": "Importing…"
  },
  "import": {
    "zh-CN": "导入",
    "en": "Import"
  },
  "candidate": {
    "zh-CN": "候选",
    "en": "Candidate"
  },
  "prediction_candidate": {
    "zh-CN": "预测候选",
    "en": "Prediction candidate"
  },
  "candidate_2": {
    "zh-CN": "候选 {0}",
    "en": "Candidate {0}"
  },
  "residues": {
    "zh-CN": "{0} 个残基",
    "en": "{0} residues"
  },
  "mean_plddt": {
    "zh-CN": "平均 pLDDT",
    "en": "Mean pLDDT"
  },
  "per_residue_plddt": {
    "zh-CN": "逐残基 pLDDT",
    "en": "Per-residue pLDDT"
  },
  "per_residue_plddt_0_1_positions": {
    "zh-CN": "逐残基 pLDDT · 0–1 · {0} 个位置",
    "en": "Per-residue pLDDT · 0–1 · {0} positions"
  },
  "export_structure": {
    "zh-CN": "导出结构",
    "en": "Export structure"
  },
  "structure_file_format": {
    "zh-CN": "结构文件格式",
    "en": "Structure file format"
  },
  "export_node_added": {
    "zh-CN": "已添加导出节点",
    "en": "Export node added"
  },
  "add_export_node": {
    "zh-CN": "添加导出节点",
    "en": "Add export node"
  },
  "prediction": {
    "zh-CN": "预测结果",
    "en": "Prediction"
  }
};
/** Prediction UI uses only the public host interface and supplied React 19. */
export const runtime = { react: 19 };

function sequenceObjects(document) {
  if (!document || Object.keys(document).join() !== 'objects' || !Array.isArray(document.objects) || !document.objects.length) throw messageError("a_nonempty_sequence_object_batch_is_required");
  const ids = new Set();
  for (const object of document.objects) {
    if (!object || typeof object !== 'object' || Object.keys(object).some(key => !['id', 'sequence', 'label', 'source', 'positions'].includes(key))) throw messageError("unsupported_sequence_object_components_or_conditions");
    if (typeof object.id !== 'string' || !object.id || ids.has(object.id)) throw messageError("sequence_object_ids_must_be_nonempty_and");
    ids.add(object.id);
    if (typeof object.sequence !== 'string' || !/^[ACDEFGHIKLMNPQRSTVWY]+$/.test(object.sequence)) throw messageError("sequence_requires_the_20_standard_amino_acid");
    if ('label' in object && typeof object.label !== 'string') throw messageError("sequence_label_must_be_text");
    if ('source' in object && (!object.source || Array.isArray(object.source) || typeof object.source !== 'object' || !Object.keys(object.source).length || Object.entries(object.source).some(([key, value]) => !['name', 'record', 'text'].includes(key) || typeof value !== 'string'))) throw messageError("source_requires_explicit_name_record_or_text");
    if ('positions' in object) {
      if (!Array.isArray(object.positions) || object.positions.length !== object.sequence.length) throw messageError("positions_must_cover_every_sequence_residue");
      const seen = new Set(), seenLabels = new Set();
      object.positions.forEach((position, index) => {
        if (!position || Object.keys(position).some(key => !['sequence_index', 'chain', 'author_number', 'insertion_code', 'label_position'].includes(key)) || position.sequence_index !== index + 1) throw messageError("positions_require_ordered_one_based_sequence_index");
        const authorKeys = ['chain','author_number','insertion_code'];
        if (authorKeys.some(key=>key in position)) {
          if (!authorKeys.every(key=>key in position) || typeof position.chain !== 'string' || !Number.isSafeInteger(position.author_number) || typeof position.insertion_code !== 'string') throw messageError("residue_correspondence_requires_explicit_chain_author_number");
          const key = JSON.stringify([position.chain, position.author_number, position.insertion_code]);
          if (seen.has(key)) throw messageError("repeated_residue_correspondence");
          seen.add(key);
        }
        if ('label_position' in position) {
          const label=position.label_position;
          if (!label || Array.isArray(label) || Object.keys(label).length!==2 || typeof label.chain!=='string' || !label.chain || !Number.isSafeInteger(label.position) || label.position<1) throw messageError("label_correspondence_requires_chain_and_a_positive");
          const key=JSON.stringify([label.chain,label.position]);
          if(seenLabels.has(key))throw messageError("repeated_label_correspondence");
          seenLabels.add(key);
        }
      });
    }
  }
  return document.objects;
}

function predictionDocument(text) {
  const document = JSON.parse(text);
  if (!document || Object.keys(document).some(key => !['objects', 'tool'].includes(key)) || !document.tool || typeof document.tool.id !== 'string' || !document.tool.id || !document.tool.parameters || Array.isArray(document.tool.parameters) || typeof document.tool.parameters !== 'object') throw messageError("prediction_result_requires_the_actual_tool_id");
  if (!Array.isArray(document.objects) || !document.objects.length) throw messageError("prediction_result_requires_sequence_objects");
  sequenceObjects({ objects: document.objects.map(object => {
    if (!object || typeof object !== 'object' || Array.isArray(object)) throw messageError("each_prediction_requires_a_sequence_object");
    return { id: object.id, sequence: object.sequence, ...('label' in object ? { label: object.label } : {}) };
  }) });
  const files = new Set();
  function file(key) {
    if (typeof key !== 'string' || !key || key === 'manifest.json') throw messageError("result_references_require_explicit_file_keys_distinct");
    files.add(key);
  }
  for (const object of document.objects) {
    if (Object.keys(object).some(key => !['id', 'sequence', 'label', 'input', 'structure', 'confidence', 'supplementary'].includes(key))) throw messageError("unsupported_prediction_result_fields");
    if ('input' in object) {
      sequenceObjects({ objects: [object.input] });
      if (object.input.sequence !== object.sequence) throw messageError("supplied_input_sequence_and_prediction_sequence_disagree");
    }
    if (!object.structure || !['pdb', 'mmcif'].includes(object.structure.format)) throw messageError("each_prediction_requires_a_pdb_or_mmcif");
    file(object.structure.file);
    if ('confidence' in object) {
      const confidence = object.confidence;
      if (!confidence || Object.keys(confidence).some(key => !['plddt', 'ptm'].includes(key))) throw messageError("unsupported_prediction_confidence");
      if ('plddt' in confidence) {
        if (confidence.plddt?.scale !== '0-1') throw messageError("prediction_plddt_requires_its_declared_0_1");
        file(confidence.plddt.file);
      }
      if ('ptm' in confidence && (typeof confidence.ptm !== 'number' || !Number.isFinite(confidence.ptm) || confidence.ptm < 0 || confidence.ptm > 1)) throw messageError("prediction_ptm_must_be_a_finite_0");
    }
    if ('supplementary' in object) file(object.supplementary?.file);
  }
  return { document, keys: [...files] };
}

export async function predictionInput(text, bindings) {
  const { document, keys } = predictionDocument(text);
  const files = Object.create(null);
  for (const key of keys) {
    const blob = Object.hasOwn(bindings, key) && bindings[key];
    if (!(blob instanceof Blob) || !blob.size) throw messageError("select_the_required_file_for", {"0": key});
    files[key] = blob;
  }
  for (const object of document.objects) {
    if (object.confidence?.plddt) {
      const { plddt } = JSON.parse(await files[object.confidence.plddt.file].text());
      if (!Array.isArray(plddt) || plddt.length !== object.sequence.length || plddt.some(value => typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1)) throw messageError("prediction_plddt_must_contain_one_finite_0");
    }
    if (object.supplementary) JSON.parse(await files[object.supplementary.file].text());
  }
  files['manifest.json'] = new Blob([text], { type: 'application/json' });
  return { format: 'workbench.prediction', entry: 'manifest.json', files };
}

export function register({ React, i18n }) {
  const t = i18n.translator(messages);
  const h = React.createElement;
  function PredictionInput({ host }) {
    const [text, setText] = React.useState('');
    const [keys, setKeys] = React.useState([]);
    const [bindings, setBindings] = React.useState({});
    const [error, setError] = React.useState('');
    const [status, setStatus] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const generation = React.useRef(0);
    React.useEffect(() => () => { generation.current++; }, []);
    async function select(event) {
      const request = ++generation.current;
      setText(''); setKeys([]); setBindings({}); setError(''); setStatus('');
      const file = event.target.files?.[0];
      if (!file) return;
      try {
        const value = await file.text();
        const { keys } = predictionDocument(value);
        if (generation.current !== request) return;
        setText(value); setKeys(keys);
      } catch (failure) { if (generation.current === request) setError(i18n.error(failure)); }
    }
    async function add() {
      setBusy(true); setError(''); setStatus('');
      try {
        const input = await predictionInput(text, bindings);
        await host.createInput(input);
        setStatus(t("imported_view_in_results"));
      } catch (failure) { setError(i18n.error(failure)); }
      finally { setBusy(false); }
    }
    return h('section', null, h('h3', null, t("import_prediction")),
      h('label', null, t("result_manifest"), h('input', { type: 'file', accept: '.json', 'aria-label': t("result_manifest"), disabled: host.readOnly || busy, onChange: select })),
      ...keys.map(key => h('label', { key }, key, h('input', { type: 'file', 'aria-label': t("file_for", {"0": key}), disabled: host.readOnly || busy, onChange: event => { const file = event.target.files?.[0]; setBindings(current => ({ ...current, [key]: file })); setError(''); setStatus(''); } }))),
      h('button', { disabled: host.readOnly || busy || !text, onClick: add }, busy ? t("importing") : t("import")),
      status && h('p', { role: 'status' }, status), error && h('p', { role: 'alert' }, error));
  }
  function PredictionViewer({ package: pkg, host }) {
    const [manifest,setManifest]=React.useState(null),[index,setIndex]=React.useState(0),[confidence,setConfidence]=React.useState(null),[error,setError]=React.useState(''),[format,setFormat]=React.useState('mmcif'),[added,setAdded]=React.useState(false);
    React.useEffect(()=>{let live=true;setManifest(null);setIndex(0);setError('');setAdded(false);host.readFile(pkg.id,pkg.entry).then(b=>b.text()).then(JSON.parse).then(value=>{if(live)setManifest(value)}).catch(e=>{if(live)setError(i18n.error(e))});return()=>{live=false}},[pkg.id,pkg.entry]);
    const object=manifest?.objects[index];
    React.useEffect(()=>{let live=true;setConfidence(null);if(object?.confidence?.plddt?.file)host.readFile(pkg.id,object.confidence.plddt.file).then(b=>b.text()).then(JSON.parse).then(value=>{if(live)setConfidence(value)}).catch(e=>{if(live)setError(i18n.error(e))});return()=>{live=false}},[pkg.id,object]);
    const values=confidence?.plddt??[],mean=values.length?values.reduce((sum,n)=>sum+n,0)/values.length:null;
    return h('section',null,error&&h('p',{role:'alert'},error),manifest&&h('label',null,t("candidate"),h('select',{'aria-label':t("prediction_candidate"),value:index,onChange:e=>{setIndex(Number(e.target.value));setAdded(false)}},manifest.objects.map((item,i)=>h('option',{key:item.id,value:i},item.label||t("candidate_2", {"0": i+1}))))),
      object&&h(React.Fragment,null,h('p',null,t("residues", {"0": object.sequence.length})),h('pre',null,object.sequence),
        h('dl',{className:'metric-summary'},mean!==null&&h(React.Fragment,null,h('dt',null,t("mean_plddt")),h('dd',null,mean.toFixed(3))),object.confidence?.ptm!==undefined&&h(React.Fragment,null,h('dt',null,'pTM'),h('dd',null,typeof object.confidence.ptm==='number'?object.confidence.ptm.toFixed(3):object.confidence.ptm.value))),
        values.length>0&&h('figure',null,h('svg',{viewBox:'0 0 360 110',role:'img','aria-label':t("per_residue_plddt")},h('line',{x1:0,x2:360,y1:100,y2:100,stroke:'#ccd6e4'}),h('polyline',{points:values.map((n,i)=>`${i*360/Math.max(1,values.length-1)},${100-n*90}`).join(' '),fill:'none',stroke:'#5278d3',strokeWidth:2})),h('figcaption',null,t("per_residue_plddt_0_1_positions", {"0": values.length}))),
        h('details',null,h('summary',null,t("export_structure")),h('select',{'aria-label':t("structure_file_format"),value:format,onChange:e=>setFormat(e.target.value)},h('option',{value:'mmcif'},'mmCIF'),h('option',{value:'pdb'},'PDB')),h('button',{disabled:host.readOnly,onClick:async()=>{try{await host.addNode({type:'workbench.export_structure',inputs:{structures:[pkg.id]},parameters:{object:object.id,format}});setAdded(true)}catch(e){setError(i18n.error(e))}}},added?t("export_node_added"):t("add_export_node")))));
  }

  return {
    actions: [{ id: 'workbench.prediction.import', name: messages.import_prediction, component: PredictionInput }],
    viewers: [{ id: 'workbench.prediction.files', name: messages.prediction, defaultFor: ['workbench.prediction'], formats: ['workbench.prediction'], component: PredictionViewer }],
  };
}

function messageError(key, values = {}) { return Object.assign(new Error(messages[key].en.replace(/\{(\w+)\}/g, (match, key) => Object.hasOwn(values, key) ? String(values[key]) : match)), {displayMessage: messages[key], values}); }
