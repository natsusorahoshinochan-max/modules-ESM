/** Self-contained comparison UI. React is supplied through the public runtime. */
export const runtime = { react: 19 };

export function register({ React }) {
  const h = React.createElement;
  function ConversionInput({ host }) {
    const [file, setFile] = React.useState(null);
    const [error, setError] = React.useState('');
    const [status, setStatus] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    async function add() {
      setBusy(true); setError(''); setStatus('');
      try {
        const format = /\.pdb$/i.test(file?.name || '') ? 'pdb' : /\.(cif|mmcif)$/i.test(file?.name || '') ? 'mmcif' : null;
        if (!format) throw new Error('Select one PDB or mmCIF reference file.');
        const key = format === 'pdb' ? 'structure.pdb' : 'structure.cif';
        const manifest = { objects: [{ id: crypto.randomUUID(), label: file.name, structure: { file: key, format } }] };
        const pkg = await host.createInput({ format: 'workbench.reference', entry: 'manifest.json', files: {
          'manifest.json': new Blob([JSON.stringify(manifest)], { type: 'application/json' }), [key]: file,
        } });
        const converter = await host.addNode({ type: 'workbench.prediction_to_structure', parameters: {}, inputs: {} });
        const comparison = await host.addNode({ type: 'workbench.compare_structure', parameters: {}, inputs: { reference: [pkg.id] } });
        await host.connect({ source: converter, source_port: 'structure', target: comparison, target_port: 'subject' });
        setStatus('Connect a prediction result to the converter prediction port, or select a historical prediction package for that port. The converter output is connected to the structure-only comparison.');
      } catch (failure) { setError(String(failure)); }
      finally { setBusy(false); }
    }
    return h('section', null, h('h3', null, 'Compare through explicit structure conversion'),
      h('p', null, 'TM-align compares complete single protein chains using Cα atoms. Select one conformation with all protein residues resolved. Ligands, metals and water remain in the saved structures and overlay; nucleic acids and modified proteins are unsupported.'),
      h('label', null, 'Reference structure', h('input', { type: 'file', accept: '.pdb,.cif,.mmcif', disabled: host.readOnly || busy,
        onChange: event => { setFile(event.target.files?.[0] || null); setError(''); setStatus(''); } })),
      h('button', { disabled: host.readOnly || busy || !file, onClick: add }, busy ? 'Adding…' : 'Add converter and structure comparison'),
      status && h('p', { role: 'status' }, status), error && h('p', { role: 'alert' }, error));
  }
  return { actions: [{ id: 'workbench.conversion.reference', name: 'Compare through explicit structure conversion', component: ConversionInput }] };
}
