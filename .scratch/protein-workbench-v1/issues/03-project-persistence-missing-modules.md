# 03 — Project persistence and missing-module handling

**What to build:** A user builds a workflow on the canvas, saves it, closes the app, reopens the app, loads the project, and sees every node, edge, parameter value, and canvas position restored exactly as it was. If the workflow references a module that isn't installed, the node still appears on the canvas but is visually marked as unavailable and cannot be executed.

This delivers the three-file project format and the split between computation state and presentation state.

**Blocked by:** 02 — Execution engine with first stub module.

**Status:** ready-for-agent

- [ ] `Project` dataclass and manager: `create()`, `save()`, `load()`. Project directory layout: `project.json`, `workflow.json`, `ui.json`, `inputs/`, `outputs/`.
- [ ] `project.json` schema: name, created_at, modified_at, workflow_version, module_dependencies list.
- [ ] `workflow.json` schema: nodes (node_id, module_id, module_version, parameters dict), edges (from node+port → to node+port). No UI fields.
- [ ] `ui.json` schema: node_positions (node_id → {x, y}), node_dimensions, groupings, colors, annotations, canvas_zoom, viewport.
- [ ] Save: serialize workflow to `workflow.json`, UI state to `ui.json`, metadata to `project.json`. Large data payloads stored as separate files under `inputs/` and `outputs/` with relative path references in the workflow.
- [ ] Load: parse `workflow.json` first, then `ui.json`. If `ui.json` is missing or corrupted, nodes auto-layout on the canvas without data loss. If `workflow.json` references a module ID not in the registry, create a placeholder node marked "unavailable" — it displays on canvas with all saved parameters and connections but cannot be executed.
- [ ] Installing a previously-missing module restores the placeholder node to executable state on next project load.
- [ ] REST API: `GET /api/projects` (list), `POST /api/projects` (create), `GET /api/projects/{id}` (metadata), `GET /api/projects/{id}/workflow` (workflow.json), `PUT /api/projects/{id}/workflow` (save workflow), `GET /api/projects/{id}/ui` (ui.json), `PUT /api/projects/{id}/ui` (save UI state).
- [ ] UI: "Save" and "Save As" buttons in toolbar. "Open Project" dialog listing saved projects. Auto-save on workflow changes (debounced).
- [ ] UI: missing-module nodes rendered with distinct styling (dashed border, warning icon, muted colors) and a tooltip showing the missing module ID.
- [ ] Tests: save-load round-trip preserves all nodes, edges, parameters. `ui.json` deleted → workflow still loads with auto-layout. Missing module ID → placeholder node created, rest of workflow intact. `workflow.json` / `ui.json` independence verified.
