export const runtime = { react: 19 }
export function register({ React }) {
  return { actions: [{ id: 'test.actions', name: 'Test author actions', component: function Actions({ host }) {
    const [result, setResult] = React.useState('')
    const resume = React.useRef(null)
    async function perform(operation) {
      try { await operation(); setResult('Completed') } catch (error) { setResult(error.message) }
    }
    return React.createElement('div', null,
      React.createElement('button', { onClick: () => perform(async () => {
        const source = await host.addNode({ type: 'test.one', parameters: {}, inputs: {} })
        const target = await host.addNode({ type: 'test.one', parameters: {}, inputs: {} })
        await host.connect({ source, source_port: 'output', target, target_port: 'input' })
      }) }, 'Add connected pair'),
      React.createElement('button', { onClick: () => perform(async () => {
        const input = await host.createInput({ format: 'test.format', entry: 'data', files: { data: new Blob(['input']) } })
        await host.addNode({ type: 'test.one', parameters: {}, inputs: { input: [input.id] } })
      }) }, 'Upload and add node'),
      React.createElement('button', { onClick: () => perform(async () => {
        await new Promise(resolve => { resume.current = resolve })
        await host.addNode({ type: 'test.one', parameters: {}, inputs: {} })
      }) }, 'Prepare delayed node'),
      React.createElement('button', { onClick: () => resume.current?.() }, 'Finish delayed node'),
      React.createElement('span', { 'data-testid': 'action-result' }, result))
  } }] }
}
