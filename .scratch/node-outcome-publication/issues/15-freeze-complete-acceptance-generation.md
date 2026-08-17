# Ticket 15 — Run the complete real Acceptance Campaign

Status: pending final clean-revision run

This ticket now owns the complete real acceptance surface. Tickets 16–20 are
folded into it so the expensive Providers and source-bound Workflows run once,
not once for Qualification and again for Certification.

## Requirements

- finish provider-free backend and frontend verification;
- commit one clean candidate;
- `prepare` one Campaign with the private Execution Profile;
- `run` all 15 canonical tiers exactly once in order and without xdist;
- stop on the first failure and do not retry inside the Campaign;
- retain each tier's already-validated public observations after its scientific
  assertions pass;
- require all 15 results to pass.

The historical 15/15 Qualification at commit `c924c48` is diagnostic evidence
only. It is not promoted into this Campaign.
