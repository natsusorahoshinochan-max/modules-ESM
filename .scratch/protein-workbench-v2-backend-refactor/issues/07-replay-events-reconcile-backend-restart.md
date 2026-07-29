# 07 — Replay events and reconcile backend restart

**What to build:** A client can disconnect from a running Workflow, reconnect with an opaque cursor, and recover an ordered public event history even across backend restart, while incomplete work is closed conservatively without invented success.

**Blocked by:** 06 — Close dispositions across branch failures.

**Status:** awaiting-controller

- [x] Durable Ledger facts receive monotonic sequence identities before any public projection or event publication.
- [x] Run Event Stream switches from replay to live delivery without omitting or duplicating a public event and rejects malformed, stale, or cross-scope cursors safely.
- [x] Manifest-equivalent data, persisted lifecycle output, WebSocket events, and Run Projection are demonstrably consistent projections of the same Ledger facts.
- [x] Restart with a started but non-terminal Node, Operation, or Invocation appends conservative interrupted or outcome-unknown facts and completes every required Node Disposition.
- [x] Restart reconciliation never publishes unproved output, writes Cache, guesses a provider result, or silently resumes the original Run.
- [x] Reconciliation is idempotent: a second restart does not append a second terminal fact or change an already closed outcome.
- [x] Projection failure does not rewrite durable facts, and the public event stream can be reconstructed after process restart.
- [x] Acceptance asserts causal closure and actual invocation relationships rather than a fixed historical event or call count.

## Executor evidence

This records executor completion only. Ticket 08 must not start until the
Controller independently runs the cumulative Tickets 01–07 gate and accepts
this state.

- Fixed implementation/review base:
  `7c01eb7ae1921a1fd2bb48d365e5ec8dbccc4d6e`.
- Implementation and review-fix commits: `1e7d652`, `21c7af7`, and
  `876f7be`.
- Focused Run/restart and public-protocol suites:
  `.venv/bin/pytest -q tests/test_run_execution_v2.py
  tests/test_public_protocol_v2.py` → `57 passed`.
- Joint Tickets 01–07 focused regression across Run execution, public
  protocol, Workflow compiler, Module Packages, Port Types, and installed-test
  source probes → `205 passed, 3 deselected`.
- Cumulative routine gate:
  `.venv/bin/python scripts/verify_backend.py routine` →
  `891 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T034732.878864Z-77543-82e91e0de6ff5017`.
- Deterministic acceptance:
  `.venv/bin/python scripts/verify_backend.py deterministic-acceptance` →
  `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T034929.049641Z-78487-e285dc3b5f1cc956`.
- Installed artifact:
  `.venv/bin/python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T035018.909926Z-78667-b052e6325648649d`.
  The installed wheel is killed during an actual Engine Invocation and then
  proves cursor-exclusive replay, conservative recovery, empty unproved
  outputs/Cache, and idempotent second restart outside the source checkout.
- `compileall`, `pip check`, `uv lock --check`, and
  `git diff --check 7c01eb7...HEAD` passed. No standalone mypy/pyright
  configuration is installed, so no separate static-type result is claimed.
- Parallel `/code-review` Standards and Spec reviewers initially found the
  durable-terminal/disposition crash window, non-atomic Ledger publication,
  unbounded unmanaged background writers, and partial projection-generation
  exposure. The executor repaired every CRITICAL/HIGH finding plus the
  projection finding; both follow-up review axes returned `APPROVE` at
  `876f7be`.
