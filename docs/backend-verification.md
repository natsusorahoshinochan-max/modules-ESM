# Backend verification tiers

Backend verification is run through one public command so that the selected tier,
interpreter, isolated roots, and final result are visible in the transcript:

```bash
.venv/bin/python scripts/verify_backend.py <tier>
```

Every invocation creates temporary, distinct project, Cache, output, and run roots.
Configured production roots are replaced only in the child verification process and
are not written. JUnit, a sanitized pytest command transcript, and provider-call
evidence when required are retained under the ignored
`verification-results/<tier>/<UTC-run-id>/` directory; set
`PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT` to select a CI artifact directory.
Plain `.venv/bin/pytest` uses the same isolation policy and defaults to the routine
marker expression.

## Available tiers

| Tier | Command | Contract |
| --- | --- | --- |
| Routine backend regression | `.venv/bin/python scripts/verify_backend.py routine` | Fast deterministic tests only; excludes acceptance, remote providers, local providers, heavy models, and intentionally red reproductions. |
| Deterministic backend acceptance | `.venv/bin/python scripts/verify_backend.py deterministic-acceptance` | Runs the canonical provider-fixture Workflow and failure variants through a real backend process using only REST, run-scoped WebSocket, manifest, Cache, and artifact APIs. |
| Installed backend artifact | `.venv/bin/python scripts/verify_backend.py installed-package` | Builds wheel and sdist, checks required YAML and canonical assets, installs the wheel with dependencies into a brand-new venv, then discovers all 45 Modules and starts the API from outside the source checkout. |
| Scientific reproduction | `.venv/bin/python scripts/verify_backend.py scientific-repro` | Runs the deterministic SCI-001 reproduction and confirms that legal amino-acid symbols reach the ESM3 boundary unchanged. |
| Mocked Workflow | `.venv/bin/python scripts/verify_backend.py mocked-workflow` | Runs the current deterministic 3GB1 Workflow tests with provider boundaries replaced by fixtures. |
| Local provider | `.venv/bin/python scripts/verify_backend.py local-provider` | Runs non-heavy installed binaries and requires both zero skips and provider-call evidence. |
| Heavy local model | `.venv/bin/python scripts/verify_backend.py heavy-model` | Explicitly loads slow local models and requires both zero skips and provider-call evidence. |
| Live remote provider | `.venv/bin/python scripts/verify_backend.py live-provider` | Makes remote provider calls and requires both zero skips and provider-call evidence. Readiness alone cannot satisfy this gate. |

Fresh remote 3GB1 acceptance is intentionally not a placeholder tier here. Its
command becomes valid only when tickets 18 through 20 add the remaining
deterministic and source-bound evidence contracts.

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
uv sync --frozen --extra providers
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
