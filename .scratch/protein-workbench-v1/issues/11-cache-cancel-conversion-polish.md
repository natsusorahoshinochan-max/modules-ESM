# 11 — Cache, cancellation, conversion nodes, and polish

**What to build:** A user re-runs a workflow and sees cached nodes skip execution with a cache-hit indicator. They force re-run a specific node when they change their mind about a scientific judgment. They cancel a long-running model call mid-execution and see unrelated branches continue. They use conversion nodes (extract sequence from a structure, select specific chains, extract backbone-only coordinates) to connect modules whose port types don't directly match. They group related nodes on the canvas and add annotations to document their workflow.

**Blocked by:** 03 — Project persistence and missing-module handling.

**Status:** ready-for-agent

- [ ] Content-addressed cache: `cache_key = hash(module_id, module_version, input_hashes, normalized_parameters, seed)`. Before executing a node, the executor computes the cache key and checks `cache/{node_id}_{cache_key}.pkl`. On hit, loads cached outputs and skips execution. On success, writes outputs to cache. Failed nodes are never cached.
- [ ] Cache management: user can clear cache for a single node (right-click → "Clear Cache"), for an entire project, or force re-run a node (ignores existing cache entry for this execution only).
- [ ] Cache storage: pickle files in `cache/` under the project directory. UI-only fields (node position, color, annotation) excluded from cache key.
- [ ] Cancel execution: "Cancel" button in toolbar during an active run. Sends cancellation signal. Currently-running node finishes its current atomic operation if possible, then marks as cancelled. All queued nodes are skipped. Already-completed nodes are unaffected.
- [ ] `Extract Sequence from Structure` module: input = `protein.structure`, output = `protein.sequence`. Extracts amino acid sequence from PDB ATOM records.
- [ ] `Extract Backbone` module: input = `protein.structure`, output = `protein.structure`. Produces a new ProteinStructure with only N, CA, C, O backbone atoms — side chains removed. PDB string rewritten accordingly.
- [ ] `Select Chains` module: input = `protein.structure`, output = `protein.structure`. Module parameter: `chains` (list of chain ID strings). Produces a new ProteinStructure containing only the specified chains.
- [ ] `Map Residue Track` module: input = `residue.track` + `residue.map`, output = `residue.track`. Applies a ResidueMap to remap a track from source layout to target layout.
- [ ] UI: cache hit indicator on nodes — small green cache icon when node was served from cache. Tooltip shows cache key and timestamp.
- [ ] UI: "Force Re-run" in node context menu. "Clear Node Cache" in node context menu. "Clear Project Cache" in project settings.
- [ ] UI: cancel button in toolbar, visible only during execution. Confirmation dialog for cancel.
- [ ] UI: node grouping — select multiple nodes, right-click → "Group". Group appears as a colored bounding box with a title. Groups can be collapsed to a single composite icon. Annotations: double-click canvas to add a text note.
- [ ] UI: conversion nodes appear in a "Conversion" category in the Add Node menu.
- [ ] Tests: cache hit returns identical output to fresh execution. Cache miss when input changes. Force re-run ignores cache. Cancel stops execution, completed nodes unaffected. Extract Sequence produces correct amino acid string from PDB. Extract Backbone keeps only backbone atoms. Select Chains filters correctly. Map Residue Track handles match/insert/delete operations.
