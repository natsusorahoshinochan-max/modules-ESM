# Backend verification tiers

Status: migration contract. The commands and tier inventory describe the current
harness. Clauses explicitly labeled **Target behavior** are accepted requirements
whose current implementation divergence is recorded in
[`known-implementation-gaps.md`](known-implementation-gaps.md).

The backend verifies one active Catalog generation and the current v2 public
protocol. Verification prioritizes scientific meaning, exact contracts,
lineage, residue mapping, units, randomness, provenance, and durable evidence;
it does not verify compatibility with superseded development artifacts.

Use one public verification command:

```bash
.venv/bin/python -m verification.backend <tier>
```

Run the final repository matrix from one explicit Acceptance Execution Profile:

```bash
.venv/bin/python -m verification.acceptance_cli verify-repository \
  --profile /absolute/path/to/acceptance-profile.json
```

This command launches the documented repository tiers serially with the complete
child-process environment produced by `ExecutionProfile.complete_environment()`.
It does not prepare or run an Acceptance Campaign.

Each invocation replaces Project, Cache, output, and Run roots only in the
child process. It never writes configured production roots. After pytest exits,
the verifier retains a bounded JUnit file, sanitized command transcript, and
environment summary under the ignored
`.local/verification-results/<tier>/<UTC-run-id>/` directory. Retained directories
are ordinary local verification output.

## Available tiers

| Tier | Command | Contract |
| --- | --- | --- |
| Routine backend regression | `.venv/bin/python -m verification.backend routine` | Runs deterministic current-generation tests and excludes acceptance, installed-package, Provider, slow-model, and scientific-reproduction markers. |
| Repository v2 examples | `.venv/bin/python -m verification.backend examples-v2` | Commits and compiles the maintained current-generation Workflow suite and compares its 12-package capability inventory with the active source Catalog. |
| Task-shaped Workflow stress | `.venv/bin/python -m verification.backend workflow-stress` | Executes seven task-shaped scenarios through the public v2 protocol: source-bound three-way comparison, fixed-backbone design, function-conditioned Prompt generation, loop insertion, 2×2×2 multi-parent design/folding, all six Selection operations with a legal zero-pass result, and Provider-backed downstream-only Commit invalidation. Every scenario performs a second Run according to each Binding's declared Cache policy and emits a compact cardinality, disposition, Engine Invocation, and oracle report. |
| Deterministic backend acceptance | `.venv/bin/python -m verification.backend deterministic-acceptance` | Runs the current canonical v2 3GB1 public-protocol journey and its failure, readiness, cancellation, isolation, and replay variants. |
| Scientific reproduction | `.venv/bin/python -m verification.backend scientific-repro` | Confirms that every Provider-representable amino-acid symbol crosses the ESM-3 Adapter seam unchanged and retains its declared scientific identity. |
| Local ESMFold2 source contract | `.venv/bin/python -m verification.backend local-esmfold2-v2-contract` | Checks the exact source/native-result contract, static confidence normalization, no-fallback lineage, and shared folding CTK without claiming a real heavy-model invocation. |
| Installed package | `.venv/bin/python -m verification.backend installed-package` | Reproducibly builds the wheel and sdist, installs the wheel outside the checkout, proves source/installed protocol and Catalog identity, and drives the installed server through the public v2 Workflow/Run journey. |
| Installed Biohub ESMC | `.venv/bin/python -m verification.backend installed-biohub-esmc` | Launches only the installed artifact and invokes exact `esmc-600m-2024-12` encode plus logits through the public Workflow/Run protocol, proving Readiness, mean-embedding output, validated sequence-logits shape, and complete Engine Invocation evidence. |
| Installed Biohub ESM-3 | `.venv/bin/python -m verification.backend installed-biohub-esm3` | Invokes all six exact medium/open sequence, structure, and paired Bindings through fresh Runs. It requires eight successful Engine Invocations and fixes SDK retries to one attempt per call. |
| Installed Biohub ESMFold2 | `.venv/bin/python -m verification.backend installed-biohub-esmfold2` | Invokes the exact remote `esmfold2-fast-2026-05` Binding once through a fresh Run with one SDK attempt. |
| Installed local ESM-3 | `.venv/bin/python -m verification.backend installed-local-esm3` | Invokes the configured local model for paired, sequence, and structure generation, explicitly forbids Hugging Face snapshot download/cache fallback, and requires complete scientific invocation evidence. |
| Installed local ESMFold2 | `.venv/bin/python -m verification.backend installed-local-esmfold2` | Invokes the configured ESMFold2 and ESMC models through a fresh Run using the Binding-owned platform device policy: CUDA on Linux/Windows and CPU on macOS, with ESMC FP32 precision. CUDA-platform failure never falls back to CPU. The gate requires effective-seed Method evidence. |
| Installed ProteinMPNN | `.venv/bin/python -m verification.backend installed-proteinmpnn` | Invokes exact design, score, native-score, and sibling-design contracts through four public Runs. Direct Adapter edge cases remain non-authoritative Provider regressions. |
| Installed mkdssp | `.venv/bin/python -m verification.backend installed-mkdssp` | Invokes exact mkdssp 4.6.1 through the public Run seam and verifies the canonical DSSP residue layout, secondary-structure track, SASA track, and complete Method evidence. |
| Installed SimpleFold folding | `.venv/bin/python -m verification.backend installed-simplefold-folding` | Invokes the configured SimpleFold folding route with the model and ESM-2 resources that it actually loads. |
| Installed SimpleFold confidence | `.venv/bin/python -m verification.backend installed-simplefold-confidence` | Invokes the configured confidence route and proves direct-confidence output without refolding. |
| Installed SoluProt | `.venv/bin/python -m verification.backend installed-soluprot` | Invokes both full and no-TM SoluProt Methods and checks their observations and terminal evidence. |
| Installed Protein-Sol | `.venv/bin/python -m verification.backend installed-protein-sol` | Invokes the source-bound Protein-Sol model for multiple sequences and all three declared Metrics. |
| Fresh Biohub source-bound 1PGA | `.venv/bin/python -m verification.backend fresh-1pga` | Runs the installed 1PGA Workflow with its Biohub ESMFold2 route and retains the complete three-way structure, confidence, pairing, retrieval, and classification evidence. |
| Fresh local source-bound 1PGA | `.venv/bin/python -m verification.backend fresh-local-1pga` | Runs the same 1PGA scientific Workflow with the exact local ESMFold2 Method, preserving the source-bound thresholds, residue scope, pairing, and actual Provider Method evidence. |
| Fresh Biohub source-bound 2EMO | `.venv/bin/python -m verification.backend fresh-2emo` | Runs the installed 2EMO Workflow with Biohub ESMFold2 and retains exact CSH normalization, ProteinMPNN, ESMFold2, Protein-Sol, four-filter, and public evidence. |
| Fresh local source-bound 2EMO | `.venv/bin/python -m verification.backend fresh-local-2emo` | Runs the same 2EMO scientific Workflow with local ESMFold2, ProteinMPNN, and Protein-Sol, preserving the selectors, lifecycle receipt, and scientific thresholds. |
| Fresh Biohub canonical 3GB1 | `.venv/bin/python -m verification.backend fresh-canonical-3gb1` | Runs the canonical scientific Workflow without historical Cache. Its four Provider stages require exactly 20 ESM-3 paired-generation calls, 10 preliminary folds, 3 ProteinMPNN parent-design calls, and 15 final folds, alongside the Workflow's valid local invocations. It is release evidence rather than a substitute for the smaller exact-Binding gates. |
| Fresh local canonical 3GB1 | `.venv/bin/python -m verification.backend fresh-local-canonical-3gb1` | Runs the canonical 3GB1 Workflow with exact local ESM-3 and local ESMFold2 Bindings plus ProteinMPNN, authoring the immutable Project Input and retaining the actual local Method evidence. |
| Fresh Biohub source-bound 5G53 | `.venv/bin/python -m verification.backend fresh-5g53` | Runs the installed 5G53 Workflow with Biohub ESM-3 and ESMFold2 and retains all six paired candidates, reconstruction, both PAE-bearing confidence collections, loop evidence, retrieval, and artifacts. |
| Fresh local source-bound 5G53 | `.venv/bin/python -m verification.backend fresh-local-5g53` | Runs the same 5G53 scientific Workflow with local ESM-3 and local ESMFold2. It preserves the requested 20 generation steps while validating the route-aware SDK-effective sequence/reconstruction steps and 20-step counterpart structure track. |

**Target behavior after the stable-identity migration:** the stress documents
live in `tests/fixtures/workflow_stress/`. After an
intentional scientific contract or scenario change, regenerate them with
`.venv/bin/python -m tests.support.generate_workflow_stress_fixtures`; the
stress suite verifies topology, stable references, scientific Port compatibility,
and scenario behavior without storing Contract Locks. The current stress harness
still stores and verifies a Contract Lock; this divergence is tracked under
[Stable Catalog and Workflow identity](known-implementation-gaps.md#stable-catalog-and-workflow-identity).

All nineteen Acceptance Campaign tiers are zero-skip gates: a missing Provider,
fixture-only collection, missing Engine Invocation,
or skipped test fails the gate. The copied acceptance harness is outside the
checkout, and its bootstrap first proves that `core`, `modules`, and
`protein_workbench_public` resolve from the installed wheel. It may expose
installed dependency locations to that isolated environment, but it cannot add
the source checkout to Python's import path. The canonical Campaign itself owns
the fixed tier selectors and binds them to one clean source revision.

All nineteen Acceptance Campaign tiers retain one lightweight public Evidence
bundle:

```text
evidence/
  catalog-snapshot.json
  public-protocol.json
  runs/<run-label>/
    projection.json
    events.json
    typed-values.json
    artifacts.json
    values/*
    artifacts/*
  model-lifecycle.json  # only ProteinMPNN tiers that require it
  tier-result.json
```

For a Campaign child, `tier-result.json` is the retained copy of the same
structured outcome returned through the Campaign-owned handoff. It identifies
the tier and clean source revision, retained location, observed Run labels,
lifecycle receipt, admitted JUnit summary, redacted diagnostic files, and one
`passed`, `failed`, or `interrupted` conclusion. The Campaign admits that
outcome once and projects its execution record, Acceptance Result, summary,
and diagnostic locations from it. The verifier's stdout, console-size and
read diagnostics, resource-warning literals, and interpreter digest do not
authorize or deny an Acceptance Result.

Projection, event, Typed Value, and Artifact data are copied only after the
test's scientific assertions have passed. The REST acceptance client returns
its already-validated retrieval metadata with each payload; the Service path
uses public observations already admitted by the runtime. The shared writer
only writes these values and does not interpret the protocol, Catalog, event
causality, or science. There are no Evidence manifests, checksums, or digest
graphs.

The installed Biohub gates read the one private credential file selected by
the required `PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE`. They do not download or
require local model shards. The direct ESMC Node, the six remote ESM-3 generation
Bindings, and remote ESMFold2 are scientifically distinct and have separate
installed gates. Local ESMFold2 also has a real zero-skip gate; the
provider-free `local-esmfold2-v2-contract` remains a separate source and
translation contract and cannot replace that invocation.

The verifier exposes no v1 provider-evidence, mocked-workflow,
aggregate-provider, or generic live-provider tier. It exposes eight exact
source-bound tier routes covering four scientific Workflows, with separate Biohub
and local-model routes. Every Provider gate consumes
current Run Evidence Ledger facts; an Adapter-owned JSONL stream,
readiness-only result, historical manifest, skip, or Cache-only replay cannot
satisfy it. A fixed expected call count is useful only together with exact
Binding, Method, `executed` disposition, and terminal Ledger evidence.

Each local source-bound route replaces only the declared Provider-backed Nodes
with their local counterparts and updates every dependent Observation Selector.
It does not change thresholds, residue scope,
lineage, or pairing. ESMFold2 route evidence accepts and retains only the actual
executed Method identity—remote
`folding.fold.esmfold2_fast_biohub_2026_05` or local
`folding.fold.esmfold2_hf_1ebf0e3`—and never rewrites a local Method as the
Biohub Method or broadens a downstream selector to arbitrary pLDDT provenance.

## Trusted Provider environment configuration

Provider filesystem locations and credentials are Environment Configuration,
not Workflow parameters and not workstation-specific literals. Set the exact
variables required by the selected gate:

The installed server requires one absolute `PROTEIN_WORKBENCH_DATA_ROOT` and
derives `projects/`, `cache/`, `outputs/`, `runs/`, and Provider runtime state
from it. Verification supplies an isolated absolute data root for each child
process; it never relies on the caller's working directory.

| Gate | Required trusted configuration |
| --- | --- |
| Biohub ESMC, ESM-3, ESMFold2 | `PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE`, selecting one private regular credential file by absolute path. |
| Local ESM-3 | `PROTEIN_WORKBENCH_ESM3_MODEL_ROOT`, selecting the configured snapshot root by absolute path. |
| Local ESMFold2 | `PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT` and `PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT`. |
| ProteinMPNN | `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT`. |
| mkdssp | `PROTEIN_WORKBENCH_MKDSSP_BINARY`, selecting the configured supported binary by absolute path. |
| SimpleFold | `PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT`, `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT`, and `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT`. |
| SoluProt | `PROTEIN_WORKBENCH_SOLUPROT_ROOT`, selecting the trusted runtime and asset root. |
| Protein-Sol | `PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT`, selecting the trusted Protein-Sol source root. |

Missing or relative required path configuration fails a zero-skip gate.
Acceptance files do not infer Provider runtimes from another workspace.
The private Campaign Execution Profile supplies every canonical requirement
explicitly, including `PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE`.

The installed `protein-workbench-server` command loads these variables into the
same Binding-scoped Environment Configuration used by verification. A separate
Python launcher that calls `create_application(v2_environment_configuration=...)`
is no longer required for ordinary backend deployment.

All declared canonical pytest file targets are required to exist. A developer
may use a focused override for local work; only the Campaign's fixed selectors
constitute canonical acceptance.

## Architecture invariants

The verification suite must prove all of the following through public or
contract-owning interfaces:

- the `FrozenCatalog` resolves exactly one current registration for every stable
  Node Type, Port Type Definition, Method, Execution Binding, Metric Definition,
  Utility Transform, and Behavior ID;
- incompatible changes update all current producers, consumers, examples, and
  fixtures together; old Workflow, Cache, and Run schemas fail closed without
  migration or legacy execution;
- an immutable `Execution Plan` fixes the stable contracts before a Run and the
  runtime does not rediscover graph, Binding, Method, or Port facts;
- canonical scientific operations accept admitted provider-independent values
  and do not receive or query the `FrozenCatalog` or internal contract versions;
- one scientific meaning has one canonical implementation; a changed wire
  contract does not introduce a second positional or legacy implementation;
- a concrete Provider Adapter is the only owner of provider-native translation;
  source, checkpoint, installation form, and device are not scientific identity;
- identical canonical PDB content has one `protein.structure` content
  digest independent of provider or project-source provenance, and the active
  structure wire admits no source-bearing historical shape;
- `structure_transform.backbone_structure` is admitted by
  structural and atomic invariants, never by a producer/source label;
- internal immutable values are trusted after admission, while scientific
  invariants, persistence admission, durable writes, and credential hygiene
  retain focused verification.

## Module Package maintainer contract

A repository-owned extension has one production entry point:
`modules/<package>/package.py:MODULE_PACKAGE`. The production Catalog discovers
exactly these 12 packages:

- `collection_ops`
- `esm3`
- `folding`
- `prompt_authoring`
- `protein_io`
- `proteinmpnn`
- `selection`
- `solubility`
- `structure_annotation`
- `structure_comparison`
- `structure_prediction`
- `structure_transform`

**Target behavior after the focused-test migration:** maintainers pass the
package's `ModulePackageRegistration` to focused owner
tests. Every scientific Port codec retains valid, invalid, and round-trip tests;
Node and Binding behavior tests cover scientific inputs, output semantics, and
Adapter translation without exact-set equality over the whole package. The
tests build the current stable-ID Catalog, commit a minimal Workflow, obtain
run-scoped Readiness for Adapter routes, and execute
through the normal v2 interface. It replays public events, decodes typed outputs, checks Result
Identity, scientific lineage, producer and Provider provenance, and retrieves
declared Artifacts. Tests exercise the same scientific-operation seam as the
runtime and do not require an operation implementation to inspect the Catalog.
The current Contract Test Kit still enforces package-wide exact case coverage;
this divergence is tracked under
[Focused scientific test ownership](known-implementation-gaps.md#focused-scientific-test-ownership).

Run the focused package contract with:

```bash
.venv/bin/pytest -q tests/test_contract_test_kit_v2.py
```

The synthetic echo package exists only under
`tests/fixtures/zero_core_packages`. Production discovery does not expose echo.
Neither the wheel nor the sdist contains the repository test tree, fixture
resources, or synthetic echo package.

## Installed parity contract

`python -m verification.build` creates byte-reproducible wheel and sdist artifacts.
The installed-package gate creates a fresh virtual environment and launches
`python -I -m protein_workbench_public.cli` from a directory outside the
checkout. The installed public protocol bundle and stable Catalog IDs must
match the source deployment. Availability remains a separately observed
diagnostic and is not execution authority.

The installed public journey uses protocol-bundle operations for Catalog,
Workflow Draft authoring, one immutable Workflow Commit, Start Run by exact
`workflow_commit_id`, Run Projection, Derived Run, Cancel Run, and Artifact
Retrieval. The Commit atomically stores the admitted Workflow, minimum scientific
definition snapshots, and execution information; clients do not orchestrate a
separate lock or compile
steps. Its WebSocket observes a bounded replay followed by live terminal
evidence. The second Run must contain a Cache replay, and retrieved artifact
bytes must match their declared digest.

## V2 public protocol and persistence

`protein_workbench_public/resources/v2/bundle.json` is the only public payload
contract. A running backend serves the same canonical bytes from
`GET /api/v2/protocol`; clients use `protein_workbench_public` request and
response contracts and do not maintain v1 route or payload fallbacks.
**Target behavior after the typed-output migration:** backend typed constructors
guarantee complete response/event/error shapes before direct serialization;
protocol tests compare those projections with the Bundle, while production
emission does not re-run the Bundle validator. Current production emission still
performs Bundle Schema admission; this divergence is tracked under
[Typed public output construction](known-implementation-gaps.md#typed-public-output-construction).
The same bundle owns Project creation and immutable input publication through
`POST /api/v2/projects` and
`POST /api/v2/projects/{project_id}/inputs`. Project Input bytes use canonical
RFC 4648 base64 in a closed JSON request and are bounded to 64 MiB after
decoding. `GET /api/v2/projects/{project_id}/inputs/{project_input_ref}`
recovers the immutable filename provenance after restart from the same durable
descriptor; there is no multipart or unversioned Project API seam.

The startup-frozen `FrozenCatalog` is the only discovery and compilation
contract source. It publishes one current registration for each stable contract
ID. The immutable `Execution Plan` carries resolved contract facts into
Readiness and execution; scientific operations do not rescan the Catalog.
Direct Port compatibility requires the same stable nominal Port Type ID.
Artifact-capable Port Types require explicit Node publication intent and an
exact media contract; no path-output or media-type fallback exists.
Artifact bytes share the Project-scoped immutable object store used by Typed
Output values. The committed Run Ledger remains the visibility authority, and
the independent Artifact route preserves exact media type, filename
provenance, Candidate association, digest, and size without a Run-scoped
authoritative file. Artifact retrieval represents that filename as an RFC 5987
UTF-8 `filename*` Content-Disposition parameter, including non-ASCII names.

Project metadata, persisted Workflows, Result Cache entries, and Run Ledger
facts use the current schema. Development state has no compatibility promise.
Before a changed result-affecting definition can execute under the same stable
ID, Cache entries written by its superseded definition must be cleared or
isolated. Other incompatible development state may be regenerated without a
migration or legacy reader.

Public projection and event replay are derived from the Run Ledger. There is no
parallel provider-evidence writer or internal filesystem integrity protocol.
Run Projection contains only bounded Typed Output descriptors. Exact canonical
values are retrieved individually through the Run-scoped v2 Typed Value route;
they are never embedded in the projection or lifecycle WebSocket stream.

## Acceptance campaign

Keep every Provider path in one private Execution Profile outside the repository
and `.local/verification-results/`. The profile contains paths and transport policy,
never token contents, and is injected explicitly into each child process.

After the provider-free/backend matrix passes, commit the clean
candidate and run one canonical Campaign:

```bash
CAMPAIGN=.local/verification-results/acceptance-campaign
PROFILE=/absolute/private/acceptance-profile.json
.venv/bin/python -m verification.acceptance_cli prepare "$CAMPAIGN" --profile "$PROFILE"
.venv/bin/python -m verification.acceptance_cli run "$CAMPAIGN" --profile "$PROFILE"
.venv/bin/python -m verification.acceptance_cli status "$CAMPAIGN"
```

`prepare` builds one wheel and sdist. `run` executes all 19 tiers exactly once
in canonical order, with one blocking child at a time and no xdist. The first
failure terminates the Campaign. There is no Qualification/Certification split,
risk-order scheduling, retry, result promotion, or digest graph.

Each tier makes its exact scientific assertions before retaining already
validated public observations. Local-model tiers remain separate child
processes. Within one child, a declared resident model may be reused for that
tier; child exit releases it before the next tier.
## Deterministic public-protocol acceptance

The deterministic tier uses
`examples/v2/canonical-3gb1.workflow.json`. It exercises Catalog and Workflow
Draft, immutable Workflow Commit, Start Run by exact `workflow_commit_id`,
durable replay, Run Projection, Cache replay, selection, lineage,
cancellation, and Artifact Retrieval. Providers are replaced only at their
declared Adapter seams; the Frozen Catalog, compiler, execution engine, Cache,
Ledger, and public routes remain real.

The tier verifies the accepted ten paired ESM-3 Candidates, initial folds,
isolated fixed-reference and paired-counterpart TM-score objectives, weighted
top three, three ProteinMPNN parents with five children each, fifteen final
folds, complete causal closure, and fifteen retrievable PDB digests. It never
uses v1 bundles, fixed historical provider counts, or separate adapter evidence.
