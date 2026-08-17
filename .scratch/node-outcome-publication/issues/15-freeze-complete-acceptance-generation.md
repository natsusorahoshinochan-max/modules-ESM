# Ticket 15 — Run the complete real Acceptance Campaign

Status: completed on 2026-08-18

This ticket now owns the complete real acceptance surface. Tickets 16–20 are
folded into it so the expensive Providers and source-bound Workflows run once,
not once for Qualification and again for Certification.

## Requirements

- [x] finish provider-free backend and frontend verification;
- [x] commit one clean candidate;
- [x] `prepare` one Campaign with the private Execution Profile;
- [x] `run` all 15 canonical tiers exactly once in order and without xdist;
- [x] stop on the first failure and do not retry inside the Campaign;
- [x] retain each tier's already-validated public observations after its
  scientific assertions pass;
- [x] require all 15 results to pass.

The historical 15/15 Qualification at commit `c924c48` is diagnostic evidence
only. It is not promoted into this Campaign.

## Completion evidence

- Accepted source revision:
  `21bd098a969a0ac24d4d3de79e9020459ac13e6e`.
- Campaign root:
  `verification-results/acceptance-campaign-21bd098`.
- Campaign schema: `protein-workbench-acceptance-campaign/v2`.
- Terminal state: `passed`; all 15 canonical results are `passed` in the
  declared order.
- The Campaign ran from `2026-08-17T16:39:27Z` through
  `2026-08-17T17:01:20Z`. Each tier ran once in one serial Campaign; no tier was
  retried and no Certification generation was created.
- The preceding provider-free matrix, frontend checks, compilation, diff check,
  and two-axis review passed before the clean revision was prepared.
