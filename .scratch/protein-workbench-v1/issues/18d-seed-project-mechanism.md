# 18d — Server-side seed project mechanism

**What to build:** On server startup, `ProjectManager.ensure_seed_project()` creates the 3GB1 pipeline example project from the workflow JSON if it doesn't already exist. The project has a deterministic UUID (UUID5 from workflow content hash), is marked `seed: true` in `project.json`, and appears in the frontend project list. Creation is idempotent — repeated restarts don't duplicate. Failure logs a warning without blocking server startup.

**Blocked by:** 18c — needs the workflow JSON and UI layout to create the project.

**Status:** ready-for-agent

- [ ] `ProjectManager.ensure_seed_project(workflow_json_path, ui_json_path)` method: computes deterministic project ID via `uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(workflow_content, sort_keys=True))`; checks if project directory exists → skip if yes; validates all `module_id` references against registry → skip on failure (log warning); creates project dir with `project.json` (including `"seed": true`), `workflow.json`, `ui.json`
- [ ] Returns `ProjectMeta | None` (meta on success/create, `None` on skip or failure)
- [ ] Hooked into FastAPI lifespan in `core/server.py` after `discover_modules()` and `ProjectManager` init
- [ ] Unit tests: first call creates project with correct files; second call is idempotent (no duplicate); invalid workflow JSON (missing module) logs warning and returns `None`; deterministic ID is stable across calls; seed project appears in `list_projects()`
- [ ] No frontend changes
*** End Patch
