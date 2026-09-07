# Node Outcome Publication design (historical record)

Status: superseded on 2026-08-17

This design introduced the current separation between Node Execution Attempts,
Operation Attempts, Engine Invocations, Typed Output publication, Artifact
publication, and Run Projection. Those scientific and public concepts remain.

Its filesystem threat model, cross-Run Result Identity authority, automatic
object garbage collection, and restart causality reconstruction were later
found to be overdesigned for a trusted, single-user, loopback-only project.
They are replaced by:

- one validation at each contract-owning scientific or public Interface;
- a small content-addressed object store with no automatic GC;
- Result Identity as a scientific cache key only;
- best-effort cache publication;
- terminal Run reload and a single `interrupted` terminal for unfinished Runs;
- one serial Acceptance Campaign with lightweight retained observations.

The active requirements are documented in
[codebase-redesign.md](./codebase-redesign.md) and
[2026-08-17-acceptance-evidence-follow-up-audit.md](./2026-08-17-acceptance-evidence-follow-up-audit.md).
