# Protein Workbench frontend

The frontend is a React, TypeScript, Vite, and React Flow client for the current
`protein-workbench-public/v2` protocol. It discovers Node Types and Bindings from
the Catalog, authors Project Workflow Drafts, commits and starts Runs, follows the
run-scoped lifecycle WebSocket, and retrieves bounded Run projections, individual
canonical Typed Output values, and Artifacts.

There is no unversioned API, legacy `/ws` stream, embedded-output path, or custom
prompt-authoring payload. Array and object scientific parameters remain typed
through the JSON parameter editor; scalar parameters use widgets derived from
their current Catalog value contracts.

## Development

```bash
npm install
npm run dev
```

Vite proxies both HTTP and WebSocket traffic under `/api` to the loopback backend
at `127.0.0.1:8000`.

## Verification

```bash
npm test
npm run lint
npm run build
```

The Vitest journeys cover explicit Binding choice, exact Workflow Selection
semantics round-trips, typed structured parameters, lifecycle events, bounded
projection metadata, single-value retrieval, Artifact links, and the WebSocket
development-proxy contract.
