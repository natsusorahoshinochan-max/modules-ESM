export function register({ React }) {
  function ExternalEditor({ workflow, nodeId, onApply, onCancel }) {
    const node = workflow.nodes.find(item => item.node_id === nodeId)
    const [value, setValue] = React.useState(node.node_parameters.message ?? '')
    return React.createElement('section', null,
      React.createElement('label', null, 'External label', React.createElement('input', {
        value, onChange: event => setValue(event.target.value),
      })),
      React.createElement('button', { onClick: () => onApply({ ...workflow,
        nodes: workflow.nodes.map(item => item.node_id === nodeId
          ? { ...item, node_parameters: { ...item.node_parameters, message: value } } : item),
      }) }, 'Apply external edit'),
      React.createElement('button', { onClick: onCancel }, 'Cancel external edit'),
    )
  }
  return { ExternalEditor }
}
