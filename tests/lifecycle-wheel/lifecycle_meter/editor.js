export function register({ React }) {
  const h = React.createElement
  function Adjust({ workflow, nodeId, onApply, onCancel }) {
    const node = workflow.nodes.find(item => item.node_id === nodeId)
    const [amount, setAmount] = React.useState(node.node_parameters.amount)
    const [note, setNote] = React.useState(node.node_parameters.note)
    return h('section', { 'aria-label': '外部测量编辑器' },
      h('label', {}, '增加值', h('input', { 'aria-label': '增加值', type: 'number', value: amount, onChange: event => setAmount(Number(event.target.value)) })),
      h('label', {}, '测量说明', h('input', { 'aria-label': '测量说明', value: note, onChange: event => setNote(event.target.value) })),
      h('button', { onClick: onCancel }, '取消测量修改'),
      h('button', { onClick: () => onApply({ ...workflow, nodes: workflow.nodes.map(item => item.node_id === nodeId ? { ...item, node_parameters: { amount, note } } : item) }) }, '采用测量修改'))
  }
  return { Adjust }
}
