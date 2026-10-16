import type { WorkflowCommitSnapshot } from './project-workspace'
import type { AdoptionMetadata, JsonObject, PublicV2Client, ResultLocation, RunProjection, Workflow, WorkflowNode } from './protocol/client'

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
    status: 'recorded' | 'ambiguous' | 'unavailable'
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
  const adoptedInputs = new Map<string, AdoptionMetadata>()
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
  const outputs: ComputationParameters['outputs'] = []
  for (const output of run.outputs) {
    const producerId = output.producer_provenance.producer_run_id as string | undefined
    const producer = producerId === undefined ? undefined : producers.get(producerId)
    const matches = producer?.run.outputs.filter(original =>
      original.materialization.resolution === 'executed'
      && original.result_identity === output.result_identity
      && original.output_port === output.output_port
      && original.content_digest === output.content_digest
      && original.value_manifest_reference === output.value_manifest_reference
      && original.producer_provenance.producer_run_id === producerId
      && (output.materialization.resolution !== 'executed' || original.node_id === output.node_id),
    ) ?? []
    const matchingIds: string[] = []
    const statuses: AdoptionMetadata['parameters']['status'][] = []
    for (const original of matches) {
      const node = producer!.commit.workflow.nodes.find(item => item.node_id === original.node_id)
      if (!node) continue
      const definition = producer!.commit.scientific_definitions.find(item => item.contract_kind === 'node_type' && item.contract_id === node.node_type_id)
      if ((definition?.descriptor as JsonObject | undefined)?.restores_published_value === true) {
        const inputRef = node.node_parameters.project_input_ref as string
        const inputKey = JSON.stringify([producer!.run.project_id, inputRef])
        const metadata = adoptedInputs.get(inputKey) ?? await client.adoptionMetadata(producer!.run.project_id, inputRef)
        adoptedInputs.set(inputKey, metadata)
        statuses.push(metadata.parameters.status)
        for (const record of metadata.parameters.records) {
          const recordId = JSON.stringify([record.project_id, record.run_id, record.node_id])
          records.set(recordId, { ...record, record_id: recordId })
          matchingIds.push(recordId)
        }
        continue
      }
      const recordId = JSON.stringify([producer!.run.project_id, producerId, node.node_id])
      const admitted = (producer!.commit.scientific_identity.nodes as Array<RecordedParameters & { node_id: string }> | undefined)?.find(item => item.node_id === node.node_id)
      records.set(recordId, {
        record_id: recordId, project_id: producer!.run.project_id, run_id: producerId!, workflow_commit_id: producer!.commit.workflow_commit_id,
        node_id: node.node_id, node_type_id: node.node_type_id, binding_id: node.binding_id,
        node_parameters: node.node_parameters, binding_parameters: node.binding_parameters,
        admitted_parameters: admitted ? { node_parameters: admitted.node_parameters, binding_parameters: admitted.binding_parameters } : null,
      })
      matchingIds.push(recordId)
    }
    const ids = [...new Set(matchingIds)]
    const originalRuns = [...new Set(ids.map(id => records.get(id)!.run_id))]
    const status = statuses.includes('unavailable') || ids.length === 0 ? 'unavailable' as const
      : statuses.includes('ambiguous') || ids.length > 1 ? 'ambiguous' as const : 'recorded' as const
    outputs.push(...Array.from({ length: output.value_count }, (_, value_index) => ({
      source: { node_id: output.node_id, output_port: output.output_port, value_index },
      producer_run_id: statuses.length > 0 ? (originalRuns.length === 1 ? originalRuns[0] : null) : producerId ?? null, status, parameter_record_ids: ids,
    })))
  }
  return { records: [...records.values()], outputs, workflows }
}
