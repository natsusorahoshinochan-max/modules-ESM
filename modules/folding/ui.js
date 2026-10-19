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

export function parseBatch(text) {
  const records = text.trim().split(/(?=^>)/m).filter(record => record.trim());
  if (!records.length || records.some(record => !record.trim().startsWith('>'))) throw new Error('Batch import requires FASTA records with headers.');
  return records.map(parseSequence);
}

function sequenceObjects(document) {
  if (!document || Object.keys(document).join() !== 'objects' || !Array.isArray(document.objects) || !document.objects.length) throw new Error('A nonempty sequence object batch is required.');
  const ids = new Set();
  for (const object of document.objects) {
    if (!object || typeof object !== 'object' || Object.keys(object).some(key => !['id', 'sequence', 'label', 'source', 'positions'].includes(key))) throw new Error('Unsupported sequence object components or conditions.');
    if (typeof object.id !== 'string' || !object.id || ids.has(object.id)) throw new Error('Sequence object IDs must be nonempty and unique.');
    ids.add(object.id);
    if (typeof object.sequence !== 'string' || !/^[ACDEFGHIKLMNPQRSTVWY]+$/.test(object.sequence)) throw new Error('Sequence requires the 20 standard amino acid letters.');
    if ('label' in object && typeof object.label !== 'string') throw new Error('Sequence label must be text.');
    if ('source' in object && (!object.source || Array.isArray(object.source) || typeof object.source !== 'object' || !Object.keys(object.source).length || Object.entries(object.source).some(([key, value]) => !['name', 'record', 'text'].includes(key) || typeof value !== 'string'))) throw new Error('Source requires explicit name, record or text fields.');
    if ('positions' in object) {
      if (!Array.isArray(object.positions) || object.positions.length !== object.sequence.length) throw new Error('Positions must cover every sequence residue.');
      const seen = new Set();
      object.positions.forEach((position, index) => {
        if (!position || Object.keys(position).some(key => !['sequence_index', 'chain', 'author_number', 'insertion_code'].includes(key)) || position.sequence_index !== index + 1) throw new Error('Positions require ordered one-based sequence_index values.');
        if (Object.keys(position).length > 1) {
          if (Object.keys(position).length !== 4 || typeof position.chain !== 'string' || !Number.isSafeInteger(position.author_number) || typeof position.insertion_code !== 'string') throw new Error('Residue correspondence requires explicit chain, author_number and insertion_code.');
          const key = JSON.stringify([position.chain, position.author_number, position.insertion_code]);
          if (seen.has(key)) throw new Error('Repeated residue correspondence.');
          seen.add(key);
        }
      });
    }
  }
  return document.objects;
}

export function sequenceInput(text, { batch = false, name, json = false } = {}) {
  const objects = json ? sequenceObjects(JSON.parse(text)) : (batch ? parseBatch(text) : [parseSequence(text)]).map(object => ({
    id: crypto.randomUUID(), ...object,
    source: { ...(name ? { name } : {}), ...(object.label ? { record: object.label } : {}), text },
    positions: Array.from(object.sequence, (_, index) => ({ sequence_index: index + 1 })),
  }));
  return { format: 'workbench.sequence', entry: 'manifest.json', files: {
    'manifest.json': new Blob([JSON.stringify({ objects })], { type: 'application/json' }),
  } };
}

function predictionDocument(text) {
  const document = JSON.parse(text);
  if (!document || Object.keys(document).some(key => !['objects', 'tool'].includes(key)) || !document.tool || typeof document.tool.id !== 'string' || !document.tool.id || !document.tool.parameters || Array.isArray(document.tool.parameters) || typeof document.tool.parameters !== 'object') throw new Error('Prediction result requires the actual tool id and existing parameters.');
  if (!Array.isArray(document.objects) || !document.objects.length) throw new Error('Prediction result requires sequence objects.');
  sequenceObjects({ objects: document.objects.map(object => {
    if (!object || typeof object !== 'object' || Array.isArray(object)) throw new Error('Each prediction requires a sequence object.');
    return { id: object.id, sequence: object.sequence, ...('label' in object ? { label: object.label } : {}) };
  }) });
  const files = new Set();
  function file(key) {
    if (typeof key !== 'string' || !key || key === 'manifest.json') throw new Error('Result references require explicit file keys distinct from manifest.json.');
    files.add(key);
  }
  for (const object of document.objects) {
    if (Object.keys(object).some(key => !['id', 'sequence', 'label', 'input', 'structure', 'confidence', 'supplementary'].includes(key))) throw new Error('Unsupported prediction result fields.');
    if ('input' in object) {
      sequenceObjects({ objects: [object.input] });
      if (object.input.sequence !== object.sequence) throw new Error('Supplied input sequence and prediction sequence disagree.');
    }
    if (!object.structure || !['pdb', 'mmcif'].includes(object.structure.format)) throw new Error('Each prediction requires a PDB or mmCIF structure.');
    file(object.structure.file);
    if ('confidence' in object) {
      const confidence = object.confidence;
      if (!confidence || Object.keys(confidence).some(key => !['plddt', 'ptm'].includes(key))) throw new Error('Unsupported prediction confidence.');
      if ('plddt' in confidence) {
        if (confidence.plddt?.scale !== '0-1') throw new Error('Prediction pLDDT requires its declared 0-1 scale.');
        file(confidence.plddt.file);
      }
      if ('ptm' in confidence && (typeof confidence.ptm !== 'number' || !Number.isFinite(confidence.ptm) || confidence.ptm < 0 || confidence.ptm > 1)) throw new Error('Prediction pTM must be a finite 0-1 value.');
    }
    if ('supplementary' in object) file(object.supplementary?.file);
  }
  return { document, keys: [...files] };
}

export async function predictionInput(text, bindings) {
  const { document, keys } = predictionDocument(text);
  const files = Object.create(null);
  for (const key of keys) {
    const blob = Object.hasOwn(bindings, key) && bindings[key];
    if (!(blob instanceof Blob) || !blob.size) throw new Error(`Select the required file for ${key}.`);
    files[key] = blob;
  }
  for (const object of document.objects) {
    if (object.confidence?.plddt) {
      const { plddt } = JSON.parse(await files[object.confidence.plddt.file].text());
      if (!Array.isArray(plddt) || plddt.length !== object.sequence.length || plddt.some(value => typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1)) throw new Error('Prediction pLDDT must contain one finite 0-1 value per sequence residue.');
    }
    if (object.supplementary) JSON.parse(await files[object.supplementary.file].text());
  }
  files['manifest.json'] = new Blob([text], { type: 'application/json' });
  return { format: 'workbench.prediction', entry: 'manifest.json', files };
}

export function register({ React }) {
  const h = React.createElement;
  function SequenceInput({ host }) {
    const [{ text, name }, setDraft] = React.useState({ text: '', name: '' });
    const [batch, setBatch] = React.useState(false);
    const [json, setJson] = React.useState(false);
    const [error, setError] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const [reading, setReading] = React.useState(false);
    const pendingRead = React.useRef(null);
    const latestHost = React.useRef(host);
    latestHost.current = host;
    function invalidateRead() {
      pendingRead.current = null;
      setReading(false);
    }
    React.useEffect(() => {
      invalidateRead();
      return () => { pendingRead.current = null; };
    }, [host]);
    function currentRead(request) {
      return pendingRead.current === request && latestHost.current === request.host && !request.host.readOnly;
    }
    async function select(event) {
      invalidateRead();
      const file = event.target.files?.[0];
      if (!file) return;
      const request = { host };
      pendingRead.current = request;
      setReading(true); setError('');
      try {
        const value = await file.text();
        if (!currentRead(request)) return;
        setDraft({ text: value, name: file.name }); setError('');
      } catch (failure) {
        if (currentRead(request)) setError(String(failure));
      } finally {
        if (currentRead(request)) invalidateRead();
      }
    }
    async function add() {
      if (pendingRead.current || host.readOnly || busy) return;
      setBusy(true); setError('');
      try {
        const pkg = await host.createInput(sequenceInput(text, { batch, name, json }));
        await host.addNode({ type: 'workbench.predict', parameters: {}, inputs: { sequence: [pkg.id] }, tools: {}, tool_parameters: {} });
      } catch (failure) { setError(String(failure)); }
      finally { setBusy(false); }
    }
    return h('section', null, h('h3', null, 'Predict a protein structure'),
      h('label', null, 'Input format', h('select', { 'aria-label': 'Sequence input format', value: json ? 'json' : 'fasta', disabled: host.readOnly || busy, onChange: event => { invalidateRead(); setJson(event.target.value === 'json'); setError(''); } }, h('option', { value: 'fasta' }, 'Sequence or FASTA'), h('option', { value: 'json' }, 'Sequence JSON with explicit correspondence'))),
      !json && h('label', null, h('input', { type: 'checkbox', 'aria-label': 'Batch FASTA import', checked: batch, disabled: host.readOnly || busy, onChange: event => { invalidateRead(); setBatch(event.target.checked); setError(''); } }), 'Batch FASTA import'),
      h('label', null, json ? 'Sequence JSON' : batch ? 'Batch FASTA records' : 'Single sequence or FASTA', h('textarea', { value: text, disabled: host.readOnly || busy, onChange: event => { invalidateRead(); setDraft({ text: event.target.value, name: '' }); setError(''); } })),
      h('label', null, 'Import sequence file', h('input', { type: 'file', accept: json ? '.json' : '.fasta,.fa,.faa,.txt', disabled: host.readOnly || busy,
        onChange: select })),
      h('button', { disabled: host.readOnly || busy || reading, onClick: add }, busy ? 'Adding…' : 'Add sequence and prediction node'),
      h('p', null, 'Choose a prediction tool and its parameters on the node.'),
      error && h('p', { role: 'alert' }, error));
  }
  function PredictionInput({ host }) {
    const [text, setText] = React.useState('');
    const [keys, setKeys] = React.useState([]);
    const [bindings, setBindings] = React.useState({});
    const [error, setError] = React.useState('');
    const [status, setStatus] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const generation = React.useRef(0);
    React.useEffect(() => () => { generation.current++; }, []);
    async function select(event) {
      const request = ++generation.current;
      setText(''); setKeys([]); setBindings({}); setError(''); setStatus('');
      const file = event.target.files?.[0];
      if (!file) return;
      try {
        const value = await file.text();
        const { keys } = predictionDocument(value);
        if (generation.current !== request) return;
        setText(value); setKeys(keys);
      } catch (failure) { if (generation.current === request) setError(String(failure)); }
    }
    async function add() {
      setBusy(true); setError(''); setStatus('');
      try {
        const input = await predictionInput(text, bindings);
        await host.createInput(input);
        setStatus('Imported prediction results. Select this package as a canvas input or view and download it in Data packages.');
      } catch (failure) { setError(String(failure)); }
      finally { setBusy(false); }
    }
    return h('section', null, h('h3', null, 'Import existing prediction results'),
      h('p', null, 'Select a workbench.prediction manifest, then explicitly bind every named structure, confidence and supplementary file. Existing object identities, correspondence, numeric results and tool parameters are preserved.'),
      h('label', null, 'Prediction result manifest', h('input', { type: 'file', accept: '.json', 'aria-label': 'Prediction result manifest', disabled: host.readOnly || busy, onChange: select })),
      ...keys.map(key => h('label', { key }, key, h('input', { type: 'file', 'aria-label': `File for ${key}`, disabled: host.readOnly || busy, onChange: event => { const file = event.target.files?.[0]; setBindings(current => ({ ...current, [key]: file })); setError(''); setStatus(''); } }))),
      h('button', { disabled: host.readOnly || busy || !text, onClick: add }, busy ? 'Importing…' : 'Import prediction results'),
      status && h('p', { role: 'status' }, status), error && h('p', { role: 'alert' }, error));
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
    actions: [{ id: 'workbench.prediction.sequence', name: 'Predict a protein structure', component: SequenceInput }, { id: 'workbench.prediction.import', name: 'Import existing prediction results', component: PredictionInput }],
    viewers: [{ id: 'workbench.prediction.files', name: 'Sequence, structure and confidence', formats: ['workbench.sequence', 'workbench.prediction'], component: PredictionViewer }],
  };
}
