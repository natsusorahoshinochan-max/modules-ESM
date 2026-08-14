export interface ContractReference {
  contract_kind: string;
  contract_id: string;
  contract_version: string;
  contract_digest: string;
}

export interface TypedOutputDescriptor {
  node_id: string;
  output_port: string;
  port_type: ContractReference;
  content_digest: string;
  value_count: number;
  value_manifest_reference: string;
  result_identity: string;
  materialization: {
    run_id: string;
    resolution: "executed" | "cache_replayed";
  };
  producer_provenance: {
    producer_run_id: string;
    producer_result_identity: string;
    output_port: string;
  };
}

export interface RetrievedTypedValue {
  canonicalBytes: Uint8Array;
  contentDigest: string;
  size: number;
  portContentDigest: string;
  portType: ContractReference;
  valueManifestReference: string;
  valueIndex: number;
  valueCount: number;
}

export async function fetchTypedOutputValue(
  projectId: string,
  runId: string,
  output: TypedOutputDescriptor,
  valueIndex: number,
): Promise<RetrievedTypedValue> {
  const route = [
    "/api/v2/projects",
    encodeURIComponent(projectId),
    "runs",
    encodeURIComponent(runId),
    "outputs",
    encodeURIComponent(output.node_id),
    encodeURIComponent(output.output_port),
    "values",
    String(valueIndex),
  ].join("/");
  const response = await fetch(route);
  if (!response.ok) {
    throw new Error(`Typed value retrieval failed (${response.status})`);
  }
  const canonicalBytes = new Uint8Array(await response.arrayBuffer());
  return {
    canonicalBytes,
    contentDigest: response.headers.get("Digest")!,
    size: Number(response.headers.get("Content-Length")),
    portContentDigest: response.headers.get("X-Port-Content-Digest")!,
    portType: {
      contract_kind: response.headers.get("X-Port-Type-Kind")!,
      contract_id: response.headers.get("X-Port-Type-Id")!,
      contract_version: response.headers.get("X-Port-Type-Version")!,
      contract_digest: response.headers.get("X-Port-Type-Digest")!,
    },
    valueManifestReference: response.headers.get(
      "X-Value-Manifest-Reference",
    )!,
    valueIndex: Number(response.headers.get("X-Value-Index")),
    valueCount: Number(response.headers.get("X-Value-Count")),
  };
}
