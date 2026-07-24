# 01 — Project scaffold, type system, and module registry

**What to build:** Set up the full project skeleton so that the backend serves a list of registered modules and their type definitions to a React canvas. A user opens the app, sees an empty node editor canvas, opens the "add node" menu, and sees all discovered modules organized by category — even though the modules don't run yet.

The deliverable is a working dev loop: `pnpm dev` for the frontend, `uvicorn` for the backend, all Python types defined and importable, YAML module definitions parsed and validated at startup, and the REST API returning real registry data to the UI.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Python package structure in place: `core/`, `types/`, `modules/`, `tests/` directories with `__init__.py` files, `pyproject.toml` with dependencies (FastAPI, uvicorn, PyYAML, pytest).
- [ ] All public Python dataclasses defined in `types/`: ProteinSequence, ProteinStructure, ProteinPrompt, ResidueLayout, ResidueMap, ResidueTrack, FunctionAnnotations, Candidate, CandidateCollection, ScoreCollection, Score, StructureAlignment.
- [ ] `TypeRegistry` implemented: register type IDs, check compatibility by exact string match, query all registered types.
- [ ] `ModuleDefinition` dataclass with YAML parsing: reads `definition.yaml`, validates required fields (module ID, version, category, input ports, output ports, parameters), produces a validated object.
- [ ] `ModuleRegistry` with two-phase registration: `register(registry)` function per subpackage, `discover_modules()` imports all subpackages under `modules/` and calls their `register()`.
- [ ] One stub module registered (`modules/stub/`) with a `definition.yaml` and a `register()` function, so the registry is non-empty at startup.
- [ ] FastAPI server with `GET /api/modules` (returns all ModuleDefinitions) and `GET /api/types` (returns all type IDs).
- [ ] React + TypeScript + Vite + React Flow frontend scaffold: empty canvas with background grid, minimap, controls. "Add Node" menu populated by fetching `/api/modules` and grouping by category.
- [ ] Tests: TypeRegistry compatibility (match, mismatch), ModuleRegistry YAML parsing (valid and invalid definitions), `discover_modules()` finds stub module. REST endpoint returns expected JSON shapes.
