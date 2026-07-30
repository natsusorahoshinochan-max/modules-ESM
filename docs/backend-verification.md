# Backend verification tiers

The v2-only backend uses one public verification command:

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
| Routine backend regression | `.venv/bin/python scripts/verify_backend.py routine` | Runs deterministic v2 tests and excludes acceptance, installed-package, provider, slow-model, and scientific-reproduction markers. |
| Repository v2 examples | `.venv/bin/python scripts/verify_backend.py examples-v2` | Parses, exactly relocks, and compiles the maintained v2 Workflow suite and compares its 11-package capability inventory with the source Catalog. |
| Deterministic backend acceptance | `.venv/bin/python scripts/verify_backend.py deterministic-acceptance` | Runs the locked canonical v2 3GB1 public-protocol journey and its current failure, readiness, cancellation, isolation, and replay variants. |
| Scientific reproduction | `.venv/bin/python scripts/verify_backend.py scientific-repro` | Confirms that every provider-representable amino-acid symbol reaches the cohesive ESM-3 package boundary unchanged. |
| Local ESMFold2 source contract | `.venv/bin/python scripts/verify_backend.py local-esmfold2-v2-contract` | Checks the exact source/native-result contract, static confidence normalization, no-fallback lineage, and shared folding CTK without claiming a real heavy-model invocation. |
| Installed package | `.venv/bin/python scripts/verify_backend.py installed-package` | Reproducibly builds the wheel and sdist, installs the wheel outside the checkout, proves source/installed protocol and Catalog identity, and drives the installed server through the public v2 Workflow/Run journey. |
| Installed local ESMFold2 | `.venv/bin/python scripts/verify_backend.py installed-local-esmfold2` | Imports the exact installed ESM and Transformers sources, then proves the local Binding's readiness-before-invocation, native result normalization, terminal evidence, and no remote fallback. |
| Installed local ESM-3 | `.venv/bin/python scripts/verify_backend.py installed-local-esm3` | Invokes the installed locked local model for paired, sequence, and structure generation and requires complete invocation evidence. |
| Installed SimpleFold folding | `.venv/bin/python scripts/verify_backend.py installed-simplefold-folding` | Invokes the installed locked SimpleFold folding model with its exact model and ESM-2 assets. |
| Installed SimpleFold confidence | `.venv/bin/python scripts/verify_backend.py installed-simplefold-confidence` | Invokes the installed exact confidence asset closure and proves direct-confidence output without refolding. |
| Installed SoluProt | `.venv/bin/python scripts/verify_backend.py installed-soluprot` | Invokes both full and no-TM locked SoluProt methods and checks their exact observations and terminal evidence. |
| Installed Protein-Sol | `.venv/bin/python scripts/verify_backend.py installed-protein-sol` | Invokes the source-bound Protein-Sol model for multiple sequences and all three declared Metrics. |
| Provider isolation | `.venv/bin/python scripts/verify_backend.py provider-isolation` | Exercises model/data replacement, runtime-tree drift, configuration invalidation, stale readiness, reusable-proof identity, and optional-sibling isolation. |
| Security and failure closure | `.venv/bin/python scripts/verify_backend.py security-failure` | Exercises path containment, no-follow/symlink defenses, redaction, process cleanup, project/run isolation, Cache conflict, and durable-evidence failure. |

The six installed provider tiers are zero-skip gates: a missing provider,
fixture-only collection, failed source-origin check, missing Engine Invocation,
or skipped test fails the gate. The copied acceptance harness is outside the
checkout, and its bootstrap first proves that `core`, `modules`, and
`protein_workbench_public` resolve from the installed wheel. It may expose
locked dependency locations to that isolated environment, but it cannot add
the source checkout to Python's import path. Installed provider gates reject
pytest target overrides so a smaller test cannot replace the required case.

The verifier exposes no v1 provider-evidence, mocked-workflow,
aggregate-provider, live-provider, or fresh-remote tier. A provider gate
consumes current v2 Run Ledger facts; an adapter-owned JSONL stream,
readiness-only result, historical manifest, fixed call count, skip, or
Cache-only replay cannot satisfy it.

All declared pytest file targets are required to exist. A focused override after
`--` accepts only repository-relative selectors beneath `tests/`; absolute
paths, parent traversal, and arbitrary pytest options are rejected.

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
`FrozenCatalog`, validates package-owned Port Type codecs, saves and explicitly
relocks a minimal Workflow, compiles it, obtains run-scoped Readiness, executes
through the normal v2 interface, replays public events, decodes typed outputs,
checks Result Identity and producer provenance, and retrieves declared
artifacts.

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
source deployment. Availability remains a separately observed startup value
and is not part of the canonical Catalog descriptor.

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

The startup-frozen `FrozenCatalog` is the only discovery, compilation,
readiness, and execution contract source. Direct Port compatibility requires an
exact nominal Port Type ID and version. Artifact-capable Port Types require
explicit Node publication intent and an exact media contract; no path-output or
media-type fallback exists.

Project metadata, persisted Workflows, Result Cache entries, and Run Ledger
facts use closed v2 schemas. Unsupported persisted schemas fail at their public
boundary with `unsupported_schema_version`. They are not migrated, relocked,
rewritten, interpreted as v2 values, or accepted as current evidence. Old
pickle/path Cache entries are ignored.

Run Ledger facts are bounded, fsynced under private temporary names, and
atomically published without replacement. Public projection and event replay
are derived from that Ledger. There is no parallel provider-evidence writer.

## Deterministic public-protocol acceptance

The deterministic tier uses
`examples/v2/canonical-3gb1.workflow.json`. It exercises Catalog and Workflow
snapshots, compile, Start Run, durable replay, Run Projection, Cache replay,
selection, lineage, cancellation, and Artifact Retrieval. Providers are
replaced only at their declared package boundaries; the Frozen Catalog,
compiler, execution engine, Cache, Ledger, and public routes remain real.

The tier verifies the accepted ten paired ESM-3 Candidates, initial folds,
isolated fixed-reference and paired-counterpart TM-score objectives, weighted
top three, three ProteinMPNN parents with five children each, fifteen final
folds, complete causal closure, and fifteen retrievable PDB digests. It never
uses v1 bundles, fixed historical provider counts, or separate adapter evidence.
