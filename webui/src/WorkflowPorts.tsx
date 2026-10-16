import { useLayoutEffect, useRef } from 'react'
import { Handle, Position, useConnection, useUpdateNodeInternals, type Node } from '@xyflow/react'
import type { PortPresentation } from './workflow-authoring'
import { workflowPortsMatch } from './workflow-connections'

export interface PortSource { nodeId: string; outputPort: string; internal?: boolean }

interface WorkflowPortsProps {
  nodeId: string
  inputs: PortPresentation[]
  outputs: PortPresentation[]
  collapsed: boolean
  readOnly?: boolean
  prompt: boolean
  sources: Record<string, PortSource[]>
}

type PortNode = Node<{ inputs: PortPresentation[]; outputs: PortPresentation[]; collapsed: boolean }>
const primaryPromptPorts = new Set(['sequence_source', 'structure_source', 'prompt_source'])

export function WorkflowPorts({ nodeId, inputs, outputs, collapsed, prompt, sources, readOnly = false }: WorkflowPortsProps) {
  const container = useRef<HTMLDivElement>(null)
  const updateNodeInternals = useUpdateNodeInternals()
  const connection = useConnection<PortNode>()

  useLayoutEffect(() => {
    const element = container.current!
    let frame = 0
    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => updateNodeInternals(nodeId))
    }
    const observer = new ResizeObserver(update)
    observer.observe(element)
    element.querySelectorAll('.workflow-port, .workflow-port-row').forEach((row) => observer.observe(row))
    update()
    return () => { observer.disconnect(); cancelAnimationFrame(frame) }
  }, [nodeId, inputs, outputs, collapsed, prompt, updateNodeInternals])

  function renderPort(port: PortPresentation, direction: 'input' | 'output') {
    const input = direction === 'input'
    const handleType = input ? 'target' : 'source'
    let match: boolean | null = null
    if (!collapsed && connection.inProgress && !connection.fromNode.data.collapsed && connection.fromNode.id !== nodeId && connection.fromHandle.type !== handleType) {
      const originInput = connection.fromHandle.type === 'target'
      const originPorts = originInput ? connection.fromNode.data.inputs : connection.fromNode.data.outputs
      const origin = originPorts.find((candidate) => `${originInput ? 'in' : 'out'}-${candidate.name}` === connection.fromHandle.id)!
      const sourcePort = input ? origin : port
      const targetPort = input ? port : origin
      match = workflowPortsMatch(sourcePort, targetPort)
    }
    const matchClass = match === null ? '' : match ? 'port-compatible' : 'port-incompatible'
    const handle = <Handle id={`${input ? 'in' : 'out'}-${port.name}`} type={handleType} position={input ? Position.Left : Position.Right} isConnectable={!collapsed && !readOnly && !port.missing} isConnectableStart={!collapsed && !readOnly && !port.missing} isConnectableEnd={!collapsed && !readOnly && !port.missing} className={`node-handle ${direction}-handle ${matchClass}`} aria-label={`${port.name} ${input ? '输入' : '输出'}`} />
    if (collapsed) return <div className={`port workflow-port-row collapsed-port-row ${direction}-port`} key={port.name} data-port-name={port.name} data-direction={direction}>{handle}</div>
    const orderedSources = sources[port.name] ?? []
    return <details key={port.name} className={`workflow-port nodrag nowheel ${direction}-port ${matchClass}`}>
      <summary className="port workflow-port-row" data-port-name={port.name} data-direction={direction} aria-label={`${port.name} 端口详情`}>
        {handle}
        <span className="port-name">{port.label ?? port.name}</span>
        <span className="port-type">{port.missing ? '模块缺失' : port.portTypeId.slice(port.portTypeId.lastIndexOf('.') + 1).replace(/_/g, ' ')}</span>
        <span className="port-rules">{port.missing ? '契约待恢复' : `${port.required ? '必选' : '可选'} · ${port.multiplicity === 'many' ? '多值' : '单值'}`}<span aria-hidden="true"> ⓘ</span></span>
        <span className="port-match-hint" aria-hidden={!match}>{match ? '端口匹配' : '\u00a0'}</span>
      </summary>
      <div className="port-details">
        <code>{port.portTypeId}</code>
        <p>{port.meaning}</p>
        {input && <><span>{port.multiplicity === 'many' ? '来源（按输入顺序）' : '来源'}</span>{orderedSources.length ? <ol>{orderedSources.map((source) => <li key={JSON.stringify([source.nodeId, source.outputPort])}><code>{source.nodeId} · {source.outputPort}{source.internal === undefined ? '' : source.internal ? ' · 组内' : ' · 组外'}</code></li>)}</ol> : <p>尚未连接</p>}</>}
      </div>
    </details>
  }

  return <div ref={container} className={`workflow-ports ${collapsed ? 'collapsed-ports' : ''}`}>
    <div className="workflow-ports-column">
      {prompt && !collapsed ? <>
        <div className="prompt-primary-ports" role="group" aria-label="Prompt 主来源">
          <p className="port-group-hint">主来源：最多选择一个；全部不选表示空白</p>
          {inputs.filter((port) => primaryPromptPorts.has(port.name)).map((port) => renderPort(port, 'input'))}
        </div>
        {inputs.filter((port) => !primaryPromptPorts.has(port.name)).map((port) => <div key={port.name}>{port.name === 'merge_sources' && <p className="port-group-hint">合并来源：有序多来源</p>}{renderPort(port, 'input')}</div>)}
      </> : inputs.map((port) => renderPort(port, 'input'))}
    </div>
    <div className="workflow-ports-column">{outputs.map((port) => renderPort(port, 'output'))}</div>
    {collapsed && <small className="collapsed-port-hint">展开后编辑连线</small>}
  </div>
}
