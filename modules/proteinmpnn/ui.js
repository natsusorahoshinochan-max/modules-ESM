export const runtime = { react: 19 };
export function register({ React }) {
  const h = React.createElement;
  function Editor() { return h('section', null,
    h('h4', null, 'Backbone-conditioned sequence design'),
    h('p', null, 'Bind a structure set or prediction package. Each explicit structure is one independent design request; failed requests stop the remaining structures. Successful partial sequences remain available to view and export. Continue uses the original call.'),
    h('p', null, 'Choose the ProteinMPNN tool and configure its native parameters in Tools. Full-backbone models require a complete canonical protein N/CA/C/O backbone. Select conformations and resolve alternate locations explicitly upstream.'),
    h('p', null, 'seed=0 chooses an actual random seed recorded in the result. Positive seeds seed Python, NumPy and PyTorch. num_seq_per_target must be divisible by batch_size. sampling_temp is a list; the requested count is generated at each temperature.'),
    h('p', null, 'Constraint positions are native 1-based positions within the named chain, in coordinate-file residue order, including insertion codes as separate positions. Use the input structure viewer and the output correspondence table; author residue numbers are retained separately.'),
    h('p', null, 'Configure designed_chains, fixed_positions, tied_positions, omit_AAs, bias_AA, bias_by_res, omit_AA and pssm in the tool parameter JSON. TOOL.md documents exact native shapes and defaults.'));
  }
  function Viewer({ package: pkg, host }) {
    const [doc, setDoc] = React.useState(null), [error, setError] = React.useState('');
    React.useEffect(() => { let active = true; setDoc(null); setError('');
      host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(JSON.parse).then(value => { if (active) setDoc(value); }).catch(err => { if (active) setError(String(err)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    return h('section', null, h('h3', null, 'Designed sequences and natural ProteinMPNN scores'), h('p', null, 'Design NLL averages the coordinate × designed-chain × nonfixed-position mask; global NLL averages coordinate mask over all chains. Both use natural logarithm units.'), error && h('p', { role: 'alert' }, error),
      doc && h(React.Fragment, null, doc.batch && h('p', null, `${doc.batch.completed}/${doc.batch.total} backbones · ${doc.batch.status}`),
        ...doc.objects.map((obj, i) => h('article', { key: obj.id }, h('h4', null, obj.label || `Sequence ${i + 1}`), h('pre', null, obj.sequence),
          obj.design && h(React.Fragment, null, h('p', null, `Design NLL: ${obj.design.score}; global NLL: ${obj.design.global_score}. Lower is better. Actual seed: ${obj.tool.actual_seed}.`),
            h('details', null, h('summary', null, 'Chains, real residues, masks, scores and parameters'), h('pre', null, JSON.stringify(obj, null, 2))))))));
  }
  return { editors: [{ node: 'workbench.design_backbone', component: Editor }], viewers: [{ id: 'workbench.proteinmpnn.design', name: 'ProteinMPNN sequences, scores and correspondence', formats: ['workbench.proteinmpnn_design'], component: Viewer }] };
}
