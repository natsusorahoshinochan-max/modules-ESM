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
import ProteinPromptEditor, { type ResidueRow, type FunctionAnnotation } from "./ProteinPromptEditor";

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

interface ProjectMeta {
  id: string;
  name: string;
  created_at: string;
  modified_at: string;
  module_dependencies: string[];
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


function initNGL(containerId: string, pdbString: string) {
  if (typeof (window as any).NGL === 'undefined') return;
  const stage = new (window as any).NGL.Stage(containerId, { backgroundColor: '#f8fafc' });
  stage.loadFile(new Blob([pdbString], { type: 'text/plain' }), { ext: 'pdb' }).then(function(c: any) {
    c.addRepresentation('cartoon', { colorScheme: 'chainid' });
    c.autoView();
  }).catch(function() {});
}

function StructureViewer({ pdbString }: { pdbString: string | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!pdbString || !containerRef.current) return;
    containerRef.current.innerHTML = '';
    initNGL(containerRef.current.id || 'ngl-container', pdbString);
  }, [pdbString]);
  const id = 'ngl-' + Math.random().toString(36).slice(2, 8);
  return (
    <div className="viewer-panel">
      <h3>3D Structure Viewer</h3>
      {!pdbString ? <p className="empty-hint">Run a workflow to see structures here.</p>
        : <div id={id} ref={containerRef} className="ngl-viewport" />}
    </div>
  );
}


function parseResidueData(params: Record<string, unknown>, chainId: string, length: number): ResidueRow[] {
  const raw = params.residues_data as string | undefined;
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as ResidueRow[];
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    } catch {}
  }
  // Default: generate from chain_id and length
  const rows: ResidueRow[] = [];
  let chain = chainId;
  if (chain === "multi") chain = "A";
  for (let i = 0; i < length; i++) {
    rows.push({
      index: i + 1,
      chain: chain,
      aminoAcid: null,
      structureVisible: false,
      secondaryStructure: null,
      sasa: null,
    });
  }
  return rows;
}

function parseAnnotationData(params: Record<string, unknown>): FunctionAnnotation[] {
  const raw = params.annotations_data as string | undefined;
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as FunctionAnnotation[];
      if (Array.isArray(parsed)) return parsed;
    } catch {}
  }
  return [];
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
  const [projectId, setProjectId] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectMeta[]>([]);
  const [openDialog, setOpenDialog] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch modules
  useEffect(() => {
    fetch("/api/modules")
      .then((r) => r.json())
      .then(setModules)
      .catch(() => setModules([]));
  }, []);

  // Fetch project list
  const refreshProjects = useCallback(() => {
    fetch("/api/projects")
      .then((r) => r.json())
      .then(setProjects)
      .catch(() => {});
  }, []);

  useEffect(() => { refreshProjects(); }, [refreshProjects]);

  // WebSocket
  const connectWS = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/execution`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "node_state") {
        setNodeStates((prev) => ({ ...prev, [data.node_id]: data.new_state }));
      } else if (
        data.type === "run_complete" || data.type === "run_error" ||
        data.type === "run_cancelled"
      ) {
        setIsRunning(false);
      }
    };
    ws.onclose = () => { wsRef.current = null; };
    wsRef.current = ws;
  }, []);

  // Sync node states to rendering
  useEffect(() => {
    setNodes((nds) =>
      nds.map((n) => {
        const nodeData = n.data as Record<string, unknown>;
        const isAvailable = nodeData.available !== false;
        const state = nodeStates[n.id] || "idle";
        const modDef = isAvailable
          ? modules.find((m) => m.module_id === (nodeData.moduleId as string))
          : undefined;
        const displayName = modDef?.display_name || (nodeData._modDisplayName as string) || (nodeData.moduleId as string);
        const label = isAvailable
          ? `${displayName} [${state}]`
          : `${displayName} (unavailable)`;

        return {
          ...n,
          data: { ...n.data, label, state, moduleDef: modDef },
          style: isAvailable ? {
            border: `2px solid ${STATE_COLORS[state] || "#94a3b8"}`,
            borderRadius: "6px",
            padding: "8px",
            background: state === "completed" ? "#f0fdf4" : state === "failed" ? "#fef2f2" : "#fff",
          } : {
            border: "2px dashed #f59e0b",
            borderRadius: "6px",
            padding: "8px",
            background: "#fffbeb",
            opacity: 0.7,
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

  // ── Project operations ──────────────────────────────────────────

  const createProject = useCallback(async () => {
    const name = prompt("Project name:") || "Untitled";
    const resp = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const meta = await resp.json();
    setProjectId(meta.id);
    setNodes([]);
    setEdges([]);
    refreshProjects();
  }, [setNodes, setEdges, refreshProjects]);

  const openProject = useCallback(async (id: string) => {
    setProjectId(id);
    setOpenDialog(false);

    const [wfResp, uiResp] = await Promise.all([
      fetch(`/api/projects/${id}/workflow`),
      fetch(`/api/projects/${id}/ui`),
    ]);
    const wf = await wfResp.json();
    const ui = await uiResp.json();

    // Build nodes from workflow
    const loadedNodes: Node[] = (wf.nodes || []).map((n: Record<string, unknown>, i: number) => {
      const pos = ui.node_positions?.[n.node_id as string] || {
        x: 100 + (i % 4) * 250,
        y: 100 + Math.floor(i / 4) * 150,
      };
      const isAvailable = n.available !== false;
      const modDef = modules.find((m) => m.module_id === (n.module_id as string));
      return {
        id: n.node_id as string,
        type: "default",
        position: pos,
        data: {
          label: isAvailable
            ? `${modDef?.display_name || n.module_id} [idle]`
            : `${n.module_id} (unavailable)`,
          moduleId: n.module_id,
          category: modDef?.category || "",
          state: "idle",
          moduleDef: modDef || null,
          parameters: n.parameters || {},
          available: isAvailable,
          _modDisplayName: modDef?.display_name || "",
        },
        style: isAvailable ? {
          border: "2px solid #94a3b8",
          borderRadius: "6px",
          padding: "8px",
        } : {
          border: "2px dashed #f59e0b",
          borderRadius: "6px",
          padding: "8px",
          background: "#fffbeb",
          opacity: 0.7,
        },
      };
    });

    const loadedEdges: Edge[] = (wf.edges || []).map((e: Record<string, string>) => ({
      id: `edge_${e.source_node_id}_${e.source_port}_${e.target_node_id}_${e.target_port}`,
      source: e.source_node_id,
      sourceHandle: e.source_port,
      target: e.target_node_id,
      targetHandle: e.target_port,
      markerEnd: { type: MarkerType.ArrowClosed },
    }));

    setNodes(loadedNodes);
    setEdges(loadedEdges);
    setNodeIdCounter(loadedNodes.length);

    // Apply viewport
    if (ui.canvas_zoom) {
      // Viewport restoration via fitView for now
    }
  }, [setNodes, setEdges, modules]);

  // Auto-save (debounced)
  const autoSave = useCallback(() => {
    if (!projectId) return;
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
    autoSaveTimer.current = setTimeout(async () => {
      const wfPayload = {
        nodes: nodes.map((n) => ({
          node_id: n.id,
          module_id: (n.data as Record<string, unknown>).moduleId as string,
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
      const uiPayload = {
        node_positions: Object.fromEntries(
          nodes.map((n) => [n.id, n.position]),
        ),
      };
      await Promise.all([
        fetch(`/api/projects/${projectId}/workflow`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(wfPayload),
        }),
        fetch(`/api/projects/${projectId}/ui`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(uiPayload),
        }),
      ]);
      refreshProjects();
    }, 2000);
  }, [projectId, nodes, edges, refreshProjects]);

  // Trigger auto-save on changes
  useEffect(() => {
    if (projectId && (nodes.length > 0 || edges.length > 0)) {
      autoSave();
    }
  }, [nodes, edges, projectId, autoSave]);

  // ── Node operations ─────────────────────────────────────────────


  const handleImport = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    const pid = projectId;
    if (!pid) { alert("Create a project first"); return; }
    const form = new FormData(); form.append("file", file);
    const r = await fetch(`/api/projects/${pid}/inputs`, { method:"POST", body:form });
    const up = await r.json();
    if (up.error) { alert(up.error); return; }
    const isPDB = file.name.endsWith(".pdb") || file.name.endsWith(".ent");
    const modId = isPDB ? "import.structure" : "import.sequence";
    const modDef = modules.find(m => m.module_id === modId);
    const id = `node_${nodeIdCounter}`; setNodeIdCounter(c => c+1);
    const nn: Node = { id, type:"default", position:{x:100+Math.random()*300, y:100+Math.random()*200},
      data: { label:`${modDef?.display_name||modId} [idle]`, moduleId:modId, category:"input", state:"idle", moduleDef:modDef||null, parameters:{file_path:up.path}, available:true },
      style:{ border:"2px solid #94a3b8", borderRadius:"6px", padding:"8px" } };
    setNodes(nds => [...nds, nn]);
    e.target.value = "";
  }, [projectId, nodeIdCounter, setNodes, modules]);

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
          available: true,
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


  const handleExport = useCallback(async (nodeId: string) => {
    const node = nodes.find(n => n.id === nodeId); if (!node) return;
    alert("Export from canvas: outputs are stored on the server. Use the Export Structure/Sequence module in your workflow.");
  }, [nodes]);

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
    (_: React.MouseEvent, node: Node) => { setSelectedNodeId(node.id); },
    [],
  );

  const updateParam = useCallback(
    (nodeId: string, paramName: string, value: unknown) => {
      setNodes((nds) =>
        nds.map((n) => {
          if (n.id !== nodeId) return n;
          const nd = n.data as Record<string, unknown>;
          return {
            ...n,
            data: {
              ...n.data,
              parameters: { ...(nd.parameters as Record<string, unknown>), [paramName]: value },
            },
          };
        }),
      );
    },
    [setNodes],
  );

  // ── Run workflow ─────────────────────────────────────────────────

  const selectedNode = selectedNodeId ? nodes.find(n => n.id===selectedNodeId) : undefined;
  const selectedParams = selectedNode
    ? ((selectedNode.data as Record<string, unknown>).parameters as Record<string, unknown>) || {}
    : {};
  const selectedAvailable = selectedNode
    ? ((selectedNode.data as Record<string, unknown>).available as boolean) !== false
    : true;
  const runWorkflow = useCallback(async () => {
    if (nodes.length === 0) return;
    connectWS();
    setIsRunning(true);
    setNodeStates({});
    for (const n of nodes) {
      setNodeStates((prev) => ({ ...prev, [n.id]: "queued" }));
    }

    const payload = {
      project_id: projectId || undefined,
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
      if (result.error) { alert(result.error); setIsRunning(false); }
    } catch {
      alert("Failed to execute workflow");
      setIsRunning(false);
    }
  }, [nodes, edges, connectWS, projectId]);

  // ── Render helpers ───────────────────────────────────────────────

  const grouped = groupByCategory(modules);
  const selectedModule = selectedNodeId ? getModuleDef(selectedNodeId) : undefined;

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
            <input type="file" ref={fileInputRef} style={{display:"none"}} accept=".pdb,.ent,.cif,.fasta,.fa" onChange={handleImport} />
            <button className="add-node-btn" onClick={() => setMenuOpen(!menuOpen)}>
              + Add Node
            </button>
            <button className="import-btn" onClick={()=>fileInputRef.current?.click()}>Import</button>
            <button className="run-btn" onClick={runWorkflow}
              disabled={isRunning || nodes.length === 0}>
              {isRunning ? "Running..." : "\u25B6 Run Workflow"}
            </button>
            <span className="toolbar-sep" />
            {!projectId ? (
              <button className="proj-btn" onClick={createProject}>
                New Project
              </button>
            ) : (
              <>
                <button className="proj-btn" onClick={() => autoSaveTimer.current && clearTimeout(autoSaveTimer.current) || autoSave()}>
                  Save
                </button>
                <button className="proj-btn" onClick={() => setOpenDialog(true)}>
                  Open
                </button>
            {selectedNode && <button className="proj-btn" onClick={()=>handleExport(selectedNode.id)}>Export</button>}
              </>
            )}
          </Panel>

          {menuOpen && (
            <Panel position="top-left" className="add-node-menu">
              <h3>Add Node</h3>
              {modules.length === 0 && <p className="empty-hint">No modules discovered.</p>}
              {[...grouped.entries()].map(([category, mods]) => (
                <div key={category} className="category-group">
                  <h4>{category}</h4>
                  {mods.map((mod) => (
                    <button key={mod.module_id} className="node-option" onClick={() => addNode(mod)}>
                      <span className="node-name">{mod.display_name}</span>
                      <span className="node-id">{mod.module_id}</span>
                    </button>
                  ))}
                </div>
              ))}
            </Panel>
          )}

          {openDialog && (
            <Panel position="top-left" className="open-dialog">
              <h3>Open Project</h3>
              {projects.length === 0 && <p className="empty-hint">No saved projects.</p>}
              {projects.map((p) => (
                <button key={p.id} className="project-option" onClick={() => openProject(p.id)}>
                  <span className="project-name">{p.name}</span>
                  <span className="project-date">{new Date(p.modified_at).toLocaleString()}</span>
                </button>
              ))}
              <button className="close-panel-btn" onClick={() => setOpenDialog(false)}>
                Cancel
              </button>
            </Panel>
          )}
        </ReactFlow>
      </div>

      {selectedModule && selectedNodeId && (
        <div className="param-panel">
          <h3>
            {selectedModule.display_name}
            {!selectedAvailable && <span className="unavailable-badge">unavailable</span>}
          </h3>
          <p className="param-desc">{selectedModule.description}</p>
          {!selectedAvailable && (
            <p className="unavailable-hint">
              Module &quot;{selectedModule.module_id}&quot; is not installed.
              Install it to enable execution.
            </p>
          )}
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
                  <input type="number"
                    value={currentValue as number ?? param.default as number ?? 0}
                    min={param.min} max={param.max}
                    step={param.type === "float" ? "0.1" : "1"}
                    onChange={(e) => updateParam(selectedNodeId, param.name,
                      param.type === "float" ? parseFloat(e.target.value) : parseInt(e.target.value, 10))}
                  />
                ) : param.type === "enum" && param.options ? (
                  <select value={(currentValue as string) ?? (param.default as string) ?? ""}
                    onChange={(e) => updateParam(selectedNodeId, param.name, e.target.value)}>
                    {param.options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                  </select>
                ) : param.type === "bool" ? (
                  <input type="checkbox"
                    checked={(currentValue as boolean) ?? (param.default as boolean) ?? false}
                    onChange={(e) => updateParam(selectedNodeId, param.name, e.target.checked)} />
                ) : (
                  <input type="text"
                    value={(currentValue as string) ?? (param.default as string) ?? ""}
                    onChange={(e) => updateParam(selectedNodeId, param.name, e.target.value)} />
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
                <div key={p.name} className="port-item">{p.display_name || p.name} <code>{p.type_id}</code></div>
              ))}
            </div>
            <div>
              <strong>Outputs:</strong>
              {selectedModule.output_ports.length === 0 && " none"}
              {selectedModule.output_ports.map((p) => (
                <div key={p.name} className="port-item">{p.display_name || p.name} <code>{p.type_id}</code></div>
              ))}
            </div>
          </div>
          <button className="close-panel-btn" onClick={() => setSelectedNodeId(null)}>Close</button>
        </div>
      )}
      {selectedModule && selectedNodeId && selectedModule.category === "prompt" && (() => {
        const nodeParams = (selectedNode?.data as Record<string, unknown>)?.parameters as Record<string, unknown> || {};
        const chainId = (nodeParams.chain_id as string) || "A";
        const length = (nodeParams.length as number) || 0;
        const residues = parseResidueData(nodeParams, chainId, length > 0 ? length : 10);
        const annotations = parseAnnotationData(nodeParams);

        const handleResiduesChange = (newResidues: ResidueRow[]) => {
          const nd = selectedNode?.data as Record<string, unknown>;
          if (!nd || !selectedNodeId) return;
          const params = { ...(nd.parameters as Record<string, unknown> || {}), residues_data: JSON.stringify(newResidues), length: newResidues.length };
          // Update node via setNodes
          setNodes((nds) => nds.map((n) => n.id === selectedNodeId ? { ...n, data: { ...n.data, parameters: params } } : n));
        };

        const handleAnnotationsChange = (newAnnotations: FunctionAnnotation[]) => {
          const nd = selectedNode?.data as Record<string, unknown>;
          if (!nd || !selectedNodeId) return;
          const params = { ...(nd.parameters as Record<string, unknown> || {}), annotations_data: JSON.stringify(newAnnotations) };
          setNodes((nds) => nds.map((n) => n.id === selectedNodeId ? { ...n, data: { ...n.data, parameters: params } } : n));
        };

        return (
          <ProteinPromptEditor
            residues={residues}
            annotations={annotations}
            onResiduesChange={handleResiduesChange}
            onAnnotationsChange={handleAnnotationsChange}
          />
        );
      })()}
      <StructureViewer pdbString={null} />
    </div>
  );
}
