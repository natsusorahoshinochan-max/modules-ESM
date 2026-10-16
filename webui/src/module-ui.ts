import * as React from 'react'
import * as ReactDOM from 'react-dom'
import * as jsxRuntime from 'react/jsx-runtime'
import type { CatalogSnapshot, PublishedResultValue, ResultCandidate, Workflow } from './protocol/client'

export type ModuleEditorProps = {
  catalog: CatalogSnapshot
  workflow: Workflow
  nodeId: string
  candidateCollections: Array<{ source: { node_id: string; output_port: string }; items: ResultCandidate[] }>
  onApply: (workflow: Workflow) => void
  onCancel: () => void
}
export type ModuleEditorDefinition = { editor_id: string; title: string; node_type_ids: string[]; component: string }
export type ModuleViewerProps = { reading: PublishedResultValue }
export type ModuleViewerDefinition = { viewer_id: string; title: string; port_type_id: string; component: string; is_default: boolean }
export type RegisteredResultViewer = { extension: ModuleUiExtension; definition: ModuleViewerDefinition }
export type ModuleUiExtension = { extension_id: string; react_major: 19; entry_url: string; style_urls: string[]; editors: ModuleEditorDefinition[]; viewers: ModuleViewerDefinition[] }
export type ModuleUiManifest = { extensions: ModuleUiExtension[]; readers: Array<{ port_type_id: string; kind: string }> }
export type RegisteredNodeEditor = { extension: ModuleUiExtension; definition: ModuleEditorDefinition }
export type ModuleUiHost = { React: typeof React; ReactDOM: typeof ReactDOM; jsxRuntime: typeof jsxRuntime }
export type ModuleUiEntry = { register: (host: ModuleUiHost) => Record<string, React.ComponentType<never>> }

const host: ModuleUiHost = { React, ReactDOM, jsxRuntime }
const runtimeKey = Symbol.for('protein-workbench.module-ui.v1')
;(globalThis as unknown as Record<symbol, ModuleUiHost>)[runtimeKey] = host
const modules = new Map<string, Promise<Record<string, React.ComponentType<never>>>>()

export function nodeEditor(manifest: ModuleUiManifest, nodeTypeId: string): RegisteredNodeEditor | undefined {
  for (const extension of manifest.extensions) {
    const definition = extension.editors.find(editor => editor.node_type_ids.includes(nodeTypeId))
    if (definition) return { extension, definition }
  }
}

export function resultViewers(manifest: ModuleUiManifest, portTypeId: string): RegisteredResultViewer[] {
  return manifest.extensions.flatMap(extension => extension.viewers
    .filter(definition => definition.port_type_id === portTypeId)
    .map(definition => ({ extension, definition })))
}

export function loadNodeEditor(editor: RegisteredNodeEditor): Promise<React.ComponentType<ModuleEditorProps>> {
  return loadComponent<ModuleEditorProps>(editor.extension, editor.definition.component)
}

export function loadResultViewer(viewer: RegisteredResultViewer): Promise<React.ComponentType<ModuleViewerProps>> {
  return loadComponent<ModuleViewerProps>(viewer.extension, viewer.definition.component)
}

async function loadComponent<Props>(extension: ModuleUiExtension, componentName: string): Promise<React.ComponentType<Props>> {
  if (Number(React.version.split('.')[0]) !== extension.react_major) throw new Error(`模块 ${extension.extension_id} 需要 React ${extension.react_major}`)
  let loaded = modules.get(extension.entry_url)
  if (!loaded) {
    loaded = (async () => {
      for (const href of extension.style_urls) {
        const style = document.createElement('link')
        style.rel = 'stylesheet'; style.href = href
        document.head.append(style)
      }
      // Package assets are already browser ESM; preserve their declared URL through dev tooling.
      const entryUrl = new URL(extension.entry_url, window.location.origin).href
      const entry = await import(/* @vite-ignore */ entryUrl) as ModuleUiEntry
      return entry.register(host)
    })()
    modules.set(extension.entry_url, loaded)
  }
  const component = (await loaded)[componentName]
  if (!component) throw new Error(`模块 ${extension.extension_id} 未导出组件 ${componentName}`)
  return component as React.ComponentType<Props>
}
