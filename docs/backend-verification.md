# Backend verification tiers

Backend verification is run through one public command so that the selected tier,
interpreter, isolated roots, and final result are visible in the transcript:

```bash
export PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION="$(git rev-parse HEAD)"
.venv/bin/python scripts/verify_backend.py <tier>
```

Every invocation creates temporary, distinct project, Cache, output, and run roots.
Configured production roots are replaced only in the child verification process and
are not written. Raw JUnit, provider events, and fresh artifacts are first written
beneath the verifier's private temporary staging root; the outer verifier keeps
its environment summary in memory and derives the sanitized transcript and
validated provider summary itself. After
the complete child process group exits, the outer verifier creates the
unpredictably named retained directory, validates child-produced fresh evidence
in a parent-only quarantine, and publishes only bounded, redacted evidence with
mode `0600` under the ignored
`verification-results/<tier>/<UTC-run-id>/` directory; the retained directory
is never exposed to pytest, uvicorn, or provider code. Set
`PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT` to select a CI artifact directory.
After a successful fresh canonical tier, every retained file is frozen to `0400`
and every evidence directory to `0500`; other tiers retain their files at `0600`.
These local permission bits prevent accidental writes, while
`bundle-checksums.sha256` detects drift relative to a separately recorded bundle
digest. They are not a signature against a malicious filesystem owner.
Plain `.venv/bin/pytest` uses the same isolation policy and defaults to the routine
marker expression.

## Available tiers

| Tier | Command | Contract |
| --- | --- | --- |
| Routine backend regression | `.venv/bin/python scripts/verify_backend.py routine` | Fast deterministic tests only; excludes acceptance, remote providers, local providers, heavy models, and intentionally red reproductions. |
| Repository v2 examples | `.venv/bin/python scripts/verify_backend.py examples-v2` | Parses, exactly relocks, and compiles the shipped v2 Workflow suite; compares the 11-package capability inventory with the source Catalog; and checks the independent exact-objective CTK fixture without invoking providers or writing Project, Cache, output, or Run roots. |
| Deterministic backend acceptance | `.venv/bin/python scripts/verify_backend.py deterministic-acceptance` | Runs both the retained failure-variant suite and the exact locked v2 canonical 3GB1 provider fixture, including its public compile, Run, replay, Ledger, selection, lineage, and artifact assertions. |
| Installed backend artifact | `.venv/bin/python scripts/verify_backend.py installed-package` | Builds wheel and sdist, checks required YAML and canonical assets, installs the wheel with dependencies into a brand-new venv, then discovers all 44 legacy Modules and 48 v2 Node Types, starts the API outside the source checkout, and completes the exact canonical v2 journey through only the public protocol. |
| Scientific reproduction | `.venv/bin/python scripts/verify_backend.py scientific-repro` | Runs the deterministic SCI-001 reproduction and confirms that legal amino-acid symbols reach the ESM3 boundary unchanged. |
| Post-review repair findings | `.venv/bin/python scripts/verify_backend.py repair-findings` | Intentionally red cumulative gate for the four independently confirmed post-handoff findings. It must report exactly the shifted final secondary-structure layout, cross-run sequence-export path reuse, repeated SimpleFold staging collisions, and incomplete public readiness/call evidence until their repair tickets land. |
| Mocked Workflow | `.venv/bin/python scripts/verify_backend.py mocked-workflow` | Runs the current deterministic 3GB1 Workflow tests with provider boundaries replaced by fixtures. |
| Local provider | `.venv/bin/python scripts/verify_backend.py local-provider` | Runs non-heavy installed binaries and requires both zero skips and provider-call evidence. |
| Local ESM-3 heavy model | `.venv/bin/python scripts/verify_backend.py local-esm3-heavy-model` | Source-bound zero-skip gate for local ESM-3 sequence, structure, and paired v2 Bindings with exact readiness and provider-call evidence. |
| Local ESMFold2 v2 contract | `.venv/bin/python scripts/verify_backend.py local-esmfold2-v2-contract` | Zero-skip source-contract gate for the exact installed ESM/Transformers sources, provider-native local result shape, static confidence normalization, no-fallback lineage, and shared folding CTK. It does not claim that the unavailable 25+ GB model was executed. |
| SimpleFold v2 heavy model | `.venv/bin/python scripts/verify_backend.py simplefold-v2-heavy-model` | Source-bound zero-skip full gate for the shared folding Node's exact local SimpleFold Binding, one real fold call, private staging cleanup, and complete provider evidence. |
| Aggregate heavy local models | `.venv/bin/python scripts/verify_backend.py heavy-model` | Explicitly loads all slow local models and requires zero skips plus exact local ESM-3, ProteinMPNN, and SimpleFold provider-call evidence. |
| Live remote provider | `.venv/bin/python scripts/verify_backend.py live-provider` | Makes remote provider calls and requires both zero skips and provider-call evidence. Readiness alone cannot satisfy this gate. |
| Remote ESMFold2 v2 | `.venv/bin/python scripts/verify_backend.py remote-esmfold2-v2` | Source-bound zero-skip gate for one real Biohub ESMFold2 call through the exact shared v2 folding Binding, including typed confidence/PAE completeness and provider-call evidence. |
| Fresh canonical 3GB1 | `.venv/bin/python scripts/verify_backend.py fresh-remote-3gb1` | Runs the protected canonical Workflow once through REST and its run-scoped WebSocket against local ESM3, Biohub ESMFold2, ProteinMPNN, mkdssp, Biopython SVD, and tmtools, then retrieves and seals exactly 15 run-bound PDBs. |

## Module Package maintainer contract

A repository-owned extension has one production entry point,
`modules/<package>/package.py:MODULE_PACKAGE`. Maintainers pass that exact
`ModulePackageRegistration` to `verify_module_package_contract` together with
independent `ModulePackageContractCase` and `ModulePackagePortCase` values.
Cases, fixtures, and package-local tests are not registration fields and are
not production wheel content.

The shared Contract Test Kit builds a temporary `FrozenCatalog`, validates a
package-owned Port Type codec, saves and relocks a minimal Workflow, compiles
it, obtains run-scoped Readiness, executes through the normal v2 direct
interface, replays durable public events, decodes Candidates and typed
Observations, verifies Result Identity and producer provenance, and retrieves
declared artifacts. It rejects unsafe public diagnostics, including fixture
credentials and private runtime paths. This executable contract is the
maintainer workflow; there is no second package template or package-specific
Core dispatch path.

Run the focused source contract and the source-versus-installed public journey
with:

```bash
.venv/bin/pytest -q tests/test_contract_test_kit_v2.py
.venv/bin/python scripts/verify_backend.py installed-package
```

The source-local synthetic package lives only under
`tests/fixtures/zero_core_packages`. The installed gate copies its production
registration and resources, but not its local cases or tests, outside the
source checkout. The installed backend discovers that package, proves the same
Catalog contract digest as source, and completes Catalog query, Workflow
compile, Run execution, cursor replay, Run Projection, and Artifact Retrieval
without a Core dispatch edit. Ordinary production discovery does not expose
the synthetic capability.

The complete real gates require these exact successful adapter-boundary calls:

- `local-provider`: `biopython-svd:structure_align`,
  `tmtools:tm_score`, and `mkdssp:secondary_structure`;
- `heavy-model`: `local_open:esm3.generate_sequence` × 2 and
  `local_open:esm3.generate_structure` × 2 (one direct mode call plus the
  corresponding call inside paired generation),
  `local-proteinmpnn:design_sequences`, `local-proteinmpnn:score_sequence`,
  `simplefold:fold_sequence`, and `simplefold:evaluate_structure`;
- `live-provider`: `biohub:esm3.generate_sequence` and
  `biohub:esmfold2.fold`.

Each call record contains the provider and model identity, readiness at the call
boundary, one actual-call count, effective seed (or an explicit provider
non-support statement), `bypassed_fresh_direct_call` Cache decision, and a bounded
terminal summary. Inputs and structures are retained only as lengths and SHA-256
digests. Tokens, sequences, PDB text, environment values, provider stdout, and
failure bodies are not retained.

Alignment and TM-score invocations that raise after reaching the scientific
engine are also retained in the run manifest exactly once per invoked boundary.
Their terminal result is `failed` and contains only the bounded exception type;
the exception message, body, paths, coordinates, and credentials are discarded.
Input-validation failures that occur before an engine invocation are not call
facts.
Operation-specific manifest details are validated before the engine boundary,
and failures while decoding an engine result share that invocation's single
failed terminal. Public Node failure kinds use the same bounded error-type
normalization.

The verifier creates a fresh nonce and fresh isolated roots on every invocation.
Evidence with another nonce, a pre-run or future timestamp, a duplicate event ID,
an invalid schema, an unexpected test/model/source identity or call count, missing
readiness, missing calls, skips, or zero selected tests cannot pass. Each full
provider tier executes a fixed, narrow node-ID allowlist rather than marker-wide
test discovery. Focused provider invocations after `--` are diagnostic and always
finish incomplete even when their selected test succeeds; only the unmodified full
tier can pass. Full provider tiers additionally require a clean committed source
tree whose HEAD exactly matches
`PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION`; the same attestation is recomputed
before success, and retained evidence binds both the commit and source-tree SHA-256. The
Biohub cases pin the literal 3GB1 PDB and extracted sequence SHA-256 before the
credential is used. The child receives a tier-specific environment allowlist rather
than all ambient credentials, and local model tiers force Hugging Face offline mode.

Use file paths rather than secret values when configuring provider access:

```bash
export PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE=/secure/path/esmkey.txt
export PROTEIN_WORKBENCH_PROTEINMPNN_ROOT=/opt/proteinmpnn
export PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT=/opt/simplefold-models
export PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT=/opt/facebookresearch-esm
export PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT=/opt/facebookresearch-esm2-models
```

The SimpleFold model root must contain the six regular non-symlink files and exact
SHA-256 values listed in `docs/provider-install-contract.md`. The adapter does not
call the upstream downloader. It stages all six objects from no-follow regular-file
descriptors into the isolated run root and rehashes them before provider import or
use. The ESM2 root must be a clean Git checkout at
`2b369911bb5b4b0dda914521b9475cad1656b2ac`; the adapter stages that checkout's
reviewed runtime source tree and imports only from the staged copy instead of using
the upstream mutable `main` alias. The two ESM2 checkpoint objects must also match
the size and SHA-256
contract in `docs/provider-install-contract.md`; they are staged and loaded by
local path without a network or inherited `TORCH_HOME` fallback. Missing files,
byte-count or digest mismatches, a symlink, an unclean or wrong ESM2 checkout,
source-tree drift, and historical PDB outputs all fail readiness.

The fresh canonical tier is a coherent run, not a replay of the narrow Ticket 19
gates. It requires the same clean approved source attestation while combining the
Biohub credential, local ESM3 snapshot, locked ProteinMPNN checkout, mkdssp, and
alignment/scoring libraries in one isolated backend process. SimpleFold is not in
the canonical Workflow and is therefore not called by this tier. The verifier
owns one process group containing pytest, uvicorn, every canonical Module worker,
and mkdssp; timeout or abnormal pytest exit terminates that complete group.

The exact successful real-boundary multiplicities are:

- `local_open:esm3.generate_sequence` × 10;
- `local_open:esm3.generate_structure` × 10;
- `biohub:esmfold2.fold` × 25;
- `local-proteinmpnn:design_sequences` × 3;
- `mkdssp:secondary_structure` × 1;
- `biopython-svd:structure_align` × 20;
- `tmtools:tm_score` × 20.

That is 89 source-bound successful events, all retained directly by the backend
run manifest: 49 existing Node-scoped provider call facts plus 20 alignment and
20 TM-score engine success facts. The separate gate evidence stream corroborates
those facts but no longer supplies calls missing from the public manifest. The
pairwise alignment adapter preserves the same sequence-tie resolution used by
scalar alignment, including its internal tmtools structural resolution when
needed, while recording one terminal `biopython-svd:structure_align` fact for
the single public adapter invocation rather than double-counting that nested
engine step as another Node call. That outer fact includes the nested tmtools
method and version on both success and failure. The
verifier rejects a missing or extra call, a Cache hit, a dirty or changed source,
a non-terminal run, incomplete lineage or scoring, a mismatched artifact, a
skipped test, or a missing evidence file.

Use an explicit token path and locked local roots:

```bash
export PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION="$(git rev-parse HEAD)"
export PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE=/secure/path/esmkey.txt
export PROTEIN_WORKBENCH_PROTEINMPNN_ROOT=/opt/proteinmpnn
export HF_HOME=/path/to/reviewed/huggingface-cache
.venv/bin/python scripts/verify_backend.py fresh-remote-3gb1
```

The dated result directory retains `sealed-manifest.json`, 15 read-only PDBs,
`artifact-checksums.sha256`, `bundle-checksums.sha256`, sanitized JUnit,
the command transcript, environment summary, raw redacted provider events, and
their validated provider summary. The sealed manifest binds the exact Git
revision and clean state, Workflow hash, ModuleDefinition versions, environment,
effective seeds, Cache bypasses, ordered Node and WebSocket outcomes, Candidate
lineage, scores, actual calls, and independently retrieved artifacts. Credential
contents, sequences, input PDB text, provider stdout, and failure bodies are not
retained.

The provider-event file and fresh artifacts are child-staged and become retained
evidence only after the parent verifier has revalidated and copied them through
no-follow, exclusive-create file descriptors. Provider events and the sealed
manifest must also pass closed key and value schemas; unexpected fields,
unrecognized providers, sensitive allowed-field values, malformed digests,
noncanonical successful-call facts, or malformed lifecycle records are rejected
before publication. Completion reports must record the
SHA-256 of `bundle-checksums.sha256` outside the bundle so later readers can
detect local bundle replacement. That detached digest is an audit anchor, not a
cryptographic signature.

## V2 public protocol bundle

The versioned `protein-workbench-public/v2` contract is shipped as
`protein_workbench_public/resources/v2/bundle.json`. Source and installed
clients load it through the public `protein_workbench_public` package, which
returns RFC 8785 canonical UTF-8 bytes and their public `sha256:` digest. A
running backend serves those exact bytes from `GET /api/v2/protocol`, with the
same digest in the `Digest` response header.

The bundle is the only payload source for the v2 REST operations, Run Event
Stream union and replay/close rules, artifact metadata, and structured-error
vocabulary. The public package supplies request preparation and closed-field
request, response, event, error, and artifact validation without importing
`core`. Acceptance clients must use those functions and the operation metadata;
they must not maintain route or payload fallbacks for v1.

Run the focused source contract and the isolated source-versus-wheel gate with:

```bash
.venv/bin/pytest -q tests/test_public_protocol_v2.py
.venv/bin/python scripts/verify_backend.py installed-package
```

The installed-package gate checks the bundle resource in both wheel and sdist,
loads it from outside the source checkout, compares canonical bytes and digest
to the source result, and retrieves the same bytes from the installed backend.
It also kills that backend during an actual Engine Invocation, restarts it
against the same private storage roots, and verifies cursor-exclusive replay,
conservative outcome-unknown/interrupted closure, empty outputs and Cache, and
idempotent projection and terminal-stream recovery after a second restart.

V2 Ledger facts are bounded to 4 MiB, fsynced under a private temporary name,
and atomically published without replacement; an invalid Run Ledger is isolated
as unavailable instead of preventing unrelated Runs from loading. Background
Run admission is bounded and Project-reserved, Node work is globally serial,
and graceful backend shutdown joins every tracked v2 writer. Manifest and
lifecycle projection publication is retried after a partial projection failure;
while a persistent mismatch remains, public projection/event reads fail closed
with the last durable cursor and retry the rebuild rather than serving
contradictory generations.

The first v2 Catalog slice is available from `GET /api/v2/catalog`. It publishes
the exact `2.0.0` nominal Port Type contracts used by the backend, including
stable validator, canonical-codec, and content-identity behavior declarations.
Private Python callables and source/install paths are not part of those
descriptors. Runtime Port values are validated, encoded as strict RFC 8785 UTF-8
bytes, and identified as `sha256:` of those bytes; malformed JSON, non-canonical
bytes, duplicate object keys, negative zero, NaN, and Infinity fail closed.
Direct connection compatibility requires the same known Port Type ID and exact
version, so scientific conversion remains an explicit Node Type.

Run the focused Port Type contract and source-versus-installed Catalog parity
checks with:

```bash
.venv/bin/pytest -q tests/test_port_types_v2.py
.venv/bin/python scripts/verify_backend.py installed-package
```

The installed-package probe compares Catalog canonical bytes, every Port Type
descriptor byte sequence, every Port Type digest, and the Catalog digest before
querying the same public contracts from the installed backend. It also proves
that a source-local conforming Module Package retains equivalent contract and
behavior identities when discovered by the installed artifact.

## Deterministic public-protocol acceptance

The deterministic tier covers the retained legacy failure variants and the
locked `examples/v2/canonical-3gb1.workflow.json`. The v2 client obtains Catalog
and Project/Workflow snapshots, compiles, starts Runs, consumes the run-scoped
WebSocket, retrieves the durable Run projection, and downloads every PDB through
the Run-bound artifact route. ESM-3, ESMFold2, and ProteinMPNN are replaced only
at their declared provider boundaries; the production prompt adapters, Frozen
Catalog, compiler, Execution Engine, Cache, Ledger, selection, lineage, and
artifact paths remain real.

The tier fixes exact acceptance evidence for ten paired ESM3 sequence/structure
Candidates, ten initial folds, isolated fixed-reference and paired-counterpart
TM-score objectives, the weighted top three, three ProteinMPNN parents with five
children each, fifteen final folds, complete causal closure, and fifteen
retrievable PDB SHA-256 values.
It also covers pre-run incompatible-edge and traversal rejection, a structured
provider failure with an unrelated successful branch, cancellation, same-project
overlap rejection, Cache replay in a fresh run scope, cross-scope reads, and
untrusted WebSocket origins. It never calls a real external provider.

## Reproducible installation

The checked-in `uv.lock` is the complete resolver result for Python 3.12. Install
the backend and development gates, including their PyTorch-backed deterministic
test seams, exactly from that lock:

```bash
uv sync --frozen --extra dev
```

Build release artifacts through the retained deterministic build command:

```bash
.venv/bin/python scripts/build_backend.py dist
```

The base install contains the API/WebSocket stack, scientific runtime
dependencies, ModuleDefinition YAML, and canonical Workflow/UI/PDB assets. Provider
SDKs and model runtimes are intentionally explicit:

```bash
uv sync --frozen --extra dev --extra providers
```

That extra pins ESM and SimpleFold to the same upstream commits recorded by this
checkout and installs PyTorch. ProteinMPNN is not copied into the wheel: clone the
read-only upstream checkout at commit
`8907e6671bfbfc92303b5f79c4b5e6ce47cdef57`, verify the required checkpoint hashes
listed in `docs/provider-install-contract.md`, and set
`PROTEIN_WORKBENCH_PROTEINMPNN_ROOT` to that external checkout.

Each command prints `BACKEND VERIFICATION TIER` before pytest starts and
`BACKEND VERIFICATION RESULT` after JUnit and provider evidence are checked.
Provider tiers fail when a required provider is unavailable; they never turn missing
provider work into a passing skip.

## Focused pytest arguments

For infrastructure diagnosis, paths may be supplied after `--`; the selected tier's
marker policy still applies:

```bash
.venv/bin/python scripts/verify_backend.py routine -- tests/test_server_projects.py
```

This is also the supported way to retain the isolation and result transcript while
running a focused test.
