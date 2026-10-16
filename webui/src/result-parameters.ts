import type { WorkflowCommitSnapshot } from './project-workspace'
import type { PublicV2Client, ResultLocation, RunProjection, Workflow, WorkflowNode } from './protocol/client'

type RecordedParameters = Pick<WorkflowNode, 'node_parameters' | 'binding_parameters'>
type ParameterRecord = WorkflowNode & {
  record_id: string
  project_id: string
  run_id: string
  workflow_commit_id: string
  admitted_parameters: RecordedParameters | null
}
export type ComputationParameters = {
  records: ParameterRecord[]
  outputs: Array<{
    source: ResultLocation
    producer_run_id: string | null
    status: 'recorded' | 'unavailable'
    parameter_record_ids: string[]
  }>
  workflows: Array<{ project_id: string; run_id: string; workflow_commit_id: string; workflow: Workflow }>
}

/** Only absence of an existing source record is an exportable missing-record outcome. */
async function existingRecord<T>(read: Promise<T>): Promise<T | undefined> {
  try { return await read } catch (error) {
    const code = (error as { error?: { code?: string } })?.error?.code
    if (code === 'run_not_found' || code === 'workflow_commit_not_found') return undefined
    throw error
  }
}

/** Read immutable producer records; a cache replay's publishing Commit is not its producer. */
export async function readComputationParameters(client: PublicV2Client, run: RunProjection, commit: WorkflowCommitSnapshot): Promise<ComputationParameters> {
  const records = new Map<string, ParameterRecord>()
  const workflows: ComputationParameters['workflows'] = []
  const producers = new Map<string, { run: RunProjection; commit: WorkflowCommitSnapshot }>()
  const commits = new Map<string, WorkflowCommitSnapshot>([[commit.workflow_commit_id, commit]])
  const producerIds = [...new Set(run.outputs.map(output => output.producer_provenance.producer_run_id as string | undefined).filter((id): id is string => id !== undefined))]
  for (const producerId of producerIds) {
    const producer = producerId === run.run_id ? run : await existingRecord(client.runProjection(run.project_id, producerId))
    if (!producer) continue
    const saved = commits.get(producer.workflow_commit_id) ?? await existingRecord(client.workflowCommit(producer.project_id, producer.workflow_commit_id))
    if (!saved) continue
    commits.set(saved.workflow_commit_id, saved)
    producers.set(producerId, { run: producer, commit: saved })
    workflows.push({ project_id: producer.project_id, run_id: producer.run_id, workflow_commit_id: saved.workflow_commit_id, workflow: saved.workflow })
  }
  const outputs: ComputationParameters['outputs'] = run.outputs.flatMap(output => {
    const producerId = output.producer_provenance.producer_run_id as string | undefined
    const producer = producerId === undefined ? undefined : producers.get(producerId)
    const matches = producer?.run.outputs.filter(original => original.result_identity === output.result_identity && original.output_port === output.output_port && original.producer_provenance.producer_run_id === producerId) ?? []
    const ids = [...new Set(matches.flatMap(original => {
      const node = producer!.commit.workflow.nodes.find(item => item.node_id === original.node_id)
      if (!node) return []
      const recordId = JSON.stringify([producer!.run.project_id, producerId, node.node_id])
      const admitted = (producer!.commit.scientific_identity.nodes as Array<RecordedParameters & { node_id: string }> | undefined)?.find(item => item.node_id === node.node_id)
      records.set(recordId, {
        record_id: recordId, project_id: producer!.run.project_id, run_id: producerId!, workflow_commit_id: producer!.commit.workflow_commit_id,
        node_id: node.node_id, node_type_id: node.node_type_id, binding_id: node.binding_id,
        node_parameters: node.node_parameters, binding_parameters: node.binding_parameters,
        admitted_parameters: admitted ? { node_parameters: admitted.node_parameters, binding_parameters: admitted.binding_parameters } : null,
      })
      return [recordId]
    }))]
    return Array.from({ length: output.value_count }, (_, value_index) => ({
      source: { node_id: output.node_id, output_port: output.output_port, value_index },
      producer_run_id: producerId ?? null, status: ids.length ? 'recorded' as const : 'unavailable' as const, parameter_record_ids: ids,
    }))
  })
  return { records: [...records.values()], outputs, workflows }
}
