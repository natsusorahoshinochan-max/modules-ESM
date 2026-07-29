# 20 — Add local ESM-3 Bindings

**What to build:** A repository maintainer can add local ESM-3 execution for sequence, structure, and paired generation by extending only the existing `esm3` Module Package, while Workflows retain the same scientific Node contracts and explicitly choose the local route.

**Blocked by:** 19 — Migrate remote ESM-3 generation.

**Status:** awaiting-controller

- [x] Local Bindings reuse the three existing ESM-3 Node Definitions and Produced Observation contracts rather than copying or weakening them.
- [x] Every local Binding fixes an exact Method, model/checkpoint/source identity, adapter/implementation identity, determinism contract, and cacheability declaration.
- [x] Model paths, device selection, runtime directories, and performance settings are injected through trusted Binding-scoped Environment Configuration and never appear as Workflow scientific parameters.
- [x] Startup Availability reports missing runtime or structural prerequisites without eager-loading the model or hiding the remote Binding.
- [x] Per-Run Readiness verifies resolved model/runtime identities and safe fingerprints before Cache lookup, and replacing a model file or configuration invalidates a previous green result.
- [x] Local and remote Bindings never auto-select, fall back, or substitute for one another based on Availability; exact Binding identity appears in Workflow Lock, Result Identity, Ledger, and projection.
- [x] Local execution preserves complete Candidate pairing, track fidelity, effective seeds, Produced Observations, and Engine Invocation evidence established by the remote contracts.
- [x] Full and partial local dependency failures are isolated to the affected Binding and return structured, redacted diagnostics.
- [x] CTK, installed discovery, deterministic fixtures, and a required local heavy-model gate prove zero Core modification across all three generation modes.

## Executor evidence

This records executor completion only. Ticket 21 must not start until the
Controller independently runs the cumulative Tickets 01–20 gate and accepts
this state. Any joint-test regression must be returned to this Ticket 20
executor for repair before that next Ticket starts.

- Fixed implementation/review base:
  `2e245b09d5e4784bd6e30fab6bfcb15379582276`.
- Implementation and review-fix commits span `6782d72` through `a889e22`.
- Joint Tickets 01–20 v2 regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `449 passed`.
- Focused ESM-3/provider/tier regression:
  `uv run --no-sync pytest -q tests/test_esm3_local_v2.py
  tests/test_esm3_v2.py tests/test_provider_evidence.py
  tests/test_verification_tiers.py` → `89 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1131 passed, 46 deselected`; retained result
  `verification-results/routine/20260729T174322.705990Z-69423-407950e0ff00e040`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T174707.885603Z-73743-90dedf0961cbcc49`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T174806.295651Z-74289-aecce9181c7dcb34`.
- The required local ESM-3 heavy acceptance ran at clean approved source
  `a889e22a86cf7e4a869c6f90f2a05ea2ff065597` and passed sequence,
  structure, and paired generation with the exact two sequence plus two
  structure provider calls. It passed both in the complete heavy-model
  invocation and as a focused diagnostic. The complete shared tier remained
  red only because its unrelated legacy ProteinMPNN and SimpleFold targets
  lacked configured external artifacts (`1 passed, 4 failed`); retained
  result:
  `verification-results/heavy-model/20260729T174846.921694Z-74435-ca1e6ace8e9367fa`.
  The focused local target was `1 passed` and then correctly reported
  incomplete because a focused provider diagnostic cannot satisfy the
  aggregate gate; retained result:
  `verification-results/heavy-model/20260729T175024.164698Z-74754-7a81055b39fadaee`.
- `compileall`, `uv lock --check`, `uv pip check`, `git diff --check`, and
  the zero-`core/` diff check passed.
- Parallel `/code-review` Standards and Spec reviewers drove repairs for
  standard Hugging Face blob links, TOCTOU-safe private staging, lazy SDK
  component loading, result-affecting runtime identity, the production
  default-loader path, staged-weight lifecycle, and cleanup error precedence.
  Both final review axes returned `APPROVE` at `a889e22`.
- Ticket 21 has not started.
