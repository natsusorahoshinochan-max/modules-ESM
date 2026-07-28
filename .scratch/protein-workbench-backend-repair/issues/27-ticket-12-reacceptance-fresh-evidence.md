# 27 — Reaccept ticket 12 and seal fresh canonical evidence

**What to build:** An acceptance operator can reaccept the repaired lifecycle contract and seal one fresh, source-bound canonical backend run whose own manifest and artifacts prove the completed repair without frontend involvement.

**Blocked by:** 26 — Publish truthful workflow-scoped readiness.

**Status:** completed

- [x] Ticket 12 remains paused until this ticket's cumulative reacceptance gate completes.
- [x] All repair reproductions and the routine, deterministic-acceptance, and installed-package gates pass together before any local-real, heavy-model, or live-provider gate starts.
- [x] Required affected local-real, heavy-model, and live-provider gates run only after offline closure and fail rather than skip when their required boundary is unavailable.
- [x] One clean final commit produces a fresh, Cache-bypassed canonical run through the public REST and run-scoped WebSocket interfaces.
- [x] The backend manifest itself records all six required readiness identities and exactly 89 source-bound calls without acceptance-wrapper supplementation.
- [x] The run proves 24 ordered terminal nodes, no historical Cache reuse, the exact 71-position provider-bound secondary-structure layout, and fifteen nonempty checksummed PDB artifacts with complete lineage.
- [x] The sealed evidence binds the source revision, deterministic source-tree identity, workflow and module versions, environment, providers, calls, seeds, Cache decisions, lifecycle outcomes, artifacts, and redacted transcripts.
- [x] The React frontend remains frozen, unmodified, and untested throughout this repair track.
- [x] The completion report and debug handoff identify the new clean commit and evidence bundle and explicitly supersede the prior canonical acceptance evidence.

## Completion evidence

- Accepted clean source: `ae3cc1fe69bb07aef6d00cf9cb5c638f4ea723ec`.
- The final cumulative gate passed `repair-findings` 5, `routine` 685,
  `deterministic-acceptance` 9, `installed-package` 3, `local-provider` 2,
  `heavy-model` 5, `live-provider` 2, and `fresh-remote-3gb1` 1. Every
  provider-bearing tier had zero skipped tests and was attested to the clean
  accepted revision.
- Accepted fresh run: `6e97fa60-6905-450a-a2d3-fc1de90ba626`.
- Sealed evidence:
  `/private/tmp/modules-esm-ticket27-final.WGneJ5/reacceptance-v3/fresh-remote-3gb1/20260728T094603.216755Z-91636-0c06f82f9236dde7`.
- The sealed bundle independently validates 24 completed ordered Nodes, 24
  Cache bypasses, six readiness facts, 89 source-bound calls, the exact
  71-position secondary-structure evidence, fifteen nonempty checksummed PDB
  artifacts, and a completed run-scoped WebSocket terminal event.
- The controller independently reran the four offline cumulative tiers at
  `/private/tmp/modules-esm-ticket27-controller.aJ6VUx`, revalidated the sealed
  bundle, and verified both artifact and bundle checksums.
- Ticket 12's pause condition is satisfied and its operational pause is lifted.
- Completion handoffs:
  `/private/tmp/modules-esm-backend-ticket27-completion-debug-handoff-20260728T175307+0800.md`
  and
  `/private/tmp/modules-esm-tickets21-27-completion-handoff-20260728T180342+0800.md`.
- The prior Ticket 20 evidence and failed Ticket 27 v2 bundle are superseded;
  their paths and rejection reasons are recorded in the Ticket 27 completion
  handoff.
- No React frontend source or frontend test was inspected, modified, or
  executed.
