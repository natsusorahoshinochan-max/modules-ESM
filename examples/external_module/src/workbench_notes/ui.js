/** Public React module entry. All React calls use the supplied host runtime. */
export const runtime = { react: 19 };
export function register({ React }) {
  const h = React.createElement;
  function NoteInput({ host }) {
    const [text, setText] = React.useState('hello');
    const [error, setError] = React.useState('');
    async function add() {
      try {
        const pkg = await host.createInput({ format: 'example.note', entry: 'text', files: { text: new Blob([text], { type: 'text/plain' }) } });
        await host.addNode({ type: 'example.uppercase', parameters: {}, inputs: { note: [pkg.id] } });
        setError('');
      } catch (failure) { setError(String(failure)); }
    }
    return h('section', null, h('h3', null, 'New note'),
      h('textarea', { 'aria-label': 'Note text', value: text, onChange: event => setText(event.target.value) }),
      h('button', { onClick: add, disabled: host.readOnly }, 'Add note input and uppercase node'),
      error && h('p', { role: 'alert' }, error));
  }
  function NoteViewer({ package: pkg, host }) {
    const [text, setText] = React.useState('Loading…');
    React.useEffect(() => { let active = true; host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(value => { if (active) setText(value); }).catch(error => { if (active) setText(String(error)); }); return () => { active = false; }; }, [pkg.id]);
    return h('pre', null, text);
  }
  function Parameters({ parameters, onChange, onDraftChange, readOnly }) {
    const accepted = JSON.stringify(parameters);
    const [text, setText] = React.useState(accepted);
    const field = React.useRef(null);
    const previousAccepted = React.useRef(accepted);
    const submitted = React.useRef(null);
    React.useLayoutEffect(() => {
      if (previousAccepted.current === accepted) return;
      previousAccepted.current = accepted;
      // An acknowledgement must not replace formatting or a newer invalid edit.
      if (submitted.current === accepted) { submitted.current = null; return; }
      submitted.current = null;
      setText(accepted);
      field.current?.setCustomValidity('');
    }, [accepted]);
    function input(event) {
      if (readOnly) return;
      const value = event.currentTarget.value;
      setText(value);
      let parsed;
      try { parsed = JSON.parse(value); } catch { /* Invalid text stays in the local draft. */ }
      const valid = parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed);
      event.currentTarget.setCustomValidity(valid ? '' : 'Enter a JSON object');
      if (valid) {
        submitted.current = JSON.stringify(parsed);
        onChange(parsed);
      } else onDraftChange?.();
    }
    return h('label', null, 'Node parameters (JSON)', h('textarea', {
      ref: field, value: text, disabled: readOnly, onInput: input,
    }));
  }

  return {
    actions: [{ id: 'example.new-note', name: 'New note', component: NoteInput }],
    editors: [{ node: 'example.uppercase', component: Parameters }],
    viewers: [{ id: 'example.note-text', name: 'Note text', formats: ['example.note'], component: NoteViewer }],
  };
}
