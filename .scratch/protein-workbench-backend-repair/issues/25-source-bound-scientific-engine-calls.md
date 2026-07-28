# 25 — Record source-bound scientific-engine calls

**What to build:** The public run manifest itself records every alignment and TM-score engine invocation alongside the already observed provider calls, allowing an acceptance operator to audit all scientific work from one run-scoped source of truth.

**Blocked by:** 24 — Isolate SimpleFold staging per invocation.

**Status:** completed

- [x] Public alignment and TM-score module paths emit run-scoped call facts that identify the scientific engine, relevant input identity, terminal result, and redacted evidence.
- [x] The canonical run manifest contains exactly 89 calls: the existing 49 calls, 20 alignment-engine calls, and 20 TM-score-engine calls.
- [x] Call capture does not duplicate the existing 49 calls and does not depend on a global blind bridge.
- [x] Concurrent runs, Cache replay, event ordering, and secret redaction preserve correct source and run attribution.
- [x] Acceptance evidence no longer needs an outer wrapper to add missing alignment or TM-score calls to the backend manifest.
- [x] Before ticket 26 starts, all completed repair checks plus the routine, deterministic-acceptance, and installed-package gates pass; only explicitly deferred findings may remain red, and no unknown failure is accepted.

## Verification evidence

- `repair-findings`: expected cumulative red, 5 selected / 4 passed / 1 failed; the only failure is the explicitly deferred Ticket 26 readiness manifest check.
- Focused scientific-call and manifest regression suite: 94 passed / 0 failed.
- `routine`: 665 passed / 41 deselected / 0 failed.
- `deterministic-acceptance`: 8 passed / 5 deselected / 0 failed.
- `installed-package`: 3 passed / 0 failed.
- Canonical public manifest call distribution: existing provider facts 49, `biopython-svd:structure_align` 20, and `tmtools:tm_score` 20; total 89.
- Focused evidence covers ordered Node attribution, concurrent run isolation, Cache replay with no repeated calls, successful terminal summaries, complete engine-input digests, token-shaped identity redaction, and the non-canonical tmtools alignment tie-break path.
- Scientific manifest details use operation-specific bounded schemas; active `node_id` attribution cannot be overridden by worker payloads.
- Failed SVD alignment, TM-score, and high-ambiguity tmtools tie-break invocations retain exactly one failed terminal per invoked boundary before/with the Node failure; only the bounded exception type is retained.
- No React frontend source or frontend test was inspected, modified, or executed. Ticket 26 readiness was not implemented.
