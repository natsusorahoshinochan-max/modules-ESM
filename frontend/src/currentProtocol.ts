export interface ContractReference {
  contract_kind: string;
  contract_id: string;
  contract_version: string;
  contract_digest: string;
}

interface PublicPort {
  name: string;
  port_type: ContractReference;
  required: boolean;
  multiplicity: "one" | "many";
  scientific_meaning: string;
}

interface NodeTypeDescriptor {
  contract_kind: "node_type";
  contract_id: string;
  contract_version: string;
  title: string;
  summary: string;
  category: string;
  inputs: PublicPort[];
  outputs: PublicPort[];
  node_parameters: Record<string, ParameterDefinition>;
}

interface BindingDescriptor {
  contract_kind: "binding";
  contract_id: string;
  contract_version: string;
  node_type: ContractReference;
  binding_parameters: Record<string, ParameterDefinition>;
}

export interface ParameterDefinition {
  required?: boolean;
  default?: unknown;
  scientific_meaning?: string;
  value_contract?: {
    type?: string;
    enum?: unknown[];
    minimum?: number;
    maximum?: number;
  };
}

interface PublicContract {
  reference: ContractReference;
  descriptor: Record<string, unknown>;
}

interface AvailabilitySnapshot {
  binding: ContractReference;
  available: boolean;
}

export interface CatalogSnapshot {
  contracts: PublicContract[];
  availability: AvailabilitySnapshot[];
}

export interface NodeParameterView {
  name: string;
  type: string;
  default: unknown;
  display_name: string;
  description: string;
  min?: number;
  max?: number;
  options?: unknown[];
  required: boolean;
}

export interface BindingView {
  binding_id: string;
  binding_version: string;
  available: boolean;
  parameters: Record<string, ParameterDefinition>;
}

export interface NodeTypeView {
  node_type_id: string;
  node_type_version: string;
  display_name: string;
  category: string;
  description: string;
  input_ports: { name: string; type_id: string; display_name: string }[];
  output_ports: { name: string; type_id: string; display_name: string }[];
  parameters: NodeParameterView[];
  bindings: BindingView[];
}

export interface WorkflowNode {
  node_id: string;
  node_type_id: string;
  node_type_version: string;
  binding_id: string;
  binding_version: string;
  node_parameters: Record<string, unknown>;
  binding_parameters: Record<string, unknown>;
}

export interface WorkflowDocument {
  schema_version: "2.1.0";
  workflow_id: string;
  nodes: WorkflowNode[];
  edges: {
    source_node_id: string;
    source_port: string;
    target_node_id: string;
    target_port: string;
  }[];
  contract_lock: Record<string, unknown>[];
  observation_selectors: Record<string, unknown>[];
  selection_objectives: Record<string, unknown>[];
}

export interface ProjectWorkflowDraft {
  draft_revision: number;
  workflow: WorkflowDocument;
}

export interface ProjectMetadata {
  id: string;
}

export interface WorkflowCommit {
  workflow_commit_id: string;
  source_draft_revision: number;
}

export interface RunReceipt {
  run_id: string;
}

interface StructuredErrorEnvelope {
  error: { message: string };
}

export async function requestJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(input, init);
  const payload = (await response.json()) as T | StructuredErrorEnvelope;
  if (!response.ok) {
    throw new Error((payload as StructuredErrorEnvelope).error.message);
  }
  return payload as T;
}

function contractKey(
  contractKind: string,
  contractId: string,
  contractVersion: string,
): string {
  return [contractKind, contractId, contractVersion].join(":");
}

export function parameterValues(
  definitions: Record<string, ParameterDefinition>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(definitions)
      .filter(([, definition]) => "default" in definition)
      .map(([name, definition]) => [name, definition.default]),
  );
}

export function catalogNodeTypes(snapshot: CatalogSnapshot): NodeTypeView[] {
  const availability = new Map(
    snapshot.availability.map((item) => [
      contractKey(
        item.binding.contract_kind,
        item.binding.contract_id,
        item.binding.contract_version,
      ),
      item.available,
    ]),
  );
  const bindings = snapshot.contracts
    .map((contract) => contract.descriptor)
    .filter((descriptor) => descriptor.contract_kind === "binding")
    .map((descriptor) => descriptor as unknown as BindingDescriptor);
  return snapshot.contracts
    .map((contract) => contract.descriptor)
    .filter((descriptor) => descriptor.contract_kind === "node_type")
    .map((descriptor) => descriptor as unknown as NodeTypeDescriptor)
    .map((descriptor) => ({
      node_type_id: descriptor.contract_id,
      node_type_version: descriptor.contract_version,
      display_name: descriptor.title,
      category: descriptor.category,
      description: descriptor.summary,
      input_ports: descriptor.inputs.map((port) => ({
        name: port.name,
        type_id: `${port.port_type.contract_id}@${port.port_type.contract_version}`,
        display_name: port.name,
      })),
      output_ports: descriptor.outputs.map((port) => ({
        name: port.name,
        type_id: `${port.port_type.contract_id}@${port.port_type.contract_version}`,
        display_name: port.name,
      })),
      parameters: Object.entries(descriptor.node_parameters).map(
        ([name, definition]) => ({
          name,
          type: definition.value_contract!.type!,
          default: definition.default,
          display_name: name,
          description: definition.scientific_meaning!,
          min: definition.value_contract?.minimum,
          max: definition.value_contract?.maximum,
          options: definition.value_contract?.enum,
          required: definition.required ?? false,
        }),
      ),
      bindings: bindings
        .filter(
          (binding) =>
            binding.node_type.contract_id === descriptor.contract_id &&
            binding.node_type.contract_version === descriptor.contract_version,
        )
        .map((binding) => {
          const key = contractKey(
            "binding",
            binding.contract_id,
            binding.contract_version,
          );
          const available = availability.get(key);
          if (available === undefined) {
            throw new Error(
              `Catalog omitted Availability for ${binding.contract_id}@${binding.contract_version}`,
            );
          }
          return {
            binding_id: binding.contract_id,
            binding_version: binding.contract_version,
            available,
            parameters: binding.binding_parameters,
          };
        }),
    }));
}

export function groupNodeTypesByCategory(
  nodeTypes: NodeTypeView[],
): Map<string, NodeTypeView[]> {
  const grouped = new Map<string, NodeTypeView[]>();
  for (const nodeType of nodeTypes) {
    const group = grouped.get(nodeType.category) ?? [];
    group.push(nodeType);
    grouped.set(nodeType.category, group);
  }
  return grouped;
}

export function encodeFileContent(bytes: Uint8Array): string {
  const chunks: string[] = [];
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    chunks.push(
      String.fromCharCode(...bytes.subarray(offset, offset + chunkSize)),
    );
  }
  return btoa(chunks.join(""));
}
