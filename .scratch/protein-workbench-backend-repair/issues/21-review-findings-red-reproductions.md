# 21 — Capture the review findings as deterministic red reproductions

**What to build:** A backend repair operator can reproduce each post-handoff finding independently, distinguish the four known defects from unrelated regressions, and use the reproductions as the cumulative gate for the remaining repair tickets.

**Blocked by:** None — can start immediately.

**Status:** completed

- [x] Dedicated, deterministic checks reproduce all four findings: shifted canonical secondary-structure intent, cross-run sequence-export reuse, repeated SimpleFold staging collision, and incomplete public readiness/call evidence.
- [x] Each check states the currently observed behavior and the repaired behavior it will require, without relying on the React frontend or historical provider artifacts.
- [x] The dedicated repair gate is red only for the four known findings while the routine, deterministic-acceptance, and installed-package gates remain green.
- [x] The repair track records tickets 02 and 11 as requiring reacceptance, ticket 12 as paused until ticket 27, and ticket 20 evidence as superseded for final acceptance, without modifying those earlier tickets.
- [x] Before ticket 22 starts, a cumulative verification run confirms the baseline gates remain green and reports no unknown failure beyond the explicitly deferred repair checks.

## Repair-track status

- Tickets 02 and 11 require reacceptance after their corresponding repairs.
- Ticket 12 remains paused until Ticket 27 completes fresh reacceptance.
- Ticket 20's historical evidence is superseded for final acceptance and remains diagnostic only.

## Verification evidence

- `repair-findings`: expected red, 4 selected / 4 failed / 0 skipped; the four failures correspond one-to-one with the known review findings.
- `routine`: 636 passed / 0 failed / 0 skipped.
- `deterministic-acceptance`: 8 passed / 0 failed / 0 skipped.
- `installed-package`: 3 passed / 0 failed / 0 skipped.
- No React frontend source or frontend test was inspected, modified, or executed.
