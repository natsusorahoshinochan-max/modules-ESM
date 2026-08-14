// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const catalog = {
  contracts: [
    {
      reference: {
        contract_kind: "node_type",
        contract_id: "test.predict",
        contract_version: "1.0.0",
        contract_digest: "sha256:node-type",
      },
      descriptor: {
        contract_kind: "node_type",
        contract_id: "test.predict",
        contract_version: "1.0.0",
        title: "Test prediction",
        summary: "Predict a test value.",
        category: "Test",
        inputs: [],
        outputs: [],
        node_parameters: {},
      },
    },
    ...["test.local", "test.remote"].map((bindingId) => ({
      reference: {
        contract_kind: "binding",
        contract_id: bindingId,
        contract_version: "1.0.0",
        contract_digest: `sha256:${bindingId}`,
      },
      descriptor: {
        contract_kind: "binding",
        contract_id: bindingId,
        contract_version: "1.0.0",
        node_type: {
          contract_kind: "node_type",
          contract_id: "test.predict",
          contract_version: "1.0.0",
          contract_digest: "sha256:node-type",
        },
        binding_parameters: {},
      },
    })),
  ],
  availability: [
    {
      binding: {
        contract_kind: "binding",
        contract_id: "test.local",
        contract_version: "1.0.0",
        contract_digest: "sha256:test.local",
      },
      available: false,
    },
    {
      binding: {
        contract_kind: "binding",
        contract_id: "test.remote",
        contract_version: "1.0.0",
        contract_digest: "sha256:test.remote",
      },
      available: true,
    },
  ],
};

class TestWebSocket {
  static instances: TestWebSocket[] = [];
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: (() => void) | null = null;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    TestWebSocket.instances.push(this);
  }

  close() {
    this.onclose?.();
  }

  emit(event: unknown) {
    this.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify({ event }) }),
    );
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("current public workflow journey", () => {
  beforeEach(() => {
    TestWebSocket.instances = [];
    vi.stubGlobal("WebSocket", TestWebSocket);
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    vi.spyOn(window, "prompt").mockReturnValue("project-one");
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("requires an explicit Binding choice and applies disposition events", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v2/catalog") return jsonResponse(catalog);
        if (url === "/api/v2/projects") {
          return jsonResponse({ id: "project-one" });
        }
        if (url.endsWith("/workflow:commit")) {
          return jsonResponse({
            workflow_commit_id: "commit-one",
            source_draft_revision: 0,
          });
        }
        if (url.endsWith("/runs")) return jsonResponse({ run_id: "run-one" });
        if (url.endsWith("/runs/run-one:cancel")) return jsonResponse({});
        throw new Error(`Unexpected request ${url}`);
      }),
    );

    render(<App />);
    await waitFor(() =>
      expect((screen.getByText("+ Add Node") as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByText("New Project"));
    await waitFor(() =>
      expect(requests.some(({ url }) => url === "/api/v2/projects")).toBe(true),
    );

    fireEvent.click(screen.getByText("+ Add Node"));
    expect(await screen.findByRole("button", { name: /test\.local@1\.0\.0/i })).not.toBeNull();
    expect(screen.getByRole("button", { name: /test\.remote@1\.0\.0/i })).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /test\.local@1\.0\.0/i }));

    fireEvent.click(screen.getByText("▶ Run Workflow"));
    await waitFor(() => expect(TestWebSocket.instances).toHaveLength(1));
    expect(TestWebSocket.instances[0].url).toContain(
      "/api/v2/projects/project-one/runs/run-one/events",
    );
    const commit = requests.find(({ url }) => url.endsWith("/workflow:commit"));
    expect(JSON.parse(String(commit?.init?.body)).workflow.nodes[0].binding_id).toBe(
      "test.local",
    );
    fireEvent.click(screen.getByText("Cancel Run"));
    await waitFor(() =>
      expect(
        requests.some(({ url }) => url.endsWith("/runs/run-one:cancel")),
      ).toBe(true),
    );

    act(() => {
      TestWebSocket.instances[0].emit({
        type: "node_disposition",
        disposition: { node_id: "node_0", outcome: "succeeded" },
      });
    });
    expect(await screen.findByText("[completed]", { exact: false })).not.toBeNull();
  });

  it("preserves Workflow-owned selection semantics across open and save", async () => {
    const contractLock: Record<string, unknown>[] = [];
    const metric = {
      contract_kind: "metric",
      contract_id: "contract_test.multi_objective_selection_score",
      contract_version: "3.0.0",
      contract_digest:
        "sha256:4110d38760eb29abeacc04efb3e03fee325320dd011024529687f4d3b78d6f11",
    };
    const method = {
      contract_kind: "method",
      contract_id: "contract_test.multi_objective_selection_source.method",
      contract_version: "2.1.0",
      contract_digest:
        "sha256:98821cca8e002d801201078a79e4e6be557a13193615208d1a9b0f102806d991",
    };
    const candidateInput = {
      node_id: "canonical-source",
      output_port: "candidates",
    };
    const scoreCollectionInput = {
      node_id: "canonical-scores",
      output_port: "scores",
    };
    const contextSelector = {
      kind: "pairwise",
      subject_role: "subject",
      reference_role: "reference",
      pairing_mode: "fixed_reference",
      normalization: "literal-unit-interval",
    };
    const observationSelectors = [
      {
        selector_id: "fixed-3gb1-raw",
        candidate_input: candidateInput,
        score_collection_input: scoreCollectionInput,
        source_partition: "canonical.selection_score.fixed_3gb1",
        metric,
        method,
        context_selector: contextSelector,
        match_cardinality: "exactly_one",
        missing_policy: "error",
      },
    ];
    const selectionObjectives = [
      {
        objective_id: "sort-fixed-3gb1",
        candidate_input: candidateInput,
        score_collection_input: scoreCollectionInput,
        source_partition: "canonical.selection_score.fixed_3gb1",
        metric,
        method,
        context_selector: contextSelector,
        utility_transform: {
          contract_kind: "utility_transform",
          contract_id:
            "contract_test.multi_objective_selection_score.fixed_3gb1.identity",
          contract_version: "3.0.0",
          contract_digest:
            "sha256:59b37204cccee949ac0d155882fb852d35eadf71707693ed9048f47f6fd1d117",
        },
        utility_parameters: {},
        weight: 0.7,
        match_cardinality: "exactly_one",
        missing_policy: "error",
      },
    ];
    let savedWorkflow: Record<string, unknown> | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/v2/catalog") return jsonResponse(catalog);
        if (url.endsWith("/workflow/draft") && init === undefined) {
          return jsonResponse({
            draft_revision: 4,
            workflow: {
              schema_version: "2.1.0",
              workflow_id: "project-one",
              nodes: [],
              edges: [],
              contract_lock: contractLock,
              observation_selectors: observationSelectors,
              selection_objectives: selectionObjectives,
            },
          });
        }
        if (url.endsWith("/workflow/draft") && init?.method === "PUT") {
          savedWorkflow = JSON.parse(String(init.body)).workflow;
          return jsonResponse({
            draft_revision: 5,
            workflow: savedWorkflow,
          });
        }
        throw new Error(`Unexpected request ${url}`);
      }),
    );

    render(<App />);
    fireEvent.click(await screen.findByText("Open"));
    await waitFor(() =>
      expect((screen.getByText("Save Draft") as HTMLButtonElement).disabled).toBe(
        false,
      ),
    );
    fireEvent.click(screen.getByText("Save Draft"));
    await waitFor(() => expect(savedWorkflow).not.toBeNull());
    expect(savedWorkflow).toMatchObject({
      contract_lock: contractLock,
      observation_selectors: observationSelectors,
      selection_objectives: selectionObjectives,
    });
  });
});
