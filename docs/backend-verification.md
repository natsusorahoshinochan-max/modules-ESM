# Backend verification tiers

The backend verifies one active Catalog generation and the current v2 public
protocol. Verification prioritizes scientific meaning, exact contracts,
lineage, residue mapping, units, randomness, provenance, and durable evidence;
it does not verify compatibility with superseded development artifacts.

Use one public verification command:

```bash
.venv/bin/python scripts/verify_backend.py <tier>
```

Each invocation replaces Project, Cache, output, and Run roots only in the
child process. It never writes configured production roots. After pytest exits,
the verifier retains a bounded JUnit file, sanitized command transcript, and
environment summary under the ignored
`verification-results/<tier>/<UTC-run-id>/` directory. Retained directories
use mode `0700` and files use mode `0600`.

## Available tiers

| Tier | Command | Contract |
| --- | --- | --- |
| Routine backend regression | `.venv/bin/python scripts/verify_backend.py routine` | Runs deterministic current-generation tests and excludes acceptance, installed-package, Provider, slow-model, and scientific-reproduction markers. |
| Repository v2 examples | `.venv/bin/python scripts/verify_backend.py examples-v2` | Commits and compiles the maintained current-generation Workflow suite and compares its 11-package capability inventory with the active source Catalog. |
| Deterministic backend acceptance | `.venv/bin/python scripts/verify_backend.py deterministic-acceptance` | Runs the locked canonical v2 3GB1 public-protocol journey and its current failure, readiness, cancellation, isolation, and replay variants. |
| Scientific reproduction | `.venv/bin/python scripts/verify_backend.py scientific-repro` | Confirms that every Provider-representable amino-acid symbol crosses the ESM-3 Adapter seam unchanged and retains its declared scientific identity. |
| Local ESMFold2 source contract | `.venv/bin/python scripts/verify_backend.py local-esmfold2-v2-contract` | Checks the exact source/native-result contract, static confidence normalization, no-fallback lineage, and shared folding CTK without claiming a real heavy-model invocation. |
| Installed package | `.venv/bin/python scripts/verify_backend.py installed-package` | Reproducibly builds the wheel and sdist, installs the wheel outside the checkout, proves source/installed protocol and Catalog identity, and drives the installed server through the public v2 Workflow/Run journey. |
| Installed Biohub ESMC | `.venv/bin/python scripts/verify_backend.py installed-biohub-esmc` | Launches only the installed artifact and invokes exact `esmc-600m-2024-12` encode plus logits through the public Workflow/Run protocol, proving Readiness, mean-embedding output, validated sequence-logits shape, and complete Engine Invocation evidence. |
| Installed local ESM-3 | `.venv/bin/python scripts/verify_backend.py installed-local-esm3` | Invokes the installed locked local model for paired, sequence, and structure generation and requires complete invocation evidence. |
| Installed SimpleFold folding | `.venv/bin/python scripts/verify_backend.py installed-simplefold-folding` | Invokes the installed locked SimpleFold folding model with its exact model and ESM-2 assets. |
| Installed SimpleFold confidence | `.venv/bin/python scripts/verify_backend.py installed-simplefold-confidence` | Invokes the installed exact confidence asset closure and proves direct-confidence output without refolding. |
| Installed SoluProt | `.venv/bin/python scripts/verify_backend.py installed-soluprot` | Invokes both full and no-TM locked SoluProt methods and checks their exact observations and terminal evidence. |
| Installed Protein-Sol | `.venv/bin/python scripts/verify_backend.py installed-protein-sol` | Invokes the source-bound Protein-Sol model for multiple sequences and all three declared Metrics. |
| Provider route isolation | `.venv/bin/python scripts/verify_backend.py provider-isolation` | Exercises exact model/data identity, configuration invalidation, stale Readiness, reusable-proof identity, and isolation of actual Provider routes. |
| Local integrity and failure closure | `.venv/bin/python scripts/verify_backend.py security-failure` | Exercises accidental path/data-loss prevention, credential redaction, process cleanup, Project/Run isolation, Cache conflict, and durable-evidence failure. This is not an attacker-hardening tier. |

The six installed Provider tiers are zero-skip gates: a missing Provider,
fixture-only collection, failed source-origin check, missing Engine Invocation,
or skipped test fails the gate. The copied acceptance harness is outside the
checkout, and its bootstrap first proves that `core`, `modules`, and
`protein_workbench_public` resolve from the installed wheel. It may expose
locked dependency locations to that isolated environment, but it cannot add
the source checkout to Python's import path. Installed provider gates reject
pytest target overrides so a smaller test cannot replace the required case.

The required installed ESMC gate reads only the private Biohub credential file
selected by `PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE`; it neither downloads nor
requires local ESMC or ESMFold2 shards. The direct ESMC Node and Binding are
scientifically distinct from the existing remote ESMFold2 folding Binding.
Local ESMFold2 remains registered and fail-closed when its exact snapshots are
absent, and its provider-free source contract remains available through
`local-esmfold2-v2-contract`; it is not a required installed zero-skip gate.

The verifier exposes no v1 provider-evidence, mocked-workflow,
aggregate-provider, live-provider, or fresh-remote tier. A Provider gate
consumes current Run Evidence Ledger facts; an Adapter-owned JSONL stream,
readiness-only result, historical manifest, fixed call count, skip, or
Cache-only replay cannot satisfy it.

All declared pytest file targets are required to exist. A focused override after
`--` accepts only repository-relative selectors beneath `tests/`; this keeps a
developer from accidentally replacing the intended verification scope.

## Architecture invariants

The verification suite must prove all of the following through public or
contract-owning interfaces:

- the `FrozenCatalog` contains exactly one active exact version for every
  logical Node Type, Port Type Definition, Method, Execution Binding, Metric
  Definition, and Utility Transform;
- incompatible changes update all current producers, consumers, examples, and
  fixtures together; old Workflow, Cache, and Run schemas fail closed without
  migration or legacy execution;
- an immutable `Execution Plan` fixes the exact contracts before a Run and the
  runtime does not rediscover graph, Binding, Method, or Port facts;
- canonical scientific operations accept admitted provider-independent values
  and do not receive or query the `FrozenCatalog` or public contract versions;
- one scientific meaning has one canonical implementation; a changed wire
  contract does not introduce a second positional or legacy implementation;
- a concrete Provider Adapter is the only owner of provider-native translation
  and exact Provider/model/checkpoint/source provenance;
- identical canonical PDB content has one `protein.structure@3.0.0` content
  digest independent of provider or project-source provenance, and the active
  structure wire admits no source-bearing historical shape;
- `structure_transform.backbone_structure@3.0.0` is admitted by exact
  structural and atomic invariants, never by a producer/source label;
- internal immutable values are trusted after admission, while scientific
  invariants, persistence admission, durable writes, and credential hygiene
  retain focused verification.

## Module Package maintainer contract

A repository-owned extension has one production entry point:
`modules/<package>/package.py:MODULE_PACKAGE`. The production Catalog discovers
exactly these 11 packages:

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
- `structure_transform`

Maintainers pass the package's `ModulePackageRegistration` to
`verify_module_package_contract` with independent `ModulePackageContractCase`
and `ModulePackagePortCase` values. The Contract Test Kit builds a temporary
single-generation `FrozenCatalog`, proves one active exact version per logical
contract, validates package-owned Port Type codecs and golden bytes, commits a
minimal Workflow, obtains run-scoped Readiness, and executes through the normal
v2 interface. It replays public events, decodes typed outputs, checks Result
Identity, scientific lineage, producer and Provider provenance, and retrieves
declared Artifacts. Tests exercise the same scientific-operation seam as the
runtime and do not require an operation implementation to inspect the Catalog.

Run the focused package contract with:

```bash
.venv/bin/pytest -q tests/test_contract_test_kit_v2.py
```

The synthetic echo package exists only under
`tests/fixtures/zero_core_packages`. Production discovery does not expose echo.
Neither the wheel nor the sdist contains the repository test tree, fixture
resources, or synthetic echo package.

## Installed parity contract

`scripts/build_backend.py` creates byte-reproducible wheel and sdist artifacts.
The installed-package gate creates a fresh virtual environment and launches
`python -I -m core.server` from a directory outside the checkout. The installed
protocol bundle bytes and digest, canonical Catalog descriptor bytes and
digest, and ordered FrozenCatalog contract references must exactly equal the
source deployment's one active generation. Availability remains a separately
observed startup value and is not part of the canonical Catalog descriptor.

The installed public journey uses protocol-bundle operations for Catalog,
Workflow save/snapshot/relock/compile, Start Run, Run Projection, Derived Run,
Cancel Run, and Artifact Retrieval. Its WebSocket observes a bounded replay
followed by live terminal evidence. The second Run must contain a Cache replay,
and retrieved artifact bytes must match their declared digest.

## V2 public protocol and persistence

`protein_workbench_public/resources/v2/bundle.json` is the only public payload
contract. A running backend serves the same canonical bytes from
`GET /api/v2/protocol`; clients use `protein_workbench_public` request and
response validation and do not maintain v1 route or payload fallbacks.

The startup-frozen `FrozenCatalog` is the only discovery and compilation
contract source. It publishes one active exact version for each logical
contract. The immutable `Execution Plan` carries resolved contract facts into
Readiness and execution; scientific operations do not rescan the Catalog.
Direct Port compatibility requires an exact nominal Port Type ID and version.
Artifact-capable Port Types require explicit Node publication intent and an
exact media contract; no path-output or media-type fallback exists.

Project metadata, persisted Workflows, Result Cache entries, and Run Ledger
facts use closed current schemas. Unsupported schemas or inactive contract
generations fail at their public seam with `unsupported_schema_version`,
`unsupported_version`, or `inactive_generation`. They are not migrated,
relocked, rewritten, interpreted as current values, or accepted as current
evidence. Old pickle/path Cache entries are ignored and development state may
be cleared and regenerated.

Run Ledger facts are bounded, fsynced under private temporary names, and
atomically published without replacement. Public projection and event replay
are derived from that Ledger. There is no parallel provider-evidence writer.

## Deterministic public-protocol acceptance

The deterministic tier uses
`examples/v2/canonical-3gb1.workflow.json`. It exercises Catalog and Workflow
snapshots, compile, Start Run, durable replay, Run Projection, Cache replay,
selection, lineage, cancellation, and Artifact Retrieval. Providers are
replaced only at their declared Adapter seams; the Frozen Catalog,
compiler, execution engine, Cache, Ledger, and public routes remain real.

The tier verifies the accepted ten paired ESM-3 Candidates, initial folds,
isolated fixed-reference and paired-counterpart TM-score objectives, weighted
top three, three ProteinMPNN parents with five children each, fifteen final
folds, complete causal closure, and fifteen retrievable PDB digests. It never
uses v1 bundles, fixed historical provider counts, or separate adapter evidence.
