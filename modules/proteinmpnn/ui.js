export const runtime = { react: 19 };
export function register({ React }) {
  const h = React.createElement;
  function Editor() { return h('section', null,
    h('h4', null, 'Backbone-conditioned sequence design'),
    h('p', null, 'Bind a structure set or prediction package. Each explicit structure is one independent design request; failed requests stop the remaining structures. Successful partial sequences remain available to view and export. Continue uses the original call.'),
    h('p', null, 'Choose the ProteinMPNN tool and configure its native parameters in Tools. Full-backbone models require a complete canonical protein N/CA/C/O backbone. Select conformations and resolve alternate locations explicitly upstream.'),
    h('p', null, 'seed=0 chooses an actual random seed recorded in the result. Positive seeds seed Python, NumPy and PyTorch. num_seq_per_target must be divisible by batch_size. sampling_temp is a list; the requested count is generated at each temperature.'),
    h('p', null, 'Constraint positions are native 1-based positions within the named chain, in coordinate-file residue order, including insertion codes as separate positions. Use the input structure viewer and the output correspondence table; author residue numbers are retained separately.'),
    h('p', null, 'Configure designed_chains, fixed_positions, tied_positions, omit_AAs, bias_AA, bias_by_res, omit_AA and pssm in the tool parameter JSON. TOOL.md documents exact native shapes and defaults.'),
    h('p', null, 'The design output preserves every actual chain and native result, including X. Add a chain sequence conversion before a single-chain sequence consumer; selecting a chain containing X reports an explicit conversion error.'));
  }
  function ChainEditor({ parameters, onChange, readOnly }) {
    return h('section', null, h('h4', null, 'Use one actual design chain'),
      h('p', null, 'One chain from every sample becomes an independent canonical sequence. Leave empty only when all samples have the same single chain. Whole-design scores remain in the original design package.'),
      h('label', null, 'Actual chain', h('input', { 'aria-label': 'Actual sequence chain', value: parameters.chain || '', disabled: readOnly,
        onChange: event => onChange(event.target.value ? { chain: event.target.value } : {}) })));
  }
  function Viewer({ package: pkg, host }) {
    const [doc, setDoc] = React.useState(null), [error, setError] = React.useState('');
    const [chain, setChain] = React.useState(''), [adding, setAdding] = React.useState(false), [status, setStatus] = React.useState('');
    React.useEffect(() => { let active = true; setDoc(null); setError(''); setChain(''); setStatus('');
      host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(JSON.parse).then(value => { if (active) setDoc(value); }).catch(err => { if (active) setError(String(err)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    async function addChain() {
      if (!chain || host.readOnly || adding) return;
      setAdding(true); setError(''); setStatus('');
      try {
        await host.addNode({ type: 'workbench.proteinmpnn_chain_sequence', parameters: { chain }, inputs: { design: [pkg.id] } });
        setStatus('Chain sequence node added. Connect its sequence output to a sequence consumer and save the canvas.');
      } catch (failure) { setError(String(failure)); }
      finally { setAdding(false); }
    }
    const chains = doc ? [...new Set(doc.objects.flatMap(obj => Object.keys(obj.chains)))] : [];
    return h('section', null, h('h3', null, 'Designed sequences and natural ProteinMPNN scores'), h('p', null, 'Design NLL averages the coordinate × designed-chain × nonfixed-position mask; global NLL averages coordinate mask over all chains. Both use natural logarithm units.'), error && h('p', { role: 'alert' }, error),
      doc && h(React.Fragment, null, doc.batch && h('p', null, `${doc.batch.completed}/${doc.batch.total} backbones · ${doc.batch.status}`),
        ...doc.objects.map((obj, i) => h('article', { key: obj.id }, h('h4', null, obj.label || `Design sample ${i + 1}`),
          ...Object.entries(obj.chains).map(([name, sequence]) => h('div', { key: name }, h('h5', null, `Chain ${name}`), h('pre', { 'aria-label': `Chain ${name} sequence` }, sequence))),
          obj.design && h(React.Fragment, null, h('p', null, `Design NLL: ${obj.design.score}; global NLL: ${obj.design.global_score}. Lower is better. Actual seed: ${obj.tool.actual_seed}.`),
            h('details', null, h('summary', null, 'Real residues, masks, scores and parameters'), h('pre', null, JSON.stringify({ positions: obj.positions, design: obj.design, tool: obj.tool }, null, 2)))))),
        h('p', null, 'Explicitly use one chain from every sample as separate sequence inputs. Missing chains or X fail conversion; the complete design remains available.'),
        h('label', null, 'Sequence chain', h('select', { 'aria-label': 'Sequence chain', value: chain, disabled: host.readOnly || adding, onChange: event => { setChain(event.target.value); setStatus(''); } },
          h('option', { value: '' }, 'Choose an actual chain'), ...chains.map(name => h('option', { key: name, value: name }, name)))),
        h('button', { disabled: host.readOnly || adding || !chain, onClick: addChain }, adding ? 'Adding…' : 'Add chain sequence node'),
        status && h('p', { role: 'status' }, status)));
  }
  return { editors: [{ node: 'workbench.design_backbone', component: Editor }, { node: 'workbench.proteinmpnn_chain_sequence', component: ChainEditor }], viewers: [{ id: 'workbench.proteinmpnn.design', name: 'ProteinMPNN sequences, scores and correspondence', formats: ['workbench.proteinmpnn_design'], component: Viewer }] };
}
