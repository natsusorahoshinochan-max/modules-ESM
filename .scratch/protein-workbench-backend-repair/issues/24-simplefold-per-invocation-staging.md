# 24 — Isolate SimpleFold staging per invocation

**What to build:** A single node execution can fold and evaluate multiple collection items through SimpleFold without one invocation colliding with another or corrupting provider evidence.

**Blocked by:** 23 — Materialize sequence exports in each run namespace.

**Status:** completed

- [x] Fold and evaluation paths process at least two collection items within one node execution, and the second item completes without a staging collision.
- [x] Every invocation receives an isolated staging namespace while preserving source, model, and checksum validation.
- [x] Produced structures, subjects, lineage, and provider evidence remain bound to the correct collection item.
- [x] A focused repeated-staging check proves the collision cannot recur under deterministic local execution.
- [x] A real heavy-provider gate is required only if the deterministic public multi-item seam cannot fully exercise the collision; a one-item heavy run does not count as collision coverage.
- [x] Before ticket 25 starts, all completed repair checks plus the routine, deterministic-acceptance, and installed-package gates pass; only explicitly deferred findings may remain red, and no unknown failure is accepted.

## Verification evidence

- Each fold and evaluate collection item receives an owner-only temporary working directory directly below the run-scoped Node temp namespace. Fixed provider staging names therefore remain isolated between invocations without changing the reviewed source, model, size, SHA-256, or no-follow copy checks.
- Invocation directories are created through held directory descriptors with `O_DIRECTORY` and `O_NOFOLLOW`, then removed after success, provider failure, or cancellation. Parent symlink escapes are rejected, cleanup failures do not mask provider failures, and staged multi-gigabyte model copies are not retained between collection items.
- If a cancellation timeout force-kills the worker before its `finally` can run, the parent Executor removes the complete Node temp namespace after worker termination. Cleanup runs off the async event loop, and any bounded cleanup-failure type is visible in the manifest and Node/run lifecycle evidence.
- The deterministic public Module seam stages reviewed miniature provider objects twice for folding and twice for evaluation. Both second items complete; fold outputs retain `parent_ids`, score subjects name the produced Candidate, evaluate subjects name the input Candidate, and provider call details carry the same Candidate bindings.
- Candidate inputs are validated before provider execution, overlong derived fold IDs use a stable digest-backed identifier, and token-shaped Candidate IDs are redacted from external provider evidence.
- Focused SimpleFold, lifecycle, evidence, and containment checks: 107 passed / exit 0. The repaired Ticket 21 finding itself passes independently.
- Focused Mypy: 6 source files passed with the one pre-existing unrelated `Path(pretrained.__file__)` `arg-type` diagnostic at `modules/simplefold_adapter.py:421` suppressed; the repository does not configure or install Mypy.
- `repair-findings`: 3 passed / 1 known deferred failure. The secondary-structure, sequence-export, and SimpleFold staging findings are green; only the Tickets 25–26 public manifest finding remains red.
- `routine`: 656 passed / 40 deselected / exit 0.
- `deterministic-acceptance`: 8 passed / 4 deselected / exit 0.
- `installed-package`: 3 passed / exit 0.
- The deterministic public multi-item seam fully reproduces the original collision boundary, including actual staged copies and checksum revalidation. No heavy-provider gate was needed; the existing one-item heavy gate would not add collision coverage.
- Independent security review: passed after the staging lifecycle, symlink-parent containment, cleanup-exception, bounded-ID, and evidence-redaction fixes; no actionable finding remains.
- `/code-review`: Spec and Python axes passed with zero findings; Standards passed with one LOW judgement-call duplication smell in the two cancellation-timeout lifecycle payload builders and no hard violation. The payloads are intentionally separate Node/run public surfaces and behave identically under regression coverage.
- No React frontend source or frontend test was inspected, modified, or executed.
