# 20 — Protein Workbench v1 full-system diagnostic

## Status

Diagnosis complete. Seven read-only workstreams have been integrated below. No implementation
changes were made during this diagnosis, and repair planning has not started.

This issue records the gap between:

1. the original Protein Workbench v1 product contract;
2. the four-stage 3GB1 design workflow;
3. the current backend, frontend, seed project, historical artifacts, and tests.

The diagnosis must establish the complete problem landscape before repair work is split into
tickets or sequenced into a plan.

## Sources of truth

- `CONTEXT.md`
- `docs/protein-workbench-v1-spec.md`
- `docs/protein_workbench_architecture.md`
- `docs/adr/`
- `docs/biohub-api-reference/`
- `.scratch/protein-workbench-v1/issues/01-19c`
- `examples/3gb1_pipeline.json`
- current source, saved projects, cache artifacts, and `output/3gb1_pipeline/`

## Original 3GB1 acceptance target

1. Build a 3GB1 ProteinPrompt with 20 randomly masked sequence residues, 15 inserted masked
   residues, 10 masked structure positions, and the requested E/H/unspecified secondary
   structure track.
2. Produce 10 index-paired ESM3 sequence/structure outputs, fold the sequences with ESMFold2,
   score each fold against both 3GB1 and the corresponding ESM3 structure, and rank with
   weights 0.7 and 0.3.
3. Select the top three folded structures, expose each complete structure to ProteinMPNN,
   fix 50% of residues, and generate five sequences per structure.
4. Fold the resulting 15 sequences with ESMFold2 and produce 15 PDB files.
5. Expose the same workflow as an editable, directly runnable default frontend example that
   depends only on the user's configured API key.

## Historical implementation evidence

- Tickets 01-19c have corresponding implementation commits.
- `scripts/3gb1_pipeline.py` contains a Python orchestration path.
- `output/3gb1_pipeline/` contains 15 historical final PDB files grouped as three
  ProteinMPNN design runs with five files per run.
- `examples/3gb1_pipeline.json` contains 22 nodes and 31 edges.
- Historical project caches contain ESM3, ESMFold2, ProteinMPNN, alignment, scoring, and final
  folding outputs.

Historical artifacts prove that code paths have executed. They do not by themselves prove
that the current checkout, current seed project, scientific scoring semantics, frontend
workflow, and one coherent live run all satisfy the acceptance target.

## Confirmed findings before parallel investigation

### DIAG-001 — Current ESM3 track conversion corrupts amino-acid sequences

`modules/esm3_adapter.py::_track_to_str()` applies the ESM3 SS8 whitelist to both the
secondary-structure track and the sequence track. Legal amino acids outside `GHITEBSC` are
converted to `C`.

Tight red-capable loop:

```bash
.venv/bin/pytest -q \
  tests/test_esm3.py::TestESM3Adapter::test_prompt_to_esm_protein_basic
```

Observed:

```text
E assert 'CGS' == 'AGS'
```

The loop is deterministic, agent-runnable, and completes in seconds.

### DIAG-002 — The current deterministic seed project is mutated and fails before ESM3

The current seed ID derived from `examples/3gb1_pipeline.json` is
`db7a32d2-ca10-51e3-a98c-9d405ad0a488`. Its saved workflow has 32 edges rather than the
canonical 31. The extra edge is:

```text
insert_struct.track -> assemble.function_annotations
```

The cached assembled ProteinPrompt consequently carries a `ResidueTrack` in
`function_annotations`. Replaying that cached prompt through
`protein_prompt_to_esm_protein()` deterministically raises:

```text
AttributeError: 'ResidueTrack' object has no attribute 'annotations'
```

The seed mechanism skips an existing deterministic project without validating or restoring
its workflow. Two projects are currently marked `seed: true`.

### DIAG-003 — The frontend seed does not implement top-three times five

The canonical seed connects the `top3` CandidateCollection to one `proteinmpnn.design` node
configured with `num_sequences: 15`.

`ProteinMPNNDesignModule` accepts a CandidateCollection only by taking `items[0].data`.
Therefore the frontend workflow redesigns the first top structure 15 times, rather than
redesigning each of three structures five times.

The existing seed E2E test checks only the total output count of 15 and cannot detect the
wrong parent distribution.

### DIAG-004 — Current batch "TM-score" is an RMSD-derived proxy

`structure.tm_score` and `structure.batch_tm_score` compute:

```text
1 / (1 + (global_rmsd / d0)^2)
```

They do not compute the standard per-residue TM-score sum or call `tmtools.tm_align` as
required by ADR 0011 and the original project contract. The reference path also matches
residues by chain/residue number, which is not a valid structural alignment after random
insertions shift residue correspondence.

### DIAG-005 — The seed secondary-structure prompt does not match the requested track

The seed computes DSSP, overwrites selected ranges, and then inserts 15 masked positions.
Consequences observed in the assembled cache:

- the requested E/H ranges are shifted by insertion;
- unspecified positions retain DSSP values such as `S` and `-`;
- the final track is not E/H at the requested absolute positions with every other position
  unspecified.

### DIAG-006 — ESM3 generation structure classification is weaker than joint sampling

The unified module calls Direct `generate(track="sequence")`. Under the dated Biohub
contract, a coordinate-conditioned response structure is `prompt_reconstruction`, not an
independently sampled structure. The 0.3 comparison therefore does not currently compare an
ESMFold2 fold against a genuinely sampled ESM3 structure.

### DIAG-007 — The frontend workflow does not produce 15 downloadable PDB files

The Python orchestration path writes final PDB files. The seed workflow ends at
`esmfold2.fold`; its 15 structures are kept in pickle cache. There is no batch export or
download path in the frontend workflow.

### DIAG-008 — Typed-port compatibility is not enforced

The canonical seed already contains three exact type-ID mismatches:

```text
residue.track.secondary_structure -> residue.track
residue.track -> residue.track.secondary_structure
candidate.collection -> protein.structure
```

The mutated seed adds a fourth:

```text
residue.track -> function.annotations
```

The frontend accepts these edges and the backend does not perform the authoritative
pre-execution compatibility check required by ADR 0017.

### DIAG-009 — Execution failure and recovery contracts are incomplete

- Node exceptions are converted to `failed` states inside the Executor without preserving a
  user-facing diagnostic.
- The server can still emit `run_complete` after one or more nodes failed.
- WebSocket messages are global rather than scoped to project/run.
- The frontend does not expose single-node run, force rerun, node/project cache clearing, or
  execution cancellation.
- Ticket 19c requires inline failure details and visible timeout/disconnect feedback, but the
  current frontend logs several of these conditions only to the console.

### DIAG-010 — The result inspection UI is far below the v1 contract

The current viewer can auto-load only the first structure found after a run. Candidate,
score, sequence, lineage, structure comparison, alignment overlay, residue selection,
secondary-structure comparison, and full ProteinMPNN constraints views remain absent or
partial.

### DIAG-011 — Current verification is not a clean acceptance record

- Targeted `.venv` verification from the repository root produced five passes and the
  deterministic DIAG-001 failure.
- Frontend lint passes.
- The mocked 22-node seed test passes but does not check 3x5 lineage, scientific TM-score,
  exact final secondary-structure semantics, typed edges, downloadable files, or browser
  behavior.
- There is no durable run manifest that binds all 22 nodes, provider calls, outputs, and
  failures to one coherent live frontend execution.
- Server tests use the production-relative `projects/` root and have created hundreds of
  test projects in the user-visible project list.
- There are no automated frontend unit or browser E2E tests.

## Parallel diagnostic workstreams

Each workstream is read-only. Agents must report evidence, minimal reproductions, violated
contracts, severity, and missing tests. They must not modify implementation files and must
not propose a repair sequence yet.

1. ESM3, ProteinPrompt, secondary structure, and Biohub generation semantics.
2. Structure alignment, TM-score, residue mapping, and weighted-ranking semantics.
3. 3GB1 seed DAG, seed persistence/drift, typed edges, 3x5 branching, lineage, and exports.
4. ProteinMPNN adapter, constraints, fixed-position semantics, collection behavior, and
   per-sequence scoring.
5. Execution Engine, REST/WebSocket contract, cache, cancellation, failure propagation,
   retry, and run isolation.
6. Frontend product-contract coverage, viewer behavior, result inspection, editing, and
   browser-test seams.
7. Test/acceptance evidence, provider readiness, artifact provenance, packaging, test
   isolation, and reproducibility.

## Consolidated problem landscape

The entries below consolidate duplicate symptoms into stable findings. A finding is marked
confirmed only when it has a deterministic source path plus either a minimal reproduction,
current cache evidence, or a contract-to-implementation comparison. Suspected risks are
recorded separately.

### A. Scientific and provider correctness

| ID | Severity | Confirmed finding | Evidence |
| --- | --- | --- | --- |
| SCI-001 | Critical | ESM3 sequence conversion applies an SS8 whitelist to amino-acid sequences. Legal residues are converted to `C`; a current test changes `AGS` to `CGS`, and replay of the seed prompt changes 26 visible residues. | `modules/esm3_adapter.py:25,79`; `.venv/bin/pytest -q tests/test_esm3.py::TestESM3Adapter::test_prompt_to_esm_protein_basic` |
| SCI-002 | Critical | `esm3.generate` performs only `generate(track="sequence")`. Its paired PDB is a `prompt_reconstruction`, not an independently sampled ESM3 structure. Index pairing exists, but the 0.3 branch does not compare against the sampled structure required by the workflow. | `modules/esm3_generate/module.py:68-97`; `docs/biohub-api-reference/product-contract-supplement.md:79-94`; ESM cookbook sequence-then-structure example |
| SCI-003 | High | A coordinate-free unified ESM3 response is still forced through PDB extraction and fails because no coordinates exist. | `modules/esm3_generate/module.py:97`; `ESMProtein(sequence="AAA").to_pdb_string()` raises an assertion |
| SCI-004 | High | `structure_visibility_track` is ignored by the ESM adapter. Hidden residues remain finite and visible to ESM3. | `modules/esm3_adapter.py:85`; two hidden residues reproduce `hidden_coords_finite=2` |
| SCI-005 | High | The structure prompt is reduced to CA-only coordinates. The other 36 atom37 positions are `NaN`, so this is not the full-template structure prompt shown by the ESM cookbook. | `modules/apply_residue_edits/module.py:27`; `modules/esm3_adapter.py:85`; current seed converts to 46 finite CA positions |
| SCI-006 | High | The seed secondary-structure prompt violates the requested final absolute positions. Overrides occur on the 56-residue DSSP track before insertion, unspecified positions retain DSSP values, and insertion shifts the requested ranges. | `examples/3gb1_pipeline.json:53,209`; current cache has 44 position mismatches and 18 unspecified positions with values |
| SCI-007 | Medium | ESM metric normalization is not fail-closed: arbitrary pTM shapes are flattened, and PAE is not emitted. | `modules/esm3_adapter.py:138`; `(1,1)` and `(2,)` pTM shapes are accepted |
| SCI-008 | Critical | Both TM-score modules calculate a global-RMSD proxy rather than standard TM-score. A 20-residue one-outlier case gives `0.0279` versus `tmtools=0.95`. Recomputing the historical 3GB1 cache changes top three from `[0,3,1]` to `[9,6,2]`. | `modules/structure_batch_tm_score/module.py:59-98`; `modules/structure_tm_score/module.py:39`; ADR 0011 |
| SCI-009 | Critical | Reference normalization and coverage are ignored. Twenty perfectly matched residues against a 56-residue reference report `1.0` instead of reference-normalized `0.3571428571`. | `modules/structure_batch_tm_score/module.py:59,87` |
| SCI-010 | Critical | Structure matching uses exact `(chain, resSeq)` equality instead of sequence/structure alignment. Insertions, renumbering, or chain changes produce wrong/empty mappings; residue numbers are also sorted lexicographically. | `modules/structure_align/module.py:84`; `modules/structure_pairwise_align/module.py:58-61`; insertion repro gives RMSD `5.946366 Å` where `tmtools=1.0` |
| SCI-011 | High | `StructureAlignment` lacks coordinates, per-residue distances, reference length, and sequences. Standard TM-score cannot be reconstructed from its RMSD and coverage fields alone. | `datatypes/protein.py:193`; conflict between ADR 0011 and ticket 18b |
| SCI-012 | High | `structure.tm_score` emits `subjects=[]`; therefore its score cannot affect `weighted_rank`, even when its numeric value is nonzero. | `modules/structure_tm_score/module.py:55`; `modules/weighted_rank/module.py:46` |
| SCI-013 | High | ProteinMPNN fixed positions cross a 0-based/1-based boundary without conversion. Position `0` fixes the last residue; position `1` fixes the first. The current 50% seed selection includes position `0`. | `modules/prompt_random_fixed_positions/module.py:42-45`; `modules/proteinmpnn/adapter.py:125-129`; `repositories/ProteinMPNN/protein_mpnn_utils.py:307-310` |
| SCI-014 | High | Most ProteinMPNN constraints are not translated to upstream format. `designable_positions` and chain selection are ignored; omit/tied/bias dictionaries have the wrong nesting/shape; multi-chain fixed positions can fail with `KeyError`. | `datatypes/protein.py:213-224`; `modules/proteinmpnn/adapter.py:114-150`; upstream `protein_mpnn_utils.py:218-225,307-355` |
| SCI-015 | High | ProteinMPNN computes one score for the input native sequence and assigns it to all generated sequences, rather than producing a score per generated sequence. | `modules/proteinmpnn/adapter.py:268-298`; `modules/proteinmpnn/module_design.py:81-86`; cache has one score with 15 subjects |
| SCI-016 | High | ProteinMPNN scoring failures are swallowed and converted to an empty score collection, so a declared output can be incomplete while the node appears successful. | `modules/proteinmpnn/adapter.py:288-298`; `core/workflow_module.py:55-58` |
| SCI-017 | Medium | The optional ProteinMPNN reference-sequence port is declared but never read. | `modules/proteinmpnn/definition_design.yaml:11-18`; `modules/proteinmpnn/module_design.py:40-62` |
| SCI-018 | Medium | `RunContext.seed` does not control ProteinMPNN randomness, while cache identity includes the workflow seed. The adapter also fixes backbone noise to `0.05`, differing from upstream default behavior. | `modules/proteinmpnn/module_design.py:52-62`; `modules/proteinmpnn/adapter.py:59-70,164-170`; upstream `protein_mpnn_run.py:24-31` |
| SCI-019 | Medium | ProteinMPNN scoring silently pads short/invalid sequences with `A` and truncates long sequences instead of rejecting invalid structure/sequence pairs. | `modules/proteinmpnn/adapter.py:251-255` |

### B. Workflow and seed correctness

| ID | Severity | Confirmed finding | Evidence |
| --- | --- | --- | --- |
| WF-001 | Critical | The canonical frontend workflow does not implement top-three times five. One ProteinMPNN node receives the collection, silently takes `items[0]`, and generates 15 sequences from only the first structure. | `examples/3gb1_pipeline.json:131-143,323-332`; `modules/proteinmpnn/module_design.py:40-47`; minimal adapter repro has one call with count 15 |
| WF-002 | Critical | The current deterministic seed `db7a32d2-...` contains an extra incompatible edge, `insert_struct.track -> assemble.function_annotations`, and fails deterministically before ESM3 with `ResidueTrack has no attribute annotations`. | `projects/db7a32d2-ca10-51e3-a98c-9d405ad0a488/workflow.json:362`; cached prompt replay |
| WF-003 | High | Seed projects are editable through normal autosave, the server does not protect `meta.seed`, and `ensure_seed_project()` does not validate or restore an existing deterministic seed. | `frontend/src/App.tsx:369`; `core/server.py:477`; `core/project.py:124`; current seed remains different from canonical after ensure |
| WF-004 | High | The seed UUID is derived from the complete workflow JSON. Canonical changes create another seed instead of upgrading a stable example; two projects are currently named `3GB1 Design Pipeline` and marked `seed:true`. | `core/project.py:120`; projects `c0644a31-...` and `db7a32d2-...` |
| WF-005 | High | Exact port compatibility is not enforced. The canonical DAG contains three type-ID mismatches; the mutated seed contains a fourth. | `core/graph.py:62`; `core/project.py:128`; registry audit of `examples/3gb1_pipeline.json` |
| WF-006 | High | ProteinMPNN candidate lineage points to the node ID instead of the selected parent structure candidate. Final results cannot be traced through the top-three decision. | `datatypes/protein.py:127`; `modules/proteinmpnn/module_design.py:67-77`; cache parents are all `mpnn_0` |
| WF-007 | High | The frontend workflow ends with a 15-item structure collection in pickle cache. It has no collection export path and produces zero final project output files. | `examples/3gb1_pipeline.json:146`; `modules/export_structure/definition.yaml:6`; `frontend/src/App.tsx:470-473` |
| WF-008 | Medium | The seed does not implement the per-node seeds specified by ticket 18. All random modules receive the same workflow seed, and ProteinMPNN does not receive it at all. | issue 18 seed contract; `core/executor.py:171`; example JSON has no node seed parameters |
| WF-009 | Medium | Server tests use the production-relative `projects/` root. The current workspace contains 441 project directories, including 47 copies each of several test project names. | `core/server.py:143-150`; `tests/test_server_projects.py`; filesystem inventory |

### C. Execution, state, cache, and API correctness

| ID | Severity | Confirmed finding | Evidence |
| --- | --- | --- | --- |
| RUN-001 | Critical | A node exception loses its diagnostic payload, while the server still emits `run_complete`. Observed event order can be `queued, running, run_complete, failed`. | `core/executor.py:222-237`; `core/server.py:328-340`; local failing-module WebSocket repro |
| RUN-002 | High | Node events are fire-and-forget tasks, so `run_complete` races ahead of terminal node states. On cache hit it can be the first event. | `core/server.py:316-340`; fresh repro `queued,running,run_complete,completed`; cache repro `run_complete,queued,running,completed` |
| RUN-003 | High | WebSocket broadcasts are global and not isolated by project or run. The frontend also ignores `run_id`, so another project/run can mutate the visible state. | `core/server.py:28-30,127-140,269-282`; `frontend/src/App.tsx:195-227`; two-socket repro |
| RUN-004 | High | The same project can run concurrently. Overlapping runs share node temp paths and cache filenames because those paths omit `run_id`. | `core/server.py:323-356`; `core/run_context.py:26-28`; local concurrency repro reaches `max_active=2` |
| RUN-005 | High | Completed run tasks remain forever in `_active_runs`; normal and failed execution paths have no cleanup. | `core/server.py:354-365`; completed-task repro leaves `active_run_count=1` |
| RUN-006 | High | Cancellation of default thread-backed modules is cosmetic: state becomes cancelled while the underlying operation continues. The frontend has no Cancel control. | `core/workflow_module.py:31-43`; `core/executor.py:212-220`; sleep repro finishes after `run_cancelled` |
| RUN-007 | Medium | A failed direct downstream node receives duplicate `blocked` transitions. | `core/executor.py:154-159,225-230`; `blocked -> blocked` event repro |
| RUN-008 | High | Most of ADR 0017's project/run-scoped execution APIs and messages are absent: status, outputs, cache listing, scoped WS, structured node errors/reasons, and run duration. | `core/server.py:267-399`; ADR 0017 |
| RUN-009 | High | Backend `force_rerun_nodes` exists as a hidden full-DAG option, but the product has no single-node run/retry, force rerun, or cache-clear action. Full-workflow rerun can reuse successful upstream cache, but it is not node-level recovery. | `core/executor.py:110-130,178-210`; `frontend/src/App.tsx:535-549,588-613` |
| RUN-010 | Medium | Cache keys do not normalize nested parameters. Semantically equal dictionaries with different insertion order produce different keys. | `core/executor.py:70-81`; local repro yields distinct hashes |
| RUN-011 | Critical | `project_id` is not contained under the projects root. Relative traversal and absolute paths escape the root and can reach cache mkdir/write paths. | `core/server.py:323-326`; `core/project.py:73-80`; `core/executor.py:84-108`; path-resolution repro |
| RUN-012 | High | Runs have no persistent manifest. Cache payloads contain only outputs, and node-output lookup chooses the newest cache by mtime rather than by run. Current and historical results cannot be bound to one coherent run. | `core/executor.py:49-108`; `core/server.py:404-448`; `c0644a31-...` has multiple keys for several nodes |

### D. Frontend product-contract completeness

| ID | Severity | Confirmed finding | Evidence |
| --- | --- | --- | --- |
| UI-001 | Critical | The generic ProteinPrompt editor writes undeclared `residues_data` and `annotations_data` parameters. Actual prompt modules read `edits`, `overrides`, or label/range fields, so visible residue edits do not affect execution. | `frontend/src/App.tsx:725-755`; prompt module definitions |
| UI-002 | High | Named handles exist, but the connection handler accepts every edge and never evaluates port `type_id`. | `frontend/src/App.tsx:475-485,574-582`; `WorkflowModuleNode.tsx:54-155` |
| UI-003 | High | Run starts immediately after creating a WebSocket without awaiting `onopen`. A fast or fully cached run can finish before subscription and leave the UI queued/running until timeout. | `frontend/src/App.tsx:191-195,520-555`; current WS test connects first and consumes no events |
| UI-004 | High | The fixed 300-second timer is total duration rather than inactivity timeout, does not cancel the backend, and discards the returned `run_id`. There are no cancel, retry, cache, or single-node controls. | `frontend/src/App.tsx:526-529,551-559,588-613` |
| UI-005 | High | Node state contains only a string; exceptions, timeout, and disconnect details are unavailable in the interface and mostly go to the console. | `frontend/src/App.tsx:51-53,195-199,229-235,652-723`; server state broadcast |
| UI-006 | High | Project open/save is incomplete: Open is hidden before creating a project, Save As is absent, viewport and most UI metadata are not restored/preserved, empty graphs are not autosaved, and project switches retain prior state/selection/viewer values. | `frontend/src/App.tsx:301-414,599-613`; UI API save path |
| UI-007 | High | Candidate, score, sequence, lineage, and comparison result panels are absent. Run completion selects only the first structure from one completed node. | `frontend/src/App.tsx:205-225`; `core/server.py:404-448` |
| UI-008 | High | The NGL viewer is a single-structure cartoon smoke. It lacks candidate selection, residue selection, alignment overlay, comparison, and explicit failures; NGL is loaded twice from an undeclared CDN dependency and errors are swallowed. | `frontend/src/App.tsx:76-83,205-225`; `frontend/index.html:8-9`; `package.json` |
| UI-009 | High | `.cif` import is incorrectly routed as a sequence, while Export is an alert rather than output download. The final 15 PDB files cannot be downloaded from the workflow. | `frontend/src/App.tsx:427-432,470-473,588-590` |
| UI-010 | Medium | Parameter forms lack file, multiline, residue-range, chain multi-select, and structured validation controls. ProteinMPNN constraints require manual JSON and do not expose the full contract. | `frontend/src/App.tsx:669-700`; ADR 0016; ProteinMPNN constraint definition |
| UI-011 | Medium | Missing-module parameter guidance is unreachable because the panel is rendered only when a module definition exists. | `frontend/src/App.tsx:274-283,317-345,652-663` |
| UI-012 | Medium | Grouping, copy, annotations, and context-menu behavior are absent. Fixed 280/360/320 px sidebars leave almost no canvas at a 1024 px desktop width. | ReactFlow props in `frontend/src/App.tsx`; `frontend/src/App.css`; `ProteinPromptEditor.css` |

### E. Verification, provenance, packaging, and reproducibility

| ID | Severity | Confirmed finding | Evidence |
| --- | --- | --- | --- |
| VER-001 | Critical | The built wheel omits module `definition.yaml` files. Isolated discovery from the wheel returns zero modules, while registry discovery swallows the registration errors. | `pyproject.toml:22`; `core/module_registry.py:86`; isolated wheel has 109 files and `discovered_modules=0` |
| VER-002 | High | The only automated 22-node tests mock ESM3, ESMFold2, ProteinMPNN, and DSSP and call `Executor` directly. They are neither remote-real nor frontend E2E. | `tests/test_e2e_seed_workflow.py:1,172`; `7 passed` with integration tests |
| VER-003 | High | Acceptance tests do not consume `run_root`, produce a manifest/JUnit evidence bundle, record provider calls, or enforce that required providers ran. Provider unavailability can be reported as skips inside a green run. | `tests/acceptance/conftest.py:31,78,98`; no `var/runs/` |
| VER-004 | High | Default `pytest` collection includes 16 live/slow acceptance tests. A generic test command can trigger provider or heavy-model work, and its result does not identify the verification tier. | `pyproject.toml:25`; `352 tests collected` |
| VER-005 | High | Server tests create projects in the user-visible production-relative project directory and do not clean them up. | Same evidence as WF-009 |
| VER-006 | High | Existing cache and 15 tracked PDB files are historical artifacts without run ID, workflow hash, Git identity, provider-call record, or output manifest. They prove code paths ran, not that the current checkout passed one coherent frontend run. | `core/executor.py:49-108`; `scripts/3gb1_pipeline.py:316`; `output/3gb1_pipeline/` |
| VER-007 | High | The Biohub observed-runtime document cites commits, tests, and run roots absent from this checkout. It is historical context, not current acceptance evidence. | `docs/biohub-api-reference/observed-runtime-overlay.md:121`; referenced identities and paths are absent |
| VER-008 | High | The frontend has no test script, unit/component tests, Playwright configuration, or browser E2E seam. Build and lint cannot validate product behavior. | `frontend/package.json`; `rg --files frontend` |
| VER-009 | Medium | The root package metadata cannot reproduce the current `.venv`. Runtime dependencies, WebSocket support, checkpoints, vendor installation, and frontend assets are not captured in a single install contract or lock. | `pyproject.toml:9`; current environment inventory |

## Evidence classification

| Verification tier | Current status |
| --- | --- |
| Current local-real module calls | Confirmed: mkdssp and single-module ProteinMPNN acceptance, `4 passed in 3.40s` |
| Current mocked workflow | Confirmed: seed/integration tests, `7 passed in 4.82s`; related module test groups also pass |
| Current frontend static checks | Confirmed: `npm run lint` and `npm run build` pass |
| Current remote Biohub readiness | API key and imports are present; no fresh remote call was made during this read-only diagnosis |
| Current remote-real workflow | Not demonstrated by an auditable run |
| Current browser E2E | Not demonstrated; no automated seam exists |
| Historical artifacts | 15 tracked PDB files and populated caches exist; no coherent run manifest binds them to current code |
| Installed-package acceptance | Fails: isolated wheel discovers zero modules |

## Known-good capabilities

- ProteinPrompt, residue layout, independent track datatypes, and length validation exist.
- Random masking produces exactly 20 and 10 masks; random insertion produces exactly 15
  sentinels. Shared insertion seeds keep sequence/structure/SS layouts index-aligned.
- DSSP is locally available and returns a 56-residue SS8 track. Current conversion preserves
  all eight SS8 symbols and maps DSSP `-`/unknown values to `C`; it does not collapse SS8 to
  SS3.
- Separate `esm3.generate_sequence`, `esm3.generate_structure`, and
  `esm3.update_prompt_sequence` modules exist. Historical unified results have sequence/PDB
  equality at all ten indices; the defect is structure provenance, not pair indexing.
- Pairwise collection count checks, index pairing, candidate-ID inheritance, and rigid-body
  SVD alignment work for structures with already-correct correspondence.
- Batch score subjects match the ten folded candidates in the historical cache. Given valid
  subjects and values, score merge plus 0.7/0.3 weighted arithmetic is exact.
- Basic Executor topology, cache reuse, input-change invalidation, force bypass, downstream
  blocking, and continuation of unrelated branches work in local tests.
- The CLI orchestration path loops over three selected structures, requests five sequences
  for each, and historically wrote 15 nonempty PDB files.
- Frontend named port handles, persisted source/target handles, Vite WebSocket proxy, and a
  non-null viewer data connection exist. Type validation and product completeness do not.

## Suspected risks requiring a separate evidence step

- The shared workflow seed makes the ten structure-mask positions a subset of the twenty
  sequence-mask positions for seed 42. The original contract does not state whether these
  selections must be statistically independent.
- Weighted ranking silently substitutes zero for a missing score and silently overwrites
  duplicate candidate/score pairs. The desired fail-closed policy is not explicit.
- Overlapping runs can write the same cache filename; cache corruption is plausible but was
  not deliberately induced.
- The frontend WebSocket startup race is source-confirmed, but a browser trace is still
  needed to attribute any one historical permanently-queued incident to that race.
- Viewer blankness may come from the event-order race, stale latest-cache selection, or
  silent CDN/NGL load failure; no trace from the historical incident is available.
- Workflow/UI autosave endpoints may race with last-write-wins behavior; no mutating
  concurrency reproduction was performed in this read-only phase.
- ProteinMPNN `temperature=0`, missing `torch.no_grad()`, and flattened multi-chain sequence
  output are credible risks that were not exercised with full model inference.
- Structure parsing may mishandle insertion codes, alternate locations, and multi-model PDBs;
  these cases were not included in the minimal reproductions.

## Ruled-out explanations

- The DSSP problem is not caused by mapping SS8 to SS3; all SS8 codes pass through unchanged.
- The three insert nodes do not choose different positions under the current shared seed.
- ESM3 sequence/PDB pairs are not independently shuffled; their index pairing is preserved.
- `mkdssp` and the local ProteinMPNN checkpoint path are not generally unavailable.
- The 0.7/0.3 arithmetic itself is correct when supplied correct per-candidate scores.
- Rigid SVD alignment is correct when residue correspondence is already valid.
- A node failure does not abort every independent workflow branch; unrelated branches run.
- The CLI path did produce a historical 3-by-5 set and 15 PDBs. This does not validate the
  frontend seed path.
- The original missing-edge display was addressed by named handles; current connection
  correctness problems are type validation and seed mutation.
- The viewer is no longer permanently hard-coded to `null`; its remaining problem is
  selection, event reliability, result APIs, CDN reliability, and missing comparison UI.
- It is inaccurate to say that the project has only smoke tests and no factual calls:
  current local-real mkdssp and ProteinMPNN calls exist. It is equally inaccurate to claim a
  current complete remote/browser end-to-end acceptance.

## Missing acceptance coverage

The following gates are absent and should be treated as requirements for later repair
planning, not as repairs in this issue:

1. Exact ESM sequence/SS/visibility/atom37 prompt assertions at the provider boundary.
2. A two-stage ESM3 sequence-then-structure test that proves ten sampled structure pairs and
   records their provenance.
3. Differential standard TM-score tests against `tmtools`, including insertions, deletions,
   renumbering, chain changes, coverage, and reference normalization.
4. ProteinMPNN tensor-seam tests for 0-based fixed positions and every constraint family.
5. Three distinct top parents times five children, per-sequence scores, and complete lineage.
6. Fifteen persisted/downloadable PDB files plus hashes and a run manifest.
7. Exact port-type checks in the graph, seed validation/upgrade/read-only behavior, and
   per-node random-seed semantics.
8. Structured failure diagnostics, ordered run events, project/run isolation, cancellation,
   active-run cleanup, and single-node recovery.
9. Frontend unit/component tests and a browser E2E through Vite, FastAPI, WebSocket, real
   output selection, viewer rendering, and failure recovery.
10. A dated acceptance bundle containing source identity, workflow hash, environment/model
    identity, provider readiness and call summary, cache decisions, node terminal states,
    lineage, output hashes, command transcript, and JUnit.
11. An isolated installed-package acceptance that discovers modules, loads the example, and
    starts the backend/frontend from a reproducible environment.

## Synthesis gate

Repair planning is blocked until:

- [x] all seven workstream reports are integrated into this issue;
- [x] duplicate symptoms are consolidated into stable findings;
- [x] confirmed issues have an evidence path and unproven risks are marked suspected;
- [x] scientific, workflow, execution, frontend, and verification findings are separated;
- [x] known-good capabilities and ruled-out explanations are recorded;
- [x] current verification evidence is classified by tier.

The diagnostic gate is now complete. The next phase may convert these findings into repair
tickets and an ordered implementation plan, but no repair order, implementation boundary, or
code change is proposed by this issue.
