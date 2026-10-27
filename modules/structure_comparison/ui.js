const messages = {

  "label_94": {
    "zh-CN": "{0} 范围",
    "en": "{0} scope"
  },
  "label_95": {
    "zh-CN": "{0} 链",
    "en": "{0} chain"
  },
  "label_96": {
    "zh-CN": "{0} 残基",
    "en": "{0} residues"
  },
  "label_97": {
    "zh-CN": "{0}（蓝）→ {1}（橙）",
    "en": "{0} (blue) → {1} (orange)"
  },
  "label_98": {
    "zh-CN": "{0} 区域：{1}",
    "en": "{0} region: {1}"
  },
  "label_99": {
    "zh-CN": "显示 {0}",
    "en": "Show {0}"
  },
  "label_100": {
    "zh-CN": "{0}：链 {1}，残基 {2}{3} {4}，原子 {5}（{6}）",
    "en": "{0}: chain {1}, residue {2}{3} {4}, atom {5} ({6})"
  },
  "label_101": {
    "zh-CN": "{0} · {1} · tmtools {2}",
    "en": "{0} · {1} · tmtools {2}"
  }
,
  "blank_chain": {
    "zh-CN": "（空白链）",
    "en": "(blank chain)"
  },
  "enter_each_actual_residue_number_and_optional": {
    "zh-CN": "请输入残基编号及可选插入码，如 12、12A、16 或 12:1。",
    "en": "Enter each actual residue number and optional insertion code, for example 12, 12A, 16 or 12:1."
  },
  "select_each_actual_residue_only_once": {
    "zh-CN": "同一残基只能选择一次。",
    "en": "Select each actual residue only once."
  },
  "region": {
    "zh-CN": "{0}范围",
    "en": "{0} region"
  },
  "region_2": {
    "zh-CN": "范围",
    "en": "Region"
  },
  "whole": {
    "zh-CN": "整体",
    "en": "Whole"
  },
  "single_chain": {
    "zh-CN": "单链",
    "en": "Single chain"
  },
  "specific_residues": {
    "zh-CN": "指定残基",
    "en": "Specific residues"
  },
  "chain": {
    "zh-CN": "链",
    "en": "Chain"
  },
  "residue_numbers_e_g_12_12a_16": {
    "zh-CN": "残基编号（如 12, 12A, 16）",
    "en": "Residue numbers (e.g. 12, 12A, 16)"
  },
  "apply_region": {
    "zh-CN": "采用{0}范围",
    "en": "Apply {0} region"
  },
  "selected": {
    "zh-CN": "已选择： {0}",
    "en": "Selected: {0}"
  },
  "chain_2": {
    "zh-CN": "链： {0}",
    "en": "Chain: {0}"
  },
  "candidate": {
    "zh-CN": "候选",
    "en": "Candidate"
  },
  "reference": {
    "zh-CN": "参考",
    "en": "Reference"
  },
  "reading": {
    "zh-CN": "读取中…",
    "en": "Reading…"
  },
  "structure_overlay": {
    "zh-CN": "结构叠合",
    "en": "Structure overlay"
  },
  "complete_structure": {
    "zh-CN": "完整结构",
    "en": "complete structure"
  },
  "tm_subject_length": {
    "zh-CN": "TM 候选 · 长度 {0}",
    "en": "TM subject · Length {0}"
  },
  "tm_reference_length": {
    "zh-CN": "TM 参考 · 长度 {0}",
    "en": "TM reference · Length {0}"
  },
  "rmsd_residue_pairs": {
    "zh-CN": "RMSD (Å) · {0} 对残基",
    "en": "RMSD (Å) · {0} residue pairs"
  },
  "atoms_other_component_atoms": {
    "zh-CN": "{0}：{1} 个原子（{2} 个其他组分原子）",
    "en": "{0}: {1} atoms ({2} other-component atoms)"
  },
  "rotate_view": {
    "zh-CN": "旋转视角",
    "en": "Rotate view"
  },
  "rotate_around_vertical_axis": {
    "zh-CN": "绕垂直轴旋转",
    "en": "Rotate around vertical axis"
  },
  "tilt": {
    "zh-CN": "俯仰",
    "en": "Tilt"
  },
  "message": {
    "zh-CN": "俯仰 around horizontal axis",
    "en": "绕水平轴旋转"
  },
  "message_2": {
    "zh-CN": "整体 atom overlay",
    "en": "完整原子叠合"
  },
  "selected_atom": {
    "zh-CN": "所选原子",
    "en": "Selected atom"
  },
  "alignment_details": {
    "zh-CN": "对齐详情",
    "en": "Alignment details"
  },
  "subject_reference": {
    "zh-CN": "候选 {0} · 参考 {1}",
    "en": "Subject {0} · Reference {1}"
  },
  "complete_overlay": {
    "zh-CN": "整体 overlay",
    "en": "Complete overlay"
  }
};
/** Self-contained comparison UI. React is supplied through the public runtime. */
export const runtime = { react: 19 };

export function register({ React, i18n }) {
  const t = i18n.translator(messages);
  const h = React.createElement;
  const positionLabel = p => `${p.chain || t("blank_chain")} ${p.author_number}${p.insertion_code ? `:${p.insertion_code}` : ''}`;
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
            if (!match || !Number.isSafeInteger(Number(match[1]))) throw new Error(t("enter_each_actual_residue_number_and_optional"));
            return { chain, author_number: Number(match[1]), insertion_code: match[2] || match[3] || '' };
          });
          if (new Set(positions.map(p => JSON.stringify(p))).size !== positions.length) throw new Error(t("select_each_actual_residue_only_once"));
          next = { positions };
        }
        onChange(next); setError('');
      } catch (failure) { setError(i18n.error(failure)); }
    }
    return h('fieldset', null, h('legend', null, t("region", {"0": t(side==='subject'?'candidate':'reference')})),
      h('label', null, t("region_2"), h('select', { 'aria-label': t("label_94", {"0": t(side==='subject'?'candidate':'reference')}), value: scope, disabled: readOnly, onChange: e => { set范围(e.target.value); setError(''); } },
        h('option', { value: 'complete' }, t("whole")), h('option', { value: 'chain' }, t("single_chain")), h('option', { value: 'positions' }, t("specific_residues")))),
      scope !== 'complete' && h('label', null, t("chain"), h('input', { 'aria-label': t("label_95", {"0": t(side==='subject'?'candidate':'reference')}), value: chain, disabled: readOnly, onChange: e => setChain(e.target.value) })),
      scope === 'positions' && h('label', null, t("residue_numbers_e_g_12_12a_16"), h('input', { 'aria-label': t("label_96", {"0": t(side==='subject'?'candidate':'reference')}), value: residues, disabled: readOnly, onChange: e => setResidues(e.target.value) })),
      h('button', { 'aria-label': t("apply_region", {"0": t(side==='subject'?'candidate':'reference')}), disabled: readOnly, onClick: apply }, t("apply_region", {"0": t(side==='subject'?'candidate':'reference')})),
      h('p', null, selection?.positions ? t("selected", {"0": selection.positions.map(positionLabel).join(', ')}) : selection?.chains ? t("chain_2", {"0": selection.chains[0] || '(blank)'}) : t("whole")),
      error && h('p', { role: 'alert' }, error));
  }
  function ComparisonEditor({ parameters, onChange, readOnly }) {
    return h('section', null,
      ...['subject', 'reference'].map(side => h(Region, { key: side, side: side === 'subject' ? t("candidate") : t("reference"), selection: parameters[`${side}_selection`], readOnly,
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
      load().catch(failure => { if (active) setError(i18n.error(failure)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    if (error) return h('p', { role: 'alert' }, error);
    if (!data) return h('p', null, t("reading"));
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
      h('h3', null, t("structure_overlay")),
      h('p', null, t("label_97", {"0": manifest.subject.label || t("candidate"), "1": manifest.reference.label || t("reference")})),

      ...['subject', 'reference'].map(side => h('p', { key: `region-${side}` }, t("label_98", {"0": t(side==='subject'?'candidate':'reference'), "1": manifest.region[side]?.positions ? manifest.region[side].positions.map(positionLabel).join(', ') : manifest.region[side]?.chains ? `chain ${manifest.region[side].chains[0] || '(blank)'}` : t("complete_structure")}))),
      h('dl', null,
        h('dt', null, t("tm_subject_length", {"0": manifest.metrics.tm_subject.normalization_length})), h('dd', null, manifest.metrics.tm_subject.value.toFixed(6)),
        h('dt', null, t("tm_reference_length", {"0": manifest.metrics.tm_reference.normalization_length})), h('dd', null, manifest.metrics.tm_reference.value.toFixed(6)),
        h('dt', null, t("rmsd_residue_pairs", {"0": manifest.metrics.rmsd.aligned_pair_count})), h('dd', null, manifest.metrics.rmsd.value.toFixed(6))),

      ...['subject', 'reference'].map(side => h('label', { key: side },
        h('input', { type: 'checkbox', 'aria-label': t("label_99", {"0": t(side==='subject'?'candidate':'reference')}), checked: visible[side], onChange: event => setVisible({ ...visible, [side]: event.target.checked }) }),
        t("atoms_other_component_atoms", {"0": t(side==='subject'?'candidate':'reference'), "1": overlay[side].length, "2": overlay[side].filter(atom => atom.component === 'other').length}))),
      h('label', null, t("rotate_view"), h('input', { type: 'range', min: -180, max: 180, value: yaw, 'aria-label': t("rotate_around_vertical_axis"), onChange: event => setYaw(Number(event.target.value)) })),
      h('label', null, t("tilt"), h('input', { type: 'range', min: -90, max: 90, value: pitch, 'aria-label': t("message"), onChange: event => setPitch(Number(event.target.value)) })),
      h('svg', { viewBox: '0 0 600 440', role: 'img', 'aria-label': t("message_2"), style: { width: '100%', maxWidth: '800px', background: '#f4f7fb' } },
        plotted.map(({ atom, side, index, point }) => h('circle', { key: `${side}-${index}`, cx: point[0], cy: point[1], r: atom.component === 'other' ? 4 : 2.5,
          fill: side === 'subject' ? '#2266cc' : '#df6b16', opacity: 0.75, tabIndex: 0, 'data-residue': atom.residue_name,
          onClick: () => setSelected({ ...atom, side }), onKeyDown: event => { if (event.key === 'Enter') setSelected({ ...atom, side }); } },
        h('title', null, `${side}: ${atom.chain} ${atom.author_number}${atom.insertion_code} ${atom.residue_name} ${atom.atom_name}`)))),
      selected && h('p', { 'aria-label': t("selected_atom") }, t("label_100", {"0": selected.side, "1": selected.chain, "2": selected.author_number, "3": selected.insertion_code, "4": selected.residue_name, "5": selected.atom_name, "6": selected.element})),
      h('details', null, h('summary', null, t("alignment_details")), h('p',null,t("label_101", {"0": manifest.method.name, "1": manifest.method.algorithm, "2": manifest.method.tmtools})), h('p',null,t("subject_reference", {"0": manifest.subject.label??'', "1": manifest.reference.label??''}))));
  }
  return { editors: [{ node: 'workbench.compare', component: ComparisonEditor }, { node: 'workbench.compare_structure', component: ComparisonEditor }], viewers: [{ id: 'workbench.comparison.overlay', name: messages.complete_overlay, formats: ['workbench.comparison'], component: ComparisonViewer }] };
}
