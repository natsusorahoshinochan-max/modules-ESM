# 24 — Consolidate ProteinMPNN constraints and design

**What to build:** A Workflow can author complete ProteinMPNN constraints, reproducibly choose random fixed positions, and design multiple child sequences per selected parent through one cohesive `proteinmpnn` Module Package with exact model identity and lineage.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** awaiting-controller

- [x] Constraint authoring, random fixed-position selection, and sequence design each have one v2 Node Definition under the single `proteinmpnn` package registration.
- [x] Constraint values cover designable and fixed positions, designed and fixed chains, omitted amino acids, tied positions, and per-residue bias with explicit layout/chain validation.
- [x] Random fixed-position selection records an effective seed and all result-affecting parameters, uses no process-global randomness, and changes Result Identity when randomness changes.
- [x] The design Binding fixes the exact ProteinMPNN Method/model/checkpoint/source and adapter/implementation identity; `model_name`, model path, device, and runtime directories are not free Workflow parameters.
- [x] Startup Availability and per-Run Readiness validate package/runtime/model prerequisites without eager model loading or a Core provider map.
- [x] Structure, collection, optional sequence, and constraints inputs normalize into one declared design contract without losing parent Candidate identity.
- [x] Each selected parent produces the requested complete number of child Candidates with stable parent/output/sample/content lineage, effective randomness, and no cross-parent identity collision.
- [x] Provider output and optional scores are validated before publication; partial children, missing parent relationships, or malformed sequences fail the Node without caching.
- [x] Deterministic tests prove the canonical three-parent by five-child shape, constraint fidelity, replay stability, actual Engine Invocation, CTK conformance, and installed discovery.

## Executor evidence

- Starting Controller gate: `1da261f48f2757b0cef192fa3d920b5edf676b08`.
- TDD RED: the initial Ticket 24 contract test failed because the production `proteinmpnn` v2 Module Package did not exist. Subsequent focused RED cases exposed standalone seed dependence on Node Instance ID, provider identity bypass, non-canonical `X` sampling, and reference-layout compatibility before their fixes.
- Implementation commits: `337e98a`, `3edcbdd`, `9f0316e`, and `8e069d0`.
- Focused final gate on implementation SHA `8e069d0e7eedb08edcb7ba69f4b4d4499a083336`: `uv run --no-sync pytest -q tests/test_proteinmpnn_v2.py tests/test_proteinmpnn.py tests/test_prompt_random_fixed_positions.py tests/test_port_types_v2.py tests/test_module_packages_v2.py tests/test_contract_test_kit_v2.py` — `169 passed`.
- Tickets 01–24 v2 joint regression on the same SHA: `uv run --no-sync pytest -q tests/*_v2.py` — `500 passed`.
- Full routine gate on the same SHA: `1188 passed, 50 deselected`; retained result: `verification-results/routine/20260729T231945.093814Z-56598-dc9c8c3239000e65`.
- Deterministic acceptance on the same SHA: `10 passed, 5 deselected`; retained result: `verification-results/deterministic-acceptance/20260729T232433.306590Z-63128-190f013408f0ca7e`.
- Installed-package gate on the same SHA: `3 passed`; retained result: `verification-results/installed-package/20260729T232542.926043Z-63752-eefd002276fb9695`.
- `/code-review` Standards initially reported two HIGH findings, one MEDIUM finding, and one LOW smell; Spec initially reported two HIGH findings and one MEDIUM finding. The executor removed Node-ID-dependent standalone randomness, centralized parameter normalization, closed canonical-sequence and reference-layout gaps, completely rejected injected production providers, and revalidated the exact checkout/checkpoint at execution. Final Standards and Spec re-reviews found no remaining or newly introduced CRITICAL/HIGH findings.
- `git diff --check 1da261f48f2757b0cef192fa3d920b5edf676b08..HEAD` passes; `git diff 1da261f48f2757b0cef192fa3d920b5edf676b08..HEAD -- core` is empty.
- Ticket 25 was not started. Ticket 24 remains `awaiting-controller` until the Controller independently runs the cumulative multi-ticket gate.
