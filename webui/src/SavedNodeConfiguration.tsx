import type { WorkflowNode } from './protocol/client'

/** Display saved opaque configuration without applying an active module's schema. */
export function SavedNodeConfiguration({ node, missingContracts, collapsed = false }: { node: WorkflowNode; missingContracts: string[]; collapsed?: boolean }) {
  if (!node.preserved_configuration && !missingContracts.length) return null
  const saved = { node_type_id: node.node_type_id, binding_id: node.binding_id, node_parameters: node.node_parameters, binding_parameters: node.binding_parameters, ...(node.preserved_configuration ? { preserved_configuration: node.preserved_configuration } : {}) }
  return <>
    <p className="parameter-empty-hint" role="status">{node.preserved_configuration ? `不可运行：${node.preserved_configuration.reason}` : `缺失模块：${missingContracts.join('、')}。已保留配置；安装并启用兼容模块后重新打开项目。`}</p>
    {!collapsed && <details className="nodrag nowheel" open={!!node.preserved_configuration}><summary>已保留配置</summary><pre>{JSON.stringify(saved, null, 2)}</pre></details>}
  </>
}
