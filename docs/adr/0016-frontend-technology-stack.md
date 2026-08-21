---
status: accepted
---

# Frontend technology stack

The node-based graphical UI is built with React, TypeScript, Vite, and React Flow.
These are the industry-standard tools for node-editor interfaces (ComfyUI uses the
same stack) and have broad community support, mature type definitions, and
well-documented patterns for custom nodes, edges, and parameter forms.

## Technology choices

### React + TypeScript

TypeScript provides compile-time safety for the complex data structures flowing
through the UI (Port Types, Node Type and Binding descriptors, Workflow state,
Run projections, and Typed Output descriptors). React's component model maps
naturally to the Node/Port/parameter decomposition in the architecture.

### Vite

Fast dev server with HMR, native TypeScript support, and straightforward
production builds. No need for a heavier framework like Next.js in a local
single-user desktop application.

### React Flow (@xyflow/react)

Purpose-built for node-based editors. Provides:
- Draggable nodes with custom rendering
- Connection lines with port validation callbacks
- Minimap, controls, and background grid
- Edge creation and deletion with type-checking hooks
- Built-in zoom, pan, and viewport management

### Parameter form generation

Parameter forms are derived from current Catalog Node Type and Binding
descriptors. The frontend maps the declared value contract to widgets:
- integer/number → number input with min/max/step
- boolean → toggle/checkbox
- string → text input
- enum → select/dropdown
- array/object → JSON editor that applies a typed value only after successful
  local parsing and root-shape validation

Prompt authoring is expressed through the same current Node Type contracts as
every other Workflow operation.

### Project structure

```text
frontend/src/
├── App.tsx                       # Project, Workflow and Run orchestration
├── currentProtocol.ts            # current public DTOs and Catalog translation
├── WorkflowNode.tsx              # React Flow Node renderer
├── ParameterField.tsx            # contract-aware parameter widgets
├── runEvents.ts                  # current lifecycle-event projection
├── TypedOutputExplorer.tsx       # bounded Run Projection and Artifact links
├── TypedOutputValueSelector.tsx  # one-value-at-a-time retrieval
└── typedOutputs.ts               # Typed Output descriptor/retrieval types
```

### Build integration

During development, Vite dev server runs on port 5173 proxying API requests to
FastAPI on port 8000. For production, Vite builds static assets into a dist/
directory that FastAPI serves directly, yielding a single-process deployment.

## Consequences

- The project now has a JavaScript/TypeScript build chain in addition to Python.
  Developers need Node.js 20+ and pnpm (or npm) installed.
- Frontend dependencies are managed separately from Python dependencies.
  No pip-installable JS bundling.
- The core Python engine has zero knowledge of the UI; the frontend uses only
  the versioned `protein-workbench-public/v2` REST and run-scoped WebSocket
  contracts.
