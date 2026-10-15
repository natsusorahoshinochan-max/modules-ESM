# Backend verification tiers

This document owns the execution policy and the current executable backend
verification matrix. Read it before changing executable examples, configuration,
runtime behavior, or verification tooling. WebUI checks are maintained in the
[WebUI verification entry point](../webui/README.md#verification).

Verification checks correct inputs and parameters, current package contracts,
data correspondence, execution behavior, and durable writes. Existing assertions
on lineage, residue mapping, units, randomness, provenance, and retained results
remain required; this does not authorize additional scientific or evidence systems.

The [current decisions](documentation-governance-decisions.md) define required
product behavior. The matrix below describes implemented verification, not proof
that every current requirement is implemented. In particular, existing ESMC
logits-shape assertions do not prove actual logits output, and the existing
ProteinMPNN gates do not define the interface of its required rebuild. Other
implementation differences remain tracked in the
[governance issue list](2026-10-15-documentation-governance-issues.md).

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

## Execution policy

Run all tests, type checks, builds, browser checks and Providers on the remote
verification host, using its existing Python 3.12 environment, frontend
dependencies and private Execution Profile. Local work is limited to reading,
editing, searching and diff inspection.

1. Freeze a task-specific source snapshot and record its digest. Keep running
   snapshots immutable and credentials outside the repository and logs.
2. In each diagnostic round, collect focused tests, all seven repository tiers
   and the applicable [WebUI checks](../webui/README.md#verification) independently. Save each
   exit code, complete log and structured result. `verify-repository` stops at
   the first failure, so diagnostic rounds invoke its seven existing tier entry
   points separately; a remote temporary collector is sufficient.
3. Finish the whole batch before fixing failures. Group failures by shared root
   cause and repair all affected callers together. Import, collection or build
   failures mark dependent checks blocked; continue other independent checks.
   Do not use `-x`, `--maxfail=1` or success-chained independent commands.
4. Start real Provider acceptance only after all non-Provider checks pass and
   failures and blockers are cleared. Use artifacts built from the final source
   snapshot. CPU checks may run independently; resource-heavy Provider work is
   serial. Preserve the formal Campaign's existing stop-on-failure semantics.
5. During both the non-Provider diagnostic batch and the real Provider phase,
   inspect remote status only once every 30 minutes, with no intermediate status,
   log or process polling. Wait silently between inspections and let started work
   continue. This changes only external monitoring, not polling required inside
   tests. Collect executed, failed and blocked results before a repair batch;
   changed code must pass the non-Provider matrix before a new Campaign.

Historical passes do not certify new artifacts. Retain scientific assertions and
required real acceptance; do not add skips or weaken gates to obtain a pass.

## Available tiers

| Tier | Command | Contract |
| --- | --- | --- |
| Routine backend regression | `.venv/bin/python -m verification.backend routine` | Runs deterministic current backend tests across the machine's physical CPU cores and excludes acceptance, installed-package, Provider, slow-model, and scientific-reproduction markers. |
| Repository v2 examples | `.venv/bin/python -m verification.backend examples-v2` | Parses and compiles the maintained stable-ID Workflow suite and checks its representative scientific topology, Port compatibility, parameters, and references against the active source Catalog. |
| Task-shaped Workflow stress | `.venv/bin/python -m verification.backend workflow-stress` | Executes seven task-shaped scenarios through the public v2 protocol: source-bound three-way comparison, fixed-backbone design, function-conditioned Prompt generation, loop insertion, 2×2×2 multi-parent design/folding, all six Selection operations with a legal zero-pass result, and Provider-backed downstream-only Commit invalidation. Every scenario performs a second Run according to each Binding's declared Cache policy and emits a compact cardinality, disposition, Engine Invocation, and oracle report. |
| Deterministic backend acceptance | `.venv/bin/python -m verification.backend deterministic-acceptance` | Runs the current canonical v2 3GB1 public-protocol journey and its failure, readiness, cancellation, isolation, and replay variants. |
| Scientific reproduction | `.venv/bin/python -m verification.backend scientific-repro` | Confirms that every Provider-representable amino-acid symbol crosses the ESM-3 Adapter seam unchanged and retains its declared scientific identity. |
| Local ESMFold2 translation contract | `.venv/bin/python -m verification.backend local-esmfold2-v2-contract` | Checks native-result translation, static confidence normalization, no-fallback lineage, and shared folding CTK without claiming a real heavy-model invocation. |
| Installed package | `.venv/bin/python -m verification.backend installed-package` | Reproducibly builds the wheel and sdist, installs the wheel outside the checkout, proves source/installed protocol and Catalog identity, and drives the installed server through the public v2 Workflow/Run journey. |
| Installed Biohub ESMC | `.venv/bin/python -m verification.backend installed-biohub-esmc` | Launches only the installed artifact and invokes exact `esmc-600m-2024-12` encode plus logits through the public Workflow/Run protocol, proving Readiness, mean-embedding output, validated sequence-logits shape, and complete Engine Invocation evidence. |
| Installed Biohub ESM-3 | `.venv/bin/python -m verification.backend installed-biohub-esm3` | Invokes all six exact medium/open sequence, structure, and paired Bindings through fresh Runs. It requires eight successful Engine Invocations and retains the applicable existing SDK retry limit. |
| Installed Biohub ESMFold2 | `.venv/bin/python -m verification.backend installed-biohub-esmfold2` | Invokes the exact remote `esmfold2-fast-2026-05` Binding once through a fresh Run, retaining the applicable existing SDK retry limit. |
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
| Fresh Biohub source-bound 5G53 | `.venv/bin/python -m verification.backend fresh-5g53` | Runs the installed 5G53 Workflow with Biohub ESM-3 and ESMFold2 and retains all six paired candidates, reconstruction, both ESM-3 confidence collections with optional PAE, required ESMFold2 PAE, loop evidence, retrieval, and artifacts. |
| Fresh local source-bound 5G53 | `.venv/bin/python -m verification.backend fresh-local-5g53` | Runs the same 5G53 scientific Workflow with local ESM-3 and local ESMFold2. It preserves the requested 20 generation steps while validating the route-aware SDK-effective sequence/reconstruction steps and 20-step counterpart structure track. |

The stress documents live in `tests/fixtures/workflow_stress/`. After an
intentional scientific contract or scenario change, regenerate them with
`.venv/bin/python -m tests.support.generate_workflow_stress_fixtures`; the
stress suite verifies topology, stable references, scientific Port compatibility,
and scenario behavior without storing internal contract versions or a Contract
Lock.

Engine Invocation counts describe runtime tool invocations, not SDK-internal
request attempts. The configured ESM-3 and ESMFold2 SDK default allows at most
five total attempts for its specified retryable outcomes. Verification uses the
existing applicable defaults; it does not force one attempt or introduce a new
retry layer. This is not a five-attempt rule for every tool or failure. See
[execution requirements](execution.md) for failure handling and user-initiated
continuation.

All nineteen Acceptance Campaign tiers are zero-skip gates: a missing Provider,
fixture-only collection, missing Engine Invocation,
or skipped test fails the gate. The copied acceptance harness is outside the
checkout, and its bootstrap proves that `core`, `modules`, and
`protein_workbench_public` resolve from the installed wheel. It may expose
installed dependency locations to that isolated environment, but it cannot add
the source checkout to Python's import path. The canonical Campaign owns the
fixed tier selectors and their scientific acceptance expectations.

All nineteen Acceptance Campaign tiers retain one lightweight public Evidence
bundle:

```text
evidence/
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
the tier, retained location, observed Run labels,
lifecycle receipt, admitted JUnit summary, redacted diagnostic files, and one
`passed`, `failed`, or `interrupted` conclusion. The Campaign admits that
outcome once and projects its execution record, Acceptance Result, summary,
and diagnostic locations from it. The verifier's stdout, console-size and
read diagnostics, and resource-warning literals do not
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
provider-free `local-esmfold2-v2-contract` remains a separate translation
contract and cannot replace that invocation.

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
not Workflow parameters and not workstation-specific literals. Configure every
requirement of the selected gate using the environment-variable and resource
mapping in [Provider configuration](provider-configuration.md). The private
Campaign Execution Profile supplies those requirements explicitly, including
`PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE` for the Biohub gates.

The installed server requires one absolute `PROTEIN_WORKBENCH_DATA_ROOT` and
derives `projects/`, `cache/`, `outputs/`, `runs/`, and Provider runtime state
from it. Verification supplies an isolated absolute data root for each child
process; it never relies on the caller's working directory.

Missing or relative required path configuration fails a zero-skip gate.
Acceptance files do not infer Provider runtimes from another workspace.

The installed `protein-workbench-server` command loads these variables into the
same Binding-scoped Environment Configuration used by verification. Deployment
and the required in-application settings interface are described in
[Provider configuration](provider-configuration.md); the private verification
Execution Profile remains explicit.

All declared canonical pytest file targets are required to exist. A developer
may use a focused override for remote diagnosis; only the Campaign's fixed selectors
constitute canonical acceptance.

## Architecture invariants

Read [architecture](architecture.md) for current responsibility boundaries. The
assertions below describe the current executable suite; startup registration and
PDB-specific assertions do not establish the required plugin installer or
PDB/mmCIF support.

The verification suite must prove all of the following through public or
contract-owning interfaces:

- the `FrozenCatalog` resolves exactly one current registration for every stable
  Node Type, Port Type Definition, Method, Execution Binding, Metric Definition,
  Utility Transform, and Behavior ID;
- incompatible changes update all current producers, consumers, examples, and
  fixtures together; superseded development Workflow, Cache, and Run data may be
  discarded or regenerated without migration or legacy execution, while saved
  user work and adopted inputs remain protected;
- an immutable `Execution Plan` fixes the stable contracts before a Run and the
  runtime does not rediscover graph, Binding, Method, or Port facts;
- canonical scientific operations accept admitted provider-independent values
  and do not receive or query the `FrozenCatalog` or internal contract versions;
- one scientific meaning has one canonical implementation; a changed wire
  contract does not introduce a second positional or legacy implementation;
- a concrete Provider Adapter is the only owner of provider-native translation;
  source, checkpoint, installation form, and device are not scientific identity;
- in the current PDB representation, identical canonical content has one
  `protein.structure` content digest independent of provider or project-source provenance, and the active
  structure wire admits no source-bearing historical shape;
- `structure_transform.backbone_structure` is admitted by
  structural and atomic invariants, never by a producer/source label;
- internal immutable values are trusted after admission, while scientific
  invariants, persistence admission, durable writes, and credential hygiene
  retain focused verification.

## Module Package maintainer contract

A repository-owned extension has one production entry point:
`modules/<package>/package.py:MODULE_PACKAGE`. The composition root explicitly
registers these production packages. This list describes the implemented Catalog,
not the final functional-module division or the complete external-plugin contract:

- `collection_ops`
- `esm3`
- `folding`
- `prompt_authoring`
- `protein_io`
- `proteinmpnn`
- `residue_data`
- `selection`
- `solubility`
- `structure_annotation`
- `structure_comparison`
- `structure_prediction`
- `structure_transform`

Maintainers pass the package's `ModulePackageRegistration` to focused owner
tests. Scientific owners retain valid/invalid admission tests; codecs retain
canonical-envelope, conformance and round-trip tests without implicit scientific
admission. Node and Binding behavior tests cover scientific inputs, output semantics, and
Adapter translation without exact-set equality over the whole package. The
tests build the current stable-ID Catalog, commit a minimal Workflow, obtain
run-scoped Readiness for Adapter routes, and execute
through the normal v2 interface. It replays public events, decodes typed outputs,
checks Result Identity, scientific lineage, producer and Provider provenance,
and retrieves declared Artifacts. Tests exercise the same scientific-operation
seam as the runtime and do not require an operation implementation to inspect
the Catalog. The shared Contract Test Kit provides focused helpers; it does not
require package-wide exact-set case coverage or a separate Capability Inventory.

Run the focused package contract with:

```bash
.venv/bin/pytest -q tests/test_contract_test_kit_v2.py
```

The synthetic echo package exists only under
`tests/fixtures/zero_core_packages`. Production discovery does not expose echo.
Neither the wheel nor the sdist contains the repository test tree, fixture
resources, or synthetic echo package.

## Test ownership and shared helpers

Package and scenario tests own their inputs, expected terminal status, parameter
translation, outputs, and required relationships. Shared helpers own protocol
requests, response validation, byte retrieval, and synchronization. A valid
terminal status is not itself success; failure, cancellation, and interruption
tests must assert the intended outcome. Error-response tests continue to call
the tested interface directly. Test reorganizations retain equivalent positive
and negative coverage and receive both standards and specification review;
smaller files or fewer tests do not establish equivalence.

### Contract Test Kit

The Kit offers independent Port conformance and one-case execution interfaces.
Port conformance obtains the owning Port through real Catalog admission and
checks representative valid values, invalid values, and canonical codec
roundtrips without requiring an executable Workflow. One-case execution may use
upstream Nodes to construct real inputs. The case declares inputs, Binding,
parameters, environment, and required graph configuration; ordinary pytest
assertions remain with its owner.

The Kit owns isolated storage, Commit, execution, terminal wait, retrieval, and
cleanup for one successful conformance case. It returns decoded target outputs,
Artifact bytes, and existing typed evidence captured before cleanup. Returned
values remain usable after the runtime and temporary directory close. Decode
with the actual Port codec and preserve exact Port, value, Candidate, Method,
Metric, Context, and Artifact references, including multiple Artifacts on one
Port. Associate evidence by target Node Attempt, Operation Attempt, and Engine
Invocation keys: upstream calls cannot satisfy the target Node's expected calls.
Zero, one, and multiple invocations are valid when explicitly expected. Invalid
codecs, invalid outputs, and failed execution cannot return conformance success.

Runtime and Ledger owner tests retain causality, Cache replay, cancellation,
restart, and failure-propagation coverage. The Kit consumes their existing
typed evidence; it does not reproduce reducers, infer expected tool behavior,
or add a second evidence model. Pytest parameterization owns independent cases
and reporting. The execution policy above governs diagnostic batching. Keep
case-specific credential checks against actual public outputs in the owning
tests; a Kit summary does not replace them.

### Public Workflow and Run support

[public_runs.py](../tests/support/public_runs.py) provides public requests,
Commit and Run receipts, terminal projection polling, exact Typed Output and
Artifact retrieval, and network event collection. The caller owns its client,
application, isolated storage, gates, and fault injection. Submit, start, wait,
and read remain independently usable; helpers do not silently change Workflow
identity, save a Draft, recommit, or retry. Preserve actual receipts, output
order, exact Port/value indices, content identity, Artifact references, and
protocol metadata rather than substituting result summaries.

[inprocess_runs.py](../tests/support/inprocess_runs.py) synchronizes a TestClient
with the durable runtime terminal state before reading the public projection.
This does not verify network transport. Installed acceptance uses actual HTTP
polling and real WebSocket collection without backend implementation imports or
`app.state` access. Event tests own connection, replay cursor, disconnect,
envelope, ordering, and terminal-collection assertions. These internal waits are
separate from the 30-minute external monitoring rule.

[runtime_results.py](../tests/support/runtime_results.py) owns direct-runtime
waiting and codec retrieval. Shared contract, direct, pipeline, and Artifact
scenarios live in [run_scenarios.py](../tests/fixtures/run_scenarios.py); consumers
use that shared fixture module rather than importing another test file.
Execution actions, Readiness, randomness, call counts, gates, and terminal fault
controls remain test seams. Owner-specific persistence faults stay with their
tests; helpers distinguish complete event envelopes from inner events.

### Required module regression coverage

Retain source identity, chain layout, residue correspondence, track values and
presence, annotations, and public Preview/Run parity in their owning module
tests. In particular, preserve 2EMO parent-span normalization, segment topology,
coordinate masks, and Prompt mapping; 5G53 modeled residues and optional tracks;
unambiguous primary sources, monotone merges and target gaps; absent versus
present-all-null tracks; explicit, inherited, and merged annotations, legal
overlap and invalid duplicates; and source admission before downstream edits.

Random insertion coverage checks actual public operation traces and
handle-to-residue correspondence without assuming an internal ID string format.
Display-axis coverage uses real Preview and verifies order, identity uniqueness,
and pending-deletion handling. Track assembly and decomposition retain direct
codec and Layout coverage as well as cross-Node journeys. Source sequence or
track-layout errors are checked through structured Preview rejection, unchanged
Drafts, and actual source-Node failure; valid sources with an invalid baseline
retain repair-and-apply coverage. Draft revision conflicts must protect saved
work. These are the current suite's scoped checks, not a generic HTTP rule for
every Provider failure. Required editing behavior remains defined in
[Prompt editing](prompt-editing.md), including editable random insertions.

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
Backend typed constructors guarantee complete response/event/error shapes before
direct serialization. Protocol tests compare those projections with the Bundle;
production emission does not re-run the Bundle validator over constructed
responses.
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
migration or legacy reader. This permission does not authorize silent loss of
saved user work or invalidate an adopted input when its source Project is deleted.

Public projection and event replay are derived from the Run Ledger. There is no
parallel provider-evidence writer or internal filesystem integrity protocol.
Run Projection contains only bounded Typed Output descriptors. Exact canonical
values are retrieved individually through the Run-scoped v2 Typed Value route;
they are never embedded in the projection or lifecycle WebSocket stream.

## Acceptance campaign

Keep every Provider path in one private Execution Profile outside the repository
and `.local/verification-results/`. The profile contains paths and transport policy,
never token contents, and is injected explicitly into each child process.

Run verification on the remote verification host, reusing its existing virtual
environment. Freeze the source before running the provider-free/backend matrix.
After the complete matrix passes, build artifacts from that same frozen snapshot
and run one canonical Campaign against those artifacts:

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

The tier verifies the maintained scenario's ten paired ESM-3 Candidates, initial folds,
isolated fixed-reference and paired-counterpart TM-score objectives, weighted
top three, three ProteinMPNN parents with five children each, fifteen final
folds, complete causal closure, and fifteen retrievable PDB digests. It never
uses v1 bundles, fixed historical provider counts, or separate adapter evidence.

## Real FASTA WebUI journey

Use this representative journey when verifying the real FASTA import,
evaluation, folding, selection, and ZIP-export path in the built WebUI. It
supplements the backend and real-browser gates; it does not replace the canonical
Campaign or the other real WebUI journeys. The other real journeys use a personal
Project based on the teaching example, edit its Prompt, explicitly reduce the
representative sample counts, and start a fresh Run through the built WebUI.

### Fixed journey inputs and computation

The input is [protein_sol_input.fasta](../modules/solubility/fixtures/protein_sol_input.fasta),
with records `116415` and `ubiquitin` in that order. Upload the original bytes
through the public immutable Project Input operation. The production inspector
and `protein_io.import_sequences` parse the file; the verifier does not fabricate
Candidates. The current executable Workflow is defined in
[webui_journey_evidence.py](../verification/webui_journey_evidence.py).

| Node | Current verification configuration |
| --- | --- |
| `import-fasta` | `protein_io.import_sequences.direct`; two independent ordered sequence Candidates. |
| `score-solubility` | `solubility.protein_sol.local`; Method `solubility.protein_sol.sequence_prediction_2017`. |
| `prefilter-solubility` | `selection.filter.direct`; `solubility.protein_sol_scaled`, partition `protein_sol_scaled`, threshold `>= 0.446`. |
| `fold` | `folding.fold.esmfold2_remote`; Method `folding.fold.esmfold2_fast_biohub_2026_05`, configured node `effective_seed=2719001`, one sample per admitted sequence. |
| `materialize-confidence` | `structure_prediction.materialize_confidence.direct`; join actual confidence facts and structure Candidates. |
| `rank-confidence` | `selection.sort.direct`; mean-residue pLDDT Utility `structure.plddt.mean_residue.esmfold2_fast_biohub_2026_05.percent_to_unit`, weight 1; descending Utility, Candidate identity ascending for ties. |
| `postfilter-confidence` | `selection.filter.direct`; exact mean-residue pLDDT `>= 70` on the 0–100 scale, applied to the original fold population. |
| `passing-ranked-candidates` | `collection_ops.intersect_candidates.direct`; ranked Candidates as `candidates_a`, threshold-passing Candidates as `candidates_b`, retaining the passing subset in ranked order. |

The Protein-Sol selector uses calibration Context
`population_scaled_solubility`, value `0.446`, unit `dimensionless`, population
`niwa_non_membrane_2396`. The fixture's recorded scaled values are `0.252` and
`0.761`; they explain this representative input but are not injected as Provider
results. Confidence selectors use intrinsic mean-residue pLDDT, partition
`prediction_confidence`, and the exact remote folding Method. Unselected Metrics
are ignored; missing required observations are errors. The configured seed
field is not a claim that the remote API supports controlled randomness.

The intersection preserves exact Candidate references, content, lineage,
metadata, and rank order; it neither rematerializes Scores nor invokes another
Provider. The raw threshold result remains separately visible. Thresholds are
this journey's settings, not universal quality criteria. Empty selections remain
empty. Do not lower thresholds, substitute sequences, add retries beyond the
applicable SDK defaults, or report an incomplete Run as completed to obtain a
passing result.

### Prepare, execute, and report

Run serially on the remote host from the frozen snapshot, after the applicable
non-Provider matrix passes. Use the same private Execution Profile for preparation
and the server. Replace the example paths below with this verification's absolute
paths: a private profile outside the repository and fresh data/evidence directories
that contain no user work. These paths are configuration, not locations to recover
from an earlier task.

```bash
FASTA_DATA_ROOT=/absolute/path/to/fresh-fasta-data
FASTA_PROFILE=/absolute/private/acceptance-profile.json
FASTA_EVIDENCE_DIRECTORY=/absolute/path/to/fresh-fasta-evidence
.venv/bin/python -m verification.webui_journey_evidence prepare \
  --data-root "$FASTA_DATA_ROOT" \
  --profile "$FASTA_PROFILE" \
  --evidence-directory "$FASTA_EVIDENCE_DIRECTORY"
```

`prepare` creates the Project, publishes and inspects the immutable input, saves
the Draft, and commits the Workflow through real public HTTP operations using an
in-process client. It loads the normal application and bundled example resource;
it does not start a Run or invoke a Provider. Installing that protected resource
does not create a replacement example Commit when the installed backend starts.

Start the [normal backend server](../webui/README.md) with the Execution Profile's
complete environment and `PROTEIN_WORKBENCH_DATA_ROOT` set to `FASTA_DATA_ROOT`.
Preparation applies the profile only to its own process and does not configure a
subsequently started server. Open the reported personal Project in the built
WebUI and start the full Run there. Supply its Project ID as
`PROTEIN_WORKBENCH_REAL_FASTA_PROJECT_ID` and the built WebUI URL as
`PROTEIN_WORKBENCH_REAL_UI_URL` to the
[real browser checks](../webui/README.md#verification).

Inspect the two imported Candidates, prefilter, fold lineage, real Scores,
ranking, and threshold results. Exercise ZIP export of sequence-only, folded
structure, and mixed selections; compare manifest references with the published
stage pages. The journey subsequently creates a `from_node` Run. Take the
original full Run ID from Playwright's `actual-run-receipt` attachment or
`Actual UI Run:` log, rather than the final page or latest Project Run.

After browser acceptance finishes, read that terminal Run from the same live
backend. Replace the example server URL and receipt identifier:

```bash
FASTA_BASE_URL=http://127.0.0.1:8000
FASTA_FULL_RUN_ID=FULL_RUN_ID_FROM_RECEIPT
.venv/bin/python -m verification.webui_journey_evidence report \
  --base-url "$FASTA_BASE_URL" \
  --run-id "$FASTA_FULL_RUN_ID" \
  --evidence-directory "$FASTA_EVIDENCE_DIRECTORY"
```

`report` reads the original public Commit snapshot, terminal projection, and
published Candidate pages; it never starts or cancels a Run, or opens another
runtime on the server's data directory. It compares the Workflow and scientific
definitions with preparation and retains both prepared and actual Commit IDs if
the WebUI committed the same definition under a new ID. The optional script
`run` subcommand is an alternative that prepares and executes once with real
Providers and collects public events. Use one execution route per journey.

The data directory owns the immutable Input, Draft, Commit, Run Ledger, typed
values, Artifacts, lineage, Scores, and selection results. The evidence directory
retains the submitted Workflow, input inspection, Commit receipt, admission,
projection, stage pages, and `report.json` with Project/Run/Commit IDs. Admission
receipts are retained immediately, including before later failure; the script
execution route also retains public events. These files locate the durable
records and do not replace them. Keep environment and credential contents out of
the report. Preparation alone does not establish a completed browser or ZIP
journey.
