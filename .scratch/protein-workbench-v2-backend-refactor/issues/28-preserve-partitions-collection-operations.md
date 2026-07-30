# 28 — Preserve partitions in collection operations

**What to build:** A Workflow can concatenate Candidate collections and merge Score collections while retaining exact Candidate identity and Observation source partitions, so later selectors can distinguish where every subject and score came from.

**Blocked by:** 12 — Prove the zero-Core extension journey.

**Status:** awaiting-controller

- [x] Candidate concatenation and Score merge each have one v2 Node Definition in a single `collection_ops` package registration.
- [x] Candidate concatenation preserves Candidate identities, parent lineage, producer/output/sample slots, stable input partitions, and deterministic ordering without minting replacement Candidates.
- [x] Score merge preserves complete Observation identity, subject identity, Method, Context, source partition, and propagation provenance.
- [x] Produced Observation propagation uses a controlled, versioned union/pass-through contract visible to the Compiler and does not execute arbitrary query code.
- [x] Identical Observation identity/value may deduplicate, while conflicting values, ambiguous duplicates, invalid multiplicity, or partition collision fail closed.
- [x] Inputs from optional collection Ports are normalized deterministically, and empty/absent collections remain distinguishable from malformed values.
- [x] The legacy subject-free cross-Metric confidence aggregation is not migrated or silently emulated.
- [x] Cache replay preserves collection membership and partition identity and does not copy historical scoring Invocations.
- [x] Both operations pass CTK and public compilation/execution tests without Core collection-specific dispatch.

## Executor evidence

- Accepted base: `e22a482903d1a5922e460d88d8d246334d8e1764`.
- Implementation commits: `974a8dc`, `bc67ca0`, `43fc02d`, `acf0fd9`.
- TDD and focused verification:
  - `uv run --no-sync pytest -q tests/test_collection_ops_v2.py` — 14 passed.
  - `uv run --no-sync pytest -q tests/test_collection_ops_v2.py tests/test_module_packages_v2.py tests/test_port_types_v2.py tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py tests/test_result_cache_v2.py tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py` — 278 passed.
  - `uv run --no-sync pytest -q tests/*_v2.py` — 564 passed.
- Required backend gates:
  - `uv run --no-sync python scripts/verify_backend.py routine` — 1253 passed, 52 deselected.
  - `uv run --no-sync python scripts/verify_backend.py deterministic-acceptance` — 10 passed, 5 deselected.
  - `uv run --no-sync python scripts/verify_backend.py installed-package` — 3 passed.
  - `uv lock --check`, `uv pip check`, `python -m compileall`, and `git diff --check` passed.
- Retained verification:
  - `verification-results/routine/20260730T050103.399110Z-32830-87db9b1a82037313`
  - `verification-results/deterministic-acceptance/20260730T050620.341035Z-40707-c511fce62b16e415`
  - `verification-results/installed-package/20260730T050731.145166Z-41366-9e00473027c899e3`
- `/code-review` Standards: APPROVE; no HIGH or MEDIUM findings.
- `/code-review` Spec: APPROVE; no HIGH or MEDIUM findings.
- Handoff boundary: executor leaves this Ticket at `awaiting-controller`; the Controller owns the independent multi-Ticket gate and may mark it `completed`.
