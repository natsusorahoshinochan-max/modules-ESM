/** Collection controls use only the public file and node interfaces. */
export const runtime = { react: 19 };

export function register({ React }) {
  const h = React.createElement;
  function useCollection(pkg, host) {
    const [document, setDocument] = React.useState(null), [error, setError] = React.useState('');
    React.useEffect(() => {
      let current = true; setDocument(null); setError('');
      if (pkg) host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => {
        if (current) setDocument(JSON.parse(text));
      }).catch(failure => { if (current) setError(failure.message); });
      return () => { current = false; };
    }, [pkg?.id, pkg?.entry, host.readFile]);
    return { document, error };
  }
  function Viewer({ package: pkg, host }) {
    const { document, error } = useCollection(pkg, host);
    const [failure, setFailure] = React.useState('');
    async function add(type, parameters = {}) {
      try { await host.addNode({ type: `workbench.collection.${type}`, parameters, inputs: { collection: [pkg.id] } }); }
      catch (error) { setFailure(error.message); }
    }
    return h('section', { 'aria-label': '候选集合' },
      (error || failure) && h('p', { role: 'alert' }, error || failure),
      h('ol', null, ...(document?.items ?? []).map((item, i) => h('li', { key: i }, item.object.label ?? `对象 ${i + 1}`))),
      h('button', { disabled: host.readOnly || !document, onClick: () => add('select', { items: document.items.map((_, i) => i) }) }, '选择对象'),
      h('button', { disabled: host.readOnly || !document, onClick: () => add('split') }, '拆分集合'),
      h('button', { disabled: host.readOnly || !document, onClick: () => add('extract_structures') }, '提取结构'),
      h('button', { disabled: host.readOnly || !document, onClick: () => add('extract_sequences') }, '提取序列'));
  }
  function Editor({ context, parameters, onChange, readOnly }) {
    const input = context.inputs.collection;
    const { document, error } = useCollection(input?.packages?.[0], context.host);
    return h('section', { 'aria-label': '选择对象' },
      input?.unavailable && h('p', null, input.unavailable), error && h('p', { role: 'alert' }, error),
      h('p', null, '按所需顺序选择对象'),
      ...(document?.items ?? []).map((item, i) => h('label', { key: i, style: { display: 'block' } },
        h('input', { type: 'checkbox', disabled: readOnly, checked: (parameters.items ?? []).includes(i),
          onChange: event => onChange({ items: event.target.checked ? [...(parameters.items ?? []), i] : (parameters.items ?? []).filter(index => index !== i) }) }),
        item.object.label ?? `对象 ${i + 1}`)),
      h('ol', { 'aria-label': '输出顺序' }, ...(parameters.items ?? []).map(i => h('li', { key: i }, document?.items[i]?.object.label ?? `对象 ${i + 1}`))));
  }
  return { editors: [{ node: 'workbench.collection.select', component: Editor }],
    viewers: [{ id: 'workbench.collection', name: '候选集合', formats: ['workbench.collection'], component: Viewer }] };
}
