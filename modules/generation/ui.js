export const runtime = { react: 19 };
function registerSequence({ React }) {
  const h = React.createElement;
  function Editor({ parameters, onChange, onDraftChange, readOnly }) {
    const acceptedText = JSON.stringify(parameters.conditions ?? {}, null, 2);
    const [text, setText] = React.useState(acceptedText);
    const [error, setError] = React.useState('');
    const textarea = React.useRef(null);
    React.useEffect(() => { setText(acceptedText); setError(''); textarea.current?.setCustomValidity(''); }, [acceptedText]);
    function changeConditions(event) {
      const control = event.currentTarget, value = control.value;
      setText(value);
      let conditions;
      try {
        conditions = JSON.parse(value);
        if (!conditions || typeof conditions !== 'object' || Array.isArray(conditions)) throw Error('Conditions must be an object');
      } catch (failure) {
        const message = String(failure);
        control.setCustomValidity(message); setError(message); onDraftChange?.(); return;
      }
      control.setCustomValidity(''); setError(''); onChange({ ...parameters, conditions });
    }
    return h('section', null,
      h('label', null, 'Samples per input', h('input', { type: 'number', min: 1, value: parameters.samples ?? 1, disabled: readOnly, onChange: event => onChange({ ...parameters, samples: Number(event.target.value) }) })),
      h('p', null, 'Fixed residues and coordinate conditions come from the selected current editing package. Each sample uses the configured local seed literally; change it to obtain a different local sample. Biohub has no seed control.'),
      h('label', null, 'Additional aligned conditions (JSON): secondary_structure, sasa, function_annotations', h('textarea', { ref: textarea, value: text, disabled: readOnly, onChange: changeConditions })),
      error && h('p', { role: 'alert' }, error));
  }
  function Viewer({ package: pkg, host }) {
    const [document, setDocument] = React.useState(null), [error, setError] = React.useState('');
    const [values, setValues] = React.useState(null), [selected, setSelected] = React.useState(0);
    React.useEffect(() => { let active = true; setDocument(null); setValues(null); setError(''); setSelected(0); host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => { if (active) setDocument(JSON.parse(text)); }).catch(failure => { if (active) setError(String(failure)); }); return () => { active = false; }; }, [pkg.id, pkg.entry, host.readFile]);
    React.useEffect(() => { let active = true; setValues(null); const object = document?.objects[selected]; if (object) host.readFile(pkg.id, object.native.file).then(blob => blob.text()).then(text => { if (active) setValues(JSON.parse(text)); }).catch(failure => { if (active) setError(String(failure)); }); return () => { active = false; }; }, [document, selected, pkg.id, host.readFile]);
    return h('section', null, error && h('p', { role: 'alert' }, error), document && h(React.Fragment, null,
      h('p', null, `${document.batch.completed}/${document.batch.total} completed; ${document.batch.status}`),
      h('label', null, 'Generated object', h('select', { value: selected, onChange: event => setSelected(Number(event.target.value)) }, document.objects.map((object, index) => h('option', { key: object.id, value: index }, `${index + 1}: ${object.sequence}`)))),
      h('pre', null, document.objects[selected].sequence),
      h('details', null, h('summary', null, 'Current conditions, position correspondence and actual tool parameters'), h('pre', null, JSON.stringify(document.objects[selected], null, 2))),
      values && h('details', null, h('summary', null, 'Native tracks and natural metrics'), h('pre', null, JSON.stringify(values, null, 2)))));
  }
  return { editors: [{ node: 'workbench.complete_sequence', component: Editor }], viewers: [{ id: 'workbench.esm3.generated', name: 'ESM3 generated sequences and native values', formats: ['workbench.esm3_generation'], component: Viewer }] };
}

function registerJoint({ React }) {
  const h = React.createElement;
  function JsonControl({ name, label, parameters, onChange, onDraftChange, readOnly }) {
    const accepted = JSON.stringify(parameters[name] ?? {}, null, 2);
    const [text, setText] = React.useState(accepted), [error, setError] = React.useState('');
    const ref = React.useRef(null);
    React.useEffect(() => { setText(accepted); setError(''); ref.current?.setCustomValidity(''); }, [accepted]);
    function change(event) {
      const control = event.currentTarget, value = control.value;
      setText(value);
      let parsed;
      try {
        parsed = JSON.parse(value);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw Error('Enter a JSON object');
      } catch (failure) {
        const message = String(failure);
        control.setCustomValidity(message); setError(message); onDraftChange?.(); return;
      }
      control.setCustomValidity(''); setError(''); onChange({ ...parameters, [name]: parsed });
    }
    return h('label', null, label, h('textarea', { ref, value: text, disabled: readOnly, onChange: change }), error && h('span', { role: 'alert' }, error));
  }
  function Editor(props) {
    const { parameters, onChange, readOnly } = props;
    return h('section', null,
      h('p', null, 'ESM3 first completes the sequence, then generates structure from that accepted sequence and the original current conditions. These are two dependent generate calls. A structure failure preserves its successful sequence for Continue.'),
      h('label', null, 'Samples per input', h('input', { type: 'number', min: 1, value: parameters.samples ?? 1, disabled: readOnly, onChange: event => onChange({ ...parameters, samples: Number(event.target.value) }) })),
      h('p', null, 'Select current sequence conditions for Prompt, fixed/variable positions and named atom coordinates. Unsupported atoms or conditions stop the operation. Tool controls apply to both phases; explicit structure overrides below apply only to the second call. Local seed is used literally, including 0. Biohub accepts no seed.'),
      h(JsonControl, { ...props, name: 'conditions', label: 'Aligned conditions (JSON): secondary_structure, sasa, function_annotations, potential_sequence_of_concern' }),
      h(JsonControl, { ...props, name: 'structure_parameters', label: 'Structure phase ESM3 control overrides (JSON; empty uses selected tool controls)' }));
  }
  function Coordinates({ coordinates }) {
    const points = Array.isArray(coordinates) ? coordinates.flatMap(row => Array.isArray(row) ? row.filter(point => Array.isArray(point) && point.length === 3 && point.every(value => typeof value === 'number' && Number.isFinite(value))) : []) : [];
    if (!points.length) return h('p', null, 'No finite atom coordinates in this phase.');
    let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
    for (const point of points) { xmin = Math.min(xmin, point[0]); xmax = Math.max(xmax, point[0]); ymin = Math.min(ymin, point[1]); ymax = Math.max(ymax, point[1]); }
    const scale = 260 / Math.max(xmax - xmin, ymax - ymin, 1);
    return h('figure', null,
      h('svg', { viewBox: '0 0 300 300', width: 300, height: 300, role: 'img', 'aria-label': 'Actual native atom37 coordinates, XY view' }, points.map((point, index) => h('circle', { key: index, cx: 20 + (point[0] - xmin) * scale, cy: 280 - (point[1] - ymin) * scale, r: 2, fill: '#1976b6' }, h('title', null, point.join(', '))))),
      h('figcaption', null, `${points.length} finite native atoms; XY view in Å. Missing atoms remain absent.`));
  }
  function Viewer({ package: pkg, host }) {
    const [loaded, setLoaded] = React.useState(null), [loadedValues, setLoadedValues] = React.useState(null), [error, setError] = React.useState('');
    const [selected, setSelected] = React.useState(0), [phase, setPhase] = React.useState('structure');
    const document = loaded?.id === pkg.id && loaded.entry === pkg.entry ? loaded.document : null;
    React.useEffect(() => { let active = true; setLoaded(null); setLoadedValues(null); setError(''); setSelected(0); setPhase('structure'); host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => { if (active) setLoaded({ id: pkg.id, entry: pkg.entry, document: JSON.parse(text) }); }).catch(failure => { if (active) setError(String(failure)); }); return () => { active = false; }; }, [pkg.id, pkg.entry, host.readFile]);
    const objects = document ? [...document.objects, ...(document.pending_sequence ? [document.pending_sequence] : [])] : [];
    const sample = objects[selected];
    const pending = sample && document?.pending_sequence?.id === sample.id;
    const object = sample?.sequence_stage && phase === 'sequence' ? sample.sequence_stage : sample;
    const nativeFile = object?.native.file;
    const values = loadedValues?.id === pkg.id && loadedValues.file === nativeFile ? loadedValues.document : null;
    React.useEffect(() => { let active = true; setLoadedValues(null); if (nativeFile) host.readFile(pkg.id, nativeFile).then(blob => blob.text()).then(text => { if (active) setLoadedValues({ id: pkg.id, file: nativeFile, document: JSON.parse(text) }); }).catch(failure => { if (active) setError(String(failure)); }); return () => { active = false; }; }, [nativeFile, pkg.id, host.readFile]);
    return h('section', null, error && h('p', { role: 'alert' }, error), document && h(React.Fragment, null,
      h('p', null, `${document.batch.completed}/${document.batch.total} completed; ${document.batch.status}`),
      h('p', null, `${document.batch.sequence_completed} sequence phases accepted`),
      h('label', null, 'Sample', h('select', { value: selected, onChange: event => setSelected(Number(event.target.value)) }, objects.map((obj, index) => h('option', { key: obj.id, value: index }, `${index + 1}: ${obj.sequence}`)))),
      pending ? h('p', null, 'sequence accepted; structure pending') : sample && h('label', null, 'Phase', h('select', { value: phase, onChange: event => setPhase(event.target.value) }, h('option', { value: 'structure' }, 'Structure'), h('option', { value: 'sequence' }, 'Sequence'))),
      object && h(React.Fragment, null,
        h('pre', null, object.sequence),
        h('details', null, h('summary', null, 'Current conditions, position correspondence and actual controls'), h('pre', null, JSON.stringify({ positions: object.positions, generation: object.generation, tool: object.tool }, null, 2))),
        values && h(React.Fragment, null, h(Coordinates, { coordinates: values.tracks.coordinates }), h('details', null, h('summary', null, 'Natural metrics with native axes and scale'), h('pre', null, JSON.stringify(values.metrics, null, 2)))),
        h('p', null, 'Use Select a joint generation phase for explicit downstream conversion. Native extended symbols and chains are retained; canonical chain conversion is a separate node. Use Convert a canonical joint structure to coordinates with explicit chain/start numbering for the existing structure viewer and PDB/mmCIF export.'))));
  }
  return { editors: [{ node: 'workbench.joint_generation', component: Editor }], viewers: [{ id: 'workbench.joint_generation.native', name: 'Joint generation phases and native structures', formats: ['workbench.joint_generation'], component: Viewer }] };
}

function registerBackbone({ React }) {
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

export function register(api) {
  const rows = [registerSequence(api), registerJoint(api), registerBackbone(api)];
  return { editors: rows.flatMap(row => row.editors), viewers: rows.flatMap(row => row.viewers) };
}
