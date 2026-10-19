/** Existing-geometry confidence using public package access and React. */
export const runtime = { react: 19 };
export function register({ React }) {
  const h = React.createElement;
  const positionLabel = p => `${p.chain || '(blank chain)'} ${p.author_number}${p.insertion_code}`;
  function Editor({ parameters, onChange, readOnly }) {
    return h('section', null,
      h('p', null, 'Choose the existing structure and residues in its Independent structure confidence viewer. Unsupported components, alternate atoms or incomplete atom correspondence stop evaluation. The original structure and source generation confidence stay in the result.'),
      h('p', null, parameters.region?.length ? `Selected residues: ${parameters.region.map(positionLabel).join(', ')}` : 'Complete structure evaluation'),
      parameters.region?.length && h('button', { disabled: readOnly, onClick: () => onChange({ ...parameters, region: null }) }, 'Use complete structure'),
      h('p', null, 'SimpleFold pLDDT is predicted local confidence on a 0–1 fraction scale. Configure existing resources in SimpleFold module settings. This method has no folding seed, steps or sampling parameters.'));
  }
  function Score({ item, objects }) {
    const e = item.evaluation, d = item.data;
    return h('article', null,
      h('h4', null, objects.find(o => o.id === e.object_id)?.label || 'Structure'),
      h('p', null, `${e.method} · ${e.per_position.unit} · ${e.region === null ? 'Complete structure' : e.region.map(positionLabel).join(', ')}`),
      h('p', null, `Mean pLDDT: ${e.values.mean_plddt.value} · ${e.values.mean_plddt.meaning}`),
      h('table', null,
        h('thead', null, h('tr', null, ...['Chain', 'Author residue', 'Insertion code', 'pLDDT (0–1)'].map(t => h('th', { key: t }, t)))),
        h('tbody', null, ...d.positions.map((p, j) => h('tr', { key: j },
          h('td', null, p.chain), h('td', null, p.author_number), h('td', null, p.insertion_code), h('td', null, String(d.plddt[j])))))));
  }
  function Viewer({ package: pkg, host }) {
    const [data, setData] = React.useState(null), [object, setObject] = React.useState('');
    const [positions, setPositions] = React.useState([]), [chosen, setChosen] = React.useState([]);
    const [exportFormat, setExportFormat] = React.useState('mmcif');
    const [scores, setScores] = React.useState([]), [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true; setData(null); setScores([]); setError('');
      host.readFile(pkg.id, pkg.entry).then(b => b.text()).then(JSON.parse).then(async value => {
        if (!Array.isArray(value.objects) || !value.objects.length) throw new Error('Missing structure objects');
        const evaluations = (value.evaluations || []).filter(e => e.origin === 'independent_existing_geometry');
        const values = await Promise.all(evaluations.map(async e => {
          if (!value.objects.some(o => o.id === e.object_id)) throw new Error('Unknown confidence object');
          const d = JSON.parse(await (await host.readFile(pkg.id, e.per_position.file)).text());
          if (!Array.isArray(d.positions) || !Array.isArray(d.plddt) || d.positions.length !== d.plddt.length || d.plddt.some(v => typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 1)) throw new Error('Incomplete confidence position correspondence or invalid fraction');
          return { evaluation: e, data: d };
        }));
        if (active) { setData(value); setObject(value.objects[0].id); setScores(values); }
      }).catch(e => { if (active) setError(String(e)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    React.useEffect(() => {
      let active = true; setPositions([]); setChosen([]);
      const obj = data?.objects.find(o => o.id === object);
      const key = data?.confidence_positions?.[object] || obj?.atoms;
      if (key) host.readFile(pkg.id, key).then(b => b.text()).then(JSON.parse).then(rows => {
        const actual = rows.map(p => ({ chain: p.chain, author_number: p.author_number, insertion_code: p.insertion_code }));
        if (actual.some(p => typeof p.chain !== 'string' || !Number.isSafeInteger(p.author_number) || typeof p.insertion_code !== 'string')) throw new Error('Missing actual residue correspondence');
        const unique = [...new Map(actual.map(p => [JSON.stringify(p), p])).values()];
        if (active) setPositions(unique);
      }).catch(e => { if (active) setError(String(e)); });
      return () => { active = false; };
    }, [data, object, pkg.id, host.readFile]);
    async function add(prepare = false) {
      try {
        await host.addNode({ type: prepare ? 'workbench.prepare_structure_confidence' : 'workbench.evaluate_structure_confidence',
          inputs: { structures: [pkg.id] }, parameters: { object, ...(!prepare && chosen.length ? { region: chosen.map(index => positions[index]) } : {}) },
          ...(!prepare ? { tools: { evaluator: 'workbench.simplefold.confidence' } } : {}) });
      } catch (failure) { setError(String(failure)); }
    }
    async function exportStructure() {
      try { await host.addNode({ type: 'workbench.export_structure', inputs: { structures: [pkg.id] }, parameters: { object, format: exportFormat } }); }
      catch (failure) { setError(String(failure)); }
    }
    const selection = h('fieldset', null, h('legend', null, 'Evaluation region (leave all unchecked for complete structure)'),
      ...positions.map((p, index) => h('label', { key: index, style: { display: 'block' } },
        h('input', { type: 'checkbox', checked: chosen.includes(index), onChange: e => setChosen(old => e.target.checked ? [...old, index].sort((a, b) => a - b) : old.filter(i => i !== index)) }), positionLabel(p))));
    return h('section', null, h('h3', null, 'Existing structure confidence'),
      data && h(React.Fragment, null,
        h('label', null, 'Structure', h('select', { 'aria-label': 'Confidence structure object', value: object, onChange: e => setObject(e.target.value) }, data.objects.map((o, i) => h('option', { key: o.id, value: o.id }, o.label || `Structure ${i + 1}`)))),
        positions.length ? selection : h('button', { onClick: () => add(true), disabled: host.readOnly || !object }, 'Prepare region selection'),
        h('p', null, 'The complete supplied structure is scored. Region selection chooses reported residues and retains the complete original file.'),
        h('button', { onClick: () => add(), disabled: host.readOnly || !object }, 'Add independent confidence evaluation'),
        ['workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence'].includes(pkg.format) && h('div', null,
          h('select', { 'aria-label': 'Confidence structure export format', value: exportFormat, onChange: e => setExportFormat(e.target.value) }, h('option', { value: 'mmcif' }, 'mmCIF'), h('option', { value: 'pdb' }, 'PDB')),
          h('button', { onClick: exportStructure, disabled: host.readOnly || !object }, 'Add structure format export')),
        ...scores.map((item, index) => h(Score, { key: index, item, objects: data.objects })),
        h('details', null, h('summary', null, 'Original objects and source generation confidence'), h('pre', null, JSON.stringify(data.objects, null, 2)))),
      error && h('p', { role: 'alert' }, error));
  }
  return { editors: [{ node: 'workbench.evaluate_structure_confidence', component: Editor }],
    viewers: [{ id: 'workbench.structure_confidence.values', name: 'Independent structure confidence', formats: ['workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence', 'workbench.confidence_input'], component: Viewer }] };
}
