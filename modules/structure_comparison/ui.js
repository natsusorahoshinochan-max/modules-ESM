/** Self-contained comparison UI. React is supplied through the public runtime. */
export const runtime = { react: 19 };

export function register({ React }) {
  const h = React.createElement;
  const positionLabel = p => `${p.chain || '(blank chain)'} ${p.author_number}${p.insertion_code ? `:${p.insertion_code}` : ''}`;
  function Region({ side, selection, onChange, readOnly }) {
    const [scope, set范围] = React.useState(selection?.positions ? 'positions' : selection?.chains ? 'chain' : 'complete');
    const [chain, setChain] = React.useState(selection?.chains?.[0] ?? selection?.positions?.[0]?.chain ?? '');
    const [residues, setResidues] = React.useState(selection?.positions?.map(p => `${p.author_number}${p.insertion_code ? `:${p.insertion_code}` : ''}`).join(', ') || '');
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      set范围(selection?.positions ? 'positions' : selection?.chains ? 'chain' : 'complete');
      setChain(selection?.chains?.[0] ?? selection?.positions?.[0]?.chain ?? '');
      setResidues(selection?.positions?.map(p => `${p.author_number}${p.insertion_code ? `:${p.insertion_code}` : ''}`).join(', ') || '');
      setError('');
    }, [selection]);
    function apply() {
      if (readOnly) return;
      try {
        let next = null;
        if (scope === 'chain') next = { chains: [chain] };
        if (scope === 'positions') {
          const positions = residues.split(',').map(token => {
            const match = /^(-?\d+)(?:([A-Za-z])|:([^\s,:]))?$/.exec(token.trim());
            if (!match || !Number.isSafeInteger(Number(match[1]))) throw new Error('Enter each actual residue number and optional insertion code, for example 12, 12A, 16 or 12:1.');
            return { chain, author_number: Number(match[1]), insertion_code: match[2] || match[3] || '' };
          });
          if (new Set(positions.map(p => JSON.stringify(p))).size !== positions.length) throw new Error('Select each actual residue only once.');
          next = { positions };
        }
        onChange(next); setError('');
      } catch (failure) { setError(String(failure)); }
    }
    return h('fieldset', null, h('legend', null, `${side}范围`),
      h('label', null, '范围', h('select', { 'aria-label': `${side} scope`, value: scope, disabled: readOnly, onChange: e => { set范围(e.target.value); setError(''); } },
        h('option', { value: 'complete' }, '整体'), h('option', { value: 'chain' }, '单链'), h('option', { value: 'positions' }, '指定残基'))),
      scope !== 'complete' && h('label', null, '链', h('input', { 'aria-label': `${side} chain`, value: chain, disabled: readOnly, onChange: e => setChain(e.target.value) })),
      scope === 'positions' && h('label', null, '残基编号（如 12, 12A, 16）', h('input', { 'aria-label': `${side} residues`, value: residues, disabled: readOnly, onChange: e => setResidues(e.target.value) })),
      h('button', { 'aria-label': `采用${side}范围`, disabled: readOnly, onClick: apply }, `采用${side}范围`),
      h('p', null, selection?.positions ? `已选择： ${selection.positions.map(positionLabel).join(', ')}` : selection?.chains ? `链： ${selection.chains[0] || '(blank)'}` : '整体'),
      error && h('p', { role: 'alert' }, error));
  }
  function ComparisonEditor({ parameters, onChange, readOnly }) {
    return h('section', null,
      ...['subject', 'reference'].map(side => h(Region, { key: side, side: side === 'subject' ? '候选' : '参考', selection: parameters[`${side}_selection`], readOnly,
        onChange: selection => onChange({ ...parameters, [`${side}_selection`]: selection }) })));
  }
  function ComparisonViewer({ package: pkg, host }) {
    const [data, setData] = React.useState(null);
    const [error, setError] = React.useState('');
    const [yaw, setYaw] = React.useState(0);
    const [pitch, setPitch] = React.useState(0);
    const [visible, setVisible] = React.useState({ subject: true, reference: true });
    const [selected, setSelected] = React.useState(null);
    React.useEffect(() => {
      let active = true;
      setData(null); setError(''); setSelected(null);
      async function load() {
        const manifest = JSON.parse(await (await host.readFile(pkg.id, pkg.entry)).text());
        const overlay = JSON.parse(await (await host.readFile(pkg.id, manifest.overlay)).text());
        if (active) setData({ manifest, overlay });
      }
      load().catch(failure => { if (active) setError(String(failure)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    if (error) return h('p', { role: 'alert' }, error);
    if (!data) return h('p', null, '读取中…');
    const { manifest, overlay } = data;
    const all = [...overlay.subject, ...overlay.reference];
    const limits = [0, 1, 2].map(axis => {
      let low = Infinity, high = -Infinity;
      for (const atom of all) { low = Math.min(low, atom.position[axis]); high = Math.max(high, atom.position[axis]); }
      return [low, high];
    });
    const center = limits.map(([low, high]) => (low + high) / 2);
    const span = Math.max(1, Math.hypot(...limits.map(([low, high]) => high - low)));
    const angle = yaw * Math.PI / 180, tilt = pitch * Math.PI / 180;
    const project = atom => {
      const [x, y, z] = atom.position.map((value, axis) => value - center[axis]);
      const rx = x * Math.cos(angle) + z * Math.sin(angle);
      const rz = z * Math.cos(angle) - x * Math.sin(angle);
      return [300 + rx * 320 / span, 220 - (y * Math.cos(tilt) - rz * Math.sin(tilt)) * 320 / span,
        y * Math.sin(tilt) + rz * Math.cos(tilt)];
    };
    const plotted = ['subject', 'reference'].flatMap(side => visible[side] ? overlay[side].map((atom, index) => ({ atom, side, index, point: project(atom) })) : []).sort((a, b) => a.point[2] - b.point[2]);
    return h('section', null,
      h('h3', null, '结构叠合'),
      h('p', null, `${manifest.subject.label || '候选'} (blue) → ${manifest.reference.label || '参考'} (orange)`),

      ...['subject', 'reference'].map(side => h('p', { key: `region-${side}` }, `${side} region: ${manifest.region[side]?.positions ? manifest.region[side].positions.map(positionLabel).join(', ') : manifest.region[side]?.chains ? `chain ${manifest.region[side].chains[0] || '(blank)'}` : 'complete structure'}`)),
      h('dl', null,
        h('dt', null, `TM 候选 · 长度 ${manifest.metrics.tm_subject.normalization_length}`), h('dd', null, manifest.metrics.tm_subject.value.toFixed(6)),
        h('dt', null, `TM 参考 · 长度 ${manifest.metrics.tm_reference.normalization_length}`), h('dd', null, manifest.metrics.tm_reference.value.toFixed(6)),
        h('dt', null, `RMSD (Å) · ${manifest.metrics.rmsd.aligned_pair_count} 对残基`), h('dd', null, manifest.metrics.rmsd.value.toFixed(6))),

      ...['subject', 'reference'].map(side => h('label', { key: side },
        h('input', { type: 'checkbox', 'aria-label': `Show ${side}`, checked: visible[side], onChange: event => setVisible({ ...visible, [side]: event.target.checked }) }),
        `${side}: ${overlay[side].length} atoms (${overlay[side].filter(atom => atom.component === 'other').length} other-component atoms)`)),
      h('label', null, '旋转视角', h('input', { type: 'range', min: -180, max: 180, value: yaw, 'aria-label': 'Rotate around vertical axis', onChange: event => setYaw(Number(event.target.value)) })),
      h('label', null, '俯仰', h('input', { type: 'range', min: -90, max: 90, value: pitch, 'aria-label': '俯仰 around horizontal axis', onChange: event => setPitch(Number(event.target.value)) })),
      h('svg', { viewBox: '0 0 600 440', role: 'img', 'aria-label': '整体 atom overlay', style: { width: '100%', maxWidth: '800px', background: '#f4f7fb' } },
        plotted.map(({ atom, side, index, point }) => h('circle', { key: `${side}-${index}`, cx: point[0], cy: point[1], r: atom.component === 'other' ? 4 : 2.5,
          fill: side === 'subject' ? '#2266cc' : '#df6b16', opacity: 0.75, tabIndex: 0, 'data-residue': atom.residue_name,
          onClick: () => setSelected({ ...atom, side }), onKeyDown: event => { if (event.key === 'Enter') setSelected({ ...atom, side }); } },
        h('title', null, `${side}: ${atom.chain} ${atom.author_number}${atom.insertion_code} ${atom.residue_name} ${atom.atom_name}`)))),
      selected && h('p', { 'aria-label': 'Selected atom' }, `${selected.side}: chain ${selected.chain}, residue ${selected.author_number}${selected.insertion_code} ${selected.residue_name}, atom ${selected.atom_name} (${selected.element})`),
      h('details', null, h('summary', null, '对齐详情'), h('p',null,`${manifest.method.name} · ${manifest.method.algorithm} · tmtools ${manifest.method.tmtools}`), h('p',null,`候选 ${manifest.subject.label??''} · 参考 ${manifest.reference.label??''}`)));
  }
  return { editors: [{ node: 'workbench.compare', component: ComparisonEditor }, { node: 'workbench.compare_structure', component: ComparisonEditor }], viewers: [{ id: 'workbench.comparison.overlay', name: '整体 overlay', formats: ['workbench.comparison'], component: ComparisonViewer }] };
}
