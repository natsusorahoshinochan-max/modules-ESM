const messages = {
  both: {"zh-CN":"嵌入与 Logits",en:"Embedding and logits"},
  embedding: {"zh-CN":"嵌入",en:"Embedding"},
"component": {"zh-CN": "分量", "en": "Component"},
"component_index": {"zh-CN": "分量 {n}", "en": "Component {n}"},
"mean_embedding": {"zh-CN": "平均嵌入", "en": "Mean embedding"},

  "label_73": {
    "zh-CN": "数值",
    "en": "Values"
  },
  "label_74": {
    "zh-CN": "{0}；{1}；维度 {2}",
    "en": "{0}; {1}; dimensions {2}"
  },
  "label_75": {
    "zh-CN": "页",
    "en": "Page"
  },
  "label_76": {
    "zh-CN": "列",
    "en": "Columns"
  },
  "label_77": {
    "zh-CN": "数值",
    "en": "Value"
  }
,
  "requested_values": {
    "zh-CN": "请求的数值",
    "en": "Requested values"
  },
  "saved_numeric_precision": {
    "zh-CN": "保存精度",
    "en": "Saved numeric precision"
  },
  "loading_esmc_manifest": {
    "zh-CN": "正在读取 ESMC 结果…",
    "en": "Loading ESMC manifest…"
  },
  "saved_esmc_values": {
    "zh-CN": "ESMC 数值",
    "en": "Saved ESMC values"
  },
  "configured_local_hf_checkpoint": {
    "zh-CN": "已配置的本地 HF 模型",
    "en": "configured local HF checkpoint"
  },
  "sequence_object": {
    "zh-CN": "序列对象",
    "en": "Sequence object"
  },
  "token_source_position": {
    "zh-CN": "Token / 来源位置",
    "en": "Token / source position"
  },
  "loading_numeric_page": {
    "zh-CN": "正在读取数值…",
    "en": "Loading numeric page…"
  },
  "esmc_numeric_values": {
    "zh-CN": "ESMC 数值",
    "en": "ESMC numeric values"
  }
};
/** ESMC owns binary decoding, numeric paging and scientific labels. */
export const runtime = { react: 19 };

export function decodePage(buffer, dtype) {
  const view = new DataView(buffer);
  const width = dtype === 'float16' ? 2 : 4;
  return Array.from({ length: buffer.byteLength / width }, (_, index) => {
    if (width === 4) return view.getFloat32(index * 4, true);
    const bits = view.getUint16(index * 2, true), sign = bits & 0x8000 ? -1 : 1;
    const exponent = (bits >> 10) & 31, fraction = bits & 1023;
    return sign * (exponent === 0 ? fraction * 2 ** -24 : exponent === 31 ? (fraction ? NaN : Infinity) : (1 + fraction / 1024) * 2 ** (exponent - 15));
  });
}

export function register({ React, i18n }) {
  const t = i18n.translator(messages);
  const h = React.createElement;
  function Parameters({ parameters, onChange, readOnly }) {
    return h('section', null, ...[
      ['outputs', t("requested_values"), ['embedding', 'logits', 'both'], 'both'],
      ['dtype', t("saved_numeric_precision"), ['float32', 'float16'], 'float32'],
    ].map(([key, label, values, fallback]) => h('label', { key }, label, h('select', { value: parameters[key] || fallback, disabled: readOnly, onChange: event => onChange({ ...parameters, [key]: event.target.value }) }, values.map(value => h('option', { key: value, value }, value==='both'||value==='embedding'?t(value):value))))));
  }
  function Viewer({ package: pkg, host }) {
    const [manifest, setManifest] = React.useState(null);
    const [objectIndex, setObjectIndex] = React.useState(0), [field, setField] = React.useState('logits');
    const [page, setPage] = React.useState(0), [column, setColumn] = React.useState(0);
    const [values, setValues] = React.useState(null), [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true;
      setManifest(null); setValues(null); setError(''); setObjectIndex(0); setPage(0); setColumn(0);
      host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => { if (active) { const document = JSON.parse(text); setManifest(document); setField(document.objects[0].logits ? 'logits' : 'mean_embedding'); } }).catch(failure => { if (active) setError(i18n.error(failure)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    const object = manifest?.objects[objectIndex], descriptor = object?.[field];
    React.useEffect(() => {
      let active = true;
      setValues(null); setError('');
      if (descriptor?.pages[page]) host.readFile(pkg.id, descriptor.pages[page].file).then(blob => blob.arrayBuffer()).then(buffer => { if (active) setValues(decodePage(buffer, descriptor.dtype)); }).catch(failure => { if (active) setError(i18n.error(failure)); });
      return () => { active = false; };
    }, [pkg.id, descriptor, page, host.readFile]);
    if (!manifest) return h('p', { role: error ? 'alert' : 'status' }, error || t("loading_esmc_manifest"));
    const shape = descriptor?.shape, width = shape?.[1] || 1, first = descriptor?.pages[page]?.start || 0;
    const rows = values && Array.from({ length: descriptor.pages[page].rows }, (_, row) => {
      const index = first + row, token = field === 'logits' ? object.tokens[index] : null;
      const position = token?.sequence_index && object.input.positions?.[token.sequence_index - 1];
      const label = token ? `Token ${index}: ${token.name || `ID ${token.id}`}${token.sequence_index ? `; residue ${token.sequence_index}` : ''}${position?.chain !== undefined ? `; author ${position.chain}:${position.author_number}${position.insertion_code}` : ''}${position?.label_position ? `; label ${position.label_position.chain}:${position.label_position.position}` : ''}` : t('component_index',{n:index});
      return h('tr', { key: index }, h('th', null, label), ...(field === 'logits' ? descriptor.columns.slice(column, column + 8).map(spec => h('td', { key: spec.index }, String(values[row * width + spec.index]))) : [h('td', { key: 'value' }, String(values[row]))]));
    });
    return h('section', null,
      h('h3', null, t("saved_esmc_values")),
      h('p', null, `${manifest.tool.id}; ${manifest.tool.parameters.model || t("configured_local_hf_checkpoint")}`),
      h('label', null, t("sequence_object"), h('select', { value: objectIndex, onChange: event => { const index = Number(event.target.value); setObjectIndex(index); setPage(0); setColumn(0); setField(manifest.objects[index].logits ? 'logits' : 'mean_embedding'); } }, manifest.objects.map((item, index) => h('option', { key: index, value: index }, item.input.label || item.input.id)))),
      h('label', null, t("label_73"), h('select', { value: field, onChange: event => { setField(event.target.value); setPage(0); setColumn(0); } }, ['logits', 'mean_embedding'].filter(key => object[key]).map(key => h('option', { key, value: key }, key==='mean_embedding'?t('mean_embedding'):key)))),
      descriptor && h('p', null, t("label_74", {"0": descriptor.semantics, "1": descriptor.dtype, "2": shape.join(' × ')})),
      descriptor && h('label', null, t("label_75"), h('select', { value: page, onChange: event => setPage(Number(event.target.value)) }, descriptor.pages.map((spec, index) => h('option', { key: index, value: index }, `${spec.start}–${spec.start + spec.rows - 1}`)))),
      field === 'logits' && h('label', null, t("label_76"), h('select', { value: column, onChange: event => setColumn(Number(event.target.value)) }, Array.from({ length: Math.ceil(width / 8) }, (_, index) => h('option', { key: index, value: index * 8 }, `${index * 8}–${Math.min(width - 1, index * 8 + 7)}`)))),
      error && h('p', { role: 'alert' }, error),
      values ? h('table', null, h('thead', null, h('tr', null, h('th', null, field === 'logits' ? t("token_source_position") : t('component')), ...(field === 'logits' ? descriptor.columns.slice(column, column + 8).map(spec => h('th', { key: spec.index }, `${spec.index}${spec.name ? ` ${spec.name}` : ''}`)) : [h('th', { key: 'value' }, t("label_77"))]))), h('tbody', null, rows)) : h('p', null, t("loading_numeric_page")));
  }
  return { editors: [{ node: 'workbench.represent', component: Parameters }], viewers: [{ id: 'workbench.esmc.values', name: messages.esmc_numeric_values, formats: ['workbench.esmc'], component: Viewer }] };
}
