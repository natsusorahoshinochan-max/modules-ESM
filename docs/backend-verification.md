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
| Installed Biohub ESM-3 | `.venv/bin/python scripts/verify_backend.py installed-biohub-esm3` | Invokes all six exact medium/open sequence, structure, and paired Bindings through fresh Runs. It requires eight successful Engine Invocations and fixes SDK retries to one attempt per call. |
| Installed Biohub ESMFold2 | `.venv/bin/python scripts/verify_backend.py installed-biohub-esmfold2` | Invokes the exact remote `esmfold2-fast-2026-05` Binding once through a fresh Run with one SDK attempt. |
| Installed local ESM-3 | `.venv/bin/python scripts/verify_backend.py installed-local-esm3` | Invokes the installed locked local model for paired, sequence, and structure generation and requires complete invocation evidence. |
| Installed local ESMFold2 | `.venv/bin/python scripts/verify_backend.py installed-local-esmfold2` | Invokes the exact locked ESMFold2 and ESMC snapshots at the declared CPU/FP32 precision through a fresh Run and requires exact-seed Method evidence. |
| Installed ProteinMPNN | `.venv/bin/python scripts/verify_backend.py installed-proteinmpnn` | Invokes exact design and native-score Bindings through fresh Runs, then verifies designed-first multi-chain restoration and fixed-residue mapping against the same installed Provider. |
| Installed mkdssp | `.venv/bin/python scripts/verify_backend.py installed-mkdssp` | Invokes exact mkdssp 4.6.1 through the public Run seam and verifies the canonical DSSP residue layout, secondary-structure track, SASA track, and complete Method evidence. |
| Installed SimpleFold folding | `.venv/bin/python scripts/verify_backend.py installed-simplefold-folding` | Invokes the installed locked SimpleFold folding model with its exact model and ESM-2 assets. |
| Installed SimpleFold confidence | `.venv/bin/python scripts/verify_backend.py installed-simplefold-confidence` | Invokes the installed exact confidence asset closure and proves direct-confidence output without refolding. |
| Installed SoluProt | `.venv/bin/python scripts/verify_backend.py installed-soluprot` | Invokes both full and no-TM locked SoluProt methods and checks their exact observations and terminal evidence. |
| Installed Protein-Sol | `.venv/bin/python scripts/verify_backend.py installed-protein-sol` | Invokes the source-bound Protein-Sol model for multiple sequences and all three declared Metrics. |
| Fresh source-bound 1PGA | `.venv/bin/python scripts/verify_backend.py fresh-1pga` | Runs the clean-source installed 1PGA Workflow and retains the complete three-way structure, confidence, pairing, retrieval, and classification evidence. |
| Fresh source-bound 2EMO | `.venv/bin/python scripts/verify_backend.py fresh-2emo` | Runs the clean-source installed 2EMO Workflow and retains exact CSH normalization, ProteinMPNN, ESMFold2, Protein-Sol, four-filter, and public evidence. |
| Fresh canonical 3GB1 | `.venv/bin/python scripts/verify_backend.py fresh-canonical-3gb1` | Runs the clean-source canonical scientific Workflow without historical Cache. Its baseline is 48 logical Engine Invocations, so it is release evidence rather than a substitute for the smaller exact-Binding gates. |
| Fresh source-bound 5G53 | `.venv/bin/python scripts/verify_backend.py fresh-5g53` | Runs the clean-source installed 5G53 Workflow and retains all six paired candidates, reconstruction, both PAE-bearing confidence collections, loop evidence, retrieval, and artifacts. |
| Provider route isolation | `.venv/bin/python scripts/verify_backend.py provider-isolation` | Exercises exact model/data identity, configuration invalidation, stale Readiness, reusable-proof identity, and isolation of actual Provider routes. |
| Local integrity and failure closure | `.venv/bin/python scripts/verify_backend.py security-failure` | Exercises accidental path/data-loss prevention, credential redaction, process cleanup, Project/Run isolation, Cache conflict, and durable-evidence failure. This is not an attacker-hardening tier. |

The eleven installed Provider tiers are zero-skip gates: a missing Provider,
fixture-only collection, failed source-origin check, missing Engine Invocation,
or skipped test fails the gate. The copied acceptance harness is outside the
checkout, and its bootstrap first proves that `core`, `modules`, and
`protein_workbench_public` resolve from the installed wheel. It may expose
locked dependency locations to that isolated environment, but it cannot add
the source checkout to Python's import path. Installed provider gates reject
pytest target overrides so a smaller test cannot replace the required case.

The installed Biohub gates read one private credential file selected by
`PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE`, or the repository's private
`keys/esmkey.txt` when that variable is absent. They do not download or require
local model shards. The direct ESMC Node, the six remote ESM-3 generation
Bindings, and remote ESMFold2 are scientifically distinct and have separate
installed gates. Local ESMFold2 also has a real zero-skip gate; the
provider-free `local-esmfold2-v2-contract` remains a separate source and
translation contract and cannot replace that invocation.

The verifier exposes no v1 provider-evidence, mocked-workflow,
aggregate-provider, or generic live-provider tier. It does expose the exact
four exact clean-source release tiers. Every Provider gate consumes
current Run Evidence Ledger facts; an Adapter-owned JSONL stream,
readiness-only result, historical manifest, skip, or Cache-only replay cannot
satisfy it. A fixed expected call count is useful only together with exact
Binding, Method, `executed` disposition, and terminal Ledger evidence.

## Trusted Provider environment configuration

Provider filesystem locations and credentials are Environment Configuration,
not Workflow parameters and not workstation-specific literals. Set the exact
variables required by the selected gate:

| Gate | Required trusted configuration |
| --- | --- |
| Biohub ESMC, ESM-3, ESMFold2 | Optional `PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE`, selecting one private regular credential file instead of `keys/esmkey.txt`. |
| Local ESM-3 | `HF_HUB_CACHE` or `HF_HOME`, containing the locked snapshot. |
| Local ESMFold2 | `PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT` and `PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT`. |
| ProteinMPNN | `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT`. |
| mkdssp | `PROTEIN_WORKBENCH_MKDSSP_BINARY`, selecting the exact 4.6.1 binary by absolute path. |
| SimpleFold | `PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT`, `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT`, and `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT`. |
| SoluProt | `PROTEIN_WORKBENCH_SOLUPROT_ROOT`, selecting the trusted runtime and asset root. |
| Protein-Sol | `PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT`, selecting the trusted Protein-Sol source root. |

Missing or relative required path configuration fails a zero-skip gate.
Acceptance files do not infer Provider runtimes from another workspace.

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
- identical canonical PDB content has one `protein.structure@4.0.0` content
  digest independent of provider or project-source provenance, and the active
  structure wire admits no source-bearing historical shape;
- `structure_transform.backbone_structure@4.0.0` is admitted by exact
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
Workflow Draft authoring, one immutable Workflow Commit, Start Run by exact
`workflow_commit_id`, Run Projection, Derived Run, Cancel Run, and Artifact
Retrieval. The Commit atomically fixes the validated Workflow, Contract Lock,
and Execution Plan; clients do not orchestrate separate relock or compile
steps. Its WebSocket observes a bounded replay followed by live terminal
evidence. The second Run must contain a Cache replay, and retrieved artifact
bytes must match their declared digest.

## V2 public protocol and persistence

`protein_workbench_public/resources/v2/bundle.json` is the only public payload
contract. A running backend serves the same canonical bytes from
`GET /api/v2/protocol`; clients use `protein_workbench_public` request and
response validation and do not maintain v1 route or payload fallbacks.
The same bundle owns Project creation and immutable input publication through
`POST /api/v2/projects` and
`POST /api/v2/projects/{project_id}/inputs`. Project Input bytes use canonical
RFC 4648 base64 in a closed JSON request and are bounded to 64 MiB after
decoding. `GET /api/v2/projects/{project_id}/inputs/{project_input_ref}`
recovers the immutable filename provenance after restart from the same durable
descriptor; there is no multipart or unversioned Project API seam.

The startup-frozen `FrozenCatalog` is the only discovery and compilation
contract source. It publishes one active exact version for each logical
contract. The immutable `Execution Plan` carries resolved contract facts into
Readiness and execution; scientific operations do not rescan the Catalog.
Direct Port compatibility requires an exact nominal Port Type ID and version.
Artifact-capable Port Types require explicit Node publication intent and an
exact media contract; no path-output or media-type fallback exists.
Artifact bytes share the Project-scoped immutable object store used by Typed
Output values. The committed Run Ledger remains the visibility authority, and
the independent Artifact route preserves exact media type, filename
provenance, Candidate association, digest, and size without a Run-scoped
authoritative file. Artifact retrieval represents that filename as an RFC 5987
UTF-8 `filename*` Content-Disposition parameter, including non-ASCII names.

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
Run Projection contains only bounded Typed Output descriptors. Exact canonical
values are retrieved individually through the Run-scoped v2 Typed Value route;
they are never embedded in the projection or lifecycle WebSocket stream.

## Acceptance campaign

The release candidate is one clean source commit, not a committed manifest that
tries to contain its own commit hash. Put every Provider path in a private
Execution Profile outside the repository and `verification-results/`; do not
reconstruct it from shell history or manifest hashes. The profile has this
closed shape and contains paths, not token contents:

```json
{
  "schema_namespace": "protein-workbench-acceptance-execution-profile/v1",
  "provider_configuration": {
    "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE": "/absolute/private/token-file",
    "HF_HUB_CACHE": "/absolute/hugging-face-cache",
    "PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT": "/absolute/esmfold2-model",
    "PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT": "/absolute/esmc-model",
    "PROTEIN_WORKBENCH_MKDSSP_BINARY": "/absolute/mkdssp",
    "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT": "/absolute/proteinmpnn-root",
    "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT": "/absolute/simplefold-model",
    "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT": "/absolute/esm2-source",
    "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT": "/absolute/esm2-model",
    "PROTEIN_WORKBENCH_SOLUPROT_ROOT": "/absolute/soluprot-root",
    "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT": "/absolute/protein-sol-root"
  },
  "remote_transport": {"proxy_policy": "direct"}
}
```

The real profile must contain every configuration name declared by
`provider_configuration_contracts` and exactly one of `HF_HUB_CACHE` or
`HF_HOME`. It is never copied into evidence. The campaign stores only its
path-free effective identity.

Run the full provider-free/backend/frontend matrix once, commit the clean
candidate, then prepare and qualify the same artifact. Qualification is
non-authoritative, may use changed/high-risk-first order, and may rerun a failed
or interrupted tier while the candidate identity is unchanged:

```bash
CAMPAIGN=verification-results/acceptance-campaign
PROFILE=/absolute/private/acceptance-profile.json
.venv/bin/python scripts/acceptance_campaign.py prepare "$CAMPAIGN" --profile "$PROFILE"
.venv/bin/python scripts/acceptance_campaign.py qualify-all "$CAMPAIGN" --profile "$PROFILE" \
  --prioritize installed-proteinmpnn \
  --prioritize installed-simplefold-folding
.venv/bin/python scripts/acceptance_campaign.py status "$CAMPAIGN" --profile "$PROFILE"
```

All 15 tiers need a latest passed Qualification Result. The controller then
runs Certification from its missing canonical prefix; certification always
starts fresh and never promotes qualification evidence:

```bash
.venv/bin/python scripts/acceptance_campaign.py certify-through "$CAMPAIGN" installed-protein-sol --profile "$PROFILE"
.venv/bin/python scripts/acceptance_campaign.py certify-through "$CAMPAIGN" fresh-1pga --profile "$PROFILE"
.venv/bin/python scripts/acceptance_campaign.py certify-through "$CAMPAIGN" fresh-2emo --profile "$PROFILE"
.venv/bin/python scripts/acceptance_campaign.py certify-through "$CAMPAIGN" fresh-canonical-3gb1 --profile "$PROFILE"
.venv/bin/python scripts/acceptance_campaign.py certify-through "$CAMPAIGN" fresh-5g53 --profile "$PROFILE"
```

`campaign.json` binds the source revision, one reproducibly built wheel and
sdist, public protocol and Catalog identities, all four input and Workflow
digests, path-free Provider Environment Configuration and Execution Profile
identities, exact tier and local-asset runtime identities, exact selectors and
tier order, every Qualification attempt, and every Certification result.
`started`, `passed`, `paused`, `failed`, and `interrupted` are written atomically. An
orphaned `started` attempt is recovered as `interrupted`; qualification can run
it again, while certification is permanently terminated.

The controller uses one blocking child at a time, never passes xdist, and never
retries a Certification tier or Workflow. The same frozen installed artifacts
are supplied to both phases. Any source, artifact, protocol, Catalog, input,
Workflow, Provider asset/configuration, tier contract, or Execution Profile
identity change invalidates the campaign instead of combining old evidence.
Each retained result contains a private bounded console log, a count-only JUnit
summary, and sanitized full JUnit diagnostics. Credential values and configured
local paths are redacted. Qualification results are never acceptance evidence.

Between Certification tickets, run only controller authority/status and process
cleanup checks. Run the complete provider-free/backend/frontend matrix once
more in the final audit after all 15 Certification tiers pass; do not repeat it
after every intermediate tier.

Local-model tiers are separate child processes. Within a child, one resident
instance of each exact local model is reused for all calls made by its operation
stage; the child must exit before the controller starts the next tier. The local
ESM-3 gate shares one client across paired, sequence, and structure generation.
The installed ProteinMPNN gate shares one resident model across every Adapter,
Operation, and test in that exact gate process. Source-bound Workflows keep
ProteinMPNN residency operation-scoped, so it is released before a later
Protein-Sol stage begins.

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
