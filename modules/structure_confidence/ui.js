const messages = {

  "label_102": {
    "zh-CN": "结构",
    "en": "Structure"
  }
,
  "blank_chain": {
    "zh-CN": "（空白链）",
    "en": "(blank chain)"
  },
  "selected_residues": {
    "zh-CN": "选中残基： {0}",
    "en": "Selected residues: {0}"
  },
  "whole": {
    "zh-CN": "整体",
    "en": "Whole"
  },
  "use_whole_structure": {
    "zh-CN": "使用整体",
    "en": "Use whole structure"
  },
  "mean_plddt": {
    "zh-CN": "平均 pLDDT： {0} · {1}",
    "en": "Mean pLDDT: {0} · {1}"
  },
  "chain": {
    "zh-CN": "链",
    "en": "Chain"
  },
  "number": {
    "zh-CN": "编号",
    "en": "Number"
  },
  "insertion_code": {
    "zh-CN": "插入码",
    "en": "Insertion code"
  },
  "missing_structure_objects": {
    "zh-CN": "缺少结构对象",
    "en": "Missing structure objects"
  },
  "unknown_confidence_object": {
    "zh-CN": "未知置信度对象",
    "en": "Unknown confidence object"
  },
  "incomplete_confidence_position_correspondence_or_invalid_fraction": {
    "zh-CN": "置信度位置对应不完整或数值无效",
    "en": "Incomplete confidence position correspondence or invalid fraction"
  },
  "missing_actual_residue_correspondence": {
    "zh-CN": "缺少残基对应",
    "en": "Missing actual residue correspondence"
  },
  "residue": {
    "zh-CN": "残基",
    "en": "Residue"
  },
  "structure_confidence": {
    "zh-CN": "结构置信度",
    "en": "Structure confidence"
  },
  "confidence_structure_object": {
    "zh-CN": "置信度结构对象",
    "en": "Confidence structure object"
  },
  "evaluation_region_residues": {
    "zh-CN": "评价区域 · {0} 个残基",
    "en": "Evaluation region · {0} residues"
  },
  "evaluation_region_whole": {
    "zh-CN": "评价区域 · 整体",
    "en": "Evaluation region · Whole"
  },
  "read_residues": {
    "zh-CN": "读取残基",
    "en": "Read residues"
  },
  "add_evaluation_node": {
    "zh-CN": "添加评价节点",
    "en": "Add evaluation node"
  },
  "confidence_structure_export_format": {
    "zh-CN": "置信度结构导出格式",
    "en": "Confidence structure export format"
  },
  "add_export_node": {
    "zh-CN": "添加导出节点",
    "en": "Add export node"
  },
  "structures": {
    "zh-CN": "{0} 个结构",
    "en": "{0} structures"
  },
  "evaluate_structure_confidence": {
    "zh-CN": "评价结构置信度",
    "en": "Evaluate structure confidence"
  }
};
/** Existing-geometry confidence using public package access and React. */
export const runtime = { react: 19 };
export function register({ React, i18n }) {
  const t = i18n.translator(messages);
  const h = React.createElement;
  const positionLabel = p => `${p.chain || t("blank_chain")} ${p.author_number}${p.insertion_code}`;
  function Editor({ parameters, onChange, readOnly }) {
    return h('section', null,
      h('p', null, parameters.region?.length ? t("selected_residues", {"0": parameters.region.map(positionLabel).join(', ')}) : t("whole")),
      parameters.region?.length && h('button', { disabled: readOnly, onClick: () => onChange({ ...parameters, region: null }) }, t("use_whole_structure")),);
  }
  function Score({ item, objects }) {
    const e = item.evaluation, d = item.data;
    return h('article', null,
      h('h4', null, objects.find(o => o.id === e.object_id)?.label || t("label_102")),
      h('p', null, `${e.method} · ${e.per_position.unit} · ${e.region === null ? t("whole") : e.region.map(positionLabel).join(', ')}`),
      h('p', null, t("mean_plddt", {"0": e.values.mean_plddt.value, "1": e.values.mean_plddt.meaning})),
      h('table', null,
        h('thead', null, h('tr', null, ...[t("chain"), t("number"), t("insertion_code"), 'pLDDT (0–1)'].map(t => h('th', { key: t }, t)))),
        h('tbody', null, ...d.positions.map((p, j) => h('tr', { key: j },
          h('td', null, p.chain), h('td', null, p.author_number), h('td', null, p.insertion_code), h('td', null, String(d.plddt[j])))))));
  }
  function Viewer({ package: pkg, host }) {
    const [data, setData] = React.useState(null), [object, setObject] = React.useState('');
    const [positions, setPositions] = React.useState([]), [chosen, setChosen] = React.useState([]);
    const [exportFormat, setExportFormat] = React.useState('mmcif');
    const [scores, setScores] = React.useState([]), [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true; setData(null); setScores([]); setError('');
      host.readFile(pkg.id, pkg.entry).then(b => b.text()).then(JSON.parse).then(async value => {
        if (!Array.isArray(value.objects) || !value.objects.length) throw new Error(t("missing_structure_objects"));
        const evaluations = (value.evaluations || []).filter(e => e.origin === 'independent_existing_geometry');
        const values = await Promise.all(evaluations.map(async e => {
          if (!value.objects.some(o => o.id === e.object_id)) throw new Error(t("unknown_confidence_object"));
          const d = JSON.parse(await (await host.readFile(pkg.id, e.per_position.file)).text());
          if (!Array.isArray(d.positions) || !Array.isArray(d.plddt) || d.positions.length !== d.plddt.length || d.plddt.some(v => typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 1)) throw new Error(t("incomplete_confidence_position_correspondence_or_invalid_fraction"));
          return { evaluation: e, data: d };
        }));
        if (active) { setData(value); setObject(value.objects[0].id); setScores(values); }
      }).catch(e => { if (active) setError(i18n.error(e)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    React.useEffect(() => {
      let active = true; setPositions([]); setChosen([]);
      const obj = data?.objects.find(o => o.id === object);
      const key = data?.confidence_positions?.[object] || obj?.atoms;
      if (key) host.readFile(pkg.id, key).then(b => b.text()).then(JSON.parse).then(rows => {
        const actual = rows.map(p => ({ chain: p.chain, author_number: p.author_number, insertion_code: p.insertion_code }));
        if (actual.some(p => typeof p.chain !== 'string' || !Number.isSafeInteger(p.author_number) || typeof p.insertion_code !== 'string')) throw new Error(t("missing_actual_residue_correspondence"));
        const unique = [...new Map(actual.map(p => [JSON.stringify(p), p])).values()];
        if (active) setPositions(unique);
      }).catch(e => { if (active) setError(i18n.error(e)); });
      return () => { active = false; };
    }, [data, object, pkg.id, host.readFile]);
    async function add(prepare = false) {
      try {
        await host.addNode({ type: prepare ? 'workbench.prepare_structure_confidence' : 'workbench.evaluate_structure_confidence',
          inputs: { structures: [pkg.id] }, parameters: { object, ...(!prepare && chosen.length ? { region: chosen.map(index => positions[index]) } : {}) },
          ...(!prepare ? { tools: { evaluator: 'workbench.simplefold.confidence' } } : {}) });
      } catch (failure) { setError(i18n.error(failure)); }
    }
    async function exportStructure() {
      try { await host.addNode({ type: 'workbench.export_structure', inputs: { structures: [pkg.id] }, parameters: { object, format: exportFormat } }); }
      catch (failure) { setError(i18n.error(failure)); }
    }
    const selection = h('fieldset', null, h('legend', null, t("residue")),
      ...positions.map((p, index) => h('label', { key: index, style: { display: 'block' } },
        h('input', { type: 'checkbox', checked: chosen.includes(index), onChange: e => setChosen(old => e.target.checked ? [...old, index].sort((a, b) => a - b) : old.filter(i => i !== index)) }), positionLabel(p))));
    return h('section', null, h('h3', null, t("structure_confidence")),
      data && h(React.Fragment, null,
        h('label', null, t("label_102"), h('select', { 'aria-label': t("confidence_structure_object"), value: object, onChange: e => setObject(e.target.value) }, data.objects.map((o, i) => h('option', { key: o.id, value: o.id }, o.label || `Structure ${i + 1}`)))),
        positions.length ? h('details',null,h('summary',null,chosen.length?t("evaluation_region_residues", {"0": chosen.length}):t("evaluation_region_whole")),selection) : h('button', { onClick: () => add(true), disabled: host.readOnly || !object }, t("read_residues")),
        h('button', { onClick: () => add(), disabled: host.readOnly || !object }, t("add_evaluation_node")),
        ['workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence'].includes(pkg.format) && h('div', null,
          h('select', { 'aria-label': t("confidence_structure_export_format"), value: exportFormat, onChange: e => setExportFormat(e.target.value) }, h('option', { value: 'mmcif' }, 'mmCIF'), h('option', { value: 'pdb' }, 'PDB')),
          h('button', { onClick: exportStructure, disabled: host.readOnly || !object }, t("add_export_node"))),
        ...scores.map((item, index) => h(Score, { key: index, item, objects: data.objects })),
        h('p',null,t("structures", {"0": data.objects.length}))),
      error && h('p', { role: 'alert' }, error));
  }
  return { editors: [{ node: 'workbench.evaluate_structure_confidence', component: Editor }],
    viewers: [{ id: 'workbench.structure_confidence.values', name: messages.evaluate_structure_confidence, formats: ['workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence', 'workbench.confidence_input'], component: Viewer }] };
}
