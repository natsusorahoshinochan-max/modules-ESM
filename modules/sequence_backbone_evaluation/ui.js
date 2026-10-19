/** Independent scoring owns object selection and complete chain correspondence. */
export const runtime = { react: 19 };
export function register({ React }) {
  const h = React.createElement;
  const positionLabel = p => `${p.chain} ${p.author_number}${p.insertion_code}`;
  const actual = ({ chain, author_number, insertion_code }) => ({ chain, author_number, insertion_code });
  function Editor({ parameters, onChange, readOnly, context }) {
    const [data, setData] = React.useState(null), [error, setError] = React.useState(''), [busy, setBusy] = React.useState(false);
    const epoch = React.useRef(0), current = React.useRef('');
    const inputs = Object.fromEntries(['sequences', 'reference'].map(port => [port, (context.inputs[port]?.packages || []).map(p => p.id)]));
    const signature = JSON.stringify([context.projectId, context.nodeId, inputs]);
    current.current = JSON.stringify([signature, context.revision, parameters]);
    React.useEffect(() => { epoch.current++; setData(null); setError(''); setBusy(false); return () => { epoch.current++; }; }, [signature]);
    function change(value) { epoch.current++; setBusy(false); onChange(value); }
    async function inspect() {
      const request = ++epoch.current, snapshot = current.current;
      let preview;
      setBusy(true); setError('');
      try {
        preview = await context.host.preview('workbench.sequence_backbone.inspect', inputs, {});
        if (request === epoch.current && snapshot === current.current) setData(preview.data);
      } catch (failure) { if (request === epoch.current && snapshot === current.current) setError(String(failure)); }
      finally {
        if (preview) {
          try { await context.host.cancelPreview(preview.id); }
          catch (failure) { if (request === epoch.current) setError(String(failure)); }
        }
        if (request === epoch.current) setBusy(false);
      }
    }
    const reference = data?.references.find(o => o.object === parameters.reference);
    const chains = reference ? [...new Set(reference.positions.map(p => p.chain))] : [];
    function bind(chain, index) {
      const bindings = (parameters.bindings || []).filter(b => b.reference_chain !== chain);
      if (index !== '') {
        const source = data.sequences[Number(index)];
        bindings.push({ reference_chain: chain, object: source.object, ...(source.source_chain === undefined ? {} : { source_chain: source.source_chain }),
          positions: reference.positions.filter(p => p.chain === chain).map(p => ({ ...actual(p), sequence_index: p.tool_position })) });
      }
      change({ ...parameters, bindings });
    }
    const unavailable = ['sequences', 'reference'].map(port => context.inputs[port]?.unavailable).filter(Boolean);
    return h('section', null,
      h('p', null, 'Bind explicit sequence and reference packages, then inspect their objects. Select a sequence for every reference chain. Whole-chain mapping follows displayed residue order; lengths must match. All chains remain separate tool context.'),
      ...unavailable.map((reason, i) => h('p', { key: i, role: 'status' }, reason)),
      h('button', { disabled: busy || readOnly || Object.values(inputs).some(ids => ids.length !== 1), onClick: inspect }, busy ? 'Reading inputs…' : 'Inspect sequence and reference inputs'),
      data && h(React.Fragment, null,
        h('label', null, 'Reference structure', h('select', { 'aria-label': 'Reference structure', value: parameters.reference || '', disabled: readOnly, onChange: e => change({ ...parameters, reference: e.target.value, bindings: [], region: null }) },
          h('option', { value: '' }, 'Choose reference'), ...data.references.map((o, i) => h('option', { key: o.object, value: o.object }, o.label || `Reference ${i + 1}`)))),
        ...chains.map(chain => {
          const positions = reference.positions.filter(p => p.chain === chain), binding = parameters.bindings?.find(b => b.reference_chain === chain);
          const selected = data.sequences.findIndex(s => s.object === binding?.object && s.source_chain === binding?.source_chain);
          return h('fieldset', { key: chain }, h('legend', null, `Reference chain ${chain} · ${positions.length} residues`),
            h('select', { 'aria-label': `Sequence for reference chain ${chain}`, value: selected < 0 ? '' : String(selected), disabled: readOnly, onChange: e => bind(chain, e.target.value) },
              h('option', { value: '' }, 'Choose complete chain sequence'), ...data.sequences.map((s, i) => h('option', { key: i, value: String(i), disabled: s.sequence.length !== positions.length }, `${s.label || `Sequence ${i + 1}`}${s.source_chain === undefined ? '' : ` · chain ${s.source_chain}`} · ${s.sequence.length} residues`))),
            selected >= 0 && h('p', null, data.sequences[selected].sequence),
            h('p', null, positions.map(positionLabel).join(', ')));
        }),
        reference && h('fieldset', null, h('legend', null, 'Report region (unchecked means all residues; full backbone remains input)'),
          ...reference.positions.map((p, i) => h('label', { key: i, style: { display: 'block' } }, h('input', { type: 'checkbox', disabled: readOnly,
            checked: (parameters.region || []).some(row => JSON.stringify(row) === JSON.stringify(actual(p))),
            onChange: e => {
              const values = (parameters.region || []).filter(row => JSON.stringify(row) !== JSON.stringify(actual(p)));
              if (e.target.checked) values.push(actual(p));
              change({ ...parameters, region: values.length ? values : null });
            } }), positionLabel(p))))),
      h('p', null, 'ProteinMPNN score_only returns mean negative log likelihood (lower is better). The scoring mask combines coordinates, selected chains and nonfixed positions; global NLL uses all coordinate positions. Region NLL reports selected residues from the same complete-context call. Configure seed, model, designed chains and fixed positions in the selected tool. Seed 0 chooses and records an actual random seed; positive seeds pass directly. Repeated evaluations use num_seq_per_target and exact batch_size divisibility. Existing ProteinMPNN resources are configured in its module settings.'),
      error && h('p', { role: 'alert' }, error));
  }
  function Viewer({ package: pkg, host }) {
    const [data, setData] = React.useState(null), [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true; setData(null); setError('');
      host.readFile(pkg.id, pkg.entry).then(b => b.text()).then(JSON.parse).then(value => { if (active) setData(value); }).catch(e => { if (active) setError(String(e)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    function sampleTable(e, sample, index) {
      const rows = e.positions.map((p, k) => {
        const offset = p.tool_position - 1;
        const values = [positionLabel(p), p.tool_position, sample.chains[p.chain][offset], sample.residue_nll[p.chain][offset], sample.design_mask[p.chain][offset], sample.coordinate_mask[p.chain][offset], sample.region_mask[p.chain][offset]];
        return h('tr', { key: k }, ...values.map((value, n) => h('td', { key: n }, String(value))));
      });
      return h('section', { key: index },
        h('p', null, `Evaluation ${index + 1} · scoring NLL ${sample.score} · global NLL ${sample.global_score} · region NLL ${sample.region_nll}`),
        h('table', null,
          h('thead', null, h('tr', null, ...['Reference residue', 'Tool chain position', 'Sequence', 'NLL', 'Scoring mask', 'Coordinate mask', 'Region mask'].map(label => h('th', { key: label }, label)))),
          h('tbody', null, ...rows)));
    }
    function evaluation(e, index) {
      const labels = e.object_ids.map(id => { const i = data.objects.findIndex(o => o.id === id); return data.objects[i]?.label || `Sequence ${i + 1}`; });
      return h('article', { key: index },
        h('h4', null, `${e.method} · ${e.reference.label || 'Selected reference'}`),
        h('p', null, `${e.unit} · actual seed ${e.actual_seed}`),
        h('p', null, e.region === null ? 'Complete reference reporting' : e.region.map(positionLabel).join(', ')),
        h('p', null, `Evaluated sequences: ${labels.join(', ')}`),
        ...e.samples.map((sample, j) => sampleTable(e, sample, j)),
        h('details', null, h('summary', null, 'Effective tool parameters'), h('pre', null, JSON.stringify(e.parameters, null, 2))));
    }
    return h('section', null, h('h3', null, 'Independent sequence / backbone evaluation'),
      data && h(React.Fragment, null,
        ...data.objects.map((o, i) => h('article', { key: o.id }, h('h4', null, o.label || `Sequence ${i + 1}`), o.sequence ? h('pre', null, o.sequence) : Object.entries(o.chains).map(([chain, sequence]) => h('p', { key: chain }, `${chain}: ${sequence}`)))),
        ...(data.evaluations || []).filter(e => e.origin === 'independent_sequence_backbone').map(evaluation)),
      error && h('p', { role: 'alert' }, error));
  }

  return { editors: [{ node: 'workbench.evaluate_sequence_backbone', component: Editor }], viewers: [{ id: 'workbench.sequence_backbone.values', name: 'Independent sequence/backbone scores and masks', formats: ['workbench.sequence_backbone_evaluation'], component: Viewer }] };
}
