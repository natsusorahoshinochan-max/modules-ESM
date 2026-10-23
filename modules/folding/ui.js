/** Prediction UI uses only the public host interface and supplied React 19. */
export const runtime = { react: 19 };

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
      const seen = new Set(), seenLabels = new Set();
      object.positions.forEach((position, index) => {
        if (!position || Object.keys(position).some(key => !['sequence_index', 'chain', 'author_number', 'insertion_code', 'label_position'].includes(key)) || position.sequence_index !== index + 1) throw new Error('Positions require ordered one-based sequence_index values.');
        const authorKeys = ['chain','author_number','insertion_code'];
        if (authorKeys.some(key=>key in position)) {
          if (!authorKeys.every(key=>key in position) || typeof position.chain !== 'string' || !Number.isSafeInteger(position.author_number) || typeof position.insertion_code !== 'string') throw new Error('Residue correspondence requires explicit chain, author_number and insertion_code.');
          const key = JSON.stringify([position.chain, position.author_number, position.insertion_code]);
          if (seen.has(key)) throw new Error('Repeated residue correspondence.');
          seen.add(key);
        }
        if ('label_position' in position) {
          const label=position.label_position;
          if (!label || Array.isArray(label) || Object.keys(label).length!==2 || typeof label.chain!=='string' || !label.chain || !Number.isSafeInteger(label.position) || label.position<1) throw new Error('Label correspondence requires chain and a positive one-based position.');
          const key=JSON.stringify([label.chain,label.position]);
          if(seenLabels.has(key))throw new Error('Repeated label correspondence.');
          seenLabels.add(key);
        }
      });
    }
  }
  return document.objects;
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
    const [exportObject, setExportObject] = React.useState('');
    const [exportFormat, setExportFormat] = React.useState('mmcif');
    const [fileText, setFileText] = React.useState('Loading…');
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true;
      setManifest(null); setConfidence(null); setError(''); setFileKey(pkg.entry);
      async function load() {
        const value = JSON.parse(await (await host.readFile(pkg.id, pkg.entry)).text());
        if (!active) return;
        setManifest(value);
        setExportObject(value.objects?.[0]?.id || '');
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
      pkg.format !== 'workbench.sequence' && manifest?.objects?.some(o => o.structure) && h('div', null,
        h('select', { 'aria-label': 'Export prediction object', value: exportObject, onChange: e => setExportObject(e.target.value) }, manifest.objects.map(o => h('option', { key: o.id, value: o.id }, o.label || o.id))),
        h('select', { 'aria-label': 'Export prediction format', value: exportFormat, onChange: e => setExportFormat(e.target.value) }, h('option', { value: 'mmcif' }, 'mmCIF'), h('option', { value: 'pdb' }, 'PDB')),
        h('button', { disabled: host.readOnly, onClick: async () => { try { await host.addNode({ type: 'workbench.export_structure', inputs: { structures: [pkg.id] }, parameters: { object: exportObject, format: exportFormat } }); } catch (failure) { setError(String(failure)); } } }, 'Add structure export node')),
      confidence && h('div', null, h('h4', null, 'Confidence'), h('pre', null, JSON.stringify(confidence, null, 2))),
      h('label', null, 'Package file', h('select', { value: fileKey, onChange: event => setFileKey(event.target.value) }, pkg.files.map(key => h('option', { key, value: key }, key)))),
      h('pre', { 'aria-label': 'Package file contents' }, fileText));
  }
  return {
    actions: [{ id: 'workbench.prediction.import', name: 'Import existing prediction results', component: PredictionInput }],
    viewers: [{ id: 'workbench.prediction.files', name: 'Sequence, structure and confidence', formats: ['workbench.prediction'], component: PredictionViewer }],
  };
}
