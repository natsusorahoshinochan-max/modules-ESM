import { memo } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import type { NodeTypeView } from "./currentProtocol";

interface PortInfo {
  name: string;
  type_id: string;
  display_name: string;
}

export interface WorkflowNodeData extends Record<string, unknown> {
  label: string;
  nodeTypeId: string;
  nodeTypeVersion: string;
  bindingId: string;
  bindingVersion: string;
  category: string;
  state: string;
  nodeType: NodeTypeView;
  nodeParameters: Record<string, unknown>;
  bindingParameters: Record<string, unknown>;
  available: boolean;
}

type WorkflowNodeType = Node<WorkflowNodeData>;

function WorkflowNode({ data, selected }: NodeProps<WorkflowNodeType>) {
  const nodeType = data.nodeType;
  const isAvailable = data.available;

  const inputPorts: PortInfo[] = nodeType.input_ports;
  const outputPorts: PortInfo[] = nodeType.output_ports;

  const handleSpacing = 22;

  return (
    <div
      className="workflow-node"
      style={{
        border: selected ? "2px solid #3b82f6" : "1px solid #cbd5e1",
        borderRadius: "6px",
        padding: "10px 12px",
        background: "#fff",
        minWidth: "180px",
        fontSize: "12px",
        boxShadow: selected ? "0 0 0 2px rgba(59,130,246,0.2)" : "0 1px 3px rgba(0,0,0,0.1)",
        opacity: isAvailable ? 1 : 0.6,
        position: "relative",
      }}
    >
      {/* Input handles (left side) */}
      {inputPorts.map((port, i) => (
        <div
          key={`input-${port.name}`}
          style={{
            position: "absolute",
            left: -8,
            top: 24 + i * handleSpacing,
            display: "flex",
            alignItems: "center",
            gap: "4px",
          }}
        >
          <Handle
            type="target"
            id={port.name}
            position={Position.Left}
            style={{
              width: 10,
              height: 10,
              background: "#94a3b8",
              border: "2px solid #fff",
              position: "relative",
              left: 0,
              transform: "none",
            }}
          />
          <span
            style={{
              fontSize: "10px",
              color: "#64748b",
              whiteSpace: "nowrap",
              marginLeft: "4px",
            }}
          >
            {port.display_name}
          </span>
        </div>
      ))}

      {/* Node header */}
      <div
        style={{
          fontWeight: 600,
          marginBottom: "4px",
          fontSize: "13px",
          color: isAvailable ? "#1e293b" : "#94a3b8",
        }}
      >
        {nodeType.display_name}
      </div>

      {/* State badge */}
      <div
        style={{
          fontSize: "10px",
          color: "#94a3b8",
          marginBottom: inputPorts.length > 0 || outputPorts.length > 0 ? "8px" : "0",
        }}
      >
        [{data.state}]
      </div>

      {/* Output handles (right side) */}
      {outputPorts.map((port, i) => (
        <div
          key={`output-${port.name}`}
          style={{
            position: "absolute",
            right: -8,
            top: 24 + i * handleSpacing,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            gap: "4px",
          }}
        >
          <span
            style={{
              fontSize: "10px",
              color: "#64748b",
              whiteSpace: "nowrap",
              marginRight: "4px",
            }}
          >
            {port.display_name}
          </span>
          <Handle
            type="source"
            id={port.name}
            position={Position.Right}
            style={{
              width: 10,
              height: 10,
              background: "#94a3b8",
              border: "2px solid #fff",
              position: "relative",
              right: 0,
              transform: "none",
            }}
          />
        </div>
      ))}
    </div>
  );
}

export default memo(WorkflowNode);
