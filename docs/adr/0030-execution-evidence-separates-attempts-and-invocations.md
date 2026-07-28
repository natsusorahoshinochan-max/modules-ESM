---
status: accepted
---

# Execution evidence separates attempts from engine invocations

A Node Execution Attempt records one scheduled Node Instance outcome. A Cache
hit terminates only that Node Execution Attempt and creates no Operation
Attempt or Engine Invocation. After a Cache miss or bypass, each actual run of
the selected implementation is an Operation Attempt, which may contain zero,
one, or several Engine Invocations.

Every Operation Attempt and Engine Invocation that starts has exactly one
terminal fact: `succeeded`, `failed`, `cancelled`, `interrupted`, or
`outcome_unknown`. Successful engine work followed by decoding, normalization,
output validation, or artifact post-processing failure remains a successful
Invocation inside a failed Operation Attempt; its terminal fact is never
rewritten as engine failure. If a worker is lost after start, the parent
records `interrupted` or `outcome_unknown` rather than inventing a remote
outcome, and any retry receives new Operation Attempt and Engine Invocation
identities.

Parent-child invocation roles are explicit. Acceptance checks ledger closure
and causal relationships rather than preserving a historical fixed invocation
count.

The Run Evidence Ledger is the single writer and ordered durable source of
typed run facts. The run manifest, JSONL lifecycle stream, and WebSocket stream
are rebuildable projections of that ledger rather than independent writers or
competing sources of truth.

Each proposed fact passes schema and causal validation, conversion to its
redacted public contract, and durable persistence with a monotonic run sequence
before it may affect a projection or be published. Projection failure cannot
change the persisted execution outcome. Failure to persist required execution
evidence prevents the Node Execution Attempt from publishing success or writing
a Cache result.

This decision refines ADR-0006 and ADR-0015.
