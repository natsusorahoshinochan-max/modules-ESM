import { useEffect, useRef, useState } from 'react'
import type { ModuleEditorProps } from '../../../webui/src/module-ui'
import type { PromptSnapshot, Workflow } from '../../../webui/src/protocol/client'
import { InputSourceDialog } from '../../../webui/src/InputSourceDialog'
import { PromptStudio } from './PromptStudio'

export function PromptEditor({ workflow: initialWorkflow, nodeId, client, catalog, versionContext, onApply, onCancel }: ModuleEditorProps) {
  const [workflow, setWorkflow] = useState(initialWorkflow)
  const [snapshot, setSnapshot] = useState<PromptSnapshot>()
  const [error, setError] = useState('')
  const [sourceWorkflow, setSourceWorkflow] = useState<Workflow>()
  const completion = useRef<((snapshot: PromptSnapshot | undefined) => void) | undefined>(undefined)
  const [request, setRequest] = useState(0)
  useEffect(() => {
    let current = true
    setError('')
    void client.openPrompt(initialWorkflow.workflow_id, nodeId, initialWorkflow).then(value => { if (current) setSnapshot(value) }, reason => { if (current) setError(reason instanceof Error ? reason.message : reason.error.message) })
    return () => { current = false; completion.current?.(undefined) }
  }, [initialWorkflow, nodeId, client, request])
  if (!snapshot) return error ? <div role="alert">{error}<button onClick={() => setRequest(request + 1)}>重新打开</button><button onClick={onCancel}>取消</button></div> : <p role="status">正在打开 Prompt…</p>
  return <><PromptStudio snapshot={snapshot} onCancel={onCancel}
    onPreview={document => client.previewPrompt(workflow.workflow_id, nodeId, document, workflow, versionContext)}
    onApply={preview => onApply({ ...workflow, nodes: workflow.nodes.map(node => node.node_id === nodeId ? { ...node, node_parameters: { ...node.node_parameters, document: preview.normalized_document } } : node) })}
    onAddMergeSource={document => new Promise(resolve => {
      completion.current = resolve
      setSourceWorkflow({ ...workflow, nodes: workflow.nodes.map(node => node.node_id === nodeId ? { ...node, node_parameters: { ...node.node_parameters, document } } : node) })
    })} />
    {sourceWorkflow && <InputSourceDialog projectId={workflow.workflow_id} workflow={sourceWorkflow} catalog={catalog} client={client}
      preparePublication={async () => ({ projectId: workflow.workflow_id, workflow: sourceWorkflow })}
      onRetrySave={async () => {}}
      mergeTargetNodeId={nodeId}
      onImportCandidates={async () => { throw new Error('请选择 Prompt 来源。') }}
      onPreparePrompt={async plan => {
        const next = await client.openPrompt(plan.workflow.workflow_id, nodeId, plan.workflow)
        setWorkflow(plan.workflow); setSnapshot(next); setSourceWorkflow(undefined)
        completion.current?.(next); completion.current = undefined
      }}
      onClose={() => { setSourceWorkflow(undefined); completion.current?.(undefined); completion.current = undefined }} />}
  </>
}
