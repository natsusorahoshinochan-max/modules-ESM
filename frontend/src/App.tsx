import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  addEdge,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./App.css";
import WorkflowNode, { type WorkflowNodeData } from "./WorkflowNode";
import TypedOutputExplorer from "./TypedOutputExplorer";
import ParameterField from "./ParameterField";
import {
  catalogNodeTypes,
  encodeFileContent,
  groupNodeTypesByCategory,
  parameterValues,
  requestJson,
  type BindingView,
  type CatalogSnapshot,
  type NodeTypeView,
  type ProjectMetadata,
  type ProjectWorkflowDraft,
  type RunReceipt,
  type WorkflowCommit,
  type WorkflowDocument,
} from "./currentProtocol";
import {
  nodeStateFromRunEvent,
  type RunEventEnvelope,
} from "./runEvents";

interface NodeStateInfo {
  [nodeId: string]: string;
}

const STATE_COLORS: Record<string, string> = {
  idle: "#94a3b8",
  queued: "#3b82f6",
  running: "#eab308",
  completed: "#22c55e",
  failed: "#ef4444",
  cancelled: "#6b7280",
  blocked: "#374151",
  interrupted: "#a855f7",
};

const reactFlowNodeTypes = { workflowNode: WorkflowNode };

function nodeStyle(state: string, available: boolean) {
  return {
    border: available
      ? `2px solid ${STATE_COLORS[state] ?? STATE_COLORS.idle}`
      : "2px dashed #f59e0b",
    borderRadius: "6px",
    padding: "8px",
    background: available ? "#fff" : "#fffbeb",
    opacity: available ? 1 : 0.7,
  };
}

function firstUnoccupiedNodeId(nodes: Node<WorkflowNodeData>[]): string {
  const occupiedNodeIds = new Set(nodes.map((node) => node.id));
  let index = 0;
  while (occupiedNodeIds.has(`node_${index}`)) index += 1;
  return `node_${index}`;
}

export default function App() {
  const [nodes, setNodes, onNodesChange] =
    useNodesState<Node<WorkflowNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [nodeTypeViews, setNodeTypeViews] = useState<NodeTypeView[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [nodeStates, setNodeStates] = useState<NodeStateInfo>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [draftRevision, setDraftRevision] = useState(0);
  const [workflowSemantics, setWorkflowSemantics] = useState<
    Pick<
      WorkflowDocument,
      "contract_lock" | "observation_selectors" | "selection_objectives"
    >
  >({
    contract_lock: [],
    observation_selectors: [],
    selection_objectives: [],
  });
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const websocketRef = useRef<WebSocket | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void requestJson<CatalogSnapshot>("/api/v2/catalog")
      .then((snapshot) => setNodeTypeViews(catalogNodeTypes(snapshot)))
      .catch((failure: Error) => setError(failure.message));
  }, []);

  useEffect(() => {
    setNodes((current) =>
      current.map((node) => {
        const data = node.data;
        const state = nodeStates[node.id] ?? data.state;
        return {
          ...node,
          data: { ...data, state, label: `${data.nodeType.display_name} [${state}]` },
          style: nodeStyle(state, data.available),
        };
      }),
    );
  }, [nodeStates, setNodes]);

  const workflowDocument = useCallback(
    (id: string): WorkflowDocument => ({
      schema_version: "2.1.0",
      workflow_id: id,
      nodes: nodes.map((node) => {
        const data = node.data;
        return {
          node_id: node.id,
          node_type_id: data.nodeTypeId,
          node_type_version: data.nodeTypeVersion,
          binding_id: data.bindingId,
          binding_version: data.bindingVersion,
          node_parameters: data.nodeParameters,
          binding_parameters: data.bindingParameters,
        };
      }),
      edges: edges.map((edge) => ({
        source_node_id: edge.source,
        source_port: edge.sourceHandle ?? "",
        target_node_id: edge.target,
        target_port: edge.targetHandle ?? "",
      })),
      ...workflowSemantics,
    }),
    [edges, nodes, workflowSemantics],
  );

  const createProject = useCallback(async () => {
    const name = window.prompt("Project name:") ?? "Untitled";
    setError(null);
    try {
      const project = await requestJson<ProjectMetadata>("/api/v2/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      setProjectId(project.id);
      setDraftRevision(0);
      setActiveRunId(null);
      setWorkflowSemantics({
        contract_lock: [],
        observation_selectors: [],
        selection_objectives: [],
      });
      setNodes([]);
      setEdges([]);
    } catch (failure) {
      setError((failure as Error).message);
    }
  }, [setEdges, setNodes]);

  const openProject = useCallback(async () => {
    const requested = window.prompt("Project ID:");
    if (requested === null || requested === "") return;
    setError(null);
    try {
      const draft = await requestJson<ProjectWorkflowDraft>(
        `/api/v2/projects/${encodeURIComponent(requested)}/workflow/draft`,
      );
      const loadedNodes: Node<WorkflowNodeData>[] = draft.workflow.nodes.map(
        (workflowNode, index) => {
          const nodeType = nodeTypeViews.find(
            (candidate) =>
              candidate.node_type_id === workflowNode.node_type_id &&
              candidate.node_type_version === workflowNode.node_type_version,
          );
          if (nodeType === undefined) {
            throw new Error(
              `Inactive Node Type ${workflowNode.node_type_id}@${workflowNode.node_type_version}`,
            );
          }
          const binding = nodeType.bindings.find(
            (candidate) =>
              candidate.binding_id === workflowNode.binding_id &&
              candidate.binding_version === workflowNode.binding_version,
          );
          if (binding === undefined) {
            throw new Error(
              `Inactive Binding ${workflowNode.binding_id}@${workflowNode.binding_version}`,
            );
          }
          const data: WorkflowNodeData = {
            nodeTypeId: nodeType.node_type_id,
            nodeTypeVersion: nodeType.node_type_version,
            bindingId: binding.binding_id,
            bindingVersion: binding.binding_version,
            nodeType,
            nodeParameters: workflowNode.node_parameters,
            bindingParameters: workflowNode.binding_parameters,
            available: binding.available,
            state: "idle",
            label: `${nodeType.display_name} [idle]`,
            category: nodeType.category,
          };
          return {
            id: workflowNode.node_id,
            type: "workflowNode",
            position: {
              x: 100 + (index % 4) * 250,
              y: 100 + Math.floor(index / 4) * 150,
            },
            data,
            style: nodeStyle("idle", binding.available),
          };
        },
      );
      setProjectId(requested);
      setDraftRevision(draft.draft_revision);
      setActiveRunId(null);
      setWorkflowSemantics({
        contract_lock: draft.workflow.contract_lock,
        observation_selectors: draft.workflow.observation_selectors ?? [],
        selection_objectives: draft.workflow.selection_objectives ?? [],
      });
      setNodes(loadedNodes);
      setEdges(
        draft.workflow.edges.map((edge) => ({
          id: `edge_${edge.source_node_id}_${edge.source_port}_${edge.target_node_id}_${edge.target_port}`,
          source: edge.source_node_id,
          sourceHandle: edge.source_port,
          target: edge.target_node_id,
          targetHandle: edge.target_port,
          markerEnd: { type: MarkerType.ArrowClosed },
        })),
      );
    } catch (failure) {
      setError((failure as Error).message);
    }
  }, [nodeTypeViews, setEdges, setNodes]);

  const saveDraft = useCallback(async (): Promise<ProjectWorkflowDraft> => {
    if (projectId === null) throw new Error("Create or open a Project first");
    const draft = await requestJson<ProjectWorkflowDraft>(
      `/api/v2/projects/${encodeURIComponent(projectId)}/workflow/draft`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_draft_revision: draftRevision,
          workflow: workflowDocument(projectId),
        }),
      },
    );
    setDraftRevision(draft.draft_revision);
    return draft;
  }, [draftRevision, projectId, workflowDocument]);

  const handleSave = useCallback(async () => {
    setError(null);
    try {
      await saveDraft();
    } catch (failure) {
      setError((failure as Error).message);
    }
  }, [saveDraft]);

  const connectRunEvents = useCallback((id: string, runId: string) => {
    websocketRef.current?.close();
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(
      `${protocol}//${window.location.host}/api/v2/projects/` +
        `${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/events`,
    );
    socket.onmessage = (message) => {
      const envelope = JSON.parse(message.data) as RunEventEnvelope;
      const update = nodeStateFromRunEvent(envelope);
      if (update !== null) {
        setNodeStates((current) => ({
          ...current,
          [update.nodeId]: update.state,
        }));
      }
      if (envelope.event.type === "run_terminal") setIsRunning(false);
    };
    socket.onclose = () => {
      websocketRef.current = null;
    };
    websocketRef.current = socket;
  }, []);

  const runWorkflow = useCallback(async () => {
    if (projectId === null || nodes.length === 0) return;
    setError(null);
    setIsRunning(true);
    setNodeStates(
      Object.fromEntries(nodes.map((node) => [node.id, "queued"])),
    );
    try {
      const committed = await requestJson<WorkflowCommit>(
        `/api/v2/projects/${encodeURIComponent(projectId)}/workflow:commit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_draft_revision: draftRevision,
            workflow: workflowDocument(projectId),
          }),
        },
      );
      setDraftRevision(committed.source_draft_revision);
      const receipt = await requestJson<RunReceipt>(
        `/api/v2/projects/${encodeURIComponent(projectId)}/runs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            workflow_commit_id: committed.workflow_commit_id,
            client_request_id: `frontend-${crypto.randomUUID()}`,
          }),
        },
      );
      setActiveRunId(receipt.run_id);
      connectRunEvents(projectId, receipt.run_id);
    } catch (failure) {
      setIsRunning(false);
      setError((failure as Error).message);
    }
  }, [connectRunEvents, draftRevision, nodes, projectId, workflowDocument]);

  const cancelRun = useCallback(async () => {
    if (projectId === null || activeRunId === null) return;
    setError(null);
    try {
      await requestJson(
        `/api/v2/projects/${encodeURIComponent(projectId)}/runs/` +
          `${encodeURIComponent(activeRunId)}:cancel`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        },
      );
    } catch (failure) {
      setError((failure as Error).message);
    }
  }, [activeRunId, projectId]);

  const addNode = useCallback(
    (
      nodeType: NodeTypeView,
      binding: BindingView,
      overrides: Record<string, unknown> = {},
    ) => {
      const data: WorkflowNodeData = {
        nodeTypeId: nodeType.node_type_id,
        nodeTypeVersion: nodeType.node_type_version,
        bindingId: binding.binding_id,
        bindingVersion: binding.binding_version,
        nodeType,
        nodeParameters: {
          ...Object.fromEntries(
            nodeType.parameters
              .filter((parameter) => parameter.default !== undefined)
              .map((parameter) => [parameter.name, parameter.default]),
          ),
          ...overrides,
        },
        bindingParameters: parameterValues(binding.parameters),
        available: binding.available,
        state: "idle",
        label: `${nodeType.display_name} [idle]`,
        category: nodeType.category,
      };
      setNodes((current) => {
        const id = firstUnoccupiedNodeId(current);
        return [
          ...current,
          {
            id,
            type: "workflowNode",
            position: {
              x: 100 + Math.random() * 300,
              y: 100 + Math.random() * 200,
            },
            data,
            style: nodeStyle("idle", binding.available),
          },
        ];
      });
      setMenuOpen(false);
    },
    [setNodes],
  );

  const handleImport = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (file === undefined || projectId === null) return;
      setError(null);
      try {
        const publication = await requestJson<{ project_input_ref: string }>(
          `/api/v2/projects/${encodeURIComponent(projectId)}/inputs`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              filename: file.name,
              content_base64: encodeFileContent(
                new Uint8Array(await file.arrayBuffer()),
              ),
            }),
          },
        );
        const nodeTypeId = /\.(pdb|ent|cif)$/i.test(file.name)
          ? "protein_io.import_structure"
          : "protein_io.import_sequence";
        const nodeType = nodeTypeViews.find(
          (candidate) => candidate.node_type_id === nodeTypeId,
        );
        if (nodeType === undefined) throw new Error(`Missing active ${nodeTypeId}`);
        if (nodeType.bindings.length !== 1) {
          throw new Error(
            `${nodeTypeId} requires an explicit Binding choice from Add Node`,
          );
        }
        addNode(nodeType, nodeType.bindings[0], {
          project_input_ref: publication.project_input_ref,
        });
      } catch (failure) {
        setError((failure as Error).message);
      } finally {
        event.target.value = "";
      }
    },
    [addNode, nodeTypeViews, projectId],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((current) =>
        addEdge(
          {
            ...connection,
            id: `edge_${connection.source}_${connection.sourceHandle}_${connection.target}_${connection.targetHandle}`,
            markerEnd: { type: MarkerType.ArrowClosed },
          },
          current,
        ),
      );
    },
    [setEdges],
  );

  const isValidConnection = useCallback(
    (connection: Edge | Connection) => {
      const source = nodes.find((node) => node.id === connection.source);
      const target = nodes.find((node) => node.id === connection.target);
      if (source === undefined || target === undefined) return false;
      const sourceData = source.data;
      const targetData = target.data;
      const sourcePort = sourceData.nodeType.output_ports.find(
        (port) => port.name === connection.sourceHandle,
      );
      const targetPort = targetData.nodeType.input_ports.find(
        (port) => port.name === connection.targetHandle,
      );
      return sourcePort?.type_id === targetPort?.type_id;
    },
    [nodes],
  );

  const selectedNode = selectedNodeId
    ? nodes.find((node) => node.id === selectedNodeId)
    : undefined;
  const selectedData = selectedNode?.data;
  const selectedBinding = selectedData?.nodeType.bindings.find(
    (binding) =>
      binding.binding_id === selectedData.bindingId &&
      binding.binding_version === selectedData.bindingVersion,
  );
  const grouped = useMemo(
    () => groupNodeTypesByCategory(nodeTypeViews),
    [nodeTypeViews],
  );

  const updateNodeParameter = useCallback(
    (name: string, value: unknown) => {
      if (selectedNodeId === null) return;
      setNodes((current) =>
        current.map((node) => {
          if (node.id !== selectedNodeId) return node;
          const data = node.data;
          return {
            ...node,
            data: {
              ...data,
              nodeParameters: { ...data.nodeParameters, [name]: value },
            },
          };
        }),
      );
    },
    [selectedNodeId, setNodes],
  );

  const selectBinding = useCallback(
    (bindingId: string, bindingVersion: string) => {
      if (selectedNodeId === null || selectedData === undefined) return;
      const binding = selectedData.nodeType.bindings.find(
        (candidate) =>
          candidate.binding_id === bindingId &&
          candidate.binding_version === bindingVersion,
      );
      if (binding === undefined) return;
      setNodes((current) =>
        current.map((node) =>
          node.id === selectedNodeId
            ? {
                ...node,
                data: {
                  ...node.data,
                  bindingId: binding.binding_id,
                  bindingVersion: binding.binding_version,
                  bindingParameters: parameterValues(binding.parameters),
                  available: binding.available,
                },
                style: nodeStyle("idle", binding.available),
              }
            : node,
        ),
      );
    },
    [selectedData, selectedNodeId, setNodes],
  );

  const updateBindingParameter = useCallback(
    (name: string, value: unknown) => {
      if (selectedNodeId === null) return;
      setNodes((current) =>
        current.map((node) => {
          if (node.id !== selectedNodeId) return node;
          const data = node.data;
          return {
            ...node,
            data: {
              ...data,
              bindingParameters: {
                ...data.bindingParameters,
                [name]: value,
              },
            },
          };
        }),
      );
    },
    [selectedNodeId, setNodes],
  );

  return (
    <div style={{ width: "100vw", height: "100vh", display: "flex" }}>
      <div style={{ flex: 1 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onNodeClick={(_, node) => setSelectedNodeId(node.id)}
          nodeTypes={reactFlowNodeTypes}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
          <Panel position="top-left" className="toolbar">
            <input
              type="file"
              ref={fileInputRef}
              style={{ display: "none" }}
              accept=".pdb,.ent,.cif,.fasta,.fa"
              onChange={handleImport}
            />
            <button className="add-node-btn" onClick={() => setMenuOpen(!menuOpen)}>
              + Add Node
            </button>
            <button
              className="proj-btn"
              disabled={projectId === null}
              onClick={() => fileInputRef.current?.click()}
            >
              Import
            </button>
            <button
              className="run-btn"
              onClick={runWorkflow}
              disabled={isRunning || nodes.length === 0 || projectId === null}
            >
              {isRunning ? "Running…" : "▶ Run Workflow"}
            </button>
            {isRunning && (
              <button className="proj-btn" onClick={cancelRun}>Cancel Run</button>
            )}
            <span className="toolbar-sep" />
            <button className="proj-btn" onClick={createProject}>New Project</button>
            <button className="proj-btn" onClick={openProject}>Open</button>
            <button
              className="proj-btn"
              disabled={projectId === null}
              onClick={handleSave}
            >
              Save Draft
            </button>
          </Panel>

          {menuOpen && (
            <Panel position="top-left" className="add-node-menu">
              <h3>Add Node</h3>
              {[...grouped.entries()].map(([category, categoryNodeTypes]) => (
                <div key={category} className="category-group">
                  <h4>{category}</h4>
                  {categoryNodeTypes.flatMap((nodeType) =>
                    nodeType.bindings.map((binding) => (
                      <button
                        key={
                          `${nodeType.node_type_id}@${nodeType.node_type_version}:` +
                          `${binding.binding_id}@${binding.binding_version}`
                        }
                        className="node-option"
                        onClick={() => addNode(nodeType, binding)}
                      >
                        <span className="node-name">{nodeType.display_name}</span>
                        <span className="node-id">
                          {binding.binding_id}@{binding.binding_version}
                          {binding.available ? "" : " (unavailable)"}
                        </span>
                      </button>
                    )),
                  )}
                </div>
              ))}
            </Panel>
          )}
        </ReactFlow>
        {error && <p className="frontend-error" role="alert">{error}</p>}
      </div>

      {selectedData && selectedNodeId && (
        <div className="param-panel">
          <h3>{selectedData.nodeType.display_name}</h3>
          <p className="param-desc">{selectedData.nodeType.description}</p>
          <h4>Execution Binding</h4>
          <select
            value={`${selectedData.bindingId}@${selectedData.bindingVersion}`}
            onChange={(event) => {
              const [bindingId, bindingVersion] = event.target.value.split("@");
              selectBinding(bindingId, bindingVersion);
            }}
          >
            {selectedData.nodeType.bindings.map((binding) => (
              <option
                key={`${binding.binding_id}@${binding.binding_version}`}
                value={`${binding.binding_id}@${binding.binding_version}`}
              >
                {binding.binding_id}@{binding.binding_version}
                {binding.available ? "" : " (unavailable)"}
              </option>
            ))}
          </select>
          <h4>Node parameters</h4>
          {selectedData.nodeType.parameters.map((parameter) => (
            <ParameterField
              key={parameter.name}
              parameter={parameter}
              value={selectedData.nodeParameters[parameter.name]}
              onChange={(value) => updateNodeParameter(parameter.name, value)}
            />
          ))}
          {selectedBinding && Object.keys(selectedBinding.parameters).length > 0 && (
            <>
              <h4>Binding parameters</h4>
              {Object.entries(selectedBinding.parameters).map(
                ([name, definition]) => (
                  <ParameterField
                    key={name}
                    parameter={{
                      name,
                      type: definition.value_contract!.type!,
                      default: definition.default,
                      display_name: name,
                      description: definition.scientific_meaning!,
                      min: definition.value_contract?.minimum,
                      max: definition.value_contract?.maximum,
                      options: definition.value_contract?.enum,
                      required: definition.required ?? false,
                    }}
                    value={selectedData.bindingParameters[name]}
                    onChange={(value) => updateBindingParameter(name, value)}
                  />
                ),
              )}
            </>
          )}
          <button className="close-panel-btn" onClick={() => setSelectedNodeId(null)}>
            Close
          </button>
        </div>
      )}

      <TypedOutputExplorer
        activeProjectId={projectId}
        activeRunId={activeRunId}
      />
    </div>
  );
}
