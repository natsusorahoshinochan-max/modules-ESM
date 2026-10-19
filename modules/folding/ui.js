/** Prediction UI uses only the public host interface and supplied React 19. */
export const runtime = { react: 19 };

export function parseSequence(text) {
  const lines = text.trim().split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const headers = lines.filter(line => line.startsWith('>'));
  if (headers.length > 1) throw new Error('Multiple FASTA records: use batch import.');
  if (headers.length && !lines[0].startsWith('>')) throw new Error('FASTA must start with a header.');
  const sequence = (headers.length ? lines.slice(1) : lines).join('').replace(/\s/g, '').toUpperCase();
  if (!sequence || !/^[ACDEFGHIKLMNPQRSTVWY]+$/.test(sequence)) throw new Error('Enter one protein sequence using the 20 standard amino acid letters.');
  return { sequence, ...(headers.length && lines[0].slice(1).trim() ? { label: lines[0].slice(1).trim() } : {}) };
}

export function register({ React }) {
  const h = React.createElement;
  function SequenceInput({ host }) {
    const [text, setText] = React.useState('');
    const [error, setError] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    async function add() {
      setBusy(true); setError('');
      try {
        const object = { id: crypto.randomUUID(), ...parseSequence(text) };
        const pkg = await host.createInput({ format: 'workbench.sequence', entry: 'manifest.json', files: {
          'manifest.json': new Blob([JSON.stringify({ objects: [object] })], { type: 'application/json' }),
        } });
        await host.addNode({ type: 'workbench.predict', parameters: {}, inputs: { sequence: [pkg.id] }, tools: {}, tool_parameters: {} });
      } catch (failure) { setError(String(failure)); }
      finally { setBusy(false); }
    }
    return h('section', null, h('h3', null, 'Predict a protein structure'),
      h('label', null, 'Single sequence or FASTA', h('textarea', { value: text, disabled: host.readOnly || busy, onChange: event => setText(event.target.value) })),
      h('label', null, 'Import sequence file', h('input', { type: 'file', accept: '.fasta,.fa,.faa,.txt', disabled: host.readOnly || busy,
        onChange: async event => {
          const file = event.target.files?.[0];
          if (!file) return;
          try { setText(await file.text()); setError(''); } catch (failure) { setError(String(failure)); }
        } })),
      h('button', { disabled: host.readOnly || busy, onClick: add }, busy ? 'Adding…' : 'Add sequence and prediction node'),
      h('p', null, 'Choose a prediction tool and its parameters on the node.'),
      error && h('p', { role: 'alert' }, error));
  }
  function PredictionViewer({ package: pkg, host }) {
    const [manifest, setManifest] = React.useState(null);
    const [confidence, setConfidence] = React.useState(null);
    const [fileKey, setFileKey] = React.useState(pkg.entry);
    const [fileText, setFileText] = React.useState('Loading…');
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true;
      setManifest(null); setConfidence(null); setError(''); setFileKey(pkg.entry);
      async function load() {
        const value = JSON.parse(await (await host.readFile(pkg.id, pkg.entry)).text());
        if (!active) return;
        setManifest(value);
        const object = value.objects?.[0];
        if (object?.structure?.file) setFileKey(object.structure.file);
        if (object?.confidence?.plddt?.file) {
          const result = JSON.parse(await (await host.readFile(pkg.id, object.confidence.plddt.file)).text());
          if (active) setConfidence(result);
        }
      }
      load().catch(failure => { if (active) setError(String(failure)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    React.useEffect(() => {
      let active = true; setFileText('Loading…');
      host.readFile(pkg.id, fileKey).then(blob => blob.text()).then(text => { if (active) setFileText(text); }).catch(failure => { if (active) setFileText(String(failure)); });
      return () => { active = false; };
    }, [pkg.id, fileKey, host.readFile]);
    return h('section', null,
      error && h('p', { role: 'alert' }, error),
      manifest && h('div', null, h('h4', null, 'Sequence and result manifest'), h('pre', null, JSON.stringify(manifest, null, 2))),
      confidence && h('div', null, h('h4', null, 'Confidence'), h('pre', null, JSON.stringify(confidence, null, 2))),
      h('label', null, 'Package file', h('select', { value: fileKey, onChange: event => setFileKey(event.target.value) }, pkg.files.map(key => h('option', { key, value: key }, key)))),
      h('pre', { 'aria-label': 'Package file contents' }, fileText));
  }
  return {
    actions: [{ id: 'workbench.prediction.sequence', name: 'Predict a protein structure', component: SequenceInput }],
    viewers: [{ id: 'workbench.prediction.files', name: 'Sequence, structure and confidence', formats: ['workbench.sequence', 'workbench.prediction'], component: PredictionViewer }],
  };
}
