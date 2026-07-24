# Frontend technology stack

The node-based graphical UI is built with React, TypeScript, Vite, and React Flow.
These are the industry-standard tools for node-editor interfaces (ComfyUI uses the
same stack) and have broad community support, mature type definitions, and
well-documented patterns for custom nodes, edges, and parameter forms.

## Technology choices

### React + TypeScript

TypeScript provides compile-time safety for the complex data structures flowing
through the UI (port types, module definitions, workflow state). React's component
model maps naturally to the node/port/parameter decomposition in the architecture.

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

Alternatives considered: building a custom canvas from scratch (reinventing
React Flow's decade of edge cases), using Cytoscape.js (graph visualization,
not a node editor), Rete.js (less mature React support).

### 3D structure viewer

For the ProteinStructure viewer, we use NGL (nglviewer) via its React wrapper.
It handles PDB strings natively, matching our PDB-string exchange format
(ADR-0010), and provides the expected molecular visualization features
(rotation, zoom, selection, coloring by chain/B-factor/SSE).

Alternatives considered: Mol* (heavier, designed for full PDB browsing rather
than embedded single-structure viewing), PyMOL web export (requires external
render step), 3Dmol.js (less modern React integration).

### Parameter form generation

Parameter forms are auto-generated from the module's YAML ModuleDefinition
served by the backend. The frontend maps parameter types to widgets:
- integer/float → number input with min/max/step
- boolean → toggle/checkbox
- string → text input
- multi-line text → textarea
- enum → select/dropdown
- file path → file picker
- residue range → dual-range slider
- chain selection → multi-select

Modules can supply an optional custom parameter editor component, but standard
modules rely on auto-generated forms.

### Project structure

```
ui/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   │   ├── canvas/
│   │   │   ├── WorkflowCanvas.tsx     # React Flow wrapper
│   │   │   ├── ModuleNode.tsx         # Custom node rendering
│   │   │   └── PortHandle.tsx         # Typed port connection handles
│   │   ├── editors/
│   │   │   ├── ParameterForm.tsx      # Auto-generated from ModuleDefinition
│   │   │   ├── ProteinPromptEditor.tsx
│   │   │   └── StructureViewer.tsx    # NGL wrapper
│   │   ├── viewers/
│   │   │   ├── SequenceViewer.tsx
│   │   │   ├── CandidateViewer.tsx
│   │   │   └── ScoreViewer.tsx
│   │   └── layout/
│   │       ├── Toolbar.tsx
│   │       ├── NodePalette.tsx        # Module browser/catalog
│   │       └── StatusBar.tsx
│   ├── api/
│   │   ├── client.ts                 # FastAPI REST client
│   │   └── websocket.ts             # Execution progress WebSocket
│   ├── stores/
│   │   ├── workflowStore.ts          # Workflow graph state
│   │   ├── uiStore.ts               # Canvas layout state
│   │   └── executionStore.ts         # Run status per node
│   └── types/
│       ├── workflow.ts               # Mirrors backend workflow model
│       ├── module.ts                 # ModuleDefinition TypeScript types
│       └── ports.ts                  # Port type ID constants
└── public/
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
- The core Python engine has zero knowledge of the UI; the contract is purely
  the REST + WebSocket API defined in ADR-0017.
