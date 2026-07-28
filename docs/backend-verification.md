# Backend verification tiers

Backend verification is run through one public command so that the selected tier,
interpreter, isolated roots, and final result are visible in the transcript:

```bash
export PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION="$(git rev-parse HEAD)"
.venv/bin/python scripts/verify_backend.py <tier>
```

Every invocation creates temporary, distinct project, Cache, output, and run roots.
Configured production roots are replaced only in the child verification process and
are not written. JUnit, a sanitized pytest command transcript, an environment
summary, raw redacted provider events, and a validated provider summary when required
are written with mode `0600` under the ignored
`verification-results/<tier>/<UTC-run-id>/` directory; set
`PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT` to select a CI artifact directory.
After a successful fresh canonical tier, every retained file is frozen to `0400`
and every evidence directory to `0500`; other tiers retain their files at `0600`.
Plain `.venv/bin/pytest` uses the same isolation policy and defaults to the routine
marker expression.

## Available tiers

| Tier | Command | Contract |
| --- | --- | --- |
| Routine backend regression | `.venv/bin/python scripts/verify_backend.py routine` | Fast deterministic tests only; excludes acceptance, remote providers, local providers, heavy models, and intentionally red reproductions. |
| Deterministic backend acceptance | `.venv/bin/python scripts/verify_backend.py deterministic-acceptance` | Runs the canonical provider-fixture Workflow and failure variants through a real backend process using only REST, run-scoped WebSocket, manifest, Cache, and artifact APIs. |
| Installed backend artifact | `.venv/bin/python scripts/verify_backend.py installed-package` | Builds wheel and sdist, checks required YAML and canonical assets, installs the wheel with dependencies into a brand-new venv, then discovers all 45 Modules and starts the API from outside the source checkout. |
| Scientific reproduction | `.venv/bin/python scripts/verify_backend.py scientific-repro` | Runs the deterministic SCI-001 reproduction and confirms that legal amino-acid symbols reach the ESM3 boundary unchanged. |
| Post-review repair findings | `.venv/bin/python scripts/verify_backend.py repair-findings` | Intentionally red cumulative gate for the four independently confirmed post-handoff findings. It must report exactly the shifted final secondary-structure layout, cross-run sequence-export path reuse, repeated SimpleFold staging collisions, and incomplete public readiness/call evidence until their repair tickets land. |
| Mocked Workflow | `.venv/bin/python scripts/verify_backend.py mocked-workflow` | Runs the current deterministic 3GB1 Workflow tests with provider boundaries replaced by fixtures. |
| Local provider | `.venv/bin/python scripts/verify_backend.py local-provider` | Runs non-heavy installed binaries and requires both zero skips and provider-call evidence. |
| Heavy local model | `.venv/bin/python scripts/verify_backend.py heavy-model` | Explicitly loads slow local models and requires both zero skips and provider-call evidence. |
| Live remote provider | `.venv/bin/python scripts/verify_backend.py live-provider` | Makes remote provider calls and requires both zero skips and provider-call evidence. Readiness alone cannot satisfy this gate. |
| Fresh canonical 3GB1 | `.venv/bin/python scripts/verify_backend.py fresh-remote-3gb1` | Runs the protected canonical Workflow once through REST and its run-scoped WebSocket against local ESM3, Biohub ESMFold2, ProteinMPNN, mkdssp, Biopython SVD, and tmtools, then retrieves and seals exactly 15 run-bound PDBs. |

The complete real gates require these exact successful adapter-boundary calls:

- `local-provider`: `biopython-svd:structure_align`,
  `tmtools:tm_score`, and `mkdssp:secondary_structure`;
- `heavy-model`: `local_open:esm3.generate_sequence`,
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

## Deterministic public-protocol acceptance

The deterministic tier starts a real uvicorn backend process and uses a small
Python client with no frontend or React dependency. The client submits the
canonical Workflow through REST, consumes only its project/run WebSocket,
retrieves the durable manifest and outputs, and downloads every PDB through the
manifest-bound artifact route. External providers and mkdssp are replaced only
inside the test-only ASGI fixture module; the production FastAPI application,
Workflow validation, Execution Engine, Cache, run manifest, and artifact
retrieval paths remain real.

The tier fixes exact acceptance evidence for ten paired ESM3 sequence/structure
Candidates, ten initial folds, both TM-score objectives, the weighted top three,
three ProteinMPNN parents with five children each, fifteen per-sequence scores,
fifteen final folds, complete lineage, and fifteen literal PDB SHA-256 values.
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
