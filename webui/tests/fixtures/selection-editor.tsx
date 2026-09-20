import { createRoot } from 'react-dom/client'
import { SelectionEditor } from '../../src/SelectionEditor'
import type { SelectionEditorProps } from '../../src/SelectionEditor'

const root = createRoot(document.getElementById('root')!)
window.addEventListener('render-selection-fixture', (event) => {
  const props = (event as CustomEvent<Omit<SelectionEditorProps, 'onChange'>>).detail
  root.render(<SelectionEditor {...props} onChange={(workflow) => { document.body.dataset.savedSelectionWorkflow = JSON.stringify(workflow) }} />)
})
document.documentElement.dataset.fixtureReady = 'true'
