const messages = {

  "label_93": {
    "zh-CN": "{0}{1} · {2} 个残基",
    "en": "{0}{1} · {2} residues"
  }
,
  "reading_inputs": {
    "zh-CN": "正在读取输入…",
    "en": "Reading inputs…"
  },
  "inspect_sequence_and_reference_inputs": {
    "zh-CN": "读取序列和参考结构",
    "en": "Inspect sequence and reference inputs"
  },
  "reference_structure": {
    "zh-CN": "参考结构",
    "en": "Reference structure"
  },
  "choose_reference": {
    "zh-CN": "选择参考",
    "en": "Choose reference"
  },
  "reference_chain_residues": {
    "zh-CN": "参考链 {0} · {1} 个残基",
    "en": "Reference chain {0} · {1} residues"
  },
  "sequence_for_reference_chain": {
    "zh-CN": "参考链 {0} 的序列",
    "en": "Sequence for reference chain {0}"
  },
  "choose_complete_chain_sequence": {
    "zh-CN": "选择完整链序列",
    "en": "Choose complete chain sequence"
  },
  "report_region_unchecked_means_all_residues_full": {
    "zh-CN": "评价区域（未选择时使用全部残基）",
    "en": "Report region (unchecked means all residues; full backbone remains input)"
  },
  "evaluation_scoring_nll_global_nll_region_nll": {
    "zh-CN": "评价 {0} · 序列 NLL {1} · 全局 NLL {2} · 区域 NLL {3}",
    "en": "Evaluation {0} · scoring NLL {1} · global NLL {2} · region NLL {3}"
  },
  "reference_residue": {
    "zh-CN": "参考残基",
    "en": "Reference residue"
  },
  "tool_chain_position": {
    "zh-CN": "工具链位置",
    "en": "Tool chain position"
  },
  "scoring_mask": {
    "zh-CN": "评分掩码",
    "en": "Scoring mask"
  },
  "coordinate_mask": {
    "zh-CN": "坐标掩码",
    "en": "Coordinate mask"
  },
  "region_mask": {
    "zh-CN": "区域掩码",
    "en": "Region mask"
  },
  "selected_reference": {
    "zh-CN": "所选参考",
    "en": "Selected reference"
  },
  "actual_seed": {
    "zh-CN": "{0} · 实际种子 {1}",
    "en": "{0} · actual seed {1}"
  },
  "complete_reference_reporting": {
    "zh-CN": "完整参考结果",
    "en": "Complete reference reporting"
  },
  "evaluated_sequences": {
    "zh-CN": "已评价序列：{0}",
    "en": "Evaluated sequences: {0}"
  },
  "parameters": {
    "zh-CN": "计算参数",
    "en": "Parameters"
  },
  "configured": {
    "zh-CN": "已配置",
    "en": "Configured"
  },
  "sequence_backbone_scores": {
    "zh-CN": "序列适配评分",
    "en": "Sequence–backbone scores"
  },
  "independent_sequence_backbone_scores_and_masks": {
    "zh-CN": "独立序列与骨架评分及掩码",
    "en": "Independent sequence/backbone scores and masks"
  }
};
/** Independent scoring owns object selection and complete chain correspondence. */
export const runtime = { react: 19 };
export function register({ React, i18n }) {
  const t = i18n.translator(messages);
  const h = React.createElement;
  const positionLabel = p => `${p.chain} ${p.author_number}${p.insertion_code}`;
  const actual = ({ chain, author_number, insertion_code }) => ({ chain, author_number, insertion_code });
  function Editor({ parameters, onChange, readOnly, context }) {
    const [data, setData] = React.useState(null), [error, setError] = React.useState(''), [busy, setBusy] = React.useState(false);
    const epoch = React.useRef(0), current = React.useRef('');
    const inputs = Object.fromEntries(['sequences', 'reference'].map(port => [port, (context.inputs[port]?.packages || []).map(p => p.id)]));
    const signature = JSON.stringify([context.projectId, context.nodeId, inputs]);
    current.current = JSON.stringify([signature, context.revision, parameters]);
    React.useEffect(() => { epoch.current++; setData(null); setError(''); setBusy(false); return () => { epoch.current++; }; }, [signature]);
    function change(value) { epoch.current++; setBusy(false); onChange(value); }
    async function inspect() {
      const request = ++epoch.current, snapshot = current.current;
      let preview;
      setBusy(true); setError('');
      try {
        preview = await context.host.preview('workbench.sequence_backbone.inspect', inputs, {});
        if (request === epoch.current && snapshot === current.current) setData(preview.data);
      } catch (failure) { if (request === epoch.current && snapshot === current.current) setError(i18n.error(failure)); }
      finally {
        if (preview) {
          try { await context.host.cancelPreview(preview.id); }
          catch (failure) { if (request === epoch.current) setError(i18n.error(failure)); }
        }
        if (request === epoch.current) setBusy(false);
      }
    }
    const reference = data?.references.find(o => o.object === parameters.reference);
    const chains = reference ? [...new Set(reference.positions.map(p => p.chain))] : [];
    function bind(chain, index) {
      const bindings = (parameters.bindings || []).filter(b => b.reference_chain !== chain);
      if (index !== '') {
        const source = data.sequences[Number(index)];
        bindings.push({ reference_chain: chain, object: source.object, ...(source.source_chain === undefined ? {} : { source_chain: source.source_chain }),
          positions: reference.positions.filter(p => p.chain === chain).map(p => ({ ...actual(p), sequence_index: p.tool_position })) });
      }
      change({ ...parameters, bindings });
    }
    const unavailable = ['sequences', 'reference'].map(port => context.inputs[port]?.unavailable).filter(Boolean);
    return h('section', null,

      ...unavailable.map((reason, i) => h('p', { key: i, role: 'status' }, reason)),
      h('button', { disabled: busy || readOnly || Object.values(inputs).some(ids => ids.length !== 1), onClick: inspect }, busy ? t("reading_inputs") : t("inspect_sequence_and_reference_inputs")),
      data && h(React.Fragment, null,
        h('label', null, t("reference_structure"), h('select', { 'aria-label': t("reference_structure"), value: parameters.reference || '', disabled: readOnly, onChange: e => change({ ...parameters, reference: e.target.value, bindings: [], region: null }) },
          h('option', { value: '' }, t("choose_reference")), ...data.references.map((o, i) => h('option', { key: o.object, value: o.object }, o.label || `Reference ${i + 1}`)))),
        ...chains.map(chain => {
          const positions = reference.positions.filter(p => p.chain === chain), binding = parameters.bindings?.find(b => b.reference_chain === chain);
          const selected = data.sequences.findIndex(s => s.object === binding?.object && s.source_chain === binding?.source_chain);
          return h('fieldset', { key: chain }, h('legend', null, t("reference_chain_residues", {"0": chain, "1": positions.length})),
            h('select', { 'aria-label': t("sequence_for_reference_chain", {"0": chain}), value: selected < 0 ? '' : String(selected), disabled: readOnly, onChange: e => bind(chain, e.target.value) },
              h('option', { value: '' }, t("choose_complete_chain_sequence")), ...data.sequences.map((s, i) => h('option', { key: i, value: String(i), disabled: s.sequence.length !== positions.length }, t("label_93", {"0": s.label || `Sequence ${i + 1}`, "1": s.source_chain === undefined ? '' : ` · chain ${s.source_chain}`, "2": s.sequence.length})))),
            selected >= 0 && h('p', null, data.sequences[selected].sequence),
            h('p', null, positions.map(positionLabel).join(', ')));
        }),
        reference && h('fieldset', null, h('legend', null, t("report_region_unchecked_means_all_residues_full")),
          ...reference.positions.map((p, i) => h('label', { key: i, style: { display: 'block' } }, h('input', { type: 'checkbox', disabled: readOnly,
            checked: (parameters.region || []).some(row => JSON.stringify(row) === JSON.stringify(actual(p))),
            onChange: e => {
              const values = (parameters.region || []).filter(row => JSON.stringify(row) !== JSON.stringify(actual(p)));
              if (e.target.checked) values.push(actual(p));
              change({ ...parameters, region: values.length ? values : null });
            } }), positionLabel(p))))),

      error && h('p', { role: 'alert' }, error));
  }
  function Viewer({ package: pkg, host }) {
    const [data, setData] = React.useState(null), [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true; setData(null); setError('');
      host.readFile(pkg.id, pkg.entry).then(b => b.text()).then(JSON.parse).then(value => { if (active) setData(value); }).catch(e => { if (active) setError(i18n.error(e)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    function sampleTable(e, sample, index) {
      const rows = e.positions.map((p, k) => {
        const offset = p.tool_position - 1;
        const values = [positionLabel(p), p.tool_position, sample.chains[p.chain][offset], sample.residue_nll[p.chain][offset], sample.design_mask[p.chain][offset], sample.coordinate_mask[p.chain][offset], sample.region_mask[p.chain][offset]];
        return h('tr', { key: k }, ...values.map((value, n) => h('td', { key: n }, String(value))));
      });
      return h('section', { key: index },
        h('p', null, t("evaluation_scoring_nll_global_nll_region_nll", {"0": index + 1, "1": sample.score, "2": sample.global_score, "3": sample.region_nll})),
        h('table', null,
          h('thead', null, h('tr', null, ...[t("reference_residue"), t("tool_chain_position"), 'Sequence', 'NLL', t("scoring_mask"), t("coordinate_mask"), t("region_mask")].map(label => h('th', { key: label }, label)))),
          h('tbody', null, ...rows)));
    }
    function evaluation(e, index) {
      const labels = e.object_ids.map(id => { const i = data.objects.findIndex(o => o.id === id); return data.objects[i]?.label || `Sequence ${i + 1}`; });
      return h('article', { key: index },
        h('h4', null, `${e.method} · ${e.reference.label || t("selected_reference")}`),
        h('p', null, t("actual_seed", {"0": e.unit, "1": e.actual_seed})),
        h('p', null, e.region === null ? t("complete_reference_reporting") : e.region.map(positionLabel).join(', ')),
        h('p', null, t("evaluated_sequences", {"0": labels.join(', ')})),
        ...e.samples.map((sample, j) => sampleTable(e, sample, j)),
        h('details', null, h('summary', null, t("parameters")), h('dl',null,Object.entries(e.parameters).map(([key,value])=>h(React.Fragment,{key},h('dt',null,key.replaceAll('_',' ')),h('dd',null,typeof value==='object'?t("configured"):String(value)))))));
    }
    return h('section', null, h('h3', null, t("sequence_backbone_scores")),
      data && h(React.Fragment, null,
        ...data.objects.map((o, i) => h('article', { key: o.id }, h('h4', null, o.label || `Sequence ${i + 1}`), o.sequence ? h('pre', null, o.sequence) : Object.entries(o.chains).map(([chain, sequence]) => h('p', { key: chain }, `${chain}: ${sequence}`)))),
        ...(data.evaluations || []).filter(e => e.origin === 'independent_sequence_backbone').map(evaluation)),
      error && h('p', { role: 'alert' }, error));
  }

  return { editors: [{ node: 'workbench.evaluate_sequence_backbone', component: Editor }], viewers: [{ id: 'workbench.sequence_backbone.values', name: messages.independent_sequence_backbone_scores_and_masks, formats: ['workbench.sequence_backbone_evaluation'], component: Viewer }] };
}
