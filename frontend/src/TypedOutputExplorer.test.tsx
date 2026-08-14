// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TypedOutputExplorer from "./TypedOutputExplorer";

describe("current Run evidence retrieval", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads bounded descriptors and retrieves one canonical value", async () => {
    const requests: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        requests.push(url);
        if (url === "/api/v2/projects/project-one/runs/run-one") {
          return new Response(
            JSON.stringify({
              outputs: [
                {
                  node_id: "node-one",
                  output_port: "confidence",
                  port_type: {
                    contract_kind: "port_type",
                    contract_id: "protein.confidence_facts",
                    contract_version: "1.0.0",
                    contract_digest: "sha256:port-type",
                  },
                  content_digest: "sha256:port",
                  value_count: 2,
                  value_manifest_reference: "sha256:manifest",
                  result_identity: "sha256:result",
                  materialization: {
                    run_id: "run-one",
                    resolution: "executed",
                  },
                  producer_provenance: {
                    producer_run_id: "run-one",
                    producer_result_identity: "sha256:result",
                    output_port: "confidence",
                  },
                },
              ],
              artifact_index: [
                {
                  artifact_reference: "sha256:artifact",
                  node_id: "node-one",
                  output_port: "structure",
                  filename: "prediction.pdb",
                  media_type: "chemical/x-pdb",
                  size: 64,
                  content_digest: "sha256:artifact",
                },
              ],
            }),
            { headers: { "Content-Type": "application/json" } },
          );
        }
        if (
          url ===
          "/api/v2/projects/project-one/runs/run-one/outputs/" +
            "node-one/confidence/values/1"
        ) {
          return new Response(new TextEncoder().encode('{"pae":[[0.0]]}'), {
            headers: {
              Digest: "sha256:value",
              "Content-Length": "19",
              "X-Port-Content-Digest": "sha256:port",
              "X-Port-Type-Kind": "port_type",
              "X-Port-Type-Id": "protein.confidence_facts",
              "X-Port-Type-Version": "1.0.0",
              "X-Port-Type-Digest": "sha256:port-type",
              "X-Value-Manifest-Reference": "sha256:manifest",
              "X-Value-Index": "1",
              "X-Value-Count": "2",
            },
          });
        }
        throw new Error(`Unexpected request ${url}`);
      }),
    );

    render(
      <TypedOutputExplorer
        activeProjectId="project-one"
        activeRunId="run-one"
      />,
    );
    fireEvent.click(await screen.findByText("Load outputs"));
    expect(await screen.findByText("protein.confidence_facts@1.0.0")).not.toBeNull();
    expect(screen.getAllByText("sha256:result")).toHaveLength(2);
    const artifact = screen.getByRole("link", { name: "prediction.pdb" });
    expect(artifact.getAttribute("href")).toBe(
      "/api/v2/projects/project-one/runs/run-one/artifacts/sha256%3Aartifact",
    );

    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "1" } });
    fireEvent.click(screen.getByText("Retrieve value"));
    expect(await screen.findByText('{"pae":[[0.0]]}')).not.toBeNull();
    await waitFor(() => expect(requests).toHaveLength(2));
  });
});
