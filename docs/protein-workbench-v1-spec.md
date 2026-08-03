> Historical v1 specification. This document is non-normative for the active
> Catalog. In particular, its built-in `StructureAlignment` design is
> superseded by ADR-0038 and `structure_comparison.alignment_evidence@4.0.0`.

## Problem Statement

A protein engineer wants to generate, fold, score, and select protein sequences and structures using state-of-the-art models (ESM3, ProteinMPNN, ESMFold2, SimpleFold), but currently every model requires its own ad-hoc scripts, manual format conversions, and separate result tracking. Switching between tools means losing lineage — there is no single surface where a user can compose models into a visual pipeline, compare candidates across branches, and save the entire workflow for reproduction.

## Solution

A modular, node-based protein design workbench for personal local use. The user builds workflows on a visual canvas by connecting typed ports between self-contained modules. The system validates port compatibility, executes the DAG in topological order, caches results by content hash, and persists projects as human-readable JSON. New models and scoring methods are added by implementing a stable Module interface — no core code changes required.

## User Stories

1. As a protein engineer, I want to import a PDB structure into the workbench, so that I can use it as a starting point for design.
2. As a protein engineer, I want to import a FASTA sequence into the workbench, so that I can fold or modify it.
3. As a protein engineer, I want to build a multi-track ProteinPrompt with per-residue control over sequence, structure visibility, secondary structure, and SASA, so that I can precisely specify what ESM3 should condition on versus generate.
4. As a protein engineer, I want to insert, delete, set, and mask individual residues in my prompt, so that I can redesign specific regions while keeping others fixed.
5. As a protein engineer, I want structure visibility and sequence specification to be independent at each residue position, so that I can provide structural constraints without fixing the sequence.
6. As a protein engineer, I want to compute DSSP secondary structure and SASA from an imported structure and optionally override them by hand, so that my prompt reflects both computational and expert knowledge.
7. As a protein engineer, I want to add named function annotations as residue ranges in my prompt, so that ESM3 receives functional constraints.
8. As a protein engineer, I want to generate protein sequences from my ProteinPrompt using ESM3, so that I can explore the model's sequence space conditioned on my structural and functional constraints.
9. As a protein engineer, I want to generate protein structures from my ProteinPrompt (or an updated sequence) using ESM3, so that I can obtain backbone coordinates consistent with the generated sequence.
10. As a protein engineer, I want to update only the sequence track of a ProteinPrompt with a generated sequence while preserving all other tracks, so that I can feed the updated prompt into structure generation.
11. As a protein engineer, I want to design new sequences conditioned on a protein structure using ProteinMPNN, so that I can explore sequence diversity for a fixed backbone.
12. As a protein engineer, I want to specify ProteinMPNN constraints (designable positions, fixed positions, chain selections, tied positions, amino acid biases) as a separate node, so that my constraints are explicit and reusable.
13. As a protein engineer, I want ProteinMPNN to produce a per-sequence score alongside the designed sequences, so that I can use the model's own confidence as a selection criterion.
14. As a protein engineer, I want to fold a protein sequence into a 3D structure using ESMFold2, so that I can evaluate whether a designed sequence adopts the intended fold.
15. As a protein engineer, I want to fold a protein sequence using SimpleFold's lightweight model for fast screening, so that I can filter candidates before running expensive scoring.
16. As a protein engineer, I want to re-score existing structures with SimpleFold's larger evaluate model without re-folding, so that I can get more accurate confidence estimates on my top candidates.
17. As a protein engineer, I want to align two protein structures and obtain a reusable StructureAlignment (residue mapping, rotation, translation, RMSD), so that multiple scoring modules can share one superposition.
18. As a protein engineer, I want to compute TM-score between two aligned structures, so that I can assess global structural similarity.
19. As a protein engineer, I want to compute RMSD between two aligned structures, so that I can quantify backbone deviation.
20. As a protein engineer, I want to compute DSSP secondary structure from a folded structure, so that I can compare it against my target secondary structure specification.
21. As a protein engineer, I want to compute secondary structure agreement between my expected track and observed DSSP output, so that I can score how well a fold matches my design intent.
22. As a protein engineer, I want to aggregate multiple pLDDT or confidence scores from a model into a single summary score, so that I can rank candidates by overall confidence.
23. As a protein engineer, I want to merge scores from different scoring modules into a single ScoreCollection, so that I can use them jointly in selection.
24. As a protein engineer, I want to filter candidates by score thresholds (e.g., TM-score >= 0.75), so that I remove poor candidates before ranking.
25. As a protein engineer, I want to sort candidates by a single score in ascending or descending order, so that I can quickly find the best candidate by one criterion.
26. As a protein engineer, I want to select the top-K candidates by a score or weighted combination, so that I keep a manageable number for further analysis.
27. As a protein engineer, I want to rank candidates by a weighted combination of multiple scores, so that I can balance competing objectives like TM-score versus sequence diversity.
28. As a protein engineer, I want to perform Pareto selection across multiple scores, so that I can identify non-dominated candidates without setting arbitrary weights.
29. As a protein engineer, I want diversity selection to pick candidates that span the score landscape, so that I don't get a cluster of near-identical top candidates.
30. As a protein engineer, I want to see the lineage of each candidate (which model produced it, from which parent candidate, through which folding step), so that I can trace how a final candidate was derived.
31. As a protein engineer, I want to view a generated protein structure in a 3D molecular viewer directly in the workbench, so that I can visually inspect folds without exporting to external tools.
32. As a protein engineer, I want to view and compare multiple sequence alignments in the workbench, so that I can spot conserved and varied positions across candidates.
33. As a protein engineer, I want to save my entire workflow (nodes, connections, parameters) to a project file, so that I can close the workbench and resume later.
34. As a protein engineer, I want to reload a saved workflow and have it restore all nodes, edges, and parameter values, so that my work is reproducible.
35. As a protein engineer, I want to open a workflow that references a module I haven't installed yet, see the missing module marked on the canvas, and have the rest of the workflow remain intact, so that a missing module doesn't break my project.
36. As a protein engineer, I want to run my entire workflow with one click and watch execution progress node by node, so that I can monitor long-running model calls.
37. As a protein engineer, I want to cancel a running workflow at any time, so that I can abort a misconfigured run without waiting for it to finish.
38. As a protein engineer, I want cached node results to be reused when I re-run a workflow with unchanged inputs and parameters, so that I don't waste time recomputing expensive model calls.
39. As a protein engineer, I want to force re-run a specific node even when it's cached, so that I can regenerate outputs after changing my scientific judgment.
40. As a protein engineer, I want to clear the cache for a project or a single node, so that I can reclaim disk space or force fresh computation.
41. As a protein engineer, I want unrelated workflow branches to continue executing when one branch fails, so that a single model error doesn't kill my entire run.
42. As a protein engineer, I want to connect one output port to multiple downstream input ports (branching), so that a single generated sequence can be folded by both ESMFold2 and SimpleFold for comparison.
43. As a protein engineer, I want a downstream node to accept inputs from multiple upstream nodes (merging), so that I can compare an ESM3 structure with a SimpleFold structure using TM-score.
44. As a protein engineer, I want to extract a protein sequence from a structure, so that I can feed it into sequence-based scoring or re-design.
45. As a protein engineer, I want to extract the backbone from a full-atom structure, so that I can compare backbone-only geometry.
46. As a protein engineer, I want to select specific chains from a multi-chain structure, so that I can work with a single chain of interest.
47. As a protein engineer, I want to group related nodes visually on the canvas and add annotations, so that I can organize complex workflows.
48. As a protein engineer, I want nodes from the same category (model, scoring, selection, etc.) to be visually distinct, so that I can scan the canvas quickly.
49. As a protein engineer, I want the system to prevent me from connecting incompatible port types (e.g., connecting a sequence to a structure input), so that I catch configuration errors at edit time rather than at run time.
50. As a protein engineer, I want parameter forms to be auto-generated from each module's definition, so that I don't need to memorize parameter names or valid ranges.
51. As a module developer, I want to add a new model module by writing a ModuleDefinition YAML and implementing a run() method, so that my model appears in the node menu without modifying the core engine.
52. As a module developer, I want to register a new port type ID and have the system check compatibility against it, so that my custom data type flows through the workbench without the core understanding its internals.
53. As a module developer, I want existing modules to continue working after a core engine upgrade, so that my investment in module development is preserved.

## Implementation Decisions

### Module system

- Each module is defined by a `definition.yaml` that declares its module ID, version, category, input ports, output ports, and configurable parameters. The YAML is parsed into a `ModuleDefinition` dataclass at startup.
- The Python interface is `WorkflowModule` with `definition`, `validate()`, and `run()` methods. Minimally, a module only needs `definition` and `run()`. The `run()` method receives `inputs: dict`, `parameters: dict`, and `context: RunContext`, and returns `dict` keyed by output port name.
- Registration is two-phase: each subpackage under `modules/` exposes a `register(registry)` function; `discover_modules()` imports every subpackage and calls `register()`. The registry is populated once at startup and never modified at runtime.
- Module ID is a stable dotted string (e.g., `esm3.generate_sequence`, `proteinmpnn.design`). Display name can change; ID must not.
- Categories (input, prompt, model, conversion, scoring, selection, output) are only for UI organization — no runtime behavior depends on category.

### Type system

- Port compatibility is checked against string type IDs (e.g., `protein.sequence`, `protein.structure`). The engine never inspects the internal structure of data passing through ports.
- Runtime data is carried by concrete Python dataclasses in a `types/` package. Each class corresponds to one type ID.
- Connection is allowed when type IDs match exactly, or when an explicit conversion node sits between them. The system never performs implicit scientific conversions.
- New modules can register new type IDs without modifying the core.
- Public types (ProteinSequence, ProteinStructure, ProteinPrompt, ScoreCollection, etc.) are independent of provider SDKs. Module adapters translate between public types and provider-native formats.

### ProteinPrompt

- All tracks (sequence, structure coordinates, structure visibility, secondary structure, SASA, function annotations) use per-residue arrays of length equal to the target layout. Each position holds either a concrete value or a sentinel meaning unspecified/masked/not-visible.
- Tracks are fully independent: sequence specification and structure visibility each have their own array.
- A `ResidueMap` stores the correspondence between a template structure and the target layout, tracking insertions, deletions, and matched positions.
- Supported edit operations: Insert, Delete, Set Residue, Mask Residue.

### Structure data

- `ProteinStructure` carries a canonical PDB string rather than raw coordinate arrays. All three providers (ESM SDK, ProteinMPNN, SimpleFold) can read and write PDB natively.
- PDB strings are self-describing and hash directly for cache keys. The trade-off (larger than binary coordinates) is accepted because protein-scale structures produce PDB files under 2 MB.
- Structure metric normalization: pTM is a dimensionless scalar; PAE is an `(L,L)` matrix aligned to the target sequence residues. Adapters perform exact normalization only — no generic squeeze or shape guessing.

### Candidate system

- Each `Candidate` has a unique ID, a data reference, a list of parent candidate IDs, and metadata (e.g., sample index). Candidates flow through the workflow in `CandidateCollection` objects.
- Lineage is tracked through parent IDs, enabling traceback from a final candidate through generation and folding steps.

### Scoring system

- `ScoreCollection` holds a list of score entries, each with a score ID, a numeric value, subject references, and optional details.
- Structure comparison is decomposed: `structure.align` produces a `StructureAlignment`, which is consumed by `structure.tm_score` and `structure.rmsd`. This avoids recomputing the superposition.

### Execution engine

- Serial execution only: nodes run one at a time in topological order. No concurrency.
- Node states: idle → queued → running → completed / failed / cancelled.
- When a node fails, its direct downstream dependencies are marked blocked. Unrelated branches continue executing.
- Modules must return either complete, valid outputs for all declared output ports, or fail entirely. No partial or degraded results.

### Cache

- Content-addressed: cache key is `hash(module_id, module_version, input_hashes, normalized_parameters, seed)`.
- Only successful runs are cached. No TTL or staleness check; entries live until manually deleted.
- UI-only fields (node position, color, annotation) are excluded from the cache key.

### Project persistence

- Three-file layout: `workflow.json` (nodes, module IDs, versions, parameters, connections), `ui.json` (canvas positions, dimensions, grouping, colors, annotations, zoom), and `project.json` (name, timestamps, workflow version, module dependencies).
- Large data payloads (sequences, structures, candidates) are stored as separate files under `inputs/` and `outputs/` with relative path references.
- The `workflow.json` / `ui.json` split keeps the computation graph independent of presentation — workflows are shareable without canvas state.
- Missing modules: the workflow loads with the missing node displayed on canvas but marked non-executable. Installing the module restores execution capability.

### Frontend-backend contract

- FastAPI serves a REST API for CRUD (modules, types, projects, workflows) and a WebSocket for real-time execution progress.
- The backend has no knowledge of the UI framework. The API is the sole contract.
- Frontend: React + TypeScript + Vite + React Flow (@xyflow/react) for the node editor canvas.

### Provider integration

- ESM SDK (esm) and SimpleFold (ml-simplefold) are installed as normal pip packages from their repository directories.
- ProteinMPNN has no package structure; a thin wrapper in `modules/proteinmpnn/` imports the `ProteinMPNN` class from `repositories/ProteinMPNN/protein_mpnn_utils.py` without modifying upstream code.
- ESM3 generation parameters (track, schedule, strategy, num_steps, temperature, top_p) are module-level parameters, not attached to ProteinPrompt.
- ESMFold2 uses strict single-chain contract: one `/fold` call per request, with optional `include_pae` and `include_embeddings` controls. Distogram is not supported. `/fold_all_atom` is not used.
- SimpleFold is split: `simplefold.fold` (100M model, sequence → structures with pLDDT) and `simplefold.evaluate` (larger model, structures → scores without re-folding).

### ESM3 generation output classification

Every present structure in a Generation Result carries a source classification:
- Direct generation without coordinates in the prompt → structure absent.
- Direct generation with template coordinates → `prompt_reconstruction` only (the structure mirrors the input). Cannot be claimed as sampled structure.
- Guided generation → `sampled_structure` only for the terminal denoise structure actually selected by the product loop.
- `independent_fold` belongs to the Folding Backend, not to generation classification.

## Testing Decisions

### What makes a good test

Tests verify external behavior through public interfaces — ModuleRegistry, TypeRegistry, Executor, module `run()` contracts, and the REST/WebSocket API. Tests never assert on internal implementation details like tensor shapes, file paths, or private method calls.

### Seams and modules tested

**Seam 1 — Module Registry + Type Registry.** Test through `ModuleRegistry` and `TypeRegistry` public methods: YAML definition parsing, port compatibility checking, module discovery, type ID registration. Mock no internal registry state.

**Seam 2 — Execution Engine.** Test through the `Executor` by submitting workflow DAGs (nodes + edges) and verifying: topological ordering, output passing, cache hit/miss, error propagation to downstream, independent branch completion. Use stub modules that return predictable outputs.

**Seam 3 — Module `run()` contracts.** Test each real module by calling `run()` with known inputs and parameters, then asserting outputs match declared port types. Provider SDKs may be mocked at the adapter boundary for unit tests; acceptance tests use live providers.

**Seam 4 — Project persistence.** Test `Project.save()` and `Project.load()` round-trips: all nodes, edges, and parameters survive serialization; missing modules produce a loadable but non-executable workflow; `ui.json` is independent of `workflow.json`.

**Seam 5 — Frontend API contract.** Test through HTTP requests to FastAPI endpoints (CRUD for modules, types, projects, workflows) and WebSocket messages (execution start, progress, completion, error). The backend is tested without a browser; the frontend is tested with the real API server.

### Prior art

No existing tests in the repo. Tests follow standard pytest conventions with fixtures for module registration, executor setup, and project directories. Acceptance tests for live providers follow the pattern in biohub-api-reference: evidence is recorded with dated run roots, readiness probes, and JUnit XML output.

## Out of Scope

- Multi-user support, authentication, or authorization
- Plugin marketplace or third-party module distribution
- Containerized module isolation or security sandboxing
- License management or scientific provenance archival system
- Remote/distributed task scheduling or cloud deployment
- Arbitrary scripting interface for user-defined scoring functions
- ComfyUI kernel or custom node framework reuse
- A universal "super-input" object with all possible future fields
- A universal "super-node" that can run any model
- Model-specific if/else branches in core engine code
- Pre-implementation of hypothetical future models or scoring methods
- Hot-reloading of modules at runtime
- Automatic cache invalidation on code changes or TTL expiry
- Concurrent or parallel node execution

## Further Notes

- The architecture document (`protein_workbench_architecture.md`) and 17 ADRs in `docs/adr/` are the authoritative design references. Where this spec is silent, the architecture document governs. Where they conflict, this spec takes precedence as the implementation-target document.
- The Biohub API reference (`docs/biohub-api-reference/`) defines provider contracts for ESM3 and ESMFold2. The `product-contract-supplement.md` defines accepted model identities and capability boundaries. The `observed-runtime-overlay.md` captures dated empirical evidence that constrains what the product can claim. When dated observations contradict static API snapshots, dated observations control.
- Module versioning: `module_api` field in ModuleDefinition governs core-to-module compatibility. Module-level versions follow semver (major for incompatible port changes, minor for backward-compatible additions, patch for implementation fixes).
- The `repositories/` directory is a read-only vendor area. Upstream code in `repositories/ProteinMPNN/`, `repositories/esm/`, and `repositories/ml-simplefold/` is never modified.
- The spec targets a personal local-use tool. Performance constraints, machine specs, and model availability are those of a single macOS workstation with Apple Silicon (MPS backend). Parallel execution is explicitly excluded (ADR 0006).
