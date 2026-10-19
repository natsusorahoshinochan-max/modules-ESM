import * as React from 'react'
import type { Extensions, ModuleEntry } from '@protein-workbench/module-ui'
import type { ModuleRecord } from './host-client'

export type LoadedExtensions = { [K in keyof Extensions]: NonNullable<Extensions[K]> extends (infer T)[] ? (T & { installation_id: string })[] : never }

export async function loadExtensions(modules: ModuleRecord[]): Promise<LoadedExtensions> {
  const extensions: Required<LoadedExtensions> = { actions: [], editors: [], viewers: [] }
  for (const module of modules.filter(item => item.enabled && item.available !== false && item.ui_url).sort((a, b) => a.id.localeCompare(b.id))) {
    const entry: ModuleEntry = await import(/* @vite-ignore */ module.ui_url!)
    if (entry.runtime?.react !== 19 || typeof entry.register !== 'function') throw new Error(`${module.name}: UI must export runtime.react = 19 and register({React})`)
    const result = entry.register({ React })
    extensions.actions.push(...(result.actions ?? []).map(item => ({ ...item, installation_id: module.installation_id })))
    extensions.editors.push(...(result.editors ?? []).map(item => ({ ...item, installation_id: module.installation_id })))
    extensions.viewers.push(...(result.viewers ?? []).map(item => ({ ...item, installation_id: module.installation_id })))
  }
  for (const values of [extensions.actions, extensions.viewers]) {
    const identities = values.map(value => value.id)
    if (new Set(identities).size !== identities.length) throw new Error('Module UI declares duplicate action or viewer IDs')
  }
  const editors = extensions.editors.map(value => value.node)
  if (new Set(editors).size !== editors.length) throw new Error('More than one configuration editor declares the same node')
  extensions.viewers.sort((a, b) => a.id.localeCompare(b.id))
  return extensions
}
