import { StructureViewer } from '../../../webui/src/StructureViewer'
import type { PublishedStructure } from '../../../webui/src/protocol/client'
import type { ModuleViewerProps } from '../../../webui/src/module-ui'

function Structure3D({ reading }: ModuleViewerProps) {
  return <section aria-label="已发布结构"><StructureViewer structure={reading.value as PublishedStructure} /></section>
}
function StructureText({ reading }: ModuleViewerProps) {
  return <section aria-label="已发布结构原文"><pre>{(reading.value as PublishedStructure).text}</pre></section>
}
export function register() { return { Structure3D, StructureText } }
