# 04 — Compile contract-locked v2 Workflows

**What to build:** A Workflow author can save and compile an exact v2 Workflow through the public protocol, and the backend either returns an immutable compile receipt bound to the author-approved reachable contract closure or rejects it before any provider or implementation activity.

**Blocked by:** 03 — Discover atomic Module Packages.

**Status:** completed

- [x] Workflow and Node Instance schemas require v2 schema identity, exact Node Type and Binding ID/version, separate Node and Binding parameters, named Ports, and no duplicated Method choice.
- [x] The Workflow Contract Lock contains exactly the reachable Node, Binding, Method, Metric, Port Type, and Utility contracts with expected digests, in canonical deterministic order.
- [x] Compilation independently recomputes the reachable closure from the current FrozenCatalog and rejects missing, duplicate, incomplete, stale-extra, or mismatched Lock entries with `contract_digest_mismatch`.
- [x] Contract mismatch is detected before Availability evaluation, provider probing, implementation construction, or any execution side effect; changes to unreachable Catalog contracts do not invalidate the Workflow.
- [x] Compilation validates schema, DAG structure, Binding ownership, parameters, exact Port compatibility, Availability, and all currently expressible contract references.
- [x] Successful compilation produces an immutable private Execution Plan while the public response exposes only the compact Workflow, Catalog, Lock, and plan identities plus structured issues.
- [x] Explicit relock creates a new Workflow revision; load, save, compile, and Run never silently refresh or repair an existing Lock.
- [x] Version ranges, `latest`, automatic Binding selection, silent fallback, mixed environment parameters, and v1 Workflow schemas are rejected with stable public errors.

## Executor evidence

- Fixed review/start commit:
  `461f0bd606647f07c532a0e9dbc9b81db7c28972`.
- Implementation commits:
  `e0a8cb0`, `a4b4a09`, `211c48b`, `36aed62`, `42d9db4`,
  `adbd853`, `8984b26`, and `45555bf`.
- Focused cross-ticket regression:
  `158 passed, 3 deselected` across Workflow compiler, public protocol,
  Module Package, Port Type, and installed-backend tests.
- Final routine gate:
  `843 passed, 44 deselected, 1 warning`; retained result
  `verification-results/routine/20260729T003721.412613Z-40373-125bfa69393e1e4b`.
- Final deterministic-acceptance gate:
  `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T003900.457972Z-41830-753d96b29c50857e`.
- Final installed-package gate:
  `3 passed`; retained result
  `verification-results/installed-package/20260729T003949.881839Z-42033-e16f125225b9e2b9`.
  The installed-wheel/real-uvicorn journey exercises public save, load,
  relock, and compile outside the source checkout.
- `git diff --check`, `compileall`, `uv lock --check`, and `pip check`
  passed. No standalone mypy, pyright, or ruff configuration/tool was
  available, so no separate type/lint gate is claimed.
- Standards and Spec reviewers both returned APPROVE with zero remaining
  CRITICAL/HIGH findings at `45555bf`.
- One earlier routine attempt observed a timing-only failure in
  `test_verifier_timeout_retains_then_cleans_supervisor_group`; the isolated
  probe immediately passed, and two later complete routine gates passed,
  including the final retained result above.
- Executor completion does not constitute Controller acceptance. Ticket 05
  remains blocked until the Controller runs the Tickets 01–04 joint gate.

## Controller cumulative acceptance

Before Ticket 05 started, the Controller independently accepted implementation
commit `e42244f8ad5cc3b9d51e1269819a35b8ca0e6377` together with the completed
Tickets 01–03 surfaces:

- Joint Ticket 01–04 focused suites: `158 passed`.
- Cumulative routine: `843 passed, 44 deselected`, with retained result
  `verification-results/routine/20260729T004305.144501Z-42522-1bf39e75d176a998`.
- Deterministic acceptance: `9 passed, 5 deselected`, with retained result
  `verification-results/deterministic-acceptance/20260729T004934.188219Z-44044-91838dbb51fa4da4`.
- Installed artifact: `3 passed`, with retained result
  `verification-results/installed-package/20260729T005022.246028Z-44166-548c41d31376b5fb`.
- `git diff --check 461f0bd...e42244f` passed and the worktree was clean before
  the Controller recorded this acceptance.

No Controller regression was returned to the executor. Ticket 05 may start from
this accepted state.
