/** Independent solubility viewer and node editor using the public React contract. */
export const runtime = { react: 19 };

export function register({ React }) {
  const h = React.createElement;
  function Viewer({ package: pkg, host }) {
    const [document, setDocument] = React.useState(null);
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true;
      setDocument(null); setError('');
      host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => {
        const value = JSON.parse(text);
        if (!Array.isArray(value.objects) || !Array.isArray(value.evaluations) || !value.tool) throw new Error('Invalid solubility evaluation manifest.');
        const ids = new Set(value.objects.map(object => object.id));
        if (!value.objects.length || ids.size !== value.objects.length || ids.has(undefined) || value.evaluations.length !== value.objects.length) throw new Error('Evaluation requires one entry per explicit sequence object.');
        const seen = new Set();
        for (const evaluation of value.evaluations) {
          if (!ids.has(evaluation.object_id) || seen.has(evaluation.object_id)) throw new Error('Evaluation refers to an unknown or repeated object.');
          seen.add(evaluation.object_id);
          if (typeof evaluation.method !== 'string' || !evaluation.method || !evaluation.values || !Object.keys(evaluation.values).length || Object.values(evaluation.values).some(metric => typeof metric?.value !== 'number' || !Number.isFinite(metric.value) || typeof metric.unit !== 'string' || typeof metric.meaning !== 'string')) throw new Error('Evaluation requires its actual method, numeric values, units and meanings.');
        }
        if (active) setDocument(value);
      }).catch(failure => { if (active) setError(String(failure)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    return h('section', null, h('h3', null, '可溶性评分'),
      error && h('p', { role: 'alert' }, error),
      !document && !error && h('p', null, '读取中…'),
      document && h(React.Fragment, null,

        ...document.evaluations.map((evaluation, index) => {
          const object = document.objects.find(item => item.id === evaluation.object_id);
          return h('article', { key: index },
            h('h4', null, object?.label || `序列 ${index + 1}`),
            h('p', null, evaluation.method, ' · 整条序列'),
            h('table', null, h('thead', null, h('tr', null, ...['指标', '数值', '单位', '含义'].map(title => h('th', { key: title }, title)))),
              h('tbody', null, ...Object.entries(evaluation.values).map(([name, metric]) => h('tr', { key: name }, h('td', null, name), h('td', null, String(metric.value)), h('td', null, metric.unit), h('td', null, metric.meaning))))),
            h('details', null, h('summary', null, '序列'), h('pre', null, object.sequence)));
        }),
        h('details', null, h('summary', null, '计算参数'), h('dl',null,Object.entries(document.tool.parameters).map(([key,value])=>h(React.Fragment,{key},h('dt',null,key.replaceAll('_',' ')),h('dd',null,String(value))))))));
  }
  return { editors: [],
    viewers: [{ id: 'workbench.solubility.values', name: '可溶性评分', formats: ['workbench.solubility'], component: Viewer }] };
}
