# Protein Workbench backend scientific and execution repair

**Status:** historical completion record; superseded; do not implement

Current authority: `CONTEXT.md`, `docs/codebase-redesign.md`,
`docs/redesign-switch-1.md`, and the accepted ADRs. Defensive path and sealed
bundle/checksum requirements below are historical.

## Problem Statement

Protein engineers cannot currently trust the Protein Workbench backend to preserve scientific
intent or to prove that a workflow completed coherently. The current implementation can execute
many individual code paths, but it can corrupt ESM3 prompt tracks, misclassify generated
structures, compute a non-standard TM-score over invalid residue correspondence, apply
ProteinMPNN constraints with inconsistent indexing, lose candidate lineage, accept incompatible
workflow edges, and report a run as complete even when nodes have failed.

The canonical 3GB1 workflow is also not a reliable backend acceptance asset. Its saved seed can
drift, its current graph does not implement three selected parents times five ProteinMPNN
children, its final structures are not persistently materialized as 15 auditable PDB files, and
historical cache entries cannot be tied to a single run. Mocked workflow tests and old output
files show that code paths have executed, but they do not establish scientific correctness,
current provider behavior, installed-package integrity, or one fresh run bound to the current
source identity.

The current React frontend is a toy implementation and must remain frozen during this work.
Backend behavior, scientific semantics, workflow contracts, persistence, packaging, and
acceptance evidence must become stable first so that a later frontend replacement can consume a
correct, independently specified API.

## Solution

Repair the backend as a dependency-aware program with one primary external acceptance seam: a
client submits the canonical 3GB1 Workflow through the backend REST API, follows its run-scoped
WebSocket event stream, and retrieves the resulting run manifest and 15 persisted PDB artifacts.
That seam must prove typed graph validation, correct scientific data flow, three-by-five lineage,
ordered terminal states, cache decisions, provider-call provenance, and source-bound output
hashes without depending on the current React frontend.

Narrow conformance seams are retained only where the primary seam cannot diagnose correctness
precisely: ESM3 provider-boundary payloads and responses, structural alignment and standard
TM-score differentials, ProteinMPNN constraint translation and per-sequence scoring, and
installed-package discovery. Every repair starts with a deterministic failing test or minimal
reproduction inside the project virtual environment, then proceeds through implementation,
focused regression, broader backend regression, and finally the primary acceptance seam.

The repaired backend will:

1. preserve ProteinPrompt track semantics and accurately classify ESM3 outputs;
2. produce standard, reference-normalized TM-scores from valid residue correspondence;
3. apply complete ProteinMPNN constraints with one explicit indexing contract, deterministic
   randomness, per-sequence scores, and correct candidate lineage;
4. reject incompatible Workflow edges before execution and maintain one validated, immutable
   canonical 3GB1 seed;
5. execute serial node lifecycles with structured failures, ordered run-scoped events, safe
   project containment, real cancellation semantics, isolated outputs, and persistent run
   provenance;
6. install with all ModuleDefinitions and reproducible dependencies, while separating fast
   default tests from explicit live-provider acceptance;
7. produce a fresh, auditable non-frontend 3GB1 run whose evidence is sufficient to authorize a
   separate frontend-rewrite specification.

## User Stories

1. As a protein engineer, I want amino-acid sequence tracks to reach ESM3 unchanged except for
   explicitly masked positions, so that generated candidates reflect my ProteinPrompt.
2. As a protein engineer, I want secondary-structure tracks to accept only their documented
   symbols without applying those rules to sequence tracks, so that track-specific semantics do
   not corrupt one another.
3. As a protein engineer, I want structure visibility to remove hidden residue coordinates at the
   ESM3 provider boundary, so that residues I hide are not accidentally used as constraints.
4. As a protein engineer, I want full template atom information preserved when a structure prompt
   is intended to condition ESM3, so that the backend does not silently reduce a full template to
   CA-only evidence.
5. As a protein engineer, I want the final secondary-structure track to place the requested E and
   H regions at the final target-layout positions and leave every other position unspecified, so
   that insertion operations do not shift or leak DSSP assignments into my design intent.
6. As a protein engineer, I want coordinate-free ESM3 sequence generation to succeed without
   pretending that a structure exists, so that sequence-only workflows remain valid.
7. As a protein engineer, I want a reconstructed template structure distinguished from a sampled
   ESM3 structure, so that I do not compare an ESMFold2 fold against the prompt it was conditioned
   on and call that independent evidence.
8. As a protein engineer, I want the 3GB1 workflow to obtain ten index-paired sampled ESM3
   sequence/structure candidates, so that each folded sequence can be compared with the correct
   generated structure.
9. As a protein engineer, I want ESM3 pTM and PAE outputs normalized only from documented shapes,
   so that malformed provider responses fail visibly instead of being guessed into plausible
   scores.
10. As a protein engineer, I want every generated structure to carry explicit source
    classification and provider provenance, so that downstream claims distinguish reconstruction,
    sampling, and independent folding.
11. As a protein engineer, I want residue correspondence established by sequence-aware structural
    alignment rather than matching chain and residue labels literally, so that insertions,
    deletions, renumbering, and chain changes do not invalidate comparison.
12. As a protein engineer, I want StructureAlignment to contain enough public data to reproduce
    RMSD, coverage, and standard TM-score, so that scoring modules share one scientifically valid
    alignment.
13. As a protein engineer, I want TM-score to use the standard per-residue definition and explicit
    normalization length, so that scores are comparable with trusted structural-alignment tools.
14. As a protein engineer, I want incomplete reference coverage reflected in TM-score, so that a
    short perfect fragment is not reported as a perfect full-reference match.
15. As a protein engineer, I want each structure score tied to the Candidate it evaluates, so that
    weighted ranking uses the intended score instead of silently ignoring it.
16. As a protein engineer, I want the 0.7 versus 3GB1 and 0.3 versus paired ESM3 score IDs to remain
    distinct, so that weighted ranking applies the documented objective.
17. As a protein engineer, I want missing or duplicate scores to fail closed during ranking, so
    that an incomplete ScoreCollection cannot silently change the selected top three.
18. As a protein engineer, I want ProteinMPNN fixed positions expressed in one documented public
    indexing convention, so that the first and last residues are constrained correctly.
19. As a protein engineer, I want ProteinMPNN designable positions, fixed positions, chain
    selection, tied positions, omit rules, and amino-acid biases translated completely, so that
    every declared constraint affects inference as specified.
20. As a protein engineer, I want multi-chain ProteinMPNN constraints validated before inference,
    so that malformed chain or residue references produce an actionable error.
21. As a protein engineer, I want invalid structure/sequence length pairs rejected rather than
    padded or truncated, so that ProteinMPNN scores describe the sequence I supplied.
22. As a protein engineer, I want every ProteinMPNN-generated sequence to receive its own model
    score, so that generated candidates can be compared honestly.
23. As a protein engineer, I want a ProteinMPNN scoring failure to fail the node rather than return
    an empty successful output, so that declared outputs are complete.
24. As a protein engineer, I want an optional reference sequence either honored according to its
    public port contract or rejected during validation, so that connected inputs are never
    ignored.
25. As a protein engineer, I want the run seed and node seed to control ProteinMPNN and all other
    stochastic modules, so that a cached or repeated workflow is reproducible.
26. As a protein engineer, I want backbone-noise and sampling parameters to be explicit rather
    than silently hard-coded, so that ProteinMPNN behavior matches the recorded run contract.
27. As a protein engineer, I want each of the selected top three structures redesigned five times,
    so that the 15 final sequences represent three distinct parents rather than 15 samples from
    one parent.
28. As a protein engineer, I want every ProteinMPNN child Candidate to reference the actual
    selected parent Candidate, so that I can trace every final PDB through ranking and design.
29. As a protein engineer, I want the backend to persist exactly 15 final nonempty PDB files with
    stable candidate-to-file mapping, so that the workflow produces usable scientific artifacts.
30. As a protein engineer, I want output hashes recorded in the run manifest, so that I can verify
    artifacts after copying or downloading them.
31. As a workflow author, I want the backend to reject edges whose port type IDs do not match
    exactly, so that invalid scientific data flow fails before any expensive provider call.
32. As a workflow author, I want required ports, module availability, graph acyclicity, and port
    existence validated as one pre-execution gate, so that a run never starts from a structurally
    invalid Workflow.
33. As a workflow author, I want CandidateCollection inputs to have explicit collection behavior,
    so that a module never silently consumes only its first Candidate.
34. As a workflow author, I want stochastic nodes to have explicit effective seeds recorded in
    the Workflow and manifest, so that each branch is independently reproducible.
35. As a new backend client, I want one canonical 3GB1 seed with a stable identity, so that opening
    the example does not create duplicates when its contents evolve.
36. As a maintainer, I want the canonical seed validated against current ModuleDefinitions and
    type contracts at startup, so that drift is detected before a user attempts a run.
37. As a maintainer, I want canonical seed content protected by the backend from ordinary writes,
    so that client behavior cannot mutate the accepted example.
38. As a maintainer, I want legacy or drifted seed projects preserved without being mistaken for
    the canonical seed, so that migration does not destroy user data or leave multiple canonical
    examples.
39. As a backend client developer, I want run-scoped REST and WebSocket contracts independent of
    React, so that a future frontend can rely on stable backend behavior.
40. As a backend client developer, I want events ordered within a run and tagged with both project
    ID and run ID, so that activity from another project cannot mutate the visible run state.
41. As a backend client developer, I want structured node failure messages with safe diagnostics
    and downstream blocking reasons, so that users can understand why a Workflow did not finish.
42. As a backend client developer, I want a run to report completed only when all required nodes
    completed successfully, so that a terminal success event is trustworthy.
43. As a backend client developer, I want failed, cancelled, and completed runs to have distinct
    terminal states, so that recovery actions can be chosen correctly.
44. As a backend client developer, I want node events to be delivered before the run terminal
    event, so that final state never races ahead of the facts it summarizes.
45. As a protein engineer, I want cancellation to remain “requested” until blocking work has
    actually stopped, so that the backend never claims cancellation while a provider or model
    continues changing state.
46. As a protein engineer, I want at most one active run per project unless explicit run isolation
    is available, so that concurrent requests cannot collide in temporary files, caches, or
    outputs.
47. As a maintainer, I want completed and failed run tasks removed from active-run tracking, so
    that long-lived backend processes do not leak task records.
48. As a backend client developer, I want APIs for run status, run outputs, node retry or force
    rerun, and node or project cache clearing, so that recovery does not require filesystem access.
49. As a security-conscious local user, I want every project ID and output path contained beneath
    the configured project root, so that API input cannot read or write arbitrary local paths.
50. As a protein engineer, I want semantically identical parameters to produce the same cache key,
    so that dictionary insertion order does not trigger unnecessary scientific recomputation.
51. As a protein engineer, I want cache hits and misses recorded per node and bound to a run, so
    that cached evidence is distinguishable from fresh provider calls.
52. As a protein engineer, I want node outputs retrieved by run ID rather than newest-file time,
    so that I never inspect an artifact from a different run by accident.
53. As a maintainer, I want each run manifest to record source identity, Workflow hash,
    ModuleDefinition versions, effective seeds, environment identity, provider readiness, actual
    provider calls, cache decisions, node states, lineage, artifact paths, and hashes, so that the
    run can be audited later.
54. As a maintainer, I want API keys and other secrets redacted from logs, errors, fixtures,
    manifests, and acceptance bundles, so that reproducibility evidence is safe to retain.
55. As a maintainer, I want backend tests to use isolated temporary project roots, so that running
    tests cannot populate the user-visible project list.
56. As a maintainer, I want default tests to exclude live and slow acceptance work, so that a
    routine regression command cannot unexpectedly call remote providers or load large models.
57. As a maintainer, I want live-provider acceptance to fail when a required call did not run,
    rather than report a green suite containing skips, so that provider readiness is not mistaken
    for provider verification.
58. As a maintainer, I want the built package to include every YAML ModuleDefinition, so that
    installed module discovery matches source-checkout discovery.
59. As a maintainer, I want runtime, provider, WebSocket, model, and test dependencies captured by
    a reproducible install contract, so that a clean environment can execute the same backend.
60. As a maintainer, I want an isolated installed-package smoke to discover modules, load the
    canonical Workflow, and start the API, so that release acceptance tests what users install.
61. As an acceptance operator, I want a dated backend-only evidence bundle with JUnit and a command
    transcript, so that every claimed gate has a durable record.
62. As an acceptance operator, I want the final 3GB1 run bound to the current source revision and
    actual provider-call summary, so that historical artifacts cannot be substituted for current
    acceptance.
63. As a future frontend developer, I want corrected contracts frozen before UI work begins, so
    that the replacement frontend implements scientific behavior rather than compensating for
    backend defects.

## Implementation Decisions

### Repair authority and boundary

- The full-system diagnostic remains the authoritative evidence record. This specification uses
  its stable finding IDs and does not duplicate the broad audit.
- The repair covers scientific/provider findings SCI-001 through SCI-019, backend-relevant
  Workflow findings WF-001 through WF-009, execution findings RUN-001 through RUN-012, and
  verification findings VER-001 through VER-007 plus VER-009.
- Existing known-good behavior recorded by the diagnostic must be preserved. In particular,
  serial node execution, continuation of unrelated branches, index pairing where already valid,
  exact weighted arithmetic when supplied complete scores, and public types independent of
  provider SDKs remain architectural constraints.
- Vendor repositories remain read-only. All normalization and compatibility work belongs in
  workbench adapters, public datatypes, modules, registries, the Execution Engine, project
  persistence, or acceptance tooling.
- The current React frontend is not an implementation target. Backend contracts are established
  and tested independently of current client behavior.

### ProteinPrompt and ESM3 provider contract

- Conversion is track-specific. Sequence validation uses the documented amino-acid alphabet;
  secondary structure uses the supported SS8 representation; one track's normalization is never
  reused for another.
- ProteinPrompt tracks remain independent and aligned to the final target residue layout.
  Insertions are resolved before absolute secondary-structure intent is applied or are mapped
  through an explicit ResidueMap so that requested final positions are invariant.
- Structure visibility controls whether coordinates are present at the provider boundary. A
  hidden residue is represented using the provider's documented masked or non-finite coordinate
  form and is verified from the outbound payload.
- Template-conditioned generation preserves the documented atom representation. Any deliberate
  backbone-only reduction must be an explicit conversion contract rather than an adapter side
  effect.
- Unified generation becomes an explicit sequence-then-structure operation when a sampled
  sequence/structure pair is required. Ten outputs remain index-paired, and a structure is called
  `sampled_structure` only when the documented generation path actually sampled it.
- Coordinate-free sequence generation may return no structure. Serialization and downstream
  validation must accept that classified absence rather than forcing PDB conversion.
- Provider metric normalization is fail-closed. Accepted pTM and PAE shapes, residue axes, and
  units are explicit; unexpected shapes fail the node with a structured diagnostic.
- Provider errors and incomplete declared outputs fail the node. They are never converted into an
  apparently successful empty or partial result.

### StructureAlignment, TM-score, and ranking

- Structure comparison continues to follow the alignment-first ADR. A shared StructureAlignment
  is the public input to both TM-score and RMSD.
- StructureAlignment is extended with the reference and mobile correspondence and all public data
  required to compute the documented metrics without reconstructing scientific state from one
  global RMSD.
- Residue correspondence is sequence-aware and robust to insertions, deletions, residue
  renumbering, and chain-label changes. PDB labels remain provenance, not the sole alignment key.
- Standard TM-score is calculated from per-residue distances using an explicit normalization
  length. The 3GB1 comparison is reference-normalized; coverage is represented rather than
  discarded.
- Differential behavior is checked against a trusted structural-alignment implementation for
  identical structures, outliers, partial coverage, insertions, deletions, renumbering, and chain
  changes.
- Every score entry carries the Candidate ID it evaluates. The two 3GB1 Workflow objectives use
  distinct score IDs before merge and weighted ranking.
- Ranking is fail-closed for required scores: missing score IDs, missing Candidate subjects, or
  duplicate Candidate/score pairs are validation errors rather than implicit zeroes or
  last-write-wins behavior.

### ProteinMPNN contract

- Public ProteinMPNN residue positions use zero-based target-layout indices. Conversion to the
  upstream one-based, chain-qualified representation occurs exactly once at the adapter boundary.
- Every declared ProteinMPNNConstraints field is either fully translated and tested or explicitly
  rejected as unsupported during validation. Inputs are never silently ignored.
- The single-structure design contract remains supported. Collection design is explicit through a
  correctly typed optional collection port; exactly one of the single-structure and collection
  ports may be populated.
- For collection design, `num_sequences` means sequences per input parent. Supplying the three
  selected structure Candidates with `num_sequences = 5` therefore yields exactly 15 child
  Candidates.
- Every child Candidate references its actual input Candidate as parent. Sample index, effective
  seed, constraint identity, and provider/model identity are retained as metadata.
- ProteinMPNN produces one score per generated sequence using that sequence's own tokens. A
  scoring failure fails the node; no native-sequence score is duplicated across children.
- Structure and sequence lengths must match exactly. Padding and truncation are not accepted
  repairs for invalid inputs.
- The optional reference-sequence port is honored and validated. If the upstream provider cannot
  support its intended behavior, the port contract must be removed through an explicit module
  version change rather than left connected and ignored.
- Each stochastic node resolves an effective seed from an explicit node override or the run seed.
  That effective seed controls ProteinMPNN and is included in cache identity and the run manifest.
  Backbone noise and sampling parameters are public ModuleDefinition parameters with documented
  defaults.

### Workflow validation, canonical seed, lineage, and output persistence

- The backend performs the authoritative pre-execution Workflow validation gate. It checks
  acyclicity, module availability, source and target port existence, required inputs, and exact
  type-ID compatibility before creating a run or calling a provider.
- No implicit scientific conversion is added. Where the canonical 3GB1 Workflow currently joins
  unequal type IDs, it must use an explicit conversion module or corrected module port contract.
- CandidateCollection behavior is declared by the receiving module. A module must process the
  collection according to that contract or reject it; taking the first item silently is forbidden.
- The canonical 3GB1 Workflow remains a backend asset and must validate with zero incompatible
  edges. It implements ten ESM3 pairs, ten ESMFold2 folds, two standard TM-score branches, weighted
  top-three selection, five ProteinMPNN children per selected parent, and 15 final ESMFold2 folds.
- The canonical seed has a stable semantic identity independent of its content hash. Startup
  validation compares the persisted canonical content with the shipped Workflow and restores or
  upgrades it atomically when required.
- The backend rejects ordinary Workflow or metadata writes to the canonical seed. Legacy or
  drifted seeds are preserved as ordinary projects or clearly marked legacy copies; they are not
  deleted and do not retain canonical-seed status.
- A collection-capable structure export contract materializes one canonical PDB file per final
  Candidate under the run's output namespace and returns relative artifact references. The 3GB1
  Workflow must materialize exactly 15 files.
- Workflow-level and Candidate-level lineage are persisted in the run manifest. The manifest can
  trace every final PDB back through its ProteinMPNN child, one of three selected parents, its
  weighted ranking scores, and its paired ESM3 generation.

### Execution lifecycle, API, cache, and containment

- Execution remains serial within a run. Branching and merging remain supported, and a node
  failure blocks dependent nodes while unrelated branches may complete.
- The backend exposes project/run-scoped execution routes and a project/run-scoped WebSocket
  stream. Every run event includes project ID, run ID, monotonic sequence number, event timestamp,
  and the relevant node ID.
- Event publication is ordered. Node terminal events and persistent manifest updates complete
  before the run terminal event is emitted.
- `run_completed` is emitted only when every required node has completed successfully, including
  valid cache hits. A run containing a failed or blocked node terminates as failed with structured
  node diagnostics and blocking reasons. Cancellation has its own terminal state.
- A cancellation request is recorded immediately, but terminal cancellation is not reported until
  the active operation has stopped or a documented cancellation timeout has produced a failed
  termination. Blocking provider or subprocess work must use a controllable boundary where
  necessary.
- Only one run may be active for a project until complete run isolation is proven. Temporary
  directories, outputs, logs, and manifests are always namespaced by run ID even with that guard.
- Active-run records are removed in a guaranteed cleanup path after every terminal outcome.
- Project IDs, run IDs, node IDs, uploaded names, and output paths are validated and resolved
  beneath configured roots before filesystem access. Absolute paths and traversal outside those
  roots are rejected.
- Cache parameter normalization is recursive and canonical. Cache identity continues to include
  module ID, module version, input hashes, normalized parameters, and effective seed.
- Successful cache entries remain content-addressed, but each use is recorded in the consuming
  run manifest. Failed or partial node outputs are never cached.
- Run output lookup is keyed by project ID and run ID. No API chooses scientific output by global
  modification time.
- Backend recovery contracts include run status, run outputs, single-node retry or rerun,
  force-rerun selection, node cache clearing, and project cache clearing. These contracts are
  specified independently of whether the current frontend exposes controls.
- Structured errors include stable error kind, safe message, node and module identity, and
  retryability where known. Secrets, raw credentials, and sensitive environment values are
  redacted.

### Persistent provenance and acceptance evidence

- A run manifest is created before execution and updated atomically through terminal state. It
  records source revision and dirty-state identity, Workflow hash, project and run IDs,
  ModuleDefinition versions, effective seeds, environment and model identity, provider readiness,
  actual provider calls, cache decisions, ordered node states, structured failures, Candidate
  lineage, artifact references, sizes, and hashes.
- Provider readiness and provider execution are separate facts. A required live-provider gate
  fails or remains explicitly incomplete when the call did not run; a skip cannot satisfy it.
- Historical cache entries and historical PDB files remain historical evidence only. They are not
  imported into a current manifest as if they were produced by the current run.
- Acceptance bundles are dated and immutable after sealing. They include the run manifest, JUnit
  results, command transcript, environment summary, and artifact checksums without secrets.

### Packaging, dependencies, and test isolation

- The distributable package includes all Python packages and every YAML ModuleDefinition needed
  by module discovery.
- Module discovery no longer hides definition or registration failures during installed-package
  acceptance. A required module-discovery failure is a test and startup failure with a structured
  diagnostic.
- Runtime dependencies, backend WebSocket support, provider integrations, local model/checkpoint
  expectations, and development/test dependencies are captured by a reproducible install
  contract. Read-only vendor sources are not modified to simulate packaging.
- Default test collection contains fast, isolated, non-live tests. Live-provider and heavy-model
  acceptance require explicit markers and commands.
- Server and project tests inject temporary project, cache, output, and run roots. Tests never
  write into the user's production project root.
- An installed-package acceptance creates a clean environment, installs the built artifact,
  discovers the expected modules, loads and validates the canonical Workflow, and starts the
  backend API without importing source-tree-only assets.

### Dependency-aware repair slices

The implementation sequence is constrained as follows:

1. Establish safe test roots, explicit verification tiers, and deterministic reproductions for
   the first repair slice.
2. Repair ProteinPrompt-to-ESM3 fidelity before any new remote ESM3 acceptance is treated as
   meaningful.
3. Repair StructureAlignment and standard TM-score before changing weighted ranking or accepting
   the top-three selection.
4. Repair ProteinMPNN indexing, all supported constraints, randomness, scores, and lineage before
   validating the 50-percent redesign stage.
5. Repair authoritative graph validation, collection semantics, canonical seed behavior,
   three-by-five branching, and collection export before workflow acceptance.
6. Repair run lifecycle, event ordering, isolation, containment, cache provenance, cancellation,
   and persistent manifests before claiming a coherent end-to-end run.
7. Close source and wheel packaging contracts, then run installed-package acceptance.
8. Run mocked backend acceptance first, local-real provider acceptance second, and the fresh
   remote-real 3GB1 backend acceptance last.

Each slice must be independently verifiable and may be split further by the ticketing workflow.
No broad repair slice begins until its prerequisite scientific or execution contract is green.

## Testing Decisions

### What makes a good test

- Tests assert externally observable scientific or backend behavior rather than private helper
  structure, call counts unrelated to a contract, or implementation-specific files.
- Every confirmed repair starts with the deterministic reproduction identified by the diagnostic
  or a tighter equivalent, run inside the project virtual environment.
- Exact quantities and identities matter: residue positions, track values, normalization length,
  Candidate subjects, parent IDs, effective seeds, event order, artifact count, and hashes are
  asserted directly.
- Provider tests capture or exercise the provider boundary without leaking credentials. Mocked
  tests prove workbench contracts; separately marked live tests prove current provider behavior.
- A test does not pass a required live gate by skipping. It reports the gate as incomplete or
  failed when the required provider call did not occur.

### Primary seam

- The highest seam is the backend API plus run-scoped WebSocket executing the canonical 3GB1
  Workflow. A deterministic provider-backed fixture verifies the complete contract quickly; a
  separately invoked live-provider acceptance uses the same observable API and manifest schema.
- The primary test submits the Workflow, verifies zero validation errors before execution,
  observes monotonically ordered run events, waits for a successful terminal state, retrieves the
  run by ID, and inspects the persisted manifest and artifacts.
- It asserts ten index-paired ESM3 Candidates, ten initial ESMFold2 structures, standard scores
  against 3GB1 and paired ESM3 structures, the weighted top three, three distinct ProteinMPNN
  parents with five children each, 15 per-sequence ProteinMPNN scores, 15 final structures, 15
  persistent PDB files, complete lineage, and matching hashes.
- Failure variants exercise an incompatible edge, a provider error, a failed node with an
  unrelated successful branch, cancellation, a repeated cache-backed run, an overlapping
  same-project run request, and traversal-like project input.

### Narrow conformance seams

- ESM3 modules are tested through their public `run()` contracts with captured outbound
  provider-native payloads and documented response fixtures. These tests cover sequence, SS8,
  visibility, atom representation, output classification, pTM, PAE, coordinate-free generation,
  and provider errors.
- Structure alignment and TM-score are tested through public module ports and compared with a
  trusted implementation across identical structures, one-outlier structures, partial coverage,
  insertions, deletions, renumbering, and chain changes.
- ProteinMPNN is tested through its public module contract plus a narrow adapter tensor/input seam
  for the upstream constraint dictionaries. It covers zero-to-one-based conversion, all supported
  constraint families, multi-chain behavior, invalid lengths, effective seed propagation,
  per-parent generation count, per-sequence scores, and lineage.
- Packaging is tested from an installed wheel in an isolated environment rather than importing
  from the source checkout.

### Modules and backend contracts tested

- ProteinPrompt datatypes, residue layout and mapping operations, ESM3 adapters, ESM3 generation,
  structural alignment, TM-score, score merging and weighted ranking, ProteinMPNN constraints and
  design, ESMFold2 folding, collection export, Candidate lineage, Module Registry, Type Registry,
  Workflow validation, ProjectManager seed behavior, Execution Engine, cache, run manifest, REST
  routes, and WebSocket event streams are in scope.
- Existing unit suites for ProteinPrompt editing, ESM3 adapters, structural scoring,
  ProteinMPNN, Workflow graph behavior, module/type registries, seed projects, Execution Engine,
  cache, project persistence, WebSocket execution, and the mocked 3GB1 Workflow provide prior art
  and should be strengthened rather than replaced wholesale.
- Existing live acceptance patterns for Biohub generation/folding, ProteinMPNN, SimpleFold, and
  DSSP provide provider-specific setup prior art, but their readiness, run-root, manifest, JUnit,
  and skip semantics must be brought under the new acceptance contract.

### Regression and completion gates

1. Focused deterministic reproduction for the repaired finding passes.
2. All related module and adapter contract tests pass.
3. Fast backend regression passes without collecting live or slow acceptance tests.
4. Mocked canonical backend acceptance passes through REST, WebSocket, manifest, and persisted
   artifacts.
5. Local-real provider gates pass where required and record actual calls.
6. The built wheel passes isolated discovery and API startup acceptance.
7. A fresh remote-real backend 3GB1 run produces and seals the complete evidence bundle.

## Out of Scope

- Any change under the current React frontend or its CSS.
- Incremental repair or extension of the current ReactFlow canvas, ProteinPrompt editor, project
  interface, toolbar, parameter forms, NGL viewer, import/export interface, or frontend state
  handling.
- UI-specific findings UI-001 through UI-012.
- Frontend unit, component, or browser end-to-end tests tied to the current toy frontend.
- Compatibility whose only purpose is to preserve accidental behavior in the current frontend.
- Design or implementation of the replacement frontend. That work requires a separate
  specification after backend contracts are stable.
- Treating the canonical Workflow's current serialization as the future frontend's required data
  model before backend contracts are settled.
- Repeating the completed full-system diagnosis or investigating already ruled-out explanations
  without new contradictory evidence.
- Resolving suspected risks from the diagnostic without first adding a separate deterministic
  evidence step.
- Parallel node execution, distributed scheduling, multi-user support, authentication,
  authorization, cloud deployment, or a third-party Module marketplace.
- Modifying vendored ESM, ProteinMPNN, or SimpleFold repositories.
- Using historical cache entries or historical PDB files as current acceptance evidence.

## Further Notes

- The full-system diagnostic is the source of truth for finding evidence and severity. This
  specification is the repair contract and dependency boundary.
- The Protein Workbench domain glossary governs terminology: Module, Node, Workflow, Port,
  ProteinPrompt, Candidate, CandidateCollection, ScoreCollection, StructureAlignment, Execution
  Engine, Module Registry, Type Registry, Cache, and PDB String are used with their established
  meanings.
- The public-type independence, exact two-layer type system, per-residue ProteinPrompt tracks,
  serial execution, hybrid project storage, PDB String exchange, alignment-first scoring,
  content-addressed Cache, downstream blocking, and REST/WebSocket ADRs remain in force unless an
  explicit superseding ADR is accepted.
- Diagnostic coverage mapping:
  - ProteinPrompt and ESM3 provider repair: SCI-001 through SCI-007.
  - StructureAlignment, TM-score, and ranking repair: SCI-008 through SCI-012.
  - ProteinMPNN contract repair: SCI-013 through SCI-019.
  - Workflow, seed, lineage, export, and test-root repair: WF-001 through WF-009.
  - Execution lifecycle, API, cache, containment, and provenance repair: RUN-001 through RUN-012.
  - Packaging and acceptance repair: VER-001 through VER-007 and VER-009.
- The accepted testing seam is the backend API plus run-scoped WebSocket and persistent run
  manifest. Narrow scientific and packaging seams exist only where that seam cannot precisely
  prove the contract.
- Completion of this specification authorizes creation of dependency-ordered repair tickets. It
  does not authorize frontend work.
