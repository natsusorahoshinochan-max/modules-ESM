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
  function Parameters({ parameters, onChange, readOnly }) {
    return h('label', null, 'Node parameters (JSON)', h('textarea', { defaultValue: JSON.stringify(parameters), disabled: readOnly,
      onBlur: event => { try { onChange(JSON.parse(event.target.value)); } catch { event.target.setCustomValidity('Enter a JSON object'); event.target.reportValidity(); } } }));
  }
  return {
    actions: [{ id: 'example.new-note', name: 'New note', component: NoteInput }],
    editors: [{ node: 'example.uppercase', component: Parameters }],
    viewers: [{ id: 'example.note-text', name: 'Note text', formats: ['example.note'], component: NoteViewer }],
  };
}
