export const runtime = { react: 19 };
export function register({ React }) {
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
        h('p', null, 'Use Select a joint generation phase for explicit downstream conversion. Native extended symbols and chains are retained; canonical chain conversion is a separate node.'))));
  }
  return { editors: [{ node: 'workbench.joint_generation', component: Editor }], viewers: [{ id: 'workbench.joint_generation.native', name: 'Joint generation phases and native structures', formats: ['workbench.joint_generation'], component: Viewer }] };
}
