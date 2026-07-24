import { useCallback, useEffect, useRef, useState } from "react";
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

interface ApiParam {
  name: string;
  type: string;
  default: unknown;
  display_name: string;
  description: string;
  min?: number;
  max?: number;
  options?: string[];
}

interface ApiModule {
  module_id: string;
  version: string;
  display_name: string;
  category: string;
  description: string;
  input_ports: { name: string; type_id: string; display_name: string }[];
  output_ports: { name: string; type_id: string; display_name: string }[];
  parameters: ApiParam[];
}

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
};

function groupByCategory(modules: ApiModule[]): Map<string, ApiModule[]> {
  const map = new Map<string, ApiModule[]>();
  for (const m of modules) {
    const list = map.get(m.category) || [];
    list.push(m);
    map.set(m.category, list);
  }
  return map;
}

export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [modules, setModules] = useState<ApiModule[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [nodeIdCounter, setNodeIdCounter] = useState(0);
  const [nodeStates, setNodeStates] = useState<NodeStateInfo>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    fetch("/api/modules")
      .then((r) => r.json())
      .then(setModules)
      .catch(() => setModules([]));
  }, []);

  const connectWS = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/execution`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "node_state") {
        setNodeStates((prev) => ({
          ...prev,
          [data.node_id]: data.new_state,
        }));
      } else if (
        data.type === "run_complete" ||
        data.type === "run_error" ||
        data.type === "run_cancelled"
      ) {
        setIsRunning(false);
      }
    };
    ws.onclose = () => {
      wsRef.current = null;
    };
    wsRef.current = ws;
  }, []);

  useEffect(() => {
    setNodes((nds) =>
      nds.map((n) => {
        const state = nodeStates[n.id] || "idle";
        const nodeData = n.data as Record<string, unknown>;
        const moduleDef = modules.find(
          (m) => m.module_id === (nodeData.moduleId as string),
        );
        const label = moduleDef
          ? `${moduleDef.display_name} [${state}]`
          : `${nodeData.label as string} [${state}]`;

        return {
          ...n,
          data: {
            ...n.data,
            label,
            state,
            moduleDef,
          },
          style: {
            border: `2px solid ${STATE_COLORS[state] || "#94a3b8"}`,
            borderRadius: "6px",
            padding: "8px",
            background: state === "completed" ? "#f0fdf4" : state === "failed" ? "#fef2f2" : "#fff",
          },
        };
      }),
    );
  }, [nodeStates, setNodes, modules]);

  const getModuleDef = useCallback(
    (nodeId: string): ApiModule | undefined => {
      const node = nodes.find((n) => n.id === nodeId);
      if (!node) return undefined;
      return modules.find(
        (m) => m.module_id === ((node.data as Record<string, unknown>).moduleId as string),
      );
    },
    [nodes, modules],
  );

  const addNode = useCallback(
    (mod: ApiModule) => {
      const id = `node_${nodeIdCounter}`;
      setNodeIdCounter((c) => c + 1);
      const newNode: Node = {
        id,
        type: "default",
        position: { x: 100 + Math.random() * 300, y: 100 + Math.random() * 200 },
        data: {
          label: mod.display_name,
          moduleId: mod.module_id,
          category: mod.category,
          state: "idle",
          moduleDef: mod,
          parameters: Object.fromEntries(
            mod.parameters.map((p) => [p.name, p.default]),
          ),
        },
        style: {
          border: `2px solid ${STATE_COLORS["idle"]}`,
          borderRadius: "6px",
          padding: "8px",
        },
      };
      setNodes((nds) => [...nds, newNode]);
      setMenuOpen(false);
    },
    [nodeIdCounter, setNodes],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      const edge: Edge = {
        ...connection,
        id: `edge_${connection.source}_${connection.sourceHandle}_${connection.target}_${connection.targetHandle}`,
        markerEnd: { type: MarkerType.ArrowClosed },
      };
      setEdges((eds) => addEdge(edge, eds));
    },
    [setEdges],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNodeId(node.id);
    },
    [],
  );

  const updateParam = useCallback(
    (nodeId: string, paramName: string, value: unknown) => {
      setNodes((nds) =>
        nds.map((n) => {
          if (n.id !== nodeId) return n;
          const nodeData = n.data as Record<string, unknown>;
          return {
            ...n,
            data: {
              ...n.data,
              parameters: {
                ...(nodeData.parameters as Record<string, unknown>),
                [paramName]: value,
              },
            },
          };
        }),
      );
    },
    [setNodes],
  );

  const runWorkflow = useCallback(async () => {
    if (nodes.length === 0) return;

    connectWS();
    setIsRunning(true);

    setNodeStates({});
    for (const n of nodes) {
      setNodeStates((prev) => ({ ...prev, [n.id]: "queued" }));
    }

    const payload = {
      nodes: nodes.map((n) => ({
        node_id: n.id,
        module_id: ((n.data as Record<string, unknown>).moduleId as string),
        module_version: "1.0.0",
        parameters: (n.data as Record<string, unknown>).parameters || {},
      })),
      edges: edges.map((e) => ({
        source_node_id: e.source,
        source_port: e.sourceHandle || "text",
        target_node_id: e.target,
        target_port: e.targetHandle || "text",
      })),
    };

    try {
      const resp = await fetch("/api/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await resp.json();
      if (result.error) {
        alert(result.error);
        setIsRunning(false);
      }
    } catch {
      alert("Failed to execute workflow");
      setIsRunning(false);
    }
  }, [nodes, edges, connectWS]);

  const grouped = groupByCategory(modules);
  const selectedModule = selectedNodeId ? getModuleDef(selectedNodeId) : undefined;
  const selectedNode = selectedNodeId ? nodes.find((n) => n.id === selectedNodeId) : undefined;
  const selectedParams = selectedNode
    ? ((selectedNode.data as Record<string, unknown>).parameters as Record<string, unknown>) || {}
    : {};

  return (
    <div style={{ width: "100vw", height: "100vh", display: "flex" }}>
      <div style={{ flex: 1 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />

          <Panel position="top-left" className="toolbar">
            <button className="add-node-btn" onClick={() => setMenuOpen(!menuOpen)}>
              + Add Node
            </button>
            <button
              className="run-btn"
              onClick={runWorkflow}
              disabled={isRunning || nodes.length === 0}
            >
              {isRunning ? "Running..." : "\u25B6 Run Workflow"}
            </button>
          </Panel>

          {menuOpen && (
            <Panel position="top-left" className="add-node-menu">
              <h3>Add Node</h3>
              {modules.length === 0 && (
                <p className="empty-hint">No modules discovered.</p>
              )}
              {[...grouped.entries()].map(([category, mods]) => (
                <div key={category} className="category-group">
                  <h4>{category}</h4>
                  {mods.map((mod) => (
                    <button
                      key={mod.module_id}
                      className="node-option"
                      onClick={() => addNode(mod)}
                    >
                      <span className="node-name">{mod.display_name}</span>
                      <span className="node-id">{mod.module_id}</span>
                    </button>
                  ))}
                </div>
              ))}
            </Panel>
          )}
        </ReactFlow>
      </div>

      {selectedModule && selectedNodeId && (
        <div className="param-panel">
          <h3>{selectedModule.display_name}</h3>
          <p className="param-desc">{selectedModule.description}</p>
          <h4>Parameters</h4>
          {selectedModule.parameters.length === 0 && (
            <p className="empty-hint">No configurable parameters.</p>
          )}
          {selectedModule.parameters.map((param) => {
            const currentValue = selectedParams[param.name];
            return (
              <div key={param.name} className="param-field">
                <label>
                  {param.display_name || param.name}
                  {param.description && (
                    <span className="param-desc-hint"> \u2014 {param.description}</span>
                  )}
                </label>
                {param.type === "int" || param.type === "float" ? (
                  <input
                    type="number"
                    value={currentValue as number ?? param.default as number ?? 0}
                    min={param.min}
                    max={param.max}
                    step={param.type === "float" ? "0.1" : "1"}
                    onChange={(e) =>
                      updateParam(
                        selectedNodeId,
                        param.name,
                        param.type === "float"
                          ? parseFloat(e.target.value)
                          : parseInt(e.target.value, 10),
                      )
                    }
                  />
                ) : param.type === "enum" && param.options ? (
                  <select
                    value={(currentValue as string) ?? (param.default as string) ?? ""}
                    onChange={(e) =>
                      updateParam(selectedNodeId, param.name, e.target.value)
                    }
                  >
                    {param.options.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : param.type === "bool" ? (
                  <input
                    type="checkbox"
                    checked={(currentValue as boolean) ?? (param.default as boolean) ?? false}
                    onChange={(e) =>
                      updateParam(selectedNodeId, param.name, e.target.checked)
                    }
                  />
                ) : (
                  <input
                    type="text"
                    value={(currentValue as string) ?? (param.default as string) ?? ""}
                    onChange={(e) =>
                      updateParam(selectedNodeId, param.name, e.target.value)
                    }
                  />
                )}
              </div>
            );
          })}

          <h4>Ports</h4>
          <div className="ports-info">
            <div>
              <strong>Inputs:</strong>
              {selectedModule.input_ports.length === 0 && " none"}
              {selectedModule.input_ports.map((p) => (
                <div key={p.name} className="port-item">
                  {p.display_name || p.name} <code>{p.type_id}</code>
                </div>
              ))}
            </div>
            <div>
              <strong>Outputs:</strong>
              {selectedModule.output_ports.length === 0 && " none"}
              {selectedModule.output_ports.map((p) => (
                <div key={p.name} className="port-item">
                  {p.display_name || p.name} <code>{p.type_id}</code>
                </div>
              ))}
            </div>
          </div>

          <button className="close-panel-btn" onClick={() => setSelectedNodeId(null)}>
            Close
          </button>
        </div>
      )}
    </div>
  );
}
