const messages = {
  "multiple_fasta_records_use_batch_import": {
    "zh-CN": "多个 FASTA 记录请使用批量导入。",
    "en": "Multiple FASTA records: use batch import."
  },
  "fasta_must_start_with_a_header": {
    "zh-CN": "FASTA 需以标题行开头。",
    "en": "FASTA must start with a header."
  },
  "enter_amino_acid_letters_or_for_an": {
    "zh-CN": "请输入氨基酸字母，空缺位置使用 _。",
    "en": "Enter amino-acid letters or _ for an unfilled position."
  },
  "batch_import_requires_fasta_records_with_headers": {
    "zh-CN": "批量导入需使用带标题行的 FASTA。",
    "en": "Batch import requires FASTA records with headers."
  },
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
  "sequence_requires_supported_amino_acid_letters_or": {
    "zh-CN": "序列需使用支持的氨基酸字母或 _。",
    "en": "Sequence requires supported amino-acid letters or _."
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
  "position_ids_must_be_unique_and_cover": {
    "zh-CN": "位置标识需唯一且覆盖完整序列。",
    "en": "Position ids must be unique and cover the complete sequence."
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
  "sequences": {
    "zh-CN": "{0} 条序列",
    "en": "{0} sequences"
  },
  "loaded": {
    "zh-CN": "已载入",
    "en": "Loaded"
  },
  "format": {
    "zh-CN": "格式",
    "en": "Format"
  },
  "sequence_input_format": {
    "zh-CN": "序列输入格式",
    "en": "Sequence input format"
  },
  "sequence_fasta": {
    "zh-CN": "序列 / FASTA",
    "en": "Sequence / FASTA"
  },
  "sequence_data_file": {
    "zh-CN": "序列数据文件",
    "en": "Sequence data file"
  },
  "multiple_sequences": {
    "zh-CN": "多条序列",
    "en": "Multiple sequences"
  },
  "sequence": {
    "zh-CN": "序列",
    "en": "Sequence"
  },
  "choose_file": {
    "zh-CN": "选择文件",
    "en": "Choose file"
  },
  "loading": {
    "zh-CN": "载入中…",
    "en": "Loading…"
  },
  "load": {
    "zh-CN": "载入",
    "en": "Load"
  },
  "sequence_2": {
    "zh-CN": "序列 {0}",
    "en": "Sequence {0}"
  },
  "position_mapping": {
    "zh-CN": "位置对应",
    "en": "Position mapping"
  },
  "position": {
    "zh-CN": "位置",
    "en": "Position"
  },
  "chain": {
    "zh-CN": "链",
    "en": "Chain"
  },
  "original_number": {
    "zh-CN": "原始编号",
    "en": "Original number"
  },
  "export_fasta": {
    "zh-CN": "导出 FASTA",
    "en": "Export FASTA"
  }
};
/** Sequence import, viewing and export through the public module UI. */
export const runtime = { react: 19 };

export function parseSequence(text) {
  const lines = text.trim().split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const headers = lines.filter(line => line.startsWith('>'));
  if (headers.length > 1) throw messageError("multiple_fasta_records_use_batch_import");
  if (headers.length && !lines[0].startsWith('>')) throw messageError("fasta_must_start_with_a_header");
  const sequence = (headers.length ? lines.slice(1) : lines).join('').replace(/\s/g, '').toUpperCase();
  if (!sequence || !/^[ACDEFGHIKLMNPQRSTVWYBXZJUO_]+$/.test(sequence)) throw messageError("enter_amino_acid_letters_or_for_an");
  return { sequence, ...(headers.length && lines[0].slice(1).trim() ? { label: lines[0].slice(1).trim() } : {}) };
}

export function parseBatch(text) {
  const records = text.trim().split(/(?=^>)/m).filter(record => record.trim());
  if (!records.length || records.some(record => !record.trim().startsWith('>'))) throw messageError("batch_import_requires_fasta_records_with_headers");
  return records.map(parseSequence);
}

function sequenceObjects(document) {
  if (!document || Object.keys(document).join() !== 'objects' || !Array.isArray(document.objects) || !document.objects.length) throw messageError("a_nonempty_sequence_object_batch_is_required");
  const ids = new Set();
  for (const object of document.objects) {
    if (!object || typeof object !== 'object' || Object.keys(object).some(key => !['id', 'sequence', 'label', 'source', 'positions'].includes(key))) throw messageError("unsupported_sequence_object_components_or_conditions");
    if (typeof object.id !== 'string' || !object.id || ids.has(object.id)) throw messageError("sequence_object_ids_must_be_nonempty_and");
    ids.add(object.id);
    if (typeof object.sequence !== 'string' || !/^[ACDEFGHIKLMNPQRSTVWYBXZJUO_]+$/.test(object.sequence)) throw messageError("sequence_requires_supported_amino_acid_letters_or");
    if ('label' in object && typeof object.label !== 'string') throw messageError("sequence_label_must_be_text");
    if ('source' in object && (!object.source || Array.isArray(object.source) || typeof object.source !== 'object' || !Object.keys(object.source).length || Object.entries(object.source).some(([key, value]) => !['name', 'record', 'text'].includes(key) || typeof value !== 'string'))) throw messageError("source_requires_explicit_name_record_or_text");
    if ('positions' in object) {
      if (!Array.isArray(object.positions) || object.positions.length !== object.sequence.length) throw messageError("positions_must_cover_every_sequence_residue");
      const seen = new Set(), seenLabels = new Set();
      const positionIds = object.positions.filter(position => position && 'id' in position).map(position => position.id);
      if (positionIds.length && (positionIds.length !== object.positions.length || positionIds.some(id => typeof id !== 'string' || !id) || new Set(positionIds).size !== positionIds.length)) throw messageError("position_ids_must_be_unique_and_cover");
      object.positions.forEach((position, index) => {
        if (!position || Object.keys(position).some(key => !['sequence_index', 'id', 'chain', 'author_number', 'insertion_code', 'label_position'].includes(key)) || position.sequence_index !== index + 1) throw messageError("positions_require_ordered_one_based_sequence_index");
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

export function sequenceInput(text, { batch = false, name, json = false } = {}) {
  const objects = json ? sequenceObjects(JSON.parse(text)) : (batch ? parseBatch(text) : [parseSequence(text)]).map(object => ({
    id: crypto.randomUUID(), ...object,
    source: { ...(name ? { name } : {}), ...(object.label ? { record: object.label } : {}), text },
    positions: Array.from(object.sequence, (_, index) => ({ sequence_index: index + 1 })),
  }));
  return { format: 'workbench.sequence', entry: 'manifest.json', files: {
    'manifest.json': new Blob([JSON.stringify({ objects })], { type: 'application/json' }),
  } };
}


export function register({ React, i18n }) {
  const t = i18n.translator(messages);
  const h = React.createElement;
  function SequenceInput({ context, readOnly }) {
    const host=context.host;
    const [{ text, name }, setDraft] = React.useState({ text: '', name: '' });
    const [batch, setBatch] = React.useState(false);
    const [json, setJson] = React.useState(false);
    const [error, setError] = React.useState('');
    const [status, setStatus] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const inputId=context.inputs.file?.packages[0]?.id;
    React.useEffect(()=>{let active=true;const pkg=context.inputs.file?.packages[0];if(pkg)host.readFile(pkg.id,pkg.entry).then(b=>b.text()).then(JSON.parse).then(doc=>{if(active){setJson(true);setDraft({text:JSON.stringify(doc),name:doc.objects?.[0]?.source?.name??''});setStatus(t("sequences", {"0": doc.objects.length}));}}).catch(e=>{if(active)setError(i18n.error(e))});return()=>{active=false}},[inputId]);
    const [reading, setReading] = React.useState(false);
    const pendingRead = React.useRef(null);
    const latestHost = React.useRef(host);
    latestHost.current = host;
    function invalidateRead() {
      pendingRead.current = null;
      setReading(false);
    }
    React.useEffect(() => {
      invalidateRead();
      return () => { pendingRead.current = null; };
    }, [host]);
    function currentRead(request) {
      return pendingRead.current === request && latestHost.current === request.host && !request.host.readOnly;
    }
    async function select(event) {
      invalidateRead();
      const file = event.target.files?.[0];
      if (!file) return;
      const request = { host };
      pendingRead.current = request;
      setReading(true); setError('');
      try {
        const value = await file.text();
        if (!currentRead(request)) return;
        setJson(/\.json$/i.test(file.name)); setDraft({ text: value, name: file.name }); setError('');
      } catch (failure) {
        if (currentRead(request)) setError(i18n.error(failure));
      } finally {
        if (currentRead(request)) invalidateRead();
      }
    }
    async function add() {
      if (pendingRead.current || host.readOnly || busy) return;
      setBusy(true); setError(''); setStatus('');
      try {
        await context.update({delivery:{input:sequenceInput(text,{batch,name,json}),port:'file'},replaceConnections:['file']});
        setStatus(t("loaded"));
      } catch (failure) { setError(i18n.error(failure)); }
      finally { setBusy(false); }
    }
    return h('section', null,
      h('label', null, t("format"), h('select', { 'aria-label': t("sequence_input_format"), value: json ? 'json' : 'fasta', disabled: host.readOnly || busy, onChange: event => { invalidateRead(); setJson(event.target.value === 'json'); setDraft({text:'',name:''}); setStatus(''); setError(''); } }, h('option', { value: 'fasta' }, t("sequence_fasta")), h('option', { value: 'json' }, t("sequence_data_file")))),
      !json && h('label', null, h('input', { type: 'checkbox', 'aria-label': t("multiple_sequences"), checked: batch, disabled: host.readOnly || busy, onChange: event => { invalidateRead(); setBatch(event.target.checked); setError(''); } }), t("multiple_sequences")),
      !json && h('label', null, batch ? 'FASTA' : t("sequence"), h('textarea', { value: text, disabled: host.readOnly || busy, onChange: event => { invalidateRead(); setDraft({ text: event.target.value, name: '' }); setError(''); } })),
      name&&h('span',{className:'inline-file-name'},name),h('label', {className:'inline-file-picker'}, t("choose_file"), h('input', { type: 'file', accept: json ? '.json' : '.fasta,.fa,.faa,.txt', disabled: host.readOnly || busy,
        onChange: select })),
      h('button', { disabled: host.readOnly || busy || reading, onClick: add }, busy ? t("loading") : t("load")),
      status && h('p', { role: 'status' }, status),
      error && h('p', { role: 'alert' }, error));
  }
  function SequenceViewer({ package: pkg, host }) {
    const [objects, setObjects] = React.useState([]);
    const [selected, setSelected] = React.useState([]);
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true;
      setObjects([]); setSelected([]); setError('');
      host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => {
        const values = sequenceObjects(JSON.parse(text));
        if (active) { setObjects(values); setSelected(values.map(object => object.id)); }
      }).catch(failure => { if (active) setError(i18n.error(failure)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    return h('section', null, h('h3', null, t("sequence")),
      ...objects.map((object,index) => h('article', {key: object.id},
        h('label', null, h('input', {type:'checkbox', checked:selected.includes(object.id),
          onChange:event => setSelected(current => event.target.checked ? [...current,object.id] : current.filter(id=>id!==object.id))}), object.label || t("sequence_2", {"0": index+1})),
        h('pre', null, object.sequence),
        object.source?.name && h('p', null, object.source.name),
        object.positions && h('details', null, h('summary', null, t("position_mapping")), h('table',null,h('thead',null,h('tr',null,...[t("position"),t("chain"),t("original_number")].map(name=>h('th',{key:name},name)))),h('tbody',null,object.positions.map(p=>h('tr',{key:p.sequence_index},h('td',null,p.sequence_index),h('td',null,p.chain??'—'),h('td',null,p.author_number==null?'—':`${p.author_number}${p.insertion_code??''}`)))))))),
      h('button', {disabled:host.readOnly || !selected.length, onClick:async()=>{
        try { await host.addNode({type:'workbench.export_sequences',inputs:{sequences:[pkg.id]},parameters:{objects:objects.filter(object=>selected.includes(object.id)).map(object=>object.id)}}); }
        catch(failure){setError(i18n.error(failure));}
      }}, t("export_fasta")), error && h('p', {role:'alert'}, error));
  }
  return {
    editors: [{node:'workbench.import_sequence',inline:true,component:SequenceInput}],
    viewers: [{id:'workbench.sequence.files',name:messages.sequence,defaultFor:['workbench.sequence'],formats:['workbench.sequence'],component:SequenceViewer}],
  };
}

function messageError(key, values = {}) { return Object.assign(new Error(messages[key].en.replace(/\{(\w+)\}/g, (match, key) => Object.hasOwn(values, key) ? String(values[key]) : match)), {displayMessage: messages[key], values}); }
