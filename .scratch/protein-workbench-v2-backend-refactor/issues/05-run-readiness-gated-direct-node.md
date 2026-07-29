# 05 — Run a readiness-gated direct Node

**What to build:** A client can start a compiled Workflow containing one deterministic direct Node, observe exact Binding readiness before any work begins, receive a trustworthy successful Run Projection, and retrieve its validated typed output or artifact through the public protocol.

**Blocked by:** 04 — Compile contract-locked v2 Workflows.

**Status:** implementation-complete-awaiting-controller-gate

- [x] Start Run binds an exact Project, Workflow revision, Contract Lock, compile identity, and FrozenCatalog before execution.
- [x] Trusted Environment Configuration supplies credentials, endpoints, devices, binaries, and runtime paths by Binding scope without persisting secrets or private paths in the Workflow or public evidence.
- [x] Every distinct selected Binding receives a Run-scoped Readiness Attestation before implementation construction or any Cache lookup; repeated Nodes using the same exact Binding may share that Run attestation.
- [x] Availability, Readiness, and Engine Invocation are recorded as different facts and cannot substitute for one another.
- [x] Volatile prerequisites are re-observed per Run, while reusable proof requires declared identity, scope, maximum age, configuration fingerprint, and invalidation behavior; stale-green mutation tests fail.
- [x] The direct Node executes through its lazy factory using only the Execution Plan, FrozenCatalog, Environment Configuration, and project-scoped Run resources.
- [x] Input and output validators run at the Port boundary, and only complete canonical output can produce a successful Node Disposition or public typed result.
- [x] The success path durably records the minimum causal Ledger facts, exposes a consistent Run Projection and event sequence, and retrieves artifacts only through opaque projection references with scope and digest validation.
- [x] Run workspace containment, ownership, no-follow, mode, symlink resistance, redaction, and cleanup-error precedence remain enforced.

## Executor evidence

This status records executor completion only. Controller cumulative multi-ticket
acceptance is still required before Ticket 06 may start.

- Fixed review base:
  `08b5935fc7a8f971fc4c2e897226b437119e5f22`.
- Implementation commits:
  `4f82694` (`feat: execute readiness-gated direct nodes`),
  `7be9a6e` (`fix: close readiness and artifact review gaps`), and
  `968adbc` (`fix: persist refreshed proofs and publish artifact contracts`).
- Focused Run, compiler, Module Package, Port Type, and public protocol suites:
  `177 passed`.
- Final routine backend gate:
  `862 passed, 44 deselected, 1 warning`; retained result
  `verification-results/routine/20260729T015553.032300Z-53466-4015bab7c14f5efd`.
- Final deterministic-acceptance gate:
  `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T015727.185888Z-54196-fc2b60ae84ca6c17`.
  Every test selected by this required tier passed.
- Final installed-package gate:
  `3 passed`; retained result
  `verification-results/installed-package/20260729T015813.933445Z-54421-4cbc8fa9da7e3209`.
  The installed wheel runs the public save/load/relock/compile/start/projection
  direct-Node journey outside the source checkout and returns the deterministic
  typed output.
- `compileall`, `pip check`, `uv lock --check`, and
  `git diff --check 08b5935...HEAD` passed. No standalone mypy, pyright, or
  ruff configuration/tool was available, so no separate type/lint gate is
  claimed.
- Mandatory Standards and Spec reviewers initially found reusable-proof
  provenance/age gaps, missing explicit artifact publication contracts,
  collection handling, public artifact bounds, event-loop blocking, and a
  closed-protocol mismatch. The executor repaired every hard/high finding;
  both original reviewers returned `APPROVE` with no remaining or new
  CRITICAL/HIGH finding at `968adbc`.

The executor did not start Ticket 06. The Controller must now run the cumulative
Tickets 01–05 joint gate; any new regression must be returned to this Ticket 05
executor before Ticket 06 begins.
