import type { PublishedResults } from './published-results'
import * as React from 'react'
import * as ReactDOM from 'react-dom'
import * as jsxRuntime from 'react/jsx-runtime'
import type { CatalogSnapshot, PublishedResultValue, Workflow, RunProjection, ResultLocation, PublicV2Client } from './protocol/client'

export type ModuleEditorProps = {
  catalog: CatalogSnapshot
  client: PublicV2Client
  versionContext?: { version_id: string }
  workflow: Workflow
  nodeId: string
  results: PublishedResults
  onApply: (workflow: Workflow) => Promise<void>
  onCancel: () => void
}
export type ModuleEditorDefinition = { editor_id: string; title: string; node_type_ids: string[]; component: string }
export type ModuleRunViewerProps = {
  run: RunProjection; results: PublishedResults; client: PublicV2Client
  active: boolean; workspaceProjectId?: string; viewStateStore: Map<string, unknown>
  requestedSource?: ResultLocation & { requestId: number }; nodeLabels: Record<string, string>
  onLocateNode: (nodeId: string) => void; scienceStatus: 'current' | 'stale' | 'unknown'
}
export type ModuleRunViewerDefinition = { viewer_id: string; title: string; port_type_ids: string[]; component: string }
export type RegisteredRunViewer = { extension: ModuleUiExtension; definition: ModuleRunViewerDefinition }
export type ModuleViewerProps = { reading: PublishedResultValue }
export type ModuleViewerDefinition = { viewer_id: string; title: string; port_type_id: string; component: string; is_default: boolean }
export type RegisteredResultViewer = { extension: ModuleUiExtension; definition: ModuleViewerDefinition }
export type ModuleUiExtension = { extension_id: string; react_major: 19; entry_url: string; style_urls: string[]; editors: ModuleEditorDefinition[]; viewers: ModuleViewerDefinition[]; run_viewers: ModuleRunViewerDefinition[] }
export type ModuleUiManifest = { authoring_actions: string[]; extensions: ModuleUiExtension[]; readers: Array<{ port_type_id: string; kind: string }> }
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

export function runViewers(manifest: ModuleUiManifest, run: RunProjection): RegisteredRunViewer[] {
  const types = new Set(run.outputs.map(output => output.port_type.contract_id))
  return manifest.extensions.flatMap(extension => extension.run_viewers
    .filter(definition => definition.port_type_ids.some(type => types.has(type)))
    .map(definition => ({ extension, definition })))
    .sort((left, right) => left.definition.viewer_id.localeCompare(right.definition.viewer_id))
}
export function loadRunViewer(viewer: RegisteredRunViewer): Promise<React.ComponentType<ModuleRunViewerProps>> {
  return loadComponent<ModuleRunViewerProps>(viewer.extension, viewer.definition.component)
}
