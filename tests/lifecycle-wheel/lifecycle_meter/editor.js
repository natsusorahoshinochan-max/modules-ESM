export function register({ React }) {
  const h = React.createElement
  function Adjust({ workflow, nodeId, onApply, onCancel }) {
    const node = workflow.nodes.find(item => item.node_id === nodeId)
    const [amount, setAmount] = React.useState(node.node_parameters.amount)
    const [note, setNote] = React.useState(node.node_parameters.note)
    const [pending, setPending] = React.useState(false)
    const [error, setError] = React.useState('')
    async function apply() {
      setPending(true)
      setError('')
      try {
        await onApply({ ...workflow, nodes: workflow.nodes.map(item => item.node_id === nodeId ? { ...item, node_parameters: { amount, note } } : item) })
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason))
      } finally {
        setPending(false)
      }
    }
    return h('section', { 'aria-label': '外部测量编辑器' },
      h('label', {}, '增加值', h('input', { 'aria-label': '增加值', type: 'number', disabled: pending, value: amount, onChange: event => setAmount(Number(event.target.value)) })),
      h('label', {}, '测量说明', h('input', { 'aria-label': '测量说明', disabled: pending, value: note, onChange: event => setNote(event.target.value) })),
      error && h('p', { role: 'alert' }, error),
      h('button', { disabled: pending, onClick: onCancel }, '取消测量修改'),
      h('button', { disabled: pending, onClick: () => void apply() }, pending ? '正在采用…' : '采用测量修改'))
  }
  return { Adjust }
}
