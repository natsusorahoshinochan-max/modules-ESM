# Ticket 05 — Result Identity as a scientific cache key

Status: superseded and simplified on 2026-08-17

The original ticket introduced a project-wide Ledger-derived authority and
`result_identity_conflict`. The trusted-core redesign removes that machinery.

Current contract:

- Result Identity includes the admitted result-affecting scientific facts;
- a cache hit replays the retained result and a miss executes the Binding;
- cache publication is best-effort and cannot rewrite Node success;
- conforming deterministic Bindings are trusted;
- there is no cross-Run conflict index or public conflict error.
