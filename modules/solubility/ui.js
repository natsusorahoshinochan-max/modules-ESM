const messages = {
  "invalid_solubility_evaluation_manifest": {
    "zh-CN": "可溶性评价清单无效。",
    "en": "Invalid solubility evaluation manifest."
  },
  "evaluation_requires_one_entry_per_explicit_sequence": {
    "zh-CN": "每个序列对象需对应一条评价。",
    "en": "Evaluation requires one entry per explicit sequence object."
  },
  "evaluation_refers_to_an_unknown_or_repeated": {
    "zh-CN": "评价引用了未知或重复的对象。",
    "en": "Evaluation refers to an unknown or repeated object."
  },
  "evaluation_requires_its_actual_method_numeric_values": {
    "zh-CN": "评价需包含实际方法、数值、单位及含义。",
    "en": "Evaluation requires its actual method, numeric values, units and meanings."
  },
  "solubility_scores": {
    "zh-CN": "可溶性评分",
    "en": "Solubility scores"
  },
  "reading": {
    "zh-CN": "读取中…",
    "en": "Reading…"
  },
  "sequence": {
    "zh-CN": "序列 {0}",
    "en": "Sequence {0}"
  },
  "full_sequence": {
    "zh-CN": " · 整条序列",
    "en": " · Full sequence"
  },
  "metric": {
    "zh-CN": "指标",
    "en": "Metric"
  },
  "number": {
    "zh-CN": "数值",
    "en": "Number"
  },
  "unit": {
    "zh-CN": "单位",
    "en": "Unit"
  },
  "meaning": {
    "zh-CN": "含义",
    "en": "Meaning"
  },
  "sequence_2": {
    "zh-CN": "序列",
    "en": "Sequence"
  },
  "parameters": {
    "zh-CN": "计算参数",
    "en": "Parameters"
  }
};
/** Independent solubility viewer and node editor using the public React contract. */
export const runtime = { react: 19 };

export function register({ React, i18n }) {
  const t = i18n.translator(messages);
  const h = React.createElement;
  function Viewer({ package: pkg, host }) {
    const [document, setDocument] = React.useState(null);
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true;
      setDocument(null); setError('');
      host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => {
        const value = JSON.parse(text);
        if (!Array.isArray(value.objects) || !Array.isArray(value.evaluations) || !value.tool) throw new Error(t("invalid_solubility_evaluation_manifest"));
        const ids = new Set(value.objects.map(object => object.id));
        if (!value.objects.length || ids.size !== value.objects.length || ids.has(undefined) || value.evaluations.length !== value.objects.length) throw new Error(t("evaluation_requires_one_entry_per_explicit_sequence"));
        const seen = new Set();
        for (const evaluation of value.evaluations) {
          if (!ids.has(evaluation.object_id) || seen.has(evaluation.object_id)) throw new Error(t("evaluation_refers_to_an_unknown_or_repeated"));
          seen.add(evaluation.object_id);
          if (typeof evaluation.method !== 'string' || !evaluation.method || !evaluation.values || !Object.keys(evaluation.values).length || Object.values(evaluation.values).some(metric => typeof metric?.value !== 'number' || !Number.isFinite(metric.value) || typeof metric.unit !== 'string' || typeof metric.meaning !== 'string')) throw new Error(t("evaluation_requires_its_actual_method_numeric_values"));
        }
        if (active) setDocument(value);
      }).catch(failure => { if (active) setError(i18n.error(failure)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    return h('section', null, h('h3', null, t("solubility_scores")),
      error && h('p', { role: 'alert' }, error),
      !document && !error && h('p', null, t("reading")),
      document && h(React.Fragment, null,

        ...document.evaluations.map((evaluation, index) => {
          const object = document.objects.find(item => item.id === evaluation.object_id);
          return h('article', { key: index },
            h('h4', null, object?.label || t("sequence", {"0": index + 1})),
            h('p', null, evaluation.method, t("full_sequence")),
            h('table', null, h('thead', null, h('tr', null, ...[t("metric"), t("number"), t("unit"), t("meaning")].map(title => h('th', { key: title }, title)))),
              h('tbody', null, ...Object.entries(evaluation.values).map(([name, metric]) => h('tr', { key: name }, h('td', null, name), h('td', null, String(metric.value)), h('td', null, metric.unit), h('td', null, metric.meaning))))),
            h('details', null, h('summary', null, t("sequence_2")), h('pre', null, object.sequence)));
        }),
        h('details', null, h('summary', null, t("parameters")), h('dl',null,Object.entries(document.tool.parameters).map(([key,value])=>h(React.Fragment,{key},h('dt',null,key.replaceAll('_',' ')),h('dd',null,String(value))))))));
  }
  return { editors: [],
    viewers: [{ id: 'workbench.solubility.values', name: messages.solubility_scores, formats: ['workbench.solubility'], component: Viewer }] };
}
