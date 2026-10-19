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

export function register({ React }) {
  const h = React.createElement;
  function Parameters({ parameters, onChange, readOnly }) {
    return h('section', null, ...[
      ['outputs', 'Requested values', ['embedding', 'logits', 'both'], 'both'],
      ['dtype', 'Saved numeric precision', ['float32', 'float16'], 'float32'],
    ].map(([key, label, values, fallback]) => h('label', { key }, label, h('select', { value: parameters[key] || fallback, disabled: readOnly, onChange: event => onChange({ ...parameters, [key]: event.target.value }) }, values.map(value => h('option', { key: value, value }, value))))));
  }
  function Viewer({ package: pkg, host }) {
    const [manifest, setManifest] = React.useState(null);
    const [objectIndex, setObjectIndex] = React.useState(0), [field, setField] = React.useState('logits');
    const [page, setPage] = React.useState(0), [column, setColumn] = React.useState(0);
    const [values, setValues] = React.useState(null), [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true;
      setManifest(null); setValues(null); setError(''); setObjectIndex(0); setPage(0); setColumn(0);
      host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => { if (active) { const document = JSON.parse(text); setManifest(document); setField(document.objects[0].logits ? 'logits' : 'mean_embedding'); } }).catch(failure => { if (active) setError(String(failure)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    const object = manifest?.objects[objectIndex], descriptor = object?.[field];
    React.useEffect(() => {
      let active = true;
      setValues(null); setError('');
      if (descriptor?.pages[page]) host.readFile(pkg.id, descriptor.pages[page].file).then(blob => blob.arrayBuffer()).then(buffer => { if (active) setValues(decodePage(buffer, descriptor.dtype)); }).catch(failure => { if (active) setError(String(failure)); });
      return () => { active = false; };
    }, [pkg.id, descriptor, page, host.readFile]);
    if (!manifest) return h('p', { role: error ? 'alert' : 'status' }, error || 'Loading ESMC manifest…');
    const shape = descriptor?.shape, width = shape?.[1] || 1, first = descriptor?.pages[page]?.start || 0;
    const rows = values && Array.from({ length: descriptor.pages[page].rows }, (_, row) => {
      const index = first + row, token = field === 'logits' ? object.tokens[index] : null;
      const position = token?.sequence_index && object.input.positions?.[token.sequence_index - 1];
      const label = token ? `Token ${index}: ${token.name || `ID ${token.id}`}${token.sequence_index ? `; residue ${token.sequence_index}` : ''}${position?.chain !== undefined ? `; ${position.chain}:${position.author_number}${position.insertion_code}` : ''}` : `Component ${index}`;
      return h('tr', { key: index }, h('th', null, label), ...(field === 'logits' ? descriptor.columns.slice(column, column + 8).map(spec => h('td', { key: spec.index }, String(values[row * width + spec.index]))) : [h('td', { key: 'value' }, String(values[row]))]));
    });
    return h('section', null,
      h('h3', null, 'Saved ESMC values'),
      h('p', null, `${manifest.tool.id}; ${manifest.tool.parameters.model || 'configured local HF checkpoint'}`),
      h('label', null, 'Sequence object', h('select', { value: objectIndex, onChange: event => { const index = Number(event.target.value); setObjectIndex(index); setPage(0); setColumn(0); setField(manifest.objects[index].logits ? 'logits' : 'mean_embedding'); } }, manifest.objects.map((item, index) => h('option', { key: index, value: index }, item.input.label || item.input.id)))),
      h('label', null, 'Values', h('select', { value: field, onChange: event => { setField(event.target.value); setPage(0); setColumn(0); } }, ['logits', 'mean_embedding'].filter(key => object[key]).map(key => h('option', { key, value: key }, key)))),
      descriptor && h('p', null, `${descriptor.semantics}; ${descriptor.dtype}; dimensions ${shape.join(' × ')}`),
      descriptor && h('label', null, 'Page', h('select', { value: page, onChange: event => setPage(Number(event.target.value)) }, descriptor.pages.map((spec, index) => h('option', { key: index, value: index }, `${spec.start}–${spec.start + spec.rows - 1}`)))),
      field === 'logits' && h('label', null, 'Columns', h('select', { value: column, onChange: event => setColumn(Number(event.target.value)) }, Array.from({ length: Math.ceil(width / 8) }, (_, index) => h('option', { key: index, value: index * 8 }, `${index * 8}–${Math.min(width - 1, index * 8 + 7)}`)))),
      error && h('p', { role: 'alert' }, error),
      values ? h('table', null, h('thead', null, h('tr', null, h('th', null, field === 'logits' ? 'Token / source position' : 'Component'), ...(field === 'logits' ? descriptor.columns.slice(column, column + 8).map(spec => h('th', { key: spec.index }, `${spec.index}${spec.name ? ` ${spec.name}` : ''}`)) : [h('th', { key: 'value' }, 'Value')]))), h('tbody', null, rows)) : h('p', null, 'Loading numeric page…'));
  }
  return { editors: [{ node: 'workbench.represent', component: Parameters }], viewers: [{ id: 'workbench.esmc.values', name: 'ESMC numeric values', formats: ['workbench.esmc'], component: Viewer }] };
}
