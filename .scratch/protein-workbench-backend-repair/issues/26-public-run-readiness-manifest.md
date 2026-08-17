# 26 — Publish truthful workflow-scoped readiness

> Historical completion evidence only. Checksums, symlink/security probes, Readiness-before-Cache, restart reconstruction, and old verification tiers mentioned below are not current requirements.

**What to build:** The public backend resolves required provider readiness for each workflow and publishes it fail-closed in the run manifest, without trusting client claims or acceptance-only postprocessing.

**Blocked by:** 25 — Record source-bound scientific-engine calls.

**Status:** completed

- [x] Readiness is resolved inside the public backend from the submitted workflow and required scientific boundaries before execution is accepted.
- [x] Production uses live readiness resolution, while deterministic fixtures can inject explicit readiness without making client payloads authoritative.
- [x] Missing, ambiguous, or failed required readiness is represented as unavailable or failed rather than silently green.
- [x] The canonical public API manifest contains all six required readiness identities and exactly 89 source-bound calls before any outer evidence aggregation.
- [x] Cache replay keeps readiness facts distinct from execution calls that did not occur in the replayed run.
- [x] Run isolation, lifecycle ordering, and secret redaction remain intact.
- [x] The repair stays within the current backend contract and does not expand into the next-stage execution-binding refactor.
- [x] Before ticket 27 starts, every completed repair check plus the routine, deterministic-acceptance, and installed-package gates passes with no unknown failure.

## Verification evidence

- Canonical readiness identities are `biohub`, `local_open`,
  `controlled-proteinmpnn`, `mkdssp`, `biopython-svd`, and `tmtools`; every
  fact records `status=ready`, a nonempty provider identity, and the exact
  Workflow Node/Module source that required the boundary.
- Production derives required boundaries from the validated Workflow and runs
  a fresh live probe for every submitted Workflow. Deterministic acceptance
  replaces only the app-factory resolver and explicitly aliases the controlled
  ProteinMPNN provider; request payload readiness fields are ignored.
- Missing readiness is `unavailable`; duplicate/ambiguous and failed resolver
  facts are `failed`. A rejected request receives `503` plus a durable failed
  run manifest with identical redacted readiness facts, no Node states, and no
  calls.
- Client-selected executable paths cannot authorize readiness. mkdssp probing
  executes only the resolved server-approved regular target with owner/mode
  checks, bounded output, timeout/process-group cleanup, off-loop execution,
  and a cancellation-safe project reservation.
- The canonical public manifest contains six readiness facts and exactly
  89 source-bound calls. A cache replay resolves the same six current
  readiness facts but records zero execution calls for work that did not run.
- Focused readiness, manifest, lifecycle, Cache, server, recovery, and executor
  regressions: 84 passed / 0 failed; the public readiness/call/Cache subset:
  3 passed / 0 failed.
- `repair-findings`: 5 passed / 0 failed.
- `routine`: 671 passed / 0 failed.
- `deterministic-acceptance`: 9 passed / 0 failed.
- `installed-package`: 3 passed / 0 failed.
- Standards, Spec, and security reviews: PASS after all amendments.
- No React frontend source or frontend test was inspected, modified, or
  executed. Ticket 27 was not started; Ticket 12 remains paused.
