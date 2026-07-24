import { useCallback, useEffect, useState } from "react";
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
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./App.css";


interface ApiModule {
  module_id: string;
  version: string;
  display_name: string;
  category: string;
  description: string;
}

function groupByCategory(modules: ApiModule[]): Map<string, ApiModule[]> {
  const map = new Map<string, ApiModule[]>();
  for (const m of modules) {
    const list = map.get(m.category) || [];
    list.push(m);
    map.set(m.category, list);
  }
  return map;
}

const initialNodes: Node[] = [];
const initialEdges: Edge[] = [];

export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, _setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [modules, setModules] = useState<ApiModule[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [nodeIdCounter, setNodeIdCounter] = useState(0);

  useEffect(() => {
    fetch("/api/modules")
      .then((r) => r.json())
      .then(setModules)
      .catch(() => {
        // Backend not running yet — show empty state
        setModules([]);
      });
  }, []);

  const addNode = useCallback(
    (mod: ApiModule) => {
      const id = `node_${nodeIdCounter}`;
      setNodeIdCounter((c) => c + 1);
      const newNode: Node = {
        id,
        type: "default",
        position: { x: 100 + Math.random() * 300, y: 100 + Math.random() * 300 },
        data: {
          label: `${mod.display_name}\n${mod.module_id}`,
          moduleId: mod.module_id,
          category: mod.category,
        },
      };
      setNodes((nds) => [...nds, newNode]);
      setMenuOpen(false);
    },
    [nodeIdCounter, setNodes],
  );

  const grouped = groupByCategory(modules);

  return (
    <div style={{ width: "100vw", height: "100vh" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap />

        <Panel position="top-left" className="toolbar">
          <button
            className="add-node-btn"
            onClick={() => setMenuOpen(!menuOpen)}
          >
            + Add Node
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
  );
}
