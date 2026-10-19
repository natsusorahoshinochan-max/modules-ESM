import * as React from 'react'
import type { Extensions, ModuleEntry } from '@protein-workbench/module-ui'
import type { ModuleRecord } from './host-client'

export async function loadExtensions(modules: ModuleRecord[]): Promise<Extensions> {
  const extensions: Required<Extensions> = { actions: [], editors: [], viewers: [] }
  for (const module of modules.filter(item => item.enabled && item.ui).sort((a, b) => a.id.localeCompare(b.id))) {
    const entry: ModuleEntry = await import(/* @vite-ignore */ `/api/modules/${encodeURIComponent(module.id)}/ui.js`)
    if (entry.runtime?.react !== 19 || typeof entry.register !== 'function') throw new Error(`${module.name}: UI must export runtime.react = 19 and register({React})`)
    const result = entry.register({ React })
    extensions.actions.push(...(result.actions ?? []))
    extensions.editors.push(...(result.editors ?? []))
    extensions.viewers.push(...(result.viewers ?? []))
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
