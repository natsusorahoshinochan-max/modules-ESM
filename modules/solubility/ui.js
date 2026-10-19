/** Independent solubility viewer and node editor using the public React contract. */
export const runtime = { react: 19 };

export function register({ React }) {
  const h = React.createElement;
  function Parameters() {
    return h('section', null,
      h('h4', null, 'Evaluate existing sequences'),
      h('p', null, 'Bind an existing workbench.sequence package to the sequence port. Every object in the selected package is evaluated as a complete sequence; object identity, source and supplied residue correspondence are retained.'),
      h('p', null, 'Choose the evaluator in Tools and configure its tool parameters there. Unsupported conditions, regions and nonstandard amino acids fail with a specific error.'),
      h('ul', null,
        h('li', null, 'SoluProt full: at least 20 residues; includes TMHMM. SoluProt no-TM: at least 20 residues; explicitly uses the independent no-TM model. threads: positive integer, default 1 from the CLI.'),
        h('li', null, 'Protein-Sol: at least 21 residues. membrane_exclude and histidine_charged: booleans, default false from the official scripts. If true, sequences excluded by its membrane check cause this evaluation to fail.')),
      h('p', null, 'Configure existing program, source, model and reference database paths in module deployment settings.'));
  }
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
    return h('section', null, h('h3', null, 'Independent sequence solubility evaluation'),
      error && h('p', { role: 'alert' }, error),
      !document && !error && h('p', null, 'Loading…'),
      document && h(React.Fragment, null,
        h('p', null, 'Tool: ', document.tool.id, ' · Parameters: ', JSON.stringify(document.tool.parameters)),
        ...document.evaluations.map((evaluation, index) => {
          const object = document.objects.find(item => item.id === evaluation.object_id);
          return h('article', { key: index },
            h('h4', null, object?.label || `Sequence ${index + 1}`),
            h('p', null, evaluation.method, ' · Complete sequence · No reference'),
            h('table', null, h('thead', null, h('tr', null, ...['Metric', 'Value', 'Unit', 'Meaning'].map(title => h('th', { key: title }, title)))),
              h('tbody', null, ...Object.entries(evaluation.values).map(([name, metric]) => h('tr', { key: name }, h('td', null, name), h('td', null, String(metric.value)), h('td', null, metric.unit), h('td', null, metric.meaning))))),
            h('details', null, h('summary', null, 'Sequence, source and residue correspondence'), h('pre', null, JSON.stringify(object, null, 2))));
        }),
        h('details', null, h('summary', null, 'Tool calibration and model context'), h('pre', null, JSON.stringify(document.tool.context, null, 2)))));
  }
  return { editors: [{ node: 'workbench.evaluate_solubility', component: Parameters }],
    viewers: [{ id: 'workbench.solubility.values', name: 'Solubility values and meanings', formats: ['workbench.solubility'], component: Viewer }] };
}
