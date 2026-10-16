import { SelectionEditor } from './SelectionEditor'
import type { ModuleEditorProps } from '../../../webui/src/module-ui'

function Editor({ onApply, ...props }: ModuleEditorProps) {
  return <SelectionEditor {...props} onChange={onApply} />
}

export function register() {
  return { SelectionEditor: Editor }
}
