# 19 — Migrate remote ESM-3 generation

**What to build:** A Workflow can perform remote ESM-3 sequence, structure, or paired generation through one cohesive `esm3` Module Package and receive complete, correctly paired Candidates with exact model identity and truthful provider evidence.

**Blocked by:** 15 — Assemble and update ProteinPrompts.

**Status:** completed

- [x] Sequence, structure, and paired generation each have one v2 Node Definition and share the ESM-3 adapter, provider contract, test assets, and package registration.
- [x] Exact Methods and Bindings fix model/source/scale and execution route; model name is not a mutable Workflow parameter, and credential/endpoint configuration is trusted environment state.
- [x] The adapter preserves every legal ProteinPrompt track and symbol and translates provider SDK values without changing the Node Type's scientific meaning.
- [x] Sequence generation publishes complete sequence Candidates, structure generation publishes complete structure Candidates, and paired generation preserves exact sequence-to-structure counterpart identity and lineage for every sample.
- [x] `track` or generation mode controls the provider operation rather than silently discarding response fields; lossy legacy wrappers are not retained as the public contract.
- [x] Effective seeds and generation parameters are resolved before Result Identity; candidate order, sample slots, parents, and content digests remain stable across Run and Cache replay.
- [x] Provider-native confidence outputs are declared through exact Produced Observations and statically normalized where required; invalid or incomplete provider output fails before Candidate publication.
- [x] Composite sequence/structure operations record their real parent-child Engine Invocations and do not use a fixed historical call count as truth.
- [x] Deterministic fixtures and a required zero-skip provider gate prove all three modes, ten paired Candidates, readiness-before-call, redaction, and complete terminal evidence.
- [x] The package passes CTK and installed discovery without an ESM-3 Core dispatch or readiness map.

## Executor evidence

This records executor completion only. Ticket 20 must not start until the
Controller independently runs the cumulative Tickets 01–19 gate and accepts
this state. Any joint-test regression must be returned to this Ticket 19
executor for repair before that next Ticket starts.

- Fixed implementation/review base:
  `87dab2ac6457e9d99603400d75c167c78968177b`.
- Implementation and review-fix commits span `0ec646f` through `4c94f1b`.
- Joint Tickets 01–19 v2 regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `434 passed`.
- Focused ESM-3 and provider-evidence regression:
  `uv run pytest -q tests/test_esm3_v2.py
  tests/test_provider_evidence.py` → `54 passed`.
- Cumulative routine gate:
  `uv run python scripts/verify_backend.py routine` →
  `1116 passed, 46 deselected`; retained result
  `verification-results/routine/20260729T160225.205956Z-15402-37ef9dd9ebc45063`.
- Deterministic acceptance:
  `uv run python scripts/verify_backend.py deterministic-acceptance` →
  `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T160543.106975Z-19027-9129e7b1579032d6`.
- Installed artifact:
  `uv run python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T160639.471966Z-19412-68070f1923d0544d`.
- The required live-provider tier names the cohesive all-modes/ten-pairs test
  and enforces 11 sequence plus 11 structure calls with no skip allowance.
  Executor preflight correctly refused to run it before a Controller-approved
  clean source revision existed; no live result is claimed here.
- `compileall`, `uv lock --check`, `uv pip check`, and `git diff --check`
  passed.
- Parallel `/code-review` Standards and Spec reviewers drove repairs for the
  second Biohub model, uncached per-Run SDK readiness, package-local provider
  boundaries, reconstruction retention, optional PAE multiplicity, explicit
  Invocation lineage, provider-neutral Metrics, and truthful post-call
  evidence failure semantics. Both final review axes returned `APPROVE` at
  `4c94f1b`.
