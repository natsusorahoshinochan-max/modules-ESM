# Frontend-backend communication: FastAPI REST + WebSocket (historical v1)

This document records the v1 transport. Its endpoint names, payloads, Workflow
JSON, Type/Module Registry responses, Cache layout, event examples, and
frontend-facing consequences below are historical and non-normative for v2.

The retained behavioral baseline is a backend-owned REST interface plus a
run-scoped WebSocket interface with ordering, Project/Run isolation,
cancellation, safe error projection, and artifact integrity. A v2 transport
ticket must restate its exact routes and payloads using the accepted contracts
in ADR-0022, ADR-0026, ADR-0028, ADR-0029, ADR-0030, and ADR-0031; nothing below
authorizes a second Registry, manifest writer, Workflow shape, or Cache model.

## Historical v1 REST API endpoints

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
POST   /api/projects/{project_id}/run/{run_id}/cancel # Cancel exact run
GET    /api/projects/{project_id}/run/{run_id}/status   # Run status
GET    /api/projects/{project_id}/run/{run_id}/manifest # Durable manifest
GET    /api/projects/{project_id}/run/{run_id}/outputs   # Output data
GET    /api/projects/{project_id}/run/{run_id}/artifacts/{reference}
POST   /api/projects/{project_id}/run/{run_id}/nodes/{node_id}/retry
POST   /api/projects/{project_id}/run/{run_id}/nodes/{node_id}/force-rerun
```

### Cache
```
GET    /api/projects/{project_id}/cache                # List cache entries
GET    /api/projects/{project_id}/cache/{node_id}      # List node cache
DELETE /api/projects/{project_id}/cache/{node_id}      # Clear node cache
DELETE /api/projects/{project_id}/cache                # Clear all cache
```

Run recovery is always explicit about both project ID and run ID. Status,
manifest, output, and artifact requests read that exact manifest; no endpoint
chooses a run or Cache entry by modification time. Artifact responses expose
run-relative references, Node ID, output Port, size, and SHA-256.
Candidate-bound artifacts additionally expose a Candidate ID. A standalone
`file.path` output Port opts into standalone publication in its Node Definition
and the manifest record declares `artifact_kind: "standalone"` with no
Candidate ID. This explicit opt-in and discriminator prevent an ordinary
Candidate-bound Port or malformed Candidate artifact from being treated as
standalone. A download is served only when the reference is declared by the
selected manifest and a stable snapshot matches its recorded size and hash.
Artifacts without an output-Port binding, Candidate artifacts without a
Candidate ID, and candidate-less artifacts without the standalone
discriminator make the public manifest invalid. Public retrieval is bounded
to 2,048 artifacts, 64 MiB per artifact, and 256 MiB in aggregate per run;
verification executes on FastAPI's worker thread rather than its event loop.
The older Node-output compatibility route therefore requires an explicit
`run_id` query parameter, and the hybrid output-download route verifies the
same manifest contract.

Both Node recovery actions create a new run and retain the source run. They
inherit its run seed unless the request supplies a valid replacement:

- `retry` bypasses Cache for the selected Node. Ancestors, descendants, and
  unrelated branches remain Cache-eligible; a descendant therefore executes
  only when the selected output changes its content-addressed input identity.
- `force-rerun` bypasses Cache for the selected Node and every transitive
  downstream Node. Ancestors and unrelated branches remain Cache-eligible.

The new manifest records the source run, action, selected Node, exact forced
Node closure, dependency semantics, effective seeds, per-Node Cache outcomes,
and ordered Node states. Recovery is rejected if the source run is not
terminal or if the current saved Workflow hash differs from the source
manifest.

Cache listing returns only entries whose authenticated envelope is valid and
does not deserialize their payload. Node-scoped operations require a Node in
the current Workflow. Project clearing is allowed to include stale, valid Node
names but removes only direct regular `.pkl` Cache entries; it preserves the
project integrity key and unrelated files. Cache clearing is rejected while
that project has an active run. A project-scoped mutation reservation is
registered before deletion moves to a worker thread, so run admission and
Cache deletion remain mutually exclusive. This exclusion relies on the
application's documented single-process deployment contract; starting multiple
backend processes against the same storage roots is unsupported.

Recovery failures use `{error: {kind, message, ...}}` with stable kinds.
Unknown project/run/Node/artifact scopes return 404, stale Workflow or artifact
integrity mismatches return 409, and invalid identifiers or traversal-like
references return 422. Diagnostics never include raw file paths, exception
text, Cache payloads, or credentials.

### File I/O
```
POST   /api/projects/{project_id}/import    # Import sequence/structure file
GET    /api/projects/{project_id}/export/{file_id}  # Download output file
```

## Historical v1 WebSocket execution progress

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

## Historical v1 data formats

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

## Historical v1 Port compatibility check

Port type compatibility is enforced on both sides:

- Frontend: the React Flow `isValidConnection` callback checks type ID
  compatibility before allowing an edge to be created. This requires the
  port type information from the module registry to be available in the
  frontend state.
- Backend: the execution engine re-checks port compatibility before running
  the workflow, as the authoritative gate. The frontend check is a UX
  convenience, not a security boundary.

## Historical v1 consequences

- The backend is fully testable without a browser: all endpoints can be
  exercised with pytest + httpx.
- The frontend can be developed against a mock API server when the real
  backend endpoints are not yet implemented.
- Adding a new module requires no changes to the API schema; the module
  registry endpoints already serve ModuleDefinitions generically.
- The WebSocket protocol is intentionally simple (no multiplexing, no
  channels) because only one user runs one workflow at a time.
