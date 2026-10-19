export const runtime = { react: 19 };
export function register({ React }) {
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
