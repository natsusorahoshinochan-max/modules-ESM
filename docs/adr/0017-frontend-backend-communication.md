# Frontend-backend communication: FastAPI REST + WebSocket

The frontend communicates with the backend through a FastAPI server exposing
a REST API for CRUD operations and a WebSocket for real-time execution progress.
The backend has no knowledge of the UI framework; the API is the sole contract.

## REST API endpoints

### Module registry
```
GET  /api/modules                    # List all registered modules
GET  /api/modules/{module_id}        # Get ModuleDefinition (ports, params)
```

### Type registry
```
GET  /api/types                      # List all registered type IDs
GET  /api/types/{type_id}            # Get type definition
```

### Workflow management
```
GET    /api/projects                          # List projects
POST   /api/projects                          # Create project
GET    /api/projects/{project_id}             # Get project metadata
GET    /api/projects/{project_id}/workflow    # Get workflow.json
PUT    /api/projects/{project_id}/workflow    # Save workflow.json
GET    /api/projects/{project_id}/ui          # Get ui.json
PUT    /api/projects/{project_id}/ui          # Save ui.json
```

### Execution
```
POST   /api/projects/{project_id}/run         # Start workflow execution
POST   /api/projects/{project_id}/cancel      # Cancel running workflow
GET    /api/projects/{project_id}/run/{run_id}/status   # Run status
GET    /api/projects/{project_id}/run/{run_id}/outputs   # Output data
```

### Cache
```
GET    /api/projects/{project_id}/cache                # List cache entries
DELETE /api/projects/{project_id}/cache/{node_id}      # Clear node cache
DELETE /api/projects/{project_id}/cache                # Clear all cache
```

### File I/O
```
POST   /api/projects/{project_id}/import    # Import sequence/structure file
GET    /api/projects/{project_id}/export/{file_id}  # Download output file
```

## WebSocket: execution progress

```
WS /api/projects/{project_id}/run/{run_id}/ws
```

Server pushes JSON messages as execution progresses:

```json
{"type": "run_started", "project_id": "...", "run_id": "...", "sequence": 1, "timestamp": "...", "node_order": ["node-1", "node-2"]}
{"type": "node_state", "project_id": "...", "run_id": "...", "sequence": 2, "timestamp": "...", "node_id": "node-1", "state": "running"}
{"type": "node_completed", "project_id": "...", "run_id": "...", "sequence": 3, "timestamp": "...", "node_id": "node-1", "output_summary": {"output_ports": ["text"], "cache": {"outcome": "miss"}}}
{"type": "node_failed", "project_id": "...", "run_id": "...", "sequence": 4, "timestamp": "...", "node_id": "node-2", "error": {"kind": "...", "message": "...", "module_id": "...", "retryable": false}}
{"type": "node_blocked", "project_id": "...", "run_id": "...", "sequence": 5, "timestamp": "...", "node_id": "node-3", "reason": {"kind": "upstream_terminal", "message": "...", "upstream_node_ids": ["node-2"]}}
{"type": "run_completed", "project_id": "...", "run_id": "...", "sequence": 6, "timestamp": "...", "status": "completed", "duration_ms": 12345}
{"type": "run_failed", "project_id": "...", "run_id": "...", "sequence": 6, "timestamp": "...", "status": "failed", "duration_ms": 12345, "error": {"kind": "node_failure", "message": "...", "retryable": false}}
{"type": "run_cancelled", "project_id": "...", "run_id": "...", "sequence": 6, "timestamp": "...", "status": "cancelled", "duration_ms": 12345}
```

Node state transitions follow the architecture document section 15.2:
idle → queued → running → completed / failed / cancelled, with blocked
as a terminal state for downstream nodes whose upstream dependency failed.
Events are scoped to exactly one project/run pair and use a contiguous,
monotonically increasing sequence. The persisted Node terminal fact is written
before its event, and the persisted run terminal status is written before the
final run event. If the run namespace itself cannot be created, the broker emits
one safe `run_failed` setup error without a manifest; this is the sole
pre-manifest exception because no durable run document exists to order first.
Once a manifest exists, terminal persistence is attempted before publication,
including a failed-state fallback after another terminal write fails. Safe
structured errors never include raw exception text or credentials.

To bound replay and subscriber memory, one executable Workflow is limited to
2,048 Nodes and 8,192 edges before semantic validation or stream creation.
Each stream uses a fixed 256-event live queue, admits at most 32 subscribers,
and keeps an overflowed subscriber counted until its WebSocket handler exits.
The broker retains the latest 32 completed streams for post-REST replay.

## Data formats

### Workflow JSON (workflow.json)

```json
{
  "nodes": [
    {
      "node_id": "node-1",
      "module_id": "esm3.generate_sequence",
      "module_version": "1.0.0",
      "parameters": {"num_steps": 8, "temperature": 0.7},
      "input_connections": {},
      "output_connections": {"sequences": ["node-2"]}
    }
  ],
  "metadata": {
    "project_name": "...",
    "created": "...",
    "modified": "..."
  }
}
```

### UI state (ui.json)

```json
{
  "nodes": {
    "node-1": {"x": 100, "y": 200, "width": 280, "height": 180},
    "node-2": {"x": 500, "y": 200, "width": 280, "height": 180}
  },
  "groups": [
    {"id": "group-1", "label": "ESM3 Pipeline", "nodes": ["node-1", "node-2"]}
  ],
  "viewport": {"x": 0, "y": 0, "zoom": 1.0}
}
```

## Port compatibility check

Port type compatibility is enforced on both sides:

- Frontend: the React Flow `isValidConnection` callback checks type ID
  compatibility before allowing an edge to be created. This requires the
  port type information from the module registry to be available in the
  frontend state.
- Backend: the execution engine re-checks port compatibility before running
  the workflow, as the authoritative gate. The frontend check is a UX
  convenience, not a security boundary.

## Consequences

- The backend is fully testable without a browser: all endpoints can be
  exercised with pytest + httpx.
- The frontend can be developed against a mock API server when the real
  backend endpoints are not yet implemented.
- Adding a new module requires no changes to the API schema; the module
  registry endpoints already serve ModuleDefinitions generically.
- The WebSocket protocol is intentionally simple (no multiplexing, no
  channels) because only one user runs one workflow at a time.
