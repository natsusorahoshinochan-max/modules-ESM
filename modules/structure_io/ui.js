/** Complete coordinate-file UI using only public React and package file access. */
export const runtime = { react: 19 };
export function register({ React }) {
  const h = React.createElement;
  function Import({ host }) {
    const [file, setFile] = React.useState(null), [model, setModel] = React.useState('all');
    const [error, setError] = React.useState(''), [busy, setBusy] = React.useState(false);
    async function add() {
      if (host.readOnly || busy) return;
      setBusy(true); setError('');
      try {
        const format = /\.pdb$/i.test(file?.name || '') ? 'pdb' : /\.(cif|mmcif)$/i.test(file?.name || '') ? 'mmcif' : null;
        if (!format) throw new Error('Select exactly one PDB or mmCIF structure file.');
        const models = model === 'all' ? 'all' : Number(model);
        if (models !== 'all' && (!model.trim() || !Number.isSafeInteger(models))) throw new Error('Enter an actual model number or all.');
        const pkg = await host.createInput({ format: 'workbench.structure_file', entry: 'manifest.json', files: {
          'manifest.json': new Blob([JSON.stringify({ name: file.name, file: 'original', format })]), original: file,
        } });
        await host.addNode({ type: 'workbench.import_structure', inputs: { file: [pkg.id] }, parameters: { models } });
        setError('Run the import node to view the selected independent candidates.');
      } catch (failure) { setError(String(failure)); }
      finally { setBusy(false); }
    }
    return h('section', null, h('h3', null, 'Import one complete structure file'),
      h('label', null, 'PDB or mmCIF', h('input', { type: 'file', accept: '.pdb,.cif,.mmcif', disabled: host.readOnly || busy, onChange: e => { setFile(e.target.files?.length === 1 ? e.target.files[0] : null); setError(''); } })),
      h('label', null, 'Actual model number, or all independent candidates', h('input', { 'aria-label': 'Conformation selection', value: model, disabled: host.readOnly || busy, onChange: e => setModel(e.target.value) })),
      h('button', { disabled: host.readOnly || busy || !file, onClick: add }, 'Add structure import node'),
      error && h('p', { role: 'status' }, error));
  }
  function Viewer({ package: pkg, host }) {
    const [data, setData] = React.useState(null), [object, setObject] = React.useState('');
    const [atoms, setAtoms] = React.useState([]), [selected, setSelected] = React.useState([]);
    const [angle, setAngle] = React.useState(0), [tilt, setTilt] = React.useState(0), [format, setFormat] = React.useState('mmcif');
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true; setData(null); setObject(''); setAtoms([]); setSelected([]); setError('');
      host.readFile(pkg.id, pkg.entry).then(b => b.text()).then(JSON.parse).then(d => { if (active) { setData(d); setObject(d.objects[0].id); } }).catch(e => { if (active) setError(String(e)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    React.useEffect(() => {
      let active = true; setAtoms([]); setSelected([]);
      const obj = data?.objects.find(o => o.id === object);
      if (obj) host.readFile(pkg.id, obj.atoms).then(b => b.text()).then(JSON.parse).then(a => { if (active) setAtoms(a); }).catch(e => { if (active) setError(String(e)); });
      return () => { active = false; };
    }, [data, object, pkg.id, host.readFile]);
    function toggle(index) { setSelected(s => s.includes(index) ? s.filter(i => i !== index) : [...s, index]); }
    async function exportSelection() {
      try {
        await host.addNode({ type: 'workbench.export_structure', inputs: { structures: [pkg.id] }, parameters: { object, format, ...(selected.length ? { atoms: selected } : {}) } });
        setError('Run the export node, then download its ZIP from Data packages. Existing parameters describe the source calculation; selection is not recalculated.');
      } catch (failure) { setError(String(failure)); }
    }
    const limits = [0, 1, 2].map(axis => atoms.reduce(([lo, hi], a) => [Math.min(lo, a.position[axis]), Math.max(hi, a.position[axis])], [Infinity, -Infinity]));
    const center = limits.map(([lo, hi]) => (lo + hi) / 2), span = Math.max(1, Math.hypot(...limits.map(([lo, hi]) => hi - lo)));
    const yaw = angle * Math.PI / 180, pitch = tilt * Math.PI / 180;
    const projected = atoms.map(a => {
      const [x, y, z] = a.position.map((p, i) => p - center[i]);
      const rx = x * Math.cos(yaw) + z * Math.sin(yaw), rz = z * Math.cos(yaw) - x * Math.sin(yaw);
      return { a, x: 300 + rx * 400 / span, y: 220 - (y * Math.cos(pitch) - rz * Math.sin(pitch)) * 400 / span, z: y * Math.sin(pitch) + rz * Math.cos(pitch) };
    }).sort((a, b) => a.z - b.z);
    const components = [...new Set(atoms.map(a => JSON.stringify([a.chain, a.author_number, a.insertion_code, a.residue_name])))];
    return h('section', null, h('h3', null, 'Complete structure and components'),
      data && h('select', { 'aria-label': 'Structure candidate', value: object, onChange: e => setObject(e.target.value) }, data.objects.map(o => h('option', { key: o.id, value: o.id }, o.label || o.id))),
      h('label', null, 'Rotation', h('input', { type: 'range', min: -180, max: 180, value: angle, 'aria-label': 'Structure rotation', onChange: e => setAngle(Number(e.target.value)) })),
      h('label', null, 'Tilt', h('input', { type: 'range', min: -90, max: 90, value: tilt, 'aria-label': 'Structure tilt', onChange: e => setTilt(Number(e.target.value)) })),
      h('svg', { viewBox: '0 0 600 440', role: 'img', 'aria-label': 'Complete structure atoms', style: { width: '100%', maxWidth: 800, background: '#edf3fa' } }, projected.map(({ a, x, y }) => h('circle', {
        key: a.index, cx: x, cy: y, r: selected.includes(a.index) ? 6 : 4, fill: selected.includes(a.index) ? '#e65c00' : '#2563aa', tabIndex: 0,
        'aria-label': `${a.model}: ${a.chain} ${a.author_number}${a.insertion_code} ${a.residue_name} ${a.atom_name} ${a.altloc}`,
        onClick: () => toggle(a.index), onKeyDown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(a.index); } },
      }, h('title', null, `${a.residue_name} ${a.atom_name}: ${a.position.join(', ')} Å`)))),
      h('p', null, `${atoms.length} atoms; ${selected.length} selected. No selection exports the complete candidate.`),
      h('button', { onClick: () => setSelected([]) }, 'Clear selection'),
      h('details', null, h('summary', null, 'Select residues and components'), components.map(key => {
        const [chain, number, insertion, name] = JSON.parse(key);
        const indices = atoms.filter(a => a.chain === chain && a.author_number === number && a.insertion_code === insertion && a.residue_name === name).map(a => a.index);
        return h('label', { key, style: { display: 'block' } }, h('input', { type: 'checkbox', checked: indices.every(i => selected.includes(i)), onChange: e => setSelected(s => e.target.checked ? [...new Set([...s, ...indices])] : s.filter(i => !indices.includes(i))) }), `${chain} ${number}${insertion} ${name}`);
      })),
      h('select', { 'aria-label': 'Export structure format', value: format, onChange: e => setFormat(e.target.value) }, h('option', { value: 'mmcif' }, 'mmCIF'), h('option', { value: 'pdb' }, 'PDB')),
      h('button', { disabled: host.readOnly || !atoms.length, onClick: exportSelection }, 'Add selected structure export node'),
      error && h('p', { role: 'status' }, error));
  }
  return { actions: [{ id: 'workbench.structure_io.import', name: 'Import PDB or mmCIF structure', component: Import }], viewers: [{ id: 'workbench.structure_io.complete', name: 'Complete structure and components', formats: ['workbench.structure_set'], component: Viewer }] };
}
