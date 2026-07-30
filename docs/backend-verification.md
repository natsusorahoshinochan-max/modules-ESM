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

The verifier exposes no v1 provider-evidence, mocked-workflow, installed,
aggregate-provider, live-provider, or fresh-remote tier. A provider gate can be
added only when it consumes current v2 Run Ledger facts through the public
protocol; an adapter-owned JSONL stream, readiness-only result, historical
manifest, fixed call count, skip, or Cache-only replay cannot satisfy it.

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
