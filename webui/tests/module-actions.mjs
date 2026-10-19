import { readFile } from 'node:fs/promises'
const comparisonSource = await readFile(new URL('../../modules/structure_comparison/ui.js', import.meta.url), 'utf8')
const { register: registerComparison } = await import(`data:text/javascript;base64,${Buffer.from(comparisonSource).toString('base64')}`)
const sequenceSource = await readFile(new URL('../../modules/sequence_edit/ui.js', import.meta.url), 'utf8')
const { register: registerSequence } = await import(`data:text/javascript;base64,${Buffer.from(sequenceSource).toString('base64')}`)
export const runtime = { react: 19 }
export function register({ React }) {
  const ComparisonEditor = registerComparison({ React }).editors[0].component
  return { editors: [{ node: 'test.sequence', component: registerSequence({React}).editors[0].component }, { node: 'test.region', component: function RegionEditor(props) {
    return React.createElement('div', null, React.createElement(ComparisonEditor, props),
      React.createElement('button', { onClick: () => props.onChange({ subject_selection: { chains: ['Q'] } }) }, 'Replace accepted region'))
  } }, { node: 'test.editor', component: function Editor({context, parameters, onChange}) {
    const [message, setMessage] = React.useState('')
    const saved = React.useRef(null)
    const abort = React.useRef(null)
    const originalEdges = React.useRef(context?.edges?.filter(edge => edge.target === context.nodeId) ?? [])
    const receive = async () => { try { const result = await context.host.preview('test.preview', {}, {}); await context.update({ delivery: {interaction:result.id,output:'edited',port:'input'},replaceConnections:['input'] }); setMessage('Input received') } catch (error) { setMessage(error.message) } }
    const apply = async () => { try { await context.update({ parameters: { edited: true }, inputs: { input: ['edited'] }, replaceConnections: ['input'] }); setMessage('Editor accepted') } catch (error) { setMessage(error.message) } }
    return React.createElement('div', null,
      React.createElement('pre', { 'data-editor-context': context?.nodeId }, JSON.stringify(context)),
      React.createElement('button', { onClick: () => {
        const submitted = { nested: { value: 'submitted' } }
        onChange(submitted); submitted.nested.value = 'changed by module'
        setMessage('Caller submission remains editable')
      } }, 'Submit owned parameters'),
      React.createElement('button', { onClick: async () => { try {
        const submitted = { nested: { value: 'async submitted' } }
        const accepted = context.update({ parameters: submitted })
        submitted.nested.value = 'changed before await'
        await accepted; submitted.nested.value = 'changed after await'
        setMessage('Async caller submission remains editable')
      } catch (error) { setMessage(error.message) } } }, 'Submit async owned parameters'),
      React.createElement('button', { onClick: () => { try {
        parameters.nested.value = 'changed snapshot'
        setMessage('Snapshot mutation succeeded')
      } catch { setMessage('Parameter snapshot is read only') } } }, 'Mutate parameter snapshot'),
      React.createElement('button', { onClick: () => setMessage(JSON.stringify(saved.current.parameters)) }, 'Show remembered parameters'),
      React.createElement('button', {onClick: apply}, 'Accept editor draft'),
      React.createElement('button', {onClick: receive}, 'Receive editor file'),
      React.createElement('button', {onClick:async()=>{abort.current=new AbortController();try{await context.host.preview('test.preview',{}, {}, {signal:abort.current.signal});setMessage('Preview returned')}catch(error){setMessage(error.message)}}}, 'Begin cancellable preview'),
      React.createElement('button', {onClick:()=>abort.current?.abort()}, 'Abort editor preview'),
      React.createElement('button', {onClick: async () => { try { await context.update({inputs:{input:[]},replaceConnections:['input'],connections:originalEdges.current}); setMessage('Connection restored') } catch(error) {setMessage(error.message)} }}, 'Restore editor connection'),
      React.createElement('button', {onClick: () => { saved.current = context }}, 'Remember editor context'),
      React.createElement('button', {onClick: async () => { try { await saved.current.update({parameters:{stale:true}}) } catch(error) { setMessage(error.message) } }}, 'Apply remembered editor'),
      React.createElement('span', null, message))
  }}], actions: [{ id: 'test.actions', name: 'Test author actions', component: function Actions({ host }) {
    const [result, setResult] = React.useState('')
    const resume = React.useRef(null)
    async function perform(operation) {
      try { await operation(); setResult('Completed') } catch (error) { setResult(error.message) }
    }
    return React.createElement('div', null,
      React.createElement('button', { onClick: () => perform(async () => {
        const parameters = { subject_selection: { chains: ['X'] } }
        await host.addNode({ type: 'test.region', parameters, inputs: {} })
        parameters.subject_selection.chains[0] = 'changed after node creation'
      }) }, 'Add region editor'),
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
