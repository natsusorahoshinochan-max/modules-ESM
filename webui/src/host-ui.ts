const messages = {
  "ui_must_export_runtime_react_19_and": {
    "zh-CN": "{0}：模块需导出 runtime.react = 19 和 register",
    "en": "{0}: UI must export runtime.react = 19 and register({React, i18n})"
  },
  "module_ui_declares_duplicate_action_or_viewer": {
    "zh-CN": "模块声明的操作或查看器标识重复",
    "en": "Module UI declares duplicate action or viewer IDs"
  },
  "more_than_one_configuration_editor_declares_the": {
    "zh-CN": "同一节点只能声明一个配置编辑器",
    "en": "More than one configuration editor declares the same node"
  }
};
const t = i18n.translator(messages)
import { i18n, useLocale, text } from './i18n'
import * as React from 'react'
import type { DisplayText, Extensions, ModuleEntry } from '@protein-workbench/module-ui'
import type { ModuleRecord } from './host-client'

export type LoadedExtensions = { [K in keyof Extensions]: NonNullable<Extensions[K]> extends (infer T)[] ? (T & { installation_id: string })[] : never }

function localized<P extends object>(Component: React.ComponentType<P>): React.ComponentType<P> {
  return function Localized(props: P) { useLocale(); return React.createElement(Component, props) }
}

export async function loadExtensions(modules: ModuleRecord<DisplayText>[]): Promise<LoadedExtensions> {
  const extensions: Required<LoadedExtensions> = { actions: [], resultActions: [], editors: [], viewers: [] }
  for (const module of modules.filter(item => item.enabled && item.available !== false && item.ui_url).sort((a, b) => a.id.localeCompare(b.id))) {
    const entry: ModuleEntry = await import(/* @vite-ignore */ module.ui_url!)
    if (entry.runtime?.react !== 19 || typeof entry.register !== 'function') throw new Error(t("ui_must_export_runtime_react_19_and", {"0": text(module.name)}))
    const result = entry.register({ React, i18n })
    extensions.resultActions.push(...(result.resultActions ?? []).map(item => ({ ...item, component: localized(item.component), installation_id: module.installation_id })))
    extensions.actions.push(...(result.actions ?? []).map(item => ({ ...item, component: localized(item.component), installation_id: module.installation_id })))
    extensions.editors.push(...(result.editors ?? []).map(item => ({ ...item, component: localized(item.component), installation_id: module.installation_id })))
    extensions.viewers.push(...(result.viewers ?? []).map(item => ({ ...item, component: localized(item.component), installation_id: module.installation_id })))
  }
  for (const values of [extensions.actions, extensions.resultActions, extensions.viewers]) {
    const identities = values.map(value => value.id)
    if (new Set(identities).size !== identities.length) throw new Error(t("module_ui_declares_duplicate_action_or_viewer"))
  }
  const editors = extensions.editors.map(value => value.node)
  if (new Set(editors).size !== editors.length) throw new Error(t("more_than_one_configuration_editor_declares_the"))
  extensions.viewers.sort((a, b) => a.id.localeCompare(b.id))
  return extensions
}
