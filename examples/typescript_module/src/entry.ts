import type { EditorProps, ModuleActionProps, ModuleEntry, ViewerProps } from '@protein-workbench/module-ui'

export const runtime: ModuleEntry['runtime'] = { react: 19 }

export const register: ModuleEntry['register'] = ({ React }) => {
  function NewNote({ host }: ModuleActionProps) {
    const [message, setMessage] = React.useState('Add a note')
    async function add() {
      try {
        const source = await host.createInput({
          format: 'example.note', entry: 'text', files: { text: new Blob(['hello']) },
        })
        await host.addNode({ type: 'example.uppercase', parameters: {}, inputs: { note: [source.id] } })
        setMessage('Note added')
      } catch (error) { setMessage(String(error)) }
    }
    return React.createElement('button', { disabled: host.readOnly, onClick: add }, message)
  }

  function Editor({ parameters, onChange, readOnly }: EditorProps) {
    return React.createElement('button', {
      disabled: readOnly, onClick: () => onChange({ ...parameters, label: 'edited' }),
    }, 'Set label')
  }

  function Viewer({ package: data, host }: ViewerProps) {
    const [text, setText] = React.useState('Loading…')
    React.useEffect(() => {
      let active = true
      host.readFile(data.id, data.entry).then(file => file.text()).then(value => {
        if (active) setText(value)
      }).catch(error => { if (active) setText(String(error)) })
      return () => { active = false }
    }, [data.id, data.entry, host])
    return React.createElement('pre', null, text)
  }

  return {
    actions: [{ id: 'typed.new-note', name: 'New note', component: NewNote }],
    editors: [{ node: 'example.uppercase', component: Editor }],
    viewers: [{ id: 'typed.note', name: 'Note text', formats: ['example.note'], component: Viewer }],
  }
}
