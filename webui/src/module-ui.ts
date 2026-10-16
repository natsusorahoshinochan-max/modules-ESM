import * as React from 'react'
import * as ReactDOM from 'react-dom'
import * as jsxRuntime from 'react/jsx-runtime'
import type { CatalogSnapshot, ResultCandidate, Workflow } from './protocol/client'

export type ModuleEditorProps = {
  catalog: CatalogSnapshot
  workflow: Workflow
  nodeId: string
  candidateCollections: Array<{ source: { node_id: string; output_port: string }; items: ResultCandidate[] }>
  onApply: (workflow: Workflow) => void
  onCancel: () => void
}
export type ModuleEditorDefinition = { editor_id: string; title: string; node_type_ids: string[]; component: string }
export type ModuleUiExtension = { extension_id: string; react_major: 19; entry_url: string; style_urls: string[]; editors: ModuleEditorDefinition[] }
export type ModuleUiManifest = { extensions: ModuleUiExtension[] }
export type RegisteredNodeEditor = { extension: ModuleUiExtension; definition: ModuleEditorDefinition }
export type ModuleUiHost = { React: typeof React; ReactDOM: typeof ReactDOM; jsxRuntime: typeof jsxRuntime }
export type ModuleUiEntry = { register: (host: ModuleUiHost) => Record<string, React.ComponentType<ModuleEditorProps>> }

const host: ModuleUiHost = { React, ReactDOM, jsxRuntime }
const runtimeKey = Symbol.for('protein-workbench.module-ui.v1')
;(globalThis as unknown as Record<symbol, ModuleUiHost>)[runtimeKey] = host
const modules = new Map<string, Promise<Record<string, React.ComponentType<ModuleEditorProps>>>>()

export function nodeEditor(manifest: ModuleUiManifest, nodeTypeId: string): RegisteredNodeEditor | undefined {
  for (const extension of manifest.extensions) {
    const definition = extension.editors.find(editor => editor.node_type_ids.includes(nodeTypeId))
    if (definition) return { extension, definition }
  }
}

export async function loadNodeEditor(editor: RegisteredNodeEditor): Promise<React.ComponentType<ModuleEditorProps>> {
  const { extension, definition } = editor
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
  const component = (await loaded)[definition.component]
  if (!component) throw new Error(`模块 ${extension.extension_id} 未导出编辑器 ${definition.component}`)
  return component
}
