const messages = {
  "candidates": {
    "zh-CN": "候选集合",
    "en": "Candidates"
  },
  "object": {
    "zh-CN": "对象 {0}",
    "en": "Object {0}"
  },
  "select_objects": {
    "zh-CN": "选择对象",
    "en": "Select objects"
  },
  "split_collection": {
    "zh-CN": "拆分集合",
    "en": "Split collection"
  },
  "extract_structures": {
    "zh-CN": "提取结构",
    "en": "Extract structures"
  },
  "extract_sequences": {
    "zh-CN": "提取序列",
    "en": "Extract sequences"
  },
  "select_objects_in_the_desired_order": {
    "zh-CN": "按所需顺序选择对象",
    "en": "Select objects in the desired order"
  },
  "output_order": {
    "zh-CN": "输出顺序",
    "en": "Output order"
  }
};
/** Collection controls use only the public file and node interfaces. */
export const runtime = { react: 19 };

export function register({ React, i18n }) {
  const t = i18n.translator(messages);
  const h = React.createElement;
  function useCollection(pkg, host) {
    const [document, setDocument] = React.useState(null), [error, setError] = React.useState('');
    React.useEffect(() => {
      let current = true; setDocument(null); setError('');
      if (pkg) host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => {
        if (current) setDocument(JSON.parse(text));
      }).catch(failure => { if (current) setError(i18n.error(failure)); });
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
    return h('section', { 'aria-label': t("candidates") },
      (error || failure) && h('p', { role: 'alert' }, error || failure),
      h('ol', null, ...(document?.items ?? []).map((item, i) => h('li', { key: i }, item.object.label ?? t("object", {"0": i + 1})))),
      h('button', { disabled: host.readOnly || !document, onClick: () => add('select', { items: document.items.map((_, i) => i) }) }, t("select_objects")),
      h('button', { disabled: host.readOnly || !document, onClick: () => add('split') }, t("split_collection")),
      h('button', { disabled: host.readOnly || !document, onClick: () => add('extract_structures') }, t("extract_structures")),
      h('button', { disabled: host.readOnly || !document, onClick: () => add('extract_sequences') }, t("extract_sequences")));
  }
  function Editor({ context, parameters, onChange, readOnly }) {
    const input = context.inputs.collection;
    const { document, error } = useCollection(input?.packages?.[0], context.host);
    return h('section', { 'aria-label': t("select_objects") },
      input?.unavailable && h('p', null, input.unavailable), error && h('p', { role: 'alert' }, error),
      h('p', null, t("select_objects_in_the_desired_order")),
      ...(document?.items ?? []).map((item, i) => h('label', { key: i, style: { display: 'block' } },
        h('input', { type: 'checkbox', disabled: readOnly, checked: (parameters.items ?? []).includes(i),
          onChange: event => onChange({ items: event.target.checked ? [...(parameters.items ?? []), i] : (parameters.items ?? []).filter(index => index !== i) }) }),
        item.object.label ?? t("object", {"0": i + 1}))),
      h('ol', { 'aria-label': t("output_order") }, ...(parameters.items ?? []).map(i => h('li', { key: i }, document?.items[i]?.object.label ?? t("object", {"0": i + 1})))));
  }
  return { editors: [{ node: 'workbench.collection.select', component: Editor }],
    viewers: [{ id: 'workbench.collection', name: messages.candidates, formats: ['workbench.collection'], component: Viewer }] };
}
